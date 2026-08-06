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
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
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
    require_admin,
    require_writer,
    require_member,
)
from agentops.rag.audit import record_audit
from agentops.project_memory.parsers import SUPPORTED_FORMATS, extract_text
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


class KnowledgeLedgerSummary(BaseModel):
    raw_document_count: int = 0
    approved_count: int = 0
    pending_count: int = 0
    rejected_count: int = 0
    unreviewed_count: int = 0
    latest_uploaded_at: str | None = None
    latest_reviewed_at: str | None = None


class KnowledgeLedgerDocument(BaseModel):
    document_id: uuid.UUID
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


class KnowledgeLedgerResponse(BaseModel):
    project: KnowledgeLedgerProject
    permissions: KnowledgeLedgerPermissions
    leaders: list[KnowledgeLedgerUser]
    uploaders: list[KnowledgeLedgerUser]
    summary: KnowledgeLedgerSummary
    documents: list[KnowledgeLedgerDocument]


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


@router.get("/knowledge/ledger", response_model=KnowledgeLedgerResponse)
def get_knowledge_ledger(
    request: Request,
    project_id: uuid.UUID,
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
    can_review = bool(role_row and role_row.role in {"owner", "admin"})

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

    filters = [
        "d.project_id = :project_id",
        "COALESCE(d.memory_type, 'raw_project_material') != 'project_long_term_memory'",
    ]
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
            SELECT d.id::text AS document_id, d.filename, d.display_name, d.format,
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
        text("""
            SELECT DISTINCT doc.created_by_user_id::text AS user_id, au.email
            FROM public.documents doc
            JOIN auth.users au ON au.id = doc.created_by_user_id
            WHERE doc.project_id = :project_id
              AND doc.created_by_user_id IS NOT NULL
              AND COALESCE(doc.memory_type, 'raw_project_material') != 'project_long_term_memory'
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
        project=KnowledgeLedgerProject(
            id=uuid.UUID(str(project_row.id)),
            name=project_row.name,
            environment=project_row.environment,
            department_id=project_row.department_id,
            created_at=str(project_row.created_at) if project_row.created_at else None,
            completed_at=str(project_row.completed_at) if project_row.completed_at else None,
        ),
        permissions=KnowledgeLedgerPermissions(can_review=can_review),
        leaders=leaders,
        uploaders=uploaders,
        summary=summary,
        documents=documents,
    )


@router.delete("/knowledge/documents/{document_id}", status_code=204)
def delete_knowledge_document(
    request: Request,
    document_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
):
    """Delete a saved knowledge document. Only project admins/leads may delete."""
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
        require_admin(orm, user_id=user_id, project_id=project_id)
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

    department_name = _department_name(department_id)
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
        draft=_row_to_draft(row),
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
