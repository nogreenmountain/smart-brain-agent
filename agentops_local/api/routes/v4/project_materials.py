from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.project_memory.ingest import ingest_markdown_memory
from agentops.project_memory.intake import (
    build_review_markdown,
    select_confirmed_files,
    validate_batch_limits,
)
from agentops.project_memory.intelligence import (
    MaterialSource,
    generate_knowledge_package,
    preview_materials,
)
from agentops.project_memory.parsers import SUPPORTED_FORMATS, extract_text
from agentops.rag.audit import record_audit
from agentops.rag.authz import AuthzError, current_user_id, require_admin, require_member
from agentops.rag.ingest import ingest_file


router = APIRouter(route_class=AuthenticatedRoute)


class MaterialPreviewFileSchema(BaseModel):
    id: uuid.UUID
    filename: str
    format: str
    size_bytes: int
    content_hash: str
    recommendation: str
    included: bool
    reason: str
    issues: list[str]


class MaterialIntakePreviewResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    summary: str
    model: str | None = None
    used_fallback: bool
    items: list[MaterialPreviewFileSchema]


class ConfirmMaterialIntakeRequest(BaseModel):
    included_file_ids: list[uuid.UUID] = Field(..., min_length=1)


class ConfirmMaterialIntakeResponse(BaseModel):
    intake_id: uuid.UUID
    status: str
    raw_document_count: int
    curated_document_id: uuid.UUID
    draft_id: uuid.UUID
    skill_count: int
    generation_model: str | None = None
    generation_used_fallback: bool


def _safe_upload_name(upload: UploadFile) -> tuple[str, str]:
    name = Path(upload.filename or "upload").name.strip() or "upload"
    suffix = Path(name).suffix.lower().lstrip(".")
    fmt = "html" if suffix == "htm" else suffix
    return name, fmt


def _project_name(orm: Session, project_id: uuid.UUID) -> str:
    row = orm.execute(
        text("SELECT name FROM public.projects WHERE id = :project_id"),
        {"project_id": str(project_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return str(row.name)


def _extract_source(filename: str, fmt: str, raw: bytes) -> MaterialSource:
    suffix = ".htm" if fmt == "html" and filename.lower().endswith(".htm") else f".{fmt}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(raw)
        temp_path = Path(handle.name)
    try:
        extracted = extract_text(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return MaterialSource(
        filename=filename,
        format=extracted.format,
        text=extracted.text,
        size_bytes=len(raw),
        content_hash=hashlib.sha256(raw).hexdigest(),
    )


def _write_temp_file(filename: str, fmt: str, raw: bytes) -> Path:
    suffix = Path(filename).suffix or f".{fmt}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(raw)
        return Path(handle.name)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


@router.post(
    "/knowledge/material-intakes/preview",
    response_model=MaterialIntakePreviewResponse,
)
def preview_project_materials(
    request: Request,
    project_id: uuid.UUID = Form(...),
    department_id: str = Form(...),
    files: list[UploadFile] = File(...),
    orm: Session = Depends(get_orm_session),
) -> MaterialIntakePreviewResponse:
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if not files:
        raise HTTPException(status_code=400, detail="at least one project material file is required")

    uploads: list[tuple[MaterialSource, bytes]] = []
    for upload in files:
        filename, fmt = _safe_upload_name(upload)
        if fmt not in SUPPORTED_FORMATS:
            raise HTTPException(status_code=400, detail=f"unsupported format: {filename}")
        raw = upload.file.read()
        uploads.append((_extract_source(filename, fmt, raw), raw))
    try:
        validate_batch_limits((source.filename, source.size_bytes) for source, _ in uploads)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    existing_hashes = {
        str(row.content_hash)
        for row in orm.execute(
            text("""
                SELECT content_hash
                FROM public.project_material_documents
                WHERE project_id = :project_id AND content_hash IS NOT NULL
            """),
            {"project_id": str(project_id)},
        ).all()
    }
    preview = preview_materials(
        [source for source, _ in uploads],
        existing_hashes=existing_hashes,
    )
    intake_row = orm.execute(
        text("""
            INSERT INTO public.project_material_intakes (
                project_id, department_id, status, preview_summary,
                preview_model, preview_used_fallback, created_by_user_id
            )
            VALUES (
                :project_id, :department_id, 'preview_ready', :summary,
                :model, :used_fallback, :user_id
            )
            RETURNING id::text
        """),
        {
            "project_id": str(project_id),
            "department_id": department_id,
            "summary": preview.summary,
            "model": preview.model,
            "used_fallback": preview.used_fallback,
            "user_id": str(user_id),
        },
    ).first()
    if intake_row is None:
        raise HTTPException(status_code=503, detail="failed to create material preview")
    intake_id = uuid.UUID(str(intake_row.id))

    response_items: list[MaterialPreviewFileSchema] = []
    for (source, raw), item in zip(uploads, preview.items):
        retain_payload = item.recommendation not in {"duplicate", "sensitive", "low_value"}
        row = orm.execute(
            text("""
                INSERT INTO public.project_material_intake_files (
                    intake_id, filename, format, size_bytes, content_hash,
                    raw_content, extracted_text, recommendation, included,
                    reason, issues
                )
                VALUES (
                    :intake_id, :filename, :format, :size_bytes, :content_hash,
                    :raw_content, :extracted_text, :recommendation, :included,
                    :reason, CAST(:issues AS jsonb)
                )
                RETURNING id::text
            """),
            {
                "intake_id": str(intake_id),
                "filename": source.filename,
                "format": source.format,
                "size_bytes": source.size_bytes,
                "content_hash": source.content_hash,
                "raw_content": raw if retain_payload else b"",
                "extracted_text": source.text if retain_payload else "",
                "recommendation": item.recommendation,
                "included": item.included,
                "reason": item.reason,
                "issues": _json(list(item.issues)),
            },
        ).first()
        if row is None:
            raise HTTPException(status_code=503, detail="failed to store material preview file")
        response_items.append(
            MaterialPreviewFileSchema(
                id=uuid.UUID(str(row.id)),
                filename=item.filename,
                format=item.format,
                size_bytes=item.size_bytes,
                content_hash=item.content_hash,
                recommendation=item.recommendation,
                included=item.included,
                reason=item.reason,
                issues=list(item.issues),
            )
        )
    orm.commit()
    return MaterialIntakePreviewResponse(
        id=intake_id,
        project_id=project_id,
        status="preview_ready",
        summary=preview.summary,
        model=preview.model,
        used_fallback=preview.used_fallback,
        items=response_items,
    )


@router.post(
    "/knowledge/material-intakes/{intake_id}/confirm",
    response_model=ConfirmMaterialIntakeResponse,
)
def confirm_project_materials(
    request: Request,
    intake_id: uuid.UUID,
    body: ConfirmMaterialIntakeRequest,
    orm: Session = Depends(get_orm_session),
) -> ConfirmMaterialIntakeResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    intake = orm.execute(
        text("""
            SELECT id::text, project_id::text, department_id, status,
                   created_by_user_id::text
            FROM public.project_material_intakes
            WHERE id = :intake_id
            FOR UPDATE
        """),
        {"intake_id": str(intake_id)},
    ).first()
    if intake is None:
        raise HTTPException(status_code=404, detail="material preview not found")
    project_id = uuid.UUID(str(intake.project_id))
    try:
        require_member(orm, user_id=user_id, project_id=project_id)
        if str(intake.created_by_user_id or "") != str(user_id):
            require_admin(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if intake.status != "preview_ready":
        raise HTTPException(status_code=409, detail=f"material preview already {intake.status}")

    file_rows = orm.execute(
        text("""
            SELECT id::text, filename, format, size_bytes, content_hash,
                   raw_content, extracted_text, recommendation, included
            FROM public.project_material_intake_files
            WHERE intake_id = :intake_id
            ORDER BY created_at, filename
        """),
        {"intake_id": str(intake_id)},
    ).all()
    selected = select_confirmed_files(
        file_rows,
        requested_ids={str(file_id) for file_id in body.included_file_ids},
    )
    if not selected:
        raise HTTPException(status_code=400, detail="no useful material selected")

    orm.execute(
        text("""
            UPDATE public.project_material_intakes
            SET status = 'processing', updated_at = now()
            WHERE id = :intake_id
        """),
        {"intake_id": str(intake_id)},
    )
    orm.commit()

    project_name = _project_name(orm, project_id)
    sources = [
        MaterialSource(
            filename=str(row.filename),
            format=str(row.format),
            text=str(row.extracted_text),
            size_bytes=int(row.size_bytes),
            content_hash=str(row.content_hash),
        )
        for row in selected
    ]
    try:
        package = generate_knowledge_package(project_name=project_name, sources=sources)
        raw_documents: list[tuple[object, uuid.UUID]] = []
        for row in selected:
            temp_path = _write_temp_file(str(row.filename), str(row.format), bytes(row.raw_content))
            try:
                result = ingest_file(
                    temp_path,
                    project_id=project_id,
                    display_name=str(row.filename),
                    created_by_user_id=user_id,
                )
            finally:
                temp_path.unlink(missing_ok=True)
            if result.error:
                raise RuntimeError(f"raw material ingest failed: {result.error}")
            raw_documents.append((row, result.document_id))

        curated_result = ingest_markdown_memory(
            markdown=package.curated_markdown,
            project_id=project_id,
            display_name=f"{project_name} - 项目资料整理版.md",
            created_by_user_id=user_id,
        )
        if curated_result.error:
            raise RuntimeError(f"curated source ingest failed: {curated_result.error}")

        skill_payload = [
            {
                "title": skill.title,
                "summary": skill.summary,
                "markdown_content": skill.markdown_content,
                "source_filenames": list(skill.source_filenames),
            }
            for skill in package.skills
        ]
        review_markdown = build_review_markdown(
            project_name=project_name,
            curated_markdown=package.curated_markdown,
            skills=package.skills,
        )
        draft_row = orm.execute(
            text("""
                INSERT INTO public.project_memory_drafts (
                    project_id, department_id, title, status, template_version,
                    markdown_content, source_count, created_by_user_id,
                    intake_id, curated_markdown_content, skill_candidates,
                    generation_model, generation_used_fallback
                )
                VALUES (
                    :project_id, :department_id, :title, 'pending_review',
                    'project-memory-v2', :markdown_content, :source_count, :user_id,
                    :intake_id, :curated_markdown, CAST(:skills AS jsonb),
                    :model, :used_fallback
                )
                RETURNING id::text
            """),
            {
                "project_id": str(project_id),
                "department_id": str(intake.department_id),
                "title": f"{project_name} 资料整理与 Skill",
                "markdown_content": review_markdown,
                "source_count": len(sources),
                "user_id": str(user_id),
                "intake_id": str(intake_id),
                "curated_markdown": package.curated_markdown,
                "skills": _json(skill_payload),
                "model": package.model,
                "used_fallback": package.used_fallback,
            },
        ).first()
        if draft_row is None:
            raise RuntimeError("failed to create memory review batch")
        draft_id = uuid.UUID(str(draft_row.id))

        orm.execute(
            text("""
                UPDATE public.documents
                SET memory_type = 'curated_project_source',
                    memory_draft_id = :draft_id,
                    template_version = 'project-memory-v2'
                WHERE id = :document_id
            """),
            {
                "draft_id": str(draft_id),
                "document_id": str(curated_result.document_id),
            },
        )
        for source in sources:
            orm.execute(
                text("""
                    INSERT INTO public.project_memory_draft_sources (
                        draft_id, filename, format, extracted_text,
                        size_bytes, content_hash
                    )
                    VALUES (
                        :draft_id, :filename, :format, :text,
                        :size_bytes, :content_hash
                    )
                """),
                {
                    "draft_id": str(draft_id),
                    "filename": source.filename,
                    "format": source.format,
                    "text": source.text,
                    "size_bytes": source.size_bytes,
                    "content_hash": source.content_hash,
                },
            )
        for row, document_id in raw_documents:
            orm.execute(
                text("""
                    UPDATE public.documents
                    SET memory_type = 'raw_project_material',
                        memory_draft_id = :draft_id,
                        template_version = 'project-memory-v2'
                    WHERE id = :document_id
                """),
                {"draft_id": str(draft_id), "document_id": str(document_id)},
            )
            orm.execute(
                text("""
                    UPDATE public.project_material_intake_files
                    SET document_id = :document_id,
                        included = true
                    WHERE id = :file_id
                """),
                {"document_id": str(document_id), "file_id": str(row.id)},
            )
            orm.execute(
                text("""
                    INSERT INTO public.project_material_documents (
                        project_id, document_id, draft_id, uploaded_by_user_id,
                        content_hash, original_file_id
                    )
                    VALUES (
                        :project_id, :document_id, :draft_id, :user_id,
                        :content_hash, :file_id
                    )
                    ON CONFLICT (document_id) DO UPDATE SET
                        draft_id = excluded.draft_id,
                        content_hash = excluded.content_hash,
                        original_file_id = excluded.original_file_id
                """),
                {
                    "project_id": str(project_id),
                    "document_id": str(document_id),
                    "draft_id": str(draft_id),
                    "user_id": str(user_id),
                    "content_hash": str(row.content_hash),
                    "file_id": str(row.id),
                },
            )
        orm.execute(
            text("""
                UPDATE public.project_material_intakes
                SET status = 'pending_review', confirmed_at = now(), updated_at = now()
                WHERE id = :intake_id
            """),
            {"intake_id": str(intake_id)},
        )
        orm.commit()
    except Exception as error:
        orm.execute(
            text("""
                UPDATE public.project_material_intakes
                SET status = 'failed', updated_at = now()
                WHERE id = :intake_id
            """),
            {"intake_id": str(intake_id)},
        )
        orm.commit()
        raise HTTPException(status_code=503, detail=f"material processing failed: {error}") from error

    record_audit(
        orm,
        user_id=user_id,
        action="upload",
        resource_type="project_material_intake",
        resource_id=str(intake_id),
        metadata={
            "project_id": str(project_id),
            "raw_document_count": len(raw_documents),
            "draft_id": str(draft_id),
            "skill_count": len(package.skills),
        },
        request=request,
    )
    return ConfirmMaterialIntakeResponse(
        intake_id=intake_id,
        status="pending_review",
        raw_document_count=len(raw_documents),
        curated_document_id=curated_result.document_id,
        draft_id=draft_id,
        skill_count=len(package.skills),
        generation_model=package.model,
        generation_used_fallback=package.used_fallback,
    )


@router.get("/knowledge/material-intakes/{intake_id}/files/{file_id}/download")
def download_original_material(
    request: Request,
    intake_id: uuid.UUID,
    file_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> Response:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    row = orm.execute(
        text("""
            SELECT f.filename, f.raw_content, i.project_id::text
            FROM public.project_material_intake_files f
            JOIN public.project_material_intakes i ON i.id = f.intake_id
            WHERE f.id = :file_id AND f.intake_id = :intake_id
        """),
        {"file_id": str(file_id), "intake_id": str(intake_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="original material not found")
    project_id = uuid.UUID(str(row.project_id))
    try:
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    filename = str(row.filename)
    return Response(
        content=bytes(row.raw_content),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename=material; filename*=UTF-8''{quote(filename)}"
            )
        },
    )
