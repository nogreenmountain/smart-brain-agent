from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
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
from agentops.project_memory.storage import (
    MaterialStorageConflict,
    append_chunk,
    build_storage_key,
    file_size,
    resolve_storage_key,
    sha256_file,
)
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


class MaterialUploadManifestFile(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(..., gt=0)


class CreateMaterialUploadSessionRequest(BaseModel):
    project_id: uuid.UUID
    department_id: str = Field(..., min_length=1, max_length=80)
    client_upload_id: uuid.UUID
    files: list[MaterialUploadManifestFile] = Field(..., min_length=1)


class MaterialUploadSessionFileSchema(BaseModel):
    id: uuid.UUID
    filename: str
    format: str
    size_bytes: int
    received_bytes: int


class MaterialUploadSessionResponse(BaseModel):
    intake_id: uuid.UUID
    status: str
    files: list[MaterialUploadSessionFileSchema]


class MaterialUploadChunkResponse(BaseModel):
    file_id: uuid.UUID
    received_bytes: int
    size_bytes: int


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


def _project_department_id(orm: Session, project_id: uuid.UUID) -> str:
    row = orm.execute(
        text("""
            SELECT department_id
            FROM public.projects
            WHERE id = :project_id
            FOR SHARE
        """),
        {"project_id": str(project_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return str(row.department_id)


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


def _safe_manifest_name(filename: str) -> tuple[str, str]:
    name = Path(filename).name.strip() or "upload"
    suffix = Path(name).suffix.lower().lstrip(".")
    fmt = "html" if suffix == "htm" else suffix
    return name, fmt


@router.post(
    "/knowledge/material-intakes/upload-sessions",
    response_model=MaterialUploadSessionResponse,
    status_code=201,
)
def create_material_upload_session(
    request: Request,
    body: CreateMaterialUploadSessionRequest,
    orm: Session = Depends(get_orm_session),
) -> MaterialUploadSessionResponse:
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=body.project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    current_department_id = _project_department_id(orm, body.project_id)
    if body.department_id != current_department_id:
        raise HTTPException(
            status_code=409,
            detail="project category changed; refresh the project before uploading materials",
        )

    manifest: list[tuple[str, str, int]] = []
    seen_names: set[str] = set()
    for item in body.files:
        filename, fmt = _safe_manifest_name(item.filename)
        if fmt not in SUPPORTED_FORMATS:
            raise HTTPException(status_code=400, detail=f"unsupported format: {filename}")
        if filename in seen_names:
            raise HTTPException(status_code=400, detail=f"duplicate filename in batch: {filename}")
        seen_names.add(filename)
        manifest.append((filename, fmt, item.size_bytes))
    try:
        validate_batch_limits((filename, size_bytes) for filename, _, size_bytes in manifest)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    existing = orm.execute(
        text("""
            SELECT id::text, status
            FROM public.project_material_intakes
            WHERE project_id = :project_id
              AND created_by_user_id = :user_id
              AND client_upload_id = :client_upload_id
        """),
        {
            "project_id": str(body.project_id),
            "user_id": str(user_id),
            "client_upload_id": str(body.client_upload_id),
        },
    ).first()
    if existing is not None:
        file_rows = orm.execute(
            text("""
                SELECT id::text, filename, format, size_bytes, uploaded_bytes
                FROM public.project_material_intake_files
                WHERE intake_id = :intake_id
                ORDER BY created_at, filename
            """),
            {"intake_id": str(existing.id)},
        ).all()
        return MaterialUploadSessionResponse(
            intake_id=uuid.UUID(str(existing.id)),
            status=str(existing.status),
            files=[
                MaterialUploadSessionFileSchema(
                    id=uuid.UUID(str(row.id)),
                    filename=str(row.filename),
                    format=str(row.format),
                    size_bytes=int(row.size_bytes),
                    received_bytes=int(row.uploaded_bytes or 0),
                )
                for row in file_rows
            ],
        )

    intake_id = uuid.uuid4()
    orm.execute(
        text("""
            INSERT INTO public.project_material_intakes (
                id, project_id, department_id, status, preview_summary,
                preview_used_fallback, created_by_user_id, client_upload_id
            )
            VALUES (
                :intake_id, :project_id, :department_id, 'uploading',
                '文件正在直接上传，未执行 AI 敏感信息识别', false, :user_id,
                :client_upload_id
            )
        """),
        {
            "intake_id": str(intake_id),
            "project_id": str(body.project_id),
            "department_id": body.department_id,
            "user_id": str(user_id),
            "client_upload_id": str(body.client_upload_id),
        },
    )
    response_files: list[MaterialUploadSessionFileSchema] = []
    for filename, fmt, size_bytes in manifest:
        file_id = uuid.uuid4()
        storage_key = build_storage_key(
            project_id=body.project_id,
            intake_id=intake_id,
            file_id=file_id,
            filename=filename,
        )
        orm.execute(
            text("""
                INSERT INTO public.project_material_intake_files (
                    id, intake_id, filename, format, size_bytes, content_hash,
                    raw_content, extracted_text, recommendation, included,
                    reason, issues, storage_key, uploaded_bytes
                )
                VALUES (
                    :file_id, :intake_id, :filename, :format, :size_bytes, '',
                    ''::bytea, '', 'keep', true,
                    '直接上传，未执行 AI 敏感信息识别', '[]'::jsonb,
                    :storage_key, 0
                )
            """),
            {
                "file_id": str(file_id),
                "intake_id": str(intake_id),
                "filename": filename,
                "format": fmt,
                "size_bytes": size_bytes,
                "storage_key": storage_key,
            },
        )
        response_files.append(
            MaterialUploadSessionFileSchema(
                id=file_id,
                filename=filename,
                format=fmt,
                size_bytes=size_bytes,
                received_bytes=0,
            )
        )
    orm.commit()
    return MaterialUploadSessionResponse(
        intake_id=intake_id,
        status="uploading",
        files=response_files,
    )


@router.put(
    "/knowledge/material-intakes/upload-sessions/{intake_id}/files/{file_id}",
    response_model=MaterialUploadChunkResponse,
)
async def upload_material_chunk(
    request: Request,
    intake_id: uuid.UUID,
    file_id: uuid.UUID,
    offset: int = Query(..., ge=0),
    orm: Session = Depends(get_orm_session),
) -> MaterialUploadChunkResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    # Receive the bounded chunk before opening a database transaction. Public
    # relay uploads can be slow; holding a row lock and a pooled connection while
    # the request body is still arriving starves concurrent uploads.
    chunk = await request.body()
    if not chunk:
        raise HTTPException(status_code=400, detail="upload chunk is empty")
    if len(chunk) > 16 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="upload chunk exceeds 16 MB")

    row = orm.execute(
        text("""
            SELECT file.id::text, file.intake_id::text, intake.project_id::text,
                   intake.status, intake.created_by_user_id::text,
                   file.filename, file.size_bytes, file.storage_key,
                   file.uploaded_bytes
            FROM public.project_material_intake_files file
            JOIN public.project_material_intakes intake ON intake.id = file.intake_id
            WHERE file.id = :file_id AND file.intake_id = :intake_id
            FOR UPDATE
        """),
        {"file_id": str(file_id), "intake_id": str(intake_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="material upload file not found")
    project_id = uuid.UUID(str(row.project_id))
    try:
        require_member(orm, user_id=user_id, project_id=project_id)
        if str(row.created_by_user_id or "") != str(user_id):
            require_admin(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if row.status != "uploading":
        raise HTTPException(status_code=409, detail=f"material upload already {row.status}")
    if not row.storage_key:
        raise HTTPException(status_code=500, detail="material upload storage is not configured")

    if offset + len(chunk) > int(row.size_bytes):
        raise HTTPException(status_code=400, detail="upload chunk exceeds declared file size")
    try:
        received_bytes = append_chunk(str(row.storage_key), offset=offset, chunk=chunk)
    except MaterialStorageConflict as error:
        raise HTTPException(
            status_code=409,
            detail=f"chunk offset mismatch; received_bytes={error.received_bytes}",
        ) from error

    orm.execute(
        text("""
            UPDATE public.project_material_intake_files
            SET uploaded_bytes = :uploaded_bytes
            WHERE id = :file_id
        """),
        {"uploaded_bytes": received_bytes, "file_id": str(file_id)},
    )
    orm.commit()
    return MaterialUploadChunkResponse(
        file_id=file_id,
        received_bytes=received_bytes,
        size_bytes=int(row.size_bytes),
    )


@router.post(
    "/knowledge/material-intakes/upload-sessions/{intake_id}/complete",
    response_model=ConfirmMaterialIntakeResponse,
)
def complete_material_upload_session(
    request: Request,
    intake_id: uuid.UUID,
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
        raise HTTPException(status_code=404, detail="material upload session not found")
    project_id = uuid.UUID(str(intake.project_id))
    try:
        require_member(orm, user_id=user_id, project_id=project_id)
        if str(intake.created_by_user_id or "") != str(user_id):
            require_admin(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    if intake.status == "pending_review":
        draft = orm.execute(
            text("SELECT id::text FROM public.project_memory_drafts WHERE intake_id = :intake_id"),
            {"intake_id": str(intake_id)},
        ).first()
        if draft is None:
            raise HTTPException(status_code=500, detail="completed upload is missing its review draft")
        count_row = orm.execute(
            text("SELECT COUNT(*) AS count FROM public.project_material_intake_files WHERE intake_id = :intake_id"),
            {"intake_id": str(intake_id)},
        ).first()
        return ConfirmMaterialIntakeResponse(
            intake_id=intake_id,
            status="pending_review",
            raw_document_count=int(count_row.count if count_row else 0),
            draft_id=uuid.UUID(str(draft.id)),
        )
    if intake.status != "uploading":
        raise HTTPException(status_code=409, detail=f"material upload already {intake.status}")

    file_rows = orm.execute(
        text("""
            SELECT id::text, filename, format, size_bytes, content_hash,
                   raw_content, extracted_text, recommendation, included,
                   reason, storage_key, uploaded_bytes
            FROM public.project_material_intake_files
            WHERE intake_id = :intake_id
            ORDER BY created_at, filename
        """),
        {"intake_id": str(intake_id)},
    ).all()
    if not file_rows:
        raise HTTPException(status_code=400, detail="material upload session has no files")

    for row in file_rows:
        expected_size = int(row.size_bytes)
        received_bytes = int(row.uploaded_bytes or 0)
        if received_bytes != expected_size or not row.storage_key:
            raise HTTPException(
                status_code=409,
                detail=f"file upload incomplete: {row.filename} ({received_bytes}/{expected_size})",
            )
        stored_size = file_size(str(row.storage_key))
        if stored_size != expected_size:
            raise HTTPException(
                status_code=409,
                detail=f"stored file size mismatch: {row.filename} ({stored_size}/{expected_size})",
            )
        orm.execute(
            text("""
                UPDATE public.project_material_intake_files
                SET content_hash = :content_hash,
                    recommendation = 'keep', included = true,
                    reason = '直接上传，未执行 AI 敏感信息识别', issues = '[]'::jsonb
                WHERE id = :file_id
            """),
            {"content_hash": sha256_file(str(row.storage_key)), "file_id": str(row.id)},
        )

    project_name = _project_name(orm, project_id)
    review_markdown = build_original_material_review_markdown(
        project_name=project_name,
        files=file_rows,
    )
    draft_row = orm.execute(
        text("""
            INSERT INTO public.project_memory_drafts (
                project_id, department_id, title, status, template_version,
                markdown_content, source_count, created_by_user_id, intake_id,
                skill_candidates, generation_used_fallback
            )
            VALUES (
                :project_id, :department_id, :title, 'pending_review',
                'project-material-original-v1', :markdown_content, :source_count,
                :user_id, :intake_id, '[]'::jsonb, false
            )
            RETURNING id::text
        """),
        {
            "project_id": str(project_id),
            "department_id": str(intake.department_id),
            "title": f"{project_name} 原始项目资料审批",
            "markdown_content": review_markdown,
            "source_count": len(file_rows),
            "user_id": str(user_id),
            "intake_id": str(intake_id),
        },
    ).first()
    if draft_row is None:
        raise HTTPException(status_code=503, detail="failed to create material review draft")
    draft_id = uuid.UUID(str(draft_row.id))

    orm.execute(
        text("""
            UPDATE public.project_material_intakes
            SET status = 'pending_review', confirmed_at = now(),
                upload_completed_at = now(), updated_at = now()
            WHERE id = :intake_id
        """),
        {"intake_id": str(intake_id)},
    )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="material_batch_upload",
        resource_type="project_material_intake",
        resource_id=str(intake_id),
        metadata={
            "project_id": str(project_id),
            "department_id": str(intake.department_id),
            "raw_document_count": len(file_rows),
            "ai_sensitive_scan": False,
        },
        request=request,
    )
    return ConfirmMaterialIntakeResponse(
        intake_id=intake_id,
        status="pending_review",
        raw_document_count=len(file_rows),
        draft_id=draft_id,
    )


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
    current_department_id = _project_department_id(orm, project_id)
    if department_id != current_department_id:
        raise HTTPException(
            status_code=409,
            detail="project category changed; refresh the project before uploading materials",
        )
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
            SELECT f.filename, f.raw_content, f.storage_key, i.project_id::text
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
    if getattr(row, "storage_key", None):
        stored_path = resolve_storage_key(str(row.storage_key))
        if not stored_path.is_file():
            raise HTTPException(status_code=404, detail="original material payload is missing")
        return FileResponse(
            path=stored_path,
            media_type="application/octet-stream",
            filename=filename,
        )
    return Response(
        content=bytes(row.raw_content),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename=material; filename*=UTF-8''{quote(filename)}"
            )
        },
    )
