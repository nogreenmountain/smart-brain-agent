from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.project_memory.ingest import ingest_markdown_memory
from agentops.project_memory.parsers import SUPPORTED_FORMATS, extract_text
from agentops.project_memory.templates import (
    TEMPLATE_VERSION,
    SourceText,
    build_project_memory_markdown,
)
from agentops.rag.audit import record_audit
from agentops.rag.authz import (
    AuthzError,
    current_user_id,
    require_admin,
    require_member,
    require_writer,
)


router = APIRouter(route_class=AuthenticatedRoute)
logger = logging.getLogger(__name__)

DepartmentId = Literal["research", "marketing", "business"]
DraftStatus = Literal["pending_review", "approved", "rejected"]

DEPARTMENTS: tuple[dict[str, object], ...] = (
    {"id": "research", "name": "研发", "sort_order": 1},
    {"id": "marketing", "name": "市场", "sort_order": 2},
    {"id": "business", "name": "业务", "sort_order": 3},
)
DEPARTMENT_NAME = {str(row["id"]): str(row["name"]) for row in DEPARTMENTS}


class DepartmentSchema(BaseModel):
    id: DepartmentId
    name: str
    sort_order: int


class ProjectRepositoryRequest(BaseModel):
    git_url: HttpUrl
    git_branch: str = Field("main", min_length=1, max_length=120)


class ProjectRepositorySchema(BaseModel):
    project_id: uuid.UUID
    git_url: str
    git_branch: str


class ProjectMemoryDraftSchema(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    department_id: DepartmentId
    department_name: str
    title: str
    status: DraftStatus
    markdown_content: str
    source_count: int
    document_id: uuid.UUID | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ReviewDraftRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(None, max_length=2000)


class ReviewDraftResponse(BaseModel):
    id: uuid.UUID
    status: DraftStatus
    document_id: uuid.UUID | None = None
    chunk_count: int = 0


def _department_name(department_id: str) -> str:
    if department_id not in DEPARTMENT_NAME:
        raise HTTPException(status_code=400, detail="unsupported department")
    return DEPARTMENT_NAME[department_id]


def _project_name(orm: Session, project_id: uuid.UUID) -> str:
    row = orm.execute(
        text("SELECT name FROM public.projects WHERE id = :project_id"),
        {"project_id": str(project_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return row.name


def _repository_for_project(orm: Session, project_id: uuid.UUID) -> dict[str, str] | None:
    row = orm.execute(
        text("""
            SELECT git_url, git_branch
            FROM public.project_repositories
            WHERE project_id = :project_id
        """),
        {"project_id": str(project_id)},
    ).first()
    if row is None:
        return None
    return {"git_url": row.git_url, "git_branch": row.git_branch}


def _copy_upload_to_temp(file: UploadFile, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        return Path(tmp.name)


def _row_to_draft(row) -> ProjectMemoryDraftSchema:
    return ProjectMemoryDraftSchema(
        id=uuid.UUID(str(row.id)),
        project_id=uuid.UUID(str(row.project_id)),
        department_id=row.department_id,
        department_name=_department_name(row.department_id),
        title=row.title,
        status=row.status,
        markdown_content=row.markdown_content,
        source_count=int(row.source_count or 0),
        document_id=uuid.UUID(str(row.approved_document_id)) if row.approved_document_id else None,
        created_at=str(row.created_at) if getattr(row, "created_at", None) else None,
        updated_at=str(row.updated_at) if getattr(row, "updated_at", None) else None,
    )


@router.get("/project-memory/departments", response_model=list[DepartmentSchema])
def list_project_memory_departments() -> list[DepartmentSchema]:
    return [DepartmentSchema(**row) for row in DEPARTMENTS]


@router.put(
    "/project-memory/projects/{project_id}/repository",
    response_model=ProjectRepositorySchema,
)
def upsert_project_repository(
    request: Request,
    project_id: uuid.UUID,
    body: ProjectRepositoryRequest,
    orm: Session = Depends(get_orm_session),
) -> ProjectRepositorySchema:
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    orm.execute(
        text("""
            INSERT INTO public.project_repositories (
                project_id, git_url, git_branch, created_by_user_id, updated_at
            )
            VALUES (:project_id, :git_url, :git_branch, :user_id, now())
            ON CONFLICT (project_id)
            DO UPDATE SET
                git_url = excluded.git_url,
                git_branch = excluded.git_branch,
                updated_at = now()
        """),
        {
            "project_id": str(project_id),
            "git_url": str(body.git_url),
            "git_branch": body.git_branch,
            "user_id": str(user_id),
        },
    )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="project_memory_repository_upsert",
        resource_type="project",
        resource_id=str(project_id),
        metadata={"git_url": str(body.git_url), "git_branch": body.git_branch},
        request=request,
    )
    return ProjectRepositorySchema(
        project_id=project_id,
        git_url=str(body.git_url),
        git_branch=body.git_branch,
    )


@router.get(
    "/project-memory/projects/{project_id}/repository",
    response_model=ProjectRepositorySchema | None,
)
def get_project_repository(
    request: Request,
    project_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> ProjectRepositorySchema | None:
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    repository = _repository_for_project(orm, project_id)
    if repository is None:
        return None
    return ProjectRepositorySchema(project_id=project_id, **repository)


@router.post("/project-memory/drafts", response_model=ProjectMemoryDraftSchema)
def create_project_memory_draft(
    request: Request,
    project_id: uuid.UUID = Form(...),
    department_id: DepartmentId = Form(...),
    files: list[UploadFile] = File(...),
    orm: Session = Depends(get_orm_session),
) -> ProjectMemoryDraftSchema:
    try:
        user_id = current_user_id(request)
        require_writer(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if not files:
        raise HTTPException(status_code=400, detail="at least one memory file is required")

    department_name = _department_name(department_id)
    project_name = _project_name(orm, project_id)
    repository = _repository_for_project(orm, project_id)
    sources: list[SourceText] = []
    temp_paths: list[Path] = []
    try:
        for file in files:
            filename = Path(file.filename or "upload").name
            suffix = Path(filename).suffix.lower()
            fmt = suffix.lstrip(".")
            if fmt == "htm":
                fmt = "html"
            if fmt not in SUPPORTED_FORMATS:
                raise HTTPException(
                    status_code=400,
                    detail=f"unsupported format .{fmt}; allowed: {sorted(SUPPORTED_FORMATS)}",
                )
            temp_path = _copy_upload_to_temp(file, suffix or f".{fmt}")
            temp_paths.append(temp_path)
            extracted = extract_text(temp_path.with_name(filename) if False else temp_path)
            sources.append(
                SourceText(
                    filename=filename,
                    format=extracted.format,
                    text=extracted.text,
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
    draft_id = row.id
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
        action="project_memory_draft_create",
        resource_type="project_memory_draft",
        resource_id=str(draft_id),
        metadata={
            "project_id": str(project_id),
            "department_id": department_id,
            "source_count": len(sources),
        },
        request=request,
    )
    return _row_to_draft(row)


@router.get("/project-memory/drafts", response_model=list[ProjectMemoryDraftSchema])
def list_project_memory_drafts(
    request: Request,
    project_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> list[ProjectMemoryDraftSchema]:
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    rows = orm.execute(
        text("""
            SELECT id::text, project_id::text, department_id, title, status,
                   markdown_content, source_count, approved_document_id::text,
                   created_at::text, updated_at::text
            FROM public.project_memory_drafts
            WHERE project_id = :project_id
            ORDER BY created_at DESC
        """),
        {"project_id": str(project_id)},
    ).all()
    return [_row_to_draft(row) for row in rows]


@router.post(
    "/project-memory/drafts/{draft_id}/review",
    response_model=ReviewDraftResponse,
)
def approve_project_memory_draft(
    request: Request,
    draft_id: uuid.UUID,
    body: ReviewDraftRequest,
    orm: Session = Depends(get_orm_session),
) -> ReviewDraftResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    row = orm.execute(
        text("""
            SELECT id::text, project_id::text, department_id, status, markdown_content, title
            FROM public.project_memory_drafts
            WHERE id = :draft_id
            FOR UPDATE
        """),
        {"draft_id": str(draft_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project memory draft not found")
    project_id = uuid.UUID(str(row.project_id))
    try:
        require_admin(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if row.status != "pending_review":
        raise HTTPException(status_code=409, detail=f"draft already {row.status}")

    if body.decision == "reject":
        orm.execute(
            text("""
                UPDATE public.project_memory_drafts
                SET status = 'rejected', reviewed_by_user_id = :user_id,
                    review_comment = :comment, reviewed_at = now(), updated_at = now()
                WHERE id = :draft_id
            """),
            {
                "draft_id": str(draft_id),
                "user_id": str(user_id),
                "comment": body.comment,
            },
        )
        orm.commit()
        status: DraftStatus = "rejected"
        document_id = None
        chunk_count = 0
    else:
        result = ingest_markdown_memory(
            markdown=row.markdown_content,
            project_id=project_id,
            display_name=f"{row.title}.md",
            created_by_user_id=user_id,
        )
        if result.error:
            raise HTTPException(status_code=500, detail=f"memory ingest failed: {result.error}")
        document_id = result.document_id
        chunk_count = result.chunk_count
        orm.execute(
            text("""
                UPDATE public.documents
                SET department_id = :department_id,
                    memory_type = 'project_long_term_memory',
                    memory_draft_id = :draft_id,
                    template_version = :template_version
                WHERE id = :document_id
            """),
            {
                "department_id": row.department_id,
                "draft_id": str(draft_id),
                "template_version": TEMPLATE_VERSION,
                "document_id": str(document_id),
            },
        )
        orm.execute(
            text("""
                UPDATE public.project_memory_drafts
                SET status = 'approved', reviewed_by_user_id = :user_id,
                    review_comment = :comment, reviewed_at = now(),
                    approved_document_id = :document_id, updated_at = now()
                WHERE id = :draft_id
            """),
            {
                "draft_id": str(draft_id),
                "user_id": str(user_id),
                "comment": body.comment,
                "document_id": str(document_id),
            },
        )
        orm.commit()
        status = "approved"

    orm.execute(
        text("""
            INSERT INTO public.project_memory_reviews (
                draft_id, reviewer_user_id, decision, comment
            )
            VALUES (:draft_id, :user_id, :decision, :comment)
        """),
        {
            "draft_id": str(draft_id),
            "user_id": str(user_id),
            "decision": body.decision,
            "comment": body.comment,
        },
    )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="project_memory_review",
        resource_type="project_memory_draft",
        resource_id=str(draft_id),
        metadata={"decision": body.decision, "project_id": str(project_id)},
        request=request,
    )
    return ReviewDraftResponse(
        id=draft_id,
        status=status,
        document_id=document_id,
        chunk_count=chunk_count,
    )
