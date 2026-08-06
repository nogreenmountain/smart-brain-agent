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
from agentops.project_memory.intake import (
    build_original_material_review_markdown,
    select_confirmed_files,
    validate_batch_limits,
)
from agentops.project_memory.intelligence import (
    MaterialSource,
    preview_materials,
)
from agentops.project_memory.parsers import SUPPORTED_FORMATS, extract_text
from agentops.rag.audit import record_audit
from agentops.rag.authz import AuthzError, current_user_id, require_admin, require_member


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
    draft_id: uuid.UUID


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
        retain_payload = item.recommendation == "keep" and item.included
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
                   created_by_user_id::text, preview_model, preview_used_fallback
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
                   raw_content, extracted_text, recommendation, included, reason
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

    project_name = _project_name(orm, project_id)
    review_markdown = build_original_material_review_markdown(
        project_name=project_name,
        files=selected,
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
                'project-material-original-v1', :markdown_content, :source_count,
                :user_id, :intake_id, NULL, '[]'::jsonb, :model, :used_fallback
            )
            RETURNING id::text
        """),
        {
            "project_id": str(project_id),
            "department_id": str(intake.department_id),
            "title": f"{project_name} 原始项目资料审批",
            "markdown_content": review_markdown,
            "source_count": len(selected),
            "user_id": str(user_id),
            "intake_id": str(intake_id),
            "model": getattr(intake, "preview_model", None),
            "used_fallback": bool(getattr(intake, "preview_used_fallback", False)),
        },
    ).first()
    if draft_row is None:
        raise HTTPException(status_code=503, detail="failed to create original material review batch")
    draft_id = uuid.UUID(str(draft_row.id))
    selected_ids = [str(row.id) for row in selected]
    orm.execute(
        text("""
            UPDATE public.project_material_intake_files
            SET included = (id::text = ANY(CAST(:selected_ids AS text[])))
            WHERE intake_id = :intake_id
        """),
        {"intake_id": str(intake_id), "selected_ids": selected_ids},
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

    record_audit(
        orm,
        user_id=user_id,
        action="upload",
        resource_type="project_material_intake",
        resource_id=str(intake_id),
        metadata={
            "project_id": str(project_id),
            "raw_document_count": len(selected),
            "draft_id": str(draft_id),
            "ai_summary_generated": False,
        },
        request=request,
    )
    return ConfirmMaterialIntakeResponse(
        intake_id=intake_id,
        status="pending_review",
        raw_document_count=len(selected),
        draft_id=draft_id,
    )


@router.delete("/knowledge/material-intakes/{intake_id}", status_code=204)
def cancel_project_materials(
    request: Request,
    intake_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> Response:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    intake = orm.execute(
        text("""
            SELECT id::text, project_id::text, status, created_by_user_id::text
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
    orm.execute(
        text("DELETE FROM public.project_material_intakes WHERE id = :intake_id"),
        {"intake_id": str(intake_id)},
    )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="upload",
        resource_type="project_material_intake",
        resource_id=str(intake_id),
        metadata={"project_id": str(project_id), "result": "cancelled"},
        request=request,
    )
    return Response(status_code=204)


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
