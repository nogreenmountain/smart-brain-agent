"""
Knowledge base API: upload, search, answer (with LLM synthesis).

Endpoints:
  POST /v4/knowledge/upload   multipart file + project_id  -> ingest
  POST /v4/knowledge/search   { project_id, query, k? }   -> top-k chunks
  POST /v4/knowledge/answer   { project_id, query, k? }   -> top-k + LLM synthesis
                              (uses Anthropic-protocol LLM if ANTHROPIC_AUTH_TOKEN
                               is set; falls back to template synthesis otherwise)

Auth: none in MVP. project_id is the trust boundary. Production should
gate by org membership.
"""
from __future__ import annotations

import logging
import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import List, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.common.orm import get_orm_session
from agentops.auth.middleware import AuthenticatedRoute
from agentops.rag.ingest import ingest_file
from agentops.rag.search import search, SearchHit
from agentops.rag.answer import synthesize as llm_synthesize
from agentops.rag.authz import (
    AuthzError,
    current_user_id,
    is_system_admin,
    require_admin,
    require_owner,
    require_writer,
    require_member,
)
from agentops.rag.audit import record_audit
from agentops.project_memory.parsers import SUPPORTED_FORMATS, extract_text
from agentops.project_memory.ingest import ingest_markdown_memory
from agentops.project_memory.storage import resolve_storage_key
from agentops.project_memory.templates import (
    TEMPLATE_VERSION,
    SourceText,
    build_project_memory_markdown,
)
from agentops.api.routes.v4.project_memory import (
    DepartmentId,
    ProjectMemoryDraftSchema,
    _department_name,
    _project_name,
    _repository_for_project,
    _row_to_draft,
)


router = APIRouter(route_class=AuthenticatedRoute)
logger = logging.getLogger(__name__)


ALLOWED_FORMATS = SUPPORTED_FORMATS


# --- upload -----------------------------------------------------------------

class UploadResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    chunk_count: int
    status: str
    error: Optional[str] = None


class MaterialDocumentResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    format: str
    chunk_count: int
    status: str


class MaterialBatchUploadResponse(BaseModel):
    raw_document_count: int
    raw_documents: list[MaterialDocumentResponse]
    draft: ProjectMemoryDraftSchema


class KnowledgeLedgerUser(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str | None = None


class KnowledgeLedgerProject(BaseModel):
    id: uuid.UUID
    name: str
    environment: str
    department_id: DepartmentId
    created_at: str | None = None
    completed_at: str | None = None


class KnowledgeLedgerPermissions(BaseModel):
    can_review: bool
    can_manage: bool
    can_delete: bool


class KnowledgeLedgerSummary(BaseModel):
    raw_document_count: int = 0
    approved_count: int = 0
    pending_count: int = 0
    rejected_count: int = 0
    unreviewed_count: int = 0
    latest_uploaded_at: str | None = None
    latest_reviewed_at: str | None = None


class KnowledgeLedgerDocument(BaseModel):
    asset_id: uuid.UUID
    asset_type: Literal["project_material", "project_wiki", "meeting_record"]
    document_id: uuid.UUID | None = None
    filename: str
    display_name: str
    format: str
    size_bytes: int
    status: str
    chunk_count: int
    error_message: str | None = None
    uploaded_by: KnowledgeLedgerUser | None = None
    uploaded_at: str
    approval_status: Literal["raw_uploaded", "pending_review", "approved", "rejected"]
    reviewed_by: KnowledgeLedgerUser | None = None
    reviewed_at: str | None = None
    review_comment: str | None = None
    draft_id: uuid.UUID | None = None
    approved_memory_document_id: uuid.UUID | None = None
    intake_id: uuid.UUID | None = None
    original_file_id: uuid.UUID | None = None
    meeting_date: str | None = None


class KnowledgeLedgerResponse(BaseModel):
    category: Literal["project_material", "project_wiki_source", "meeting_record"]
    project: KnowledgeLedgerProject
    permissions: KnowledgeLedgerPermissions
    leaders: list[KnowledgeLedgerUser]
    uploaders: list[KnowledgeLedgerUser]
    summary: KnowledgeLedgerSummary
    documents: list[KnowledgeLedgerDocument]


KnowledgeAssetType = Literal["project_material", "project_wiki", "meeting_record"]


class KnowledgeAssetRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class KnowledgeAssetMoveRequest(BaseModel):
    target_project_id: uuid.UUID


class KnowledgeAssetMutationResponse(BaseModel):
    asset_id: uuid.UUID
    asset_type: KnowledgeAssetType
    project_id: uuid.UUID
    name: str


class KnowledgeAssetPreviewResponse(BaseModel):
    asset_id: uuid.UUID
    asset_type: KnowledgeAssetType
    project_id: uuid.UUID
    name: str
    format: str
    content: str


def _safe_upload_name(file: UploadFile) -> tuple[str, str]:
    raw = file.filename or "upload"
    safe_name = Path(raw).name
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    ext = "html" if ext == "htm" else ext
    return safe_name, ext


def _copy_upload_to_temp(file: UploadFile, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        return Path(tmp.name)


def _ledger_user(user_id: str | None, email: str | None, role: str | None = None) -> KnowledgeLedgerUser | None:
    if not user_id or not email:
        return None
    return KnowledgeLedgerUser(user_id=uuid.UUID(str(user_id)), email=email, role=role)


def _approval_status(value: str | None) -> Literal["raw_uploaded", "pending_review", "approved", "rejected"]:
    if value in {"pending_review", "approved", "rejected"}:
        return value
    return "raw_uploaded"


def _asset_user(request: Request) -> uuid.UUID:
    try:
        return current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _asset_authorize(check, orm: Session, *, user_id: uuid.UUID, project_id: uuid.UUID) -> None:
    try:
        check(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _load_asset(orm: Session, *, asset_type: KnowledgeAssetType, asset_id: uuid.UUID):
    if asset_type == "project_material":
        return orm.execute(
            text("""
                SELECT d.id::text AS asset_id, d.project_id::text AS project_id,
                       d.display_name AS name, d.filename, d.format,
                       d.id::text AS document_id,
                       file.id::text AS original_file_id, file.filename AS original_filename,
                       CASE d.format
                           WHEN 'pdf' THEN 'application/pdf'
                           WHEN 'md' THEN 'text/markdown; charset=utf-8'
                           WHEN 'txt' THEN 'text/plain; charset=utf-8'
                           WHEN 'csv' THEN 'text/csv; charset=utf-8'
                           WHEN 'docx' THEN 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                           WHEN 'xlsx' THEN 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                           WHEN 'pptx' THEN 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
                           ELSE 'application/octet-stream'
                       END AS mime_type,
                       file.raw_content, file.storage_key
                FROM public.documents d
                LEFT JOIN public.project_material_documents material
                       ON material.document_id = d.id
                LEFT JOIN public.project_material_intake_files file
                       ON file.id = material.original_file_id
                WHERE d.id = :asset_id
                  AND COALESCE(d.memory_type, 'raw_project_material') = 'raw_project_material'
            """),
            {"asset_id": str(asset_id)},
        ).first()
    if asset_type == "project_wiki":
        return orm.execute(
            text("""
                SELECT page.id::text AS asset_id, page.project_id::text AS project_id,
                       page.title AS name, page.page_key, page.markdown_content,
                       page.document_id::text AS document_id
                FROM public.project_wiki_pages page
                WHERE page.id = :asset_id OR page.document_id = :asset_id
            """),
            {"asset_id": str(asset_id)},
        ).first()
    return orm.execute(
        text("""
            SELECT meeting.id::text AS asset_id, meeting.project_id::text AS project_id,
                   meeting.title AS name, meeting.summary_markdown,
                   file.filename AS original_filename, file.format, file.mime_type,
                   file.raw_content
            FROM public.meeting_summaries meeting
            LEFT JOIN public.meeting_summary_files file
                   ON file.meeting_summary_id = meeting.id
            WHERE meeting.id = :asset_id
        """),
        {"asset_id": str(asset_id)},
    ).first()


def _require_asset(orm: Session, *, asset_type: KnowledgeAssetType, asset_id: uuid.UUID):
    row = _load_asset(orm, asset_type=asset_type, asset_id=asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="knowledge asset not found")
    return row


def _embed_asset(value: str) -> list[float] | None:
    try:
        from agentops.rag.model_clients import EmbeddingServiceClient

        return EmbeddingServiceClient().embed_documents([value])[0]
    except Exception:
        return None


@router.get("/knowledge/ledger", response_model=KnowledgeLedgerResponse)
def get_knowledge_ledger(
    request: Request,
    project_id: uuid.UUID,
    category: Literal["project_material", "project_wiki_source", "meeting_record"] = "project_material",
    uploader_user_id: uuid.UUID | None = None,
    approval_status: Literal["raw_uploaded", "pending_review", "approved", "rejected"] | None = None,
    uploaded_from: str | None = None,
    uploaded_to: str | None = None,
    reviewed_from: str | None = None,
    reviewed_to: str | None = None,
    orm: Session = Depends(get_orm_session),
) -> KnowledgeLedgerResponse:
    """Return a read-only project material ledger for any authenticated user."""
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    project_row = orm.execute(
        text("""
            SELECT p.id::text AS id, p.name, p.environment::text AS environment,
                   COALESCE(p.department_id, 'research') AS department_id,
                   p.created_at::text AS created_at, p.completed_at::text AS completed_at
            FROM public.projects p
            WHERE p.id = :project_id
        """),
        {"project_id": str(project_id)},
    ).first()
    if project_row is None:
        raise HTTPException(status_code=404, detail="project not found")

    role_row = orm.execute(
        text("""
            SELECT pm.role::text AS role
            FROM public.project_members pm
            WHERE pm.project_id = :project_id
              AND pm.user_id = :user_id
        """),
        {"project_id": str(project_id), "user_id": str(user_id)},
    ).first()
    system_admin = is_system_admin(orm, user_id=user_id)
    can_review = system_admin or bool(
        role_row and role_row.role in {"owner", "admin"}
    )
    can_manage = can_review
    can_delete = system_admin or bool(role_row and role_row.role == "owner")

    member_rows = orm.execute(
        text("""
            SELECT pm.user_id::text AS user_id, au.email, pm.role::text AS role
            FROM public.project_members pm
            JOIN auth.users au ON au.id = pm.user_id
            WHERE pm.project_id = :project_id
            ORDER BY
                CASE pm.role::text
                    WHEN 'owner' THEN 0
                    WHEN 'admin' THEN 1
                    ELSE 2
                END,
                au.email
        """),
        {"project_id": str(project_id)},
    ).all()
    leaders = [
        KnowledgeLedgerUser(
            user_id=uuid.UUID(str(row.user_id)),
            email=row.email,
            role=row.role,
        )
        for row in member_rows
        if row.role in {"owner", "admin"}
    ]

    if category == "meeting_record":
        meeting_filters = ["meeting.project_id = :project_id"]
        meeting_params: dict[str, str] = {"project_id": str(project_id)}
        if uploader_user_id is not None:
            meeting_filters.append("meeting.created_by = :uploader_user_id")
            meeting_params["uploader_user_id"] = str(uploader_user_id)
        if approval_status == "pending_review":
            meeting_filters.append("draft.status = 'pending_review'")
        elif approval_status == "rejected":
            meeting_filters.append("draft.status = 'rejected'")
        elif approval_status in {"approved", "raw_uploaded"}:
            meeting_filters.append("(draft.status = 'approved' OR meeting.approval_draft_id IS NULL)")
        if uploaded_from:
            meeting_filters.append("meeting.created_at >= CAST(:uploaded_from AS timestamptz)")
            meeting_params["uploaded_from"] = uploaded_from
        if uploaded_to:
            meeting_filters.append("meeting.created_at <= CAST(:uploaded_to AS timestamptz)")
            meeting_params["uploaded_to"] = uploaded_to
        if reviewed_from:
            meeting_filters.append("draft.reviewed_at >= CAST(:reviewed_from AS timestamptz)")
            meeting_params["reviewed_from"] = reviewed_from
        if reviewed_to:
            meeting_filters.append("draft.reviewed_at <= CAST(:reviewed_to AS timestamptz)")
            meeting_params["reviewed_to"] = reviewed_to
        meeting_rows = orm.execute(
            text(f"""
                SELECT meeting.id::text AS asset_id,
                       meeting.title, meeting.meeting_date::text AS meeting_date,
                       meeting.source_filename,
                       file.format, file.size_bytes,
                       meeting.created_at::text AS uploaded_at,
                       meeting.created_by::text AS uploaded_by_user_id,
                       uploader.email AS uploaded_by_email,
                       draft.id::text AS draft_id,
                       draft.status AS draft_status,
                       draft.reviewed_by_user_id::text AS reviewed_by_user_id,
                       reviewer.email AS reviewed_by_email,
                       draft.reviewed_at::text AS reviewed_at,
                       draft.review_comment
                FROM public.meeting_summaries meeting
                LEFT JOIN public.meeting_summary_files file
                       ON file.meeting_summary_id = meeting.id
                LEFT JOIN public.project_memory_drafts draft
                       ON draft.id = meeting.approval_draft_id
                LEFT JOIN auth.users uploader ON uploader.id = meeting.created_by
                LEFT JOIN auth.users reviewer ON reviewer.id = draft.reviewed_by_user_id
                WHERE {" AND ".join(meeting_filters)}
                ORDER BY meeting.meeting_date DESC, meeting.created_at DESC
            """),
            meeting_params,
        ).all()
        uploader_rows = orm.execute(
            text("""
                SELECT DISTINCT meeting.created_by::text AS user_id, au.email
                FROM public.meeting_summaries meeting
                JOIN auth.users au ON au.id = meeting.created_by
                WHERE meeting.project_id = :project_id
                ORDER BY au.email
            """),
            {"project_id": str(project_id)},
        ).all()
        documents: list[KnowledgeLedgerDocument] = []
        summary = KnowledgeLedgerSummary()
        for row in meeting_rows:
            status = "approved" if not row.draft_id else _approval_status(row.draft_status)
            summary.approved_count += int(status == "approved")
            summary.pending_count += int(status == "pending_review")
            summary.rejected_count += int(status == "rejected")
            if row.uploaded_at and (
                summary.latest_uploaded_at is None or str(row.uploaded_at) > summary.latest_uploaded_at
            ):
                summary.latest_uploaded_at = str(row.uploaded_at)
            documents.append(KnowledgeLedgerDocument(
                asset_id=uuid.UUID(str(row.asset_id)),
                asset_type="meeting_record",
                filename=str(row.source_filename or f"{row.title}.md"),
                display_name=str(row.title),
                format=str(row.format or "md"),
                size_bytes=int(row.size_bytes or 0),
                status="ready",
                chunk_count=1,
                uploaded_by=_ledger_user(row.uploaded_by_user_id, row.uploaded_by_email),
                uploaded_at=str(row.uploaded_at),
                approval_status=status,
                reviewed_by=_ledger_user(row.reviewed_by_user_id, row.reviewed_by_email),
                reviewed_at=str(row.reviewed_at) if row.reviewed_at else None,
                review_comment=row.review_comment,
                draft_id=uuid.UUID(str(row.draft_id)) if row.draft_id else None,
                meeting_date=str(row.meeting_date),
            ))
        summary.raw_document_count = len(documents)
        return KnowledgeLedgerResponse(
            category=category,
            project=KnowledgeLedgerProject(
                id=uuid.UUID(str(project_row.id)),
                name=project_row.name,
                environment=project_row.environment,
                department_id=project_row.department_id,
                created_at=str(project_row.created_at) if project_row.created_at else None,
                completed_at=str(project_row.completed_at) if project_row.completed_at else None,
            ),
            permissions=KnowledgeLedgerPermissions(
                can_review=can_review, can_manage=can_manage, can_delete=can_delete,
            ),
            leaders=leaders,
            uploaders=[
                KnowledgeLedgerUser(user_id=uuid.UUID(str(item.user_id)), email=item.email)
                for item in uploader_rows if item.user_id and item.email
            ],
            summary=summary,
            documents=documents,
        )

    category_filter = (
        "COALESCE(d.memory_type, 'raw_project_material') = 'raw_project_material'"
        if category == "project_material"
        else "d.memory_type = 'project_wiki_page'"
    )
    uploader_category_filter = (
        "COALESCE(doc.memory_type, 'raw_project_material') = 'raw_project_material'"
        if category == "project_material"
        else "doc.memory_type = 'project_wiki_page'"
    )
    filters = ["d.project_id = :project_id", category_filter]
    params: dict[str, str] = {"project_id": str(project_id)}
    if uploader_user_id is not None:
        filters.append("d.created_by_user_id = :uploader_user_id")
        params["uploader_user_id"] = str(uploader_user_id)
    if approval_status == "raw_uploaded":
        filters.append("draft.status IS NULL")
    elif approval_status is not None:
        filters.append("draft.status = :approval_status")
        params["approval_status"] = approval_status
    if uploaded_from:
        filters.append("d.created_at >= CAST(:uploaded_from AS timestamptz)")
        params["uploaded_from"] = uploaded_from
    if uploaded_to:
        filters.append("d.created_at <= CAST(:uploaded_to AS timestamptz)")
        params["uploaded_to"] = uploaded_to
    if reviewed_from:
        filters.append("draft.reviewed_at >= CAST(:reviewed_from AS timestamptz)")
        params["reviewed_from"] = reviewed_from
    if reviewed_to:
        filters.append("draft.reviewed_at <= CAST(:reviewed_to AS timestamptz)")
        params["reviewed_to"] = reviewed_to

    document_rows = orm.execute(
        text(f"""
            SELECT d.id::text AS document_id, page.id::text AS wiki_page_id,
                   d.filename, d.display_name, d.format,
                   d.size_bytes, d.status, d.chunk_count, d.error_message,
                   d.created_at::text AS uploaded_at,
                   d.created_by_user_id::text AS uploaded_by_user_id,
                   uploader.email AS uploaded_by_email,
                   pmd.draft_id::text AS draft_id,
                   draft.status AS draft_status,
                   draft.reviewed_by_user_id::text AS reviewed_by_user_id,
                   reviewer.email AS reviewed_by_email,
                   draft.reviewed_at::text AS reviewed_at,
                   draft.review_comment,
                   draft.approved_document_id::text AS approved_memory_document_id,
                   draft.intake_id::text AS intake_id,
                   pmd.original_file_id::text AS original_file_id
            FROM public.documents d
            LEFT JOIN public.project_material_documents pmd
                   ON pmd.document_id = d.id
            LEFT JOIN public.project_wiki_pages page ON page.document_id = d.id
            LEFT JOIN public.project_memory_drafts draft
                   ON draft.id = COALESCE(pmd.draft_id, d.memory_draft_id)
            LEFT JOIN auth.users uploader
                   ON uploader.id = d.created_by_user_id
            LEFT JOIN auth.users reviewer
                   ON reviewer.id = draft.reviewed_by_user_id
            WHERE {" AND ".join(filters)}
            ORDER BY d.created_at DESC, d.filename
        """),
        params,
    ).all()

    uploader_rows = orm.execute(
        text(f"""
            SELECT DISTINCT doc.created_by_user_id::text AS user_id, au.email
            FROM public.documents doc
            JOIN auth.users au ON au.id = doc.created_by_user_id
            WHERE doc.project_id = :project_id
              AND doc.created_by_user_id IS NOT NULL
              AND {uploader_category_filter}
            ORDER BY au.email
        """),
        {"project_id": str(project_id)},
    ).all()
    uploaders = [
        KnowledgeLedgerUser(user_id=uuid.UUID(str(row.user_id)), email=row.email)
        for row in uploader_rows
        if getattr(row, "user_id", None) and getattr(row, "email", None)
    ]

    documents: list[KnowledgeLedgerDocument] = []
    summary = KnowledgeLedgerSummary()
    for row in document_rows:
        status = _approval_status(row.draft_status)
        if status == "approved":
            summary.approved_count += 1
        elif status == "pending_review":
            summary.pending_count += 1
        elif status == "rejected":
            summary.rejected_count += 1
        else:
            summary.unreviewed_count += 1
        if row.uploaded_at and (
            summary.latest_uploaded_at is None or str(row.uploaded_at) > summary.latest_uploaded_at
        ):
            summary.latest_uploaded_at = str(row.uploaded_at)
        if row.reviewed_at and (
            summary.latest_reviewed_at is None or str(row.reviewed_at) > summary.latest_reviewed_at
        ):
            summary.latest_reviewed_at = str(row.reviewed_at)
        documents.append(
            KnowledgeLedgerDocument(
                asset_id=uuid.UUID(str(getattr(row, "wiki_page_id", None) or row.document_id)),
                asset_type=("project_wiki" if category == "project_wiki_source" else "project_material"),
                document_id=uuid.UUID(str(row.document_id)),
                filename=row.filename,
                display_name=row.display_name,
                format=row.format,
                size_bytes=int(row.size_bytes or 0),
                status=row.status,
                chunk_count=int(row.chunk_count or 0),
                error_message=row.error_message,
                uploaded_by=_ledger_user(row.uploaded_by_user_id, row.uploaded_by_email),
                uploaded_at=str(row.uploaded_at),
                approval_status=status,
                reviewed_by=_ledger_user(row.reviewed_by_user_id, row.reviewed_by_email),
                reviewed_at=str(row.reviewed_at) if row.reviewed_at else None,
                review_comment=row.review_comment,
                draft_id=uuid.UUID(str(row.draft_id)) if row.draft_id else None,
                approved_memory_document_id=(
                    uuid.UUID(str(row.approved_memory_document_id))
                    if row.approved_memory_document_id
                    else None
                ),
                intake_id=(
                    uuid.UUID(str(row.intake_id))
                    if getattr(row, "intake_id", None)
                    else None
                ),
                original_file_id=(
                    uuid.UUID(str(row.original_file_id))
                    if getattr(row, "original_file_id", None)
                    else None
                ),
            )
        )
    summary.raw_document_count = len(documents)

    return KnowledgeLedgerResponse(
        category=category,
        project=KnowledgeLedgerProject(
            id=uuid.UUID(str(project_row.id)),
            name=project_row.name,
            environment=project_row.environment,
            department_id=project_row.department_id,
            created_at=str(project_row.created_at) if project_row.created_at else None,
            completed_at=str(project_row.completed_at) if project_row.completed_at else None,
        ),
        permissions=KnowledgeLedgerPermissions(
            can_review=can_review,
            can_manage=can_manage,
            can_delete=can_delete,
        ),
        leaders=leaders,
        uploaders=uploaders,
        summary=summary,
        documents=documents,
    )


@router.patch(
    "/knowledge/assets/{asset_type}/{asset_id}",
    response_model=KnowledgeAssetMutationResponse,
)
def rename_knowledge_asset(
    request: Request,
    asset_type: KnowledgeAssetType,
    asset_id: uuid.UUID,
    body: KnowledgeAssetRenameRequest,
    orm: Session = Depends(get_orm_session),
) -> KnowledgeAssetMutationResponse:
    user_id = _asset_user(request)
    row = _require_asset(orm, asset_type=asset_type, asset_id=asset_id)
    project_id = uuid.UUID(str(row.project_id))
    _asset_authorize(require_admin, orm, user_id=user_id, project_id=project_id)
    name = body.name.strip()
    if asset_type == "project_material":
        orm.execute(
            text("UPDATE public.documents SET display_name = :name WHERE id = :asset_id"),
            {"asset_id": str(row.asset_id), "name": name},
        )
    elif asset_type == "project_wiki":
        markdown = re.sub(
            r"^# .*?$", f"# {name}", str(row.markdown_content),
            count=1, flags=re.MULTILINE,
        )
        ingested = ingest_markdown_memory(
            markdown=markdown,
            project_id=project_id,
            display_name=f"{name}.md",
            created_by_user_id=user_id,
        )
        if ingested.error:
            raise HTTPException(status_code=500, detail=f"Wiki rename ingest failed: {ingested.error}")
        orm.execute(
            text("""
                UPDATE public.project_wiki_pages
                SET title = :name, markdown_content = :markdown,
                    current_version = current_version + 1,
                    document_id = :new_document_id, updated_at = now()
                WHERE id = :asset_id
            """),
            {
                "asset_id": str(row.asset_id), "name": name,
                "markdown": markdown, "new_document_id": str(ingested.document_id),
            },
        )
        orm.execute(
            text("""
                INSERT INTO public.project_wiki_page_versions (
                    page_id, version, markdown_content, summary, source_ids,
                    change_reason, created_by_user_id
                )
                SELECT id, current_version, markdown_content, summary, '[]'::jsonb,
                       'knowledge_asset_rename', :user_id
                FROM public.project_wiki_pages
                WHERE id = :asset_id
                ON CONFLICT (page_id, version) DO NOTHING
            """),
            {"asset_id": str(row.asset_id), "user_id": str(user_id)},
        )
        if row.document_id and str(row.document_id) != str(ingested.document_id):
            orm.execute(
                text("DELETE FROM public.documents WHERE id = :document_id"),
                {"document_id": str(row.document_id)},
            )
    else:
        markdown = re.sub(r"^# .*?$", f"# {name}", str(row.summary_markdown), count=1, flags=re.MULTILINE)
        embedding = _embed_asset(markdown)
        orm.execute(
            text("""
                UPDATE public.meeting_summaries
                SET title = :name, summary_markdown = :markdown,
                    embedding = CAST(:embedding AS vector(1024)),
                    embedding_model = :embedding_model,
                    embedding_version = :embedding_version,
                    updated_at = now()
                WHERE id = :asset_id
            """),
            {
                "asset_id": str(row.asset_id),
                "name": name,
                "markdown": markdown,
                "embedding": json.dumps(embedding) if embedding is not None else None,
                "embedding_model": "BAAI/bge-m3" if embedding is not None else None,
                "embedding_version": "2026-07-21-bge-m3" if embedding is not None else None,
            },
        )
    orm.commit()
    record_audit(
        orm, user_id=user_id, action="update_project", resource_type="knowledge_asset",
        resource_id=str(row.asset_id),
        metadata={"operation": "rename", "asset_type": asset_type, "project_id": str(project_id)},
        request=request,
    )
    return KnowledgeAssetMutationResponse(
        asset_id=uuid.UUID(str(row.asset_id)), asset_type=asset_type,
        project_id=project_id, name=name,
    )


@router.post(
    "/knowledge/assets/{asset_type}/{asset_id}/move",
    response_model=KnowledgeAssetMutationResponse,
)
def move_knowledge_asset(
    request: Request,
    asset_type: KnowledgeAssetType,
    asset_id: uuid.UUID,
    body: KnowledgeAssetMoveRequest,
    orm: Session = Depends(get_orm_session),
) -> KnowledgeAssetMutationResponse:
    user_id = _asset_user(request)
    row = _require_asset(orm, asset_type=asset_type, asset_id=asset_id)
    source_project_id = uuid.UUID(str(row.project_id))
    _asset_authorize(require_admin, orm, user_id=user_id, project_id=source_project_id)
    _asset_authorize(require_admin, orm, user_id=user_id, project_id=body.target_project_id)
    target = orm.execute(
        text("SELECT department_id FROM public.projects WHERE id = :project_id"),
        {"project_id": str(body.target_project_id)},
    ).first()
    if target is None:
        raise HTTPException(status_code=404, detail="target project not found")
    if asset_type == "project_material":
        document_id = str(row.document_id)
        orm.execute(
            text("""
                UPDATE public.documents
                SET project_id = :project_id, department_id = :department_id
                WHERE id = :document_id
            """),
            {
                "project_id": str(body.target_project_id),
                "department_id": str(target.department_id),
                "document_id": document_id,
            },
        )
        orm.execute(
            text("UPDATE public.document_chunks SET project_id = :project_id WHERE document_id = :document_id"),
            {"project_id": str(body.target_project_id), "document_id": document_id},
        )
        orm.execute(
            text("UPDATE public.document_chunks_v2 SET project_id = :project_id WHERE document_id = :document_id"),
            {"project_id": str(body.target_project_id), "document_id": document_id},
        )
        orm.execute(
            text("UPDATE public.project_material_documents SET project_id = :project_id WHERE document_id = :document_id"),
            {"project_id": str(body.target_project_id), "document_id": document_id},
        )
    elif asset_type == "project_wiki":
        conflict = orm.execute(
            text("""
                SELECT id FROM public.project_wiki_pages
                WHERE project_id = :project_id AND page_key = :page_key AND id <> :asset_id
            """),
            {
                "project_id": str(body.target_project_id),
                "page_key": str(row.page_key),
                "asset_id": str(row.asset_id),
            },
        ).first()
        if conflict is not None:
            raise HTTPException(status_code=409, detail="target project already has a Wiki page with this key")
        orm.execute(
            text("UPDATE public.project_wiki_pages SET project_id = :project_id, updated_at = now() WHERE id = :asset_id"),
            {"project_id": str(body.target_project_id), "asset_id": str(row.asset_id)},
        )
        if row.document_id:
            document_id = str(row.document_id)
            orm.execute(
                text("""
                    UPDATE public.documents
                    SET project_id = :project_id, department_id = :department_id
                    WHERE id = :document_id
                """),
                {
                    "project_id": str(body.target_project_id),
                    "department_id": str(target.department_id),
                    "document_id": document_id,
                },
            )
            orm.execute(
                text("UPDATE public.document_chunks SET project_id = :project_id WHERE document_id = :document_id"),
                {"project_id": str(body.target_project_id), "document_id": document_id},
            )
            orm.execute(
                text("UPDATE public.document_chunks_v2 SET project_id = :project_id WHERE document_id = :document_id"),
                {"project_id": str(body.target_project_id), "document_id": document_id},
            )
    else:
        orm.execute(
            text("UPDATE public.meeting_summaries SET project_id = :project_id, updated_at = now() WHERE id = :asset_id"),
            {"project_id": str(body.target_project_id), "asset_id": str(row.asset_id)},
        )
    orm.commit()
    record_audit(
        orm, user_id=user_id, action="update_project", resource_type="knowledge_asset",
        resource_id=str(row.asset_id),
        metadata={
            "operation": "move", "asset_type": asset_type,
            "source_project_id": str(source_project_id),
            "target_project_id": str(body.target_project_id),
        },
        request=request,
    )
    return KnowledgeAssetMutationResponse(
        asset_id=uuid.UUID(str(row.asset_id)), asset_type=asset_type,
        project_id=body.target_project_id, name=str(row.name),
    )


@router.get(
    "/knowledge/assets/{asset_type}/{asset_id}/preview",
    response_model=KnowledgeAssetPreviewResponse,
)
def preview_knowledge_asset(
    request: Request,
    asset_type: KnowledgeAssetType,
    asset_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> KnowledgeAssetPreviewResponse:
    user_id = _asset_user(request)
    row = _require_asset(orm, asset_type=asset_type, asset_id=asset_id)
    project_id = uuid.UUID(str(row.project_id))
    _asset_authorize(require_member, orm, user_id=user_id, project_id=project_id)
    if asset_type == "project_material":
        preview = orm.execute(
            text("""
                SELECT COALESCE(
                    (SELECT string_agg(content, E'\n\n' ORDER BY chunk_index)
                     FROM (SELECT content, chunk_index FROM public.document_chunks_v2
                           WHERE document_id = :document_id ORDER BY chunk_index LIMIT 12) chunks),
                    (SELECT string_agg(content, E'\n\n' ORDER BY chunk_index)
                     FROM (SELECT content, chunk_index FROM public.document_chunks
                           WHERE document_id = :document_id ORDER BY chunk_index LIMIT 12) chunks),
                    ''
                ) AS content
            """),
            {"document_id": str(row.document_id)},
        ).first()
        content = str(preview.content if preview else "")
        fmt = str(row.format or "txt")
    elif asset_type == "project_wiki":
        content = str(row.markdown_content)
        fmt = "md"
    else:
        content = str(row.summary_markdown)
        fmt = str(row.format or "md")
    return KnowledgeAssetPreviewResponse(
        asset_id=uuid.UUID(str(row.asset_id)), asset_type=asset_type,
        project_id=project_id, name=str(row.name), format=fmt,
        content=content[:200_000],
    )


@router.get("/knowledge/assets/{asset_type}/{asset_id}/download")
def download_knowledge_asset(
    request: Request,
    asset_type: KnowledgeAssetType,
    asset_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> Response:
    user_id = _asset_user(request)
    row = _require_asset(orm, asset_type=asset_type, asset_id=asset_id)
    project_id = uuid.UUID(str(row.project_id))
    _asset_authorize(require_member, orm, user_id=user_id, project_id=project_id)
    if asset_type == "project_material":
        raw = bytes(row.raw_content or b"")
        if row.storage_key:
            stored_path = resolve_storage_key(str(row.storage_key))
            if stored_path.exists():
                raw = stored_path.read_bytes()
        if not raw:
            raise HTTPException(status_code=404, detail="original material file not found")
        suffix = Path(str(row.original_filename or row.filename)).suffix
        filename = str(row.name or row.filename)
        if suffix and not filename.lower().endswith(suffix.lower()):
            filename += suffix
        media_type = str(row.mime_type or "application/octet-stream")
    elif asset_type == "project_wiki":
        raw = str(row.markdown_content).encode("utf-8")
        filename = f"{row.name}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        raw = bytes(row.raw_content or b"")
        if not raw:
            raise HTTPException(status_code=404, detail="meeting original file not found")
        filename = str(row.original_filename or f"{row.name}.{row.format or 'md'}")
        media_type = str(row.mime_type or "application/octet-stream")
    return Response(
        content=raw,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=download; filename*=UTF-8''{quote(filename)}"},
    )


@router.delete("/knowledge/assets/{asset_type}/{asset_id}", status_code=204)
def delete_knowledge_asset(
    request: Request,
    asset_type: KnowledgeAssetType,
    asset_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
):
    user_id = _asset_user(request)
    row = _require_asset(orm, asset_type=asset_type, asset_id=asset_id)
    project_id = uuid.UUID(str(row.project_id))
    _asset_authorize(require_owner, orm, user_id=user_id, project_id=project_id)
    storage_path = None
    if asset_type == "project_material":
        if row.storage_key:
            storage_path = resolve_storage_key(str(row.storage_key))
        if row.original_file_id:
            orm.execute(
                text("""
                    UPDATE public.project_material_intake_files
                    SET raw_content = ''::bytea, extracted_text = '', storage_key = NULL,
                        included = false, document_id = NULL
                    WHERE id = :file_id
                """),
                {"file_id": str(row.original_file_id)},
            )
        orm.execute(text("DELETE FROM public.documents WHERE id = :asset_id"), {"asset_id": str(row.asset_id)})
    elif asset_type == "project_wiki":
        orm.execute(text("DELETE FROM public.project_wiki_pages WHERE id = :asset_id"), {"asset_id": str(row.asset_id)})
        if row.document_id:
            orm.execute(text("DELETE FROM public.documents WHERE id = :document_id"), {"document_id": str(row.document_id)})
    else:
        orm.execute(text("DELETE FROM public.meeting_summaries WHERE id = :asset_id"), {"asset_id": str(row.asset_id)})
    orm.commit()
    if storage_path is not None:
        storage_path.unlink(missing_ok=True)
    record_audit(
        orm, user_id=user_id, action="delete_document", resource_type="knowledge_asset",
        resource_id=str(row.asset_id),
        metadata={"asset_type": asset_type, "project_id": str(project_id), "name": str(row.name)},
        request=request,
    )
    return None


@router.delete("/knowledge/documents/{document_id}", status_code=204)
def delete_knowledge_document(
    request: Request,
    document_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
):
    """Delete a saved knowledge document. Only the overall project lead may delete."""
    try:
        user_id = current_user_id(request)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    row = orm.execute(
        text("""
            SELECT id::text AS document_id, project_id::text AS project_id,
                   filename, display_name, COALESCE(memory_type, 'raw_project_material') AS memory_type
            FROM public.documents
            WHERE id = :document_id
        """),
        {"document_id": str(document_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")

    project_id = uuid.UUID(str(row.project_id))
    try:
        require_owner(orm, user_id=user_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    orm.execute(
        text("DELETE FROM public.documents WHERE id = :document_id"),
        {"document_id": str(document_id)},
    )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="delete_document",
        resource_type="document",
        resource_id=str(document_id),
        metadata={
            "project_id": str(project_id),
            "filename": row.filename,
            "display_name": row.display_name,
            "memory_type": row.memory_type,
        },
        request=request,
    )
    return None


@router.post("/knowledge/upload", response_model=UploadResponse)
def knowledge_upload(
    request: Request,
    project_id: uuid.UUID = Form(...),
    display_name: Optional[str] = Form(None),
    file: UploadFile = File(...),
    orm: Session = Depends(get_orm_session),
) -> UploadResponse:
    """Upload a PDF/MD/TXT file and run the ingest pipeline."""
    try:
        user_id = current_user_id(request)
        require_writer(orm, user_id=user_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    safe_name, ext = _safe_upload_name(file)
    if ext not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported format .{ext}; allowed: {sorted(ALLOWED_FORMATS)}",
        )

    tmp_path = _copy_upload_to_temp(file, f".{ext}")

    try:
        result = ingest_file(
            tmp_path,
            project_id=project_id,
            display_name=display_name or safe_name,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    if result.error:
        raise HTTPException(status_code=500, detail=f"ingest failed: {result.error}")

    record_audit(
        orm,
        user_id=user_id,
        action="upload",
        resource_type="document",
        resource_id=str(result.document_id),
        metadata={
            "filename": safe_name,
            "format": ext,
            "chunk_count": result.chunk_count,
            "status": result.status,
        },
        request=request,
    )

    return UploadResponse(
        document_id=result.document_id,
        filename=safe_name,
        chunk_count=result.chunk_count,
        status=result.status,
    )


@router.post("/knowledge/material-batches", response_model=MaterialBatchUploadResponse)
def knowledge_material_batch_upload(
    request: Request,
    project_id: uuid.UUID = Form(...),
    department_id: DepartmentId = Form(...),
    files: list[UploadFile] = File(...),
    orm: Session = Depends(get_orm_session),
) -> MaterialBatchUploadResponse:
    """Upload mixed original project materials and create a review draft."""
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    if not files:
        raise HTTPException(status_code=400, detail="at least one project material file is required")

    file_meta = [_safe_upload_name(file) for file in files]
    unsupported = [f".{ext or '(none)'}" for _, ext in file_meta if ext not in ALLOWED_FORMATS]
    if unsupported:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported format {unsupported[0]}; allowed: {sorted(ALLOWED_FORMATS)}",
        )

    department_name = _department_name(orm, department_id)
    project_name = _project_name(orm, project_id)
    repository = _repository_for_project(orm, project_id)
    raw_documents: list[MaterialDocumentResponse] = []
    sources: list[SourceText] = []
    temp_paths: list[Path] = []
    try:
        for file, (safe_name, ext) in zip(files, file_meta):
            temp_path = _copy_upload_to_temp(file, f".{ext}")
            temp_paths.append(temp_path)
            extracted = extract_text(temp_path)
            sources.append(
                SourceText(
                    filename=safe_name,
                    format=extracted.format,
                    text=extracted.text,
                )
            )
            result = ingest_file(
                temp_path,
                project_id=project_id,
                display_name=safe_name,
                created_by_user_id=user_id,
            )
            if result.error:
                raise HTTPException(status_code=500, detail=f"raw material ingest failed: {result.error}")
            raw_documents.append(
                MaterialDocumentResponse(
                    document_id=result.document_id,
                    filename=safe_name,
                    format=ext,
                    chunk_count=result.chunk_count,
                    status=result.status,
                )
            )
    finally:
        for path in temp_paths:
            path.unlink(missing_ok=True)

    markdown = build_project_memory_markdown(
        department_id=department_id,
        department_name=department_name,
        project_name=project_name,
        repository=repository,
        sources=sources,
    )
    title = f"{project_name} 长期记忆"
    row = orm.execute(
        text("""
            INSERT INTO public.project_memory_drafts (
                project_id, department_id, title, status, template_version,
                markdown_content, source_count, created_by_user_id
            )
            VALUES (
                :project_id, :department_id, :title, 'pending_review',
                :template_version, :markdown_content, :source_count, :user_id
            )
            RETURNING id::text, project_id::text, department_id, title, status,
                      markdown_content, source_count, approved_document_id::text,
                      created_at::text, updated_at::text
        """),
        {
            "project_id": str(project_id),
            "department_id": department_id,
            "title": title,
            "template_version": TEMPLATE_VERSION,
            "markdown_content": markdown,
            "source_count": len(sources),
            "user_id": str(user_id),
        },
    ).first()
    if row is None:
        raise HTTPException(status_code=503, detail="failed to create project memory draft")
    draft_id = str(row.id)
    for document in raw_documents:
        orm.execute(
            text("""
                INSERT INTO public.project_material_documents (
                    project_id, document_id, draft_id, uploaded_by_user_id
                )
                VALUES (
                    :project_id, :document_id, :draft_id, :user_id
                )
                ON CONFLICT (document_id)
                DO UPDATE SET
                    draft_id = excluded.draft_id,
                    uploaded_by_user_id = excluded.uploaded_by_user_id
            """),
            {
                "project_id": str(project_id),
                "document_id": str(document.document_id),
                "draft_id": draft_id,
                "user_id": str(user_id),
            },
        )
    for source in sources:
        orm.execute(
            text("""
                INSERT INTO public.project_memory_draft_sources (
                    draft_id, filename, format, extracted_text, size_bytes
                )
                VALUES (:draft_id, :filename, :format, :extracted_text, :size_bytes)
            """),
            {
                "draft_id": draft_id,
                "filename": source.filename,
                "format": source.format,
                "extracted_text": source.text,
                "size_bytes": len(source.text.encode("utf-8")),
            },
        )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="upload",
        resource_type="project_material_batch",
        resource_id=draft_id,
        metadata={
            "project_id": str(project_id),
            "department_id": department_id,
            "raw_document_count": len(raw_documents),
            "draft_id": draft_id,
        },
        request=request,
    )

    return MaterialBatchUploadResponse(
        raw_document_count=len(raw_documents),
        raw_documents=raw_documents,
        draft=_row_to_draft(orm, row),
    )


# --- search -----------------------------------------------------------------

class SearchRequest(BaseModel):
    project_id: uuid.UUID
    query: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(5, ge=1, le=20)
    retrieval_version: Optional[
        Literal["v1", "v2-vector", "v2-hybrid", "v2-hybrid-rerank"]
    ] = None


class SearchHitSchema(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    content: str
    source_page: Optional[int] = None
    source_line: Optional[int] = None
    chunk_index: int
    score: float
    heading_path: Optional[str] = None
    retrieval_mode: Optional[str] = None
    vector_score: Optional[float] = None
    keyword_score: Optional[float] = None
    vector_rank: Optional[int] = None
    keyword_rank: Optional[int] = None
    rrf_score: Optional[float] = None
    rerank_score: Optional[float] = None
    embedding_model: Optional[str] = None
    embedding_version: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    hits: List[SearchHitSchema]


class AnswerResponse(BaseModel):
    query: str
    hits: List[SearchHitSchema]
    synthesis: str
    source: Literal["llm", "stub"]  # tells caller which path produced the text


@router.post("/knowledge/search", response_model=SearchResponse)
def knowledge_search(
    request: Request,
    body: SearchRequest,
    orm: Session = Depends(get_orm_session),
) -> SearchResponse:
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=body.project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    hits = search(
        orm,
        query=body.query,
        project_id=body.project_id,
        k=body.k,
        retrieval_version=body.retrieval_version,
    )
    record_audit(
        orm,
        user_id=user_id,
        action="search",
        resource_type="project",
        resource_id=str(body.project_id),
        metadata={
            "query_len": len(body.query),
            "k": body.k,
            "hits": len(hits),
            "top_score": round(hits[0].score, 4) if hits else None,
            "retrieval_version": body.retrieval_version,
            "retrieval_mode": hits[0].retrieval_mode if hits else None,
        },
        request=request,
    )
    return SearchResponse(
        query=body.query,
        hits=[SearchHitSchema(**h.__dict__) for h in hits],
    )


@router.post("/knowledge/answer", response_model=AnswerResponse)
def knowledge_answer(
    request: Request,
    body: SearchRequest,
    orm: Session = Depends(get_orm_session),
) -> AnswerResponse:
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=body.project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    hits = search(
        orm,
        query=body.query,
        project_id=body.project_id,
        k=body.k,
        retrieval_version=body.retrieval_version,
    )
    synthesis, source = llm_synthesize(body.query, hits)
    record_audit(
        orm,
        user_id=user_id,
        action="answer",
        resource_type="project",
        resource_id=str(body.project_id),
        metadata={
            "query_len": len(body.query),
            "k": body.k,
            "hits": len(hits),
            "source": source,
            "retrieval_version": body.retrieval_version,
            "retrieval_mode": hits[0].retrieval_mode if hits else None,
        },
        request=request,
    )
    return AnswerResponse(
        query=body.query,
        hits=[SearchHitSchema(**h.__dict__) for h in hits],
        synthesis=synthesis,
        source=source,
    )
