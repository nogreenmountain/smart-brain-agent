from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import uuid
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.meeting_summaries.domain import build_meeting_markdown
from agentops.project_memory.ingest import ingest_markdown_memory
from agentops.project_memory.publish import build_skill_candidates
from agentops.project_memory.parsers import SUPPORTED_FORMATS, extract_text
from agentops.project_memory.storage import resolve_storage_key
from agentops.project_memory.templates import (
    TEMPLATE_VERSION,
    SourceText,
    build_project_memory_markdown,
)
from agentops.rag.audit import record_audit
from agentops.rag.authz import (
    AuthzError,
    current_user_id,
    is_system_admin,
    require_admin,
    require_member,
    require_writer,
)
from agentops.rag.ingest import ingest_file
from agentops.project_wiki.service import publish_approved_candidates


router = APIRouter(route_class=AuthenticatedRoute)
logger = logging.getLogger(__name__)

DepartmentId = str
DraftStatus = Literal["pending_review", "approved", "rejected"]
GLOBAL_PROJECT_REVIEWER_EMAIL = "hanshangbo@local.dev"


class DepartmentSchema(BaseModel):
    id: str
    name: str
    sort_order: int
    parent_id: str | None = None
    parent_name: str | None = None
    allows_projects: bool = True
    level: int = 1
    is_direct: bool = False


class CreateDepartmentRequest(BaseModel):
    id: str | None = Field(None, pattern="^[a-z][a-z0-9_-]{1,39}$")
    name: str = Field(..., min_length=1, max_length=80)
    parent_id: str | None = Field(None, pattern="^[a-z][a-z0-9_-]{1,39}$")


class UpdateDepartmentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    sort_order: int = Field(..., ge=0, le=100000)
    parent_id: str | None = Field(None, pattern="^[a-z][a-z0-9_-]{1,39}$")


class ReorderDepartmentsRequest(BaseModel):
    parent_id: str | None = Field(None, pattern="^[a-z][a-z0-9_-]{1,39}$")
    department_ids: list[str] = Field(..., min_length=1, max_length=1000)


class ProjectRepositoryRequest(BaseModel):
    git_url: HttpUrl
    git_branch: str = Field("main", min_length=1, max_length=120)


class ProjectRepositorySchema(BaseModel):
    project_id: uuid.UUID
    git_url: str
    git_branch: str
    status: DraftStatus | None = None
    draft_id: uuid.UUID | None = None


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
    skill_count: int = 0
    generation_model: str | None = None
    generation_used_fallback: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class ReviewQueueUploaderSchema(BaseModel):
    user_id: uuid.UUID | None = None
    username: str | None = None
    nickname: str | None = None
    display_name: str


class ProjectMemoryReviewQueueItemSchema(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    department_id: DepartmentId
    department_name: str
    department_path: str
    title: str
    status: DraftStatus
    markdown_content: str
    source_count: int
    review_kind: Literal["project_material", "meeting_summary", "project_repository"] = "project_material"
    uploader: ReviewQueueUploaderSchema
    file_names: list[str]
    total_size_bytes: int
    repository_url: str | None = None
    repository_branch: str | None = None
    meeting_date: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ReviewDraftRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(None, max_length=2000)


class ReviewDraftResponse(BaseModel):
    id: uuid.UUID
    status: DraftStatus
    document_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    chunk_count: int = 0
    wiki_page_count: int = 0


def _is_global_project_reviewer(orm: Session, user_id: uuid.UUID) -> bool:
    row = orm.execute(
        text("SELECT lower(email) AS email FROM auth.users WHERE id = :user_id"),
        {"user_id": str(user_id)},
    ).first()
    return bool(
        row
        and str(row.email or "").strip().lower() == GLOBAL_PROJECT_REVIEWER_EMAIL
    )


def _require_project_reviewer(
    orm: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    if _is_global_project_reviewer(orm, user_id):
        return
    row = orm.execute(
        text("""
            SELECT role::text AS role
            FROM public.project_members
            WHERE project_id = :project_id
              AND user_id = :user_id
        """),
        {"project_id": str(project_id), "user_id": str(user_id)},
    ).first()
    if row is None or row.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="only a project leader can review this project's submissions",
        )


def _department_name(orm: Session, department_id: str) -> str:
    row = orm.execute(
        text("SELECT name FROM public.departments WHERE id = :department_id"),
        {"department_id": department_id},
    ).first()
    if row is None:
        raise HTTPException(status_code=400, detail="unsupported department")
    return str(row.name)


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


def _embed_markdown(value: str) -> list[float] | None:
    try:
        from agentops.rag.model_clients import EmbeddingServiceClient

        return EmbeddingServiceClient().embed_documents([value])[0]
    except Exception:
        return None


def _submission_payload(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise HTTPException(status_code=500, detail="approval submission payload is invalid")


def _publish_meeting_submission(
    orm: Session,
    *,
    draft_id: uuid.UUID,
    project_id: uuid.UUID,
    row,
) -> uuid.UUID:
    payload = _submission_payload(row.submission_payload)
    raw_content = bytes(row.submission_raw_content or b"")
    if not raw_content:
        raise HTTPException(status_code=500, detail="pending meeting file is missing")
    suffix = f".{str(row.submission_format or '').lstrip('.')}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(raw_content)
        temp_path = Path(handle.name)
    try:
        extracted = extract_text(temp_path)
    except Exception as error:
        raise HTTPException(
            status_code=422,
            detail=f"meeting content could not be read: {row.submission_filename}",
        ) from error
    finally:
        temp_path.unlink(missing_ok=True)

    try:
        meeting_date = date.fromisoformat(str(payload["meeting_date"]))
        participant_user_ids = [str(uuid.UUID(str(item))) for item in payload["participant_user_ids"]]
        participants = [str(item) for item in payload["participants"]]
        title = str(payload["title"]).strip()
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=500, detail="pending meeting metadata is invalid") from error
    markdown = build_meeting_markdown(
        title=title,
        meeting_date=meeting_date,
        participants=participants,
        tags=[],
        summary=extracted.text,
        decisions=[],
        action_items=[],
    )
    embedding = _embed_markdown(markdown)
    inserted = orm.execute(
        text("""
            INSERT INTO public.meeting_summaries (
                project_id, title, meeting_date, participant_user_ids,
                participants, tags, summary_markdown, decisions, action_items,
                source_filename, created_by, approval_draft_id,
                embedding, embedding_model, embedding_version
            ) VALUES (
                :project_id, :title, :meeting_date,
                CAST(:participant_user_ids AS uuid[]), CAST(:participants AS text[]),
                ARRAY[]::text[], :summary_markdown, ARRAY[]::text[], ARRAY[]::text[],
                :source_filename, :created_by, :draft_id,
                CAST(:embedding AS vector(1024)), :embedding_model, :embedding_version
            ) RETURNING id::text
        """),
        {
            "project_id": str(project_id),
            "title": title,
            "meeting_date": meeting_date,
            "participant_user_ids": participant_user_ids,
            "participants": participants,
            "summary_markdown": markdown,
            "source_filename": str(row.submission_filename),
            "created_by": str(row.created_by_user_id),
            "draft_id": str(draft_id),
            "embedding": json.dumps(embedding) if embedding is not None else None,
            "embedding_model": "BAAI/bge-m3" if embedding is not None else None,
            "embedding_version": "2026-07-21-bge-m3" if embedding is not None else None,
        },
    ).first()
    if inserted is None:
        raise HTTPException(status_code=503, detail="failed to publish meeting record")
    summary_id = uuid.UUID(str(inserted.id))
    orm.execute(
        text("""
            INSERT INTO public.meeting_summary_files (
                meeting_summary_id, filename, format, mime_type, size_bytes,
                content_hash, raw_content, extracted_text
            ) VALUES (
                :meeting_summary_id, :filename, :format, :mime_type, :size_bytes,
                :content_hash, :raw_content, :extracted_text
            )
        """),
        {
            "meeting_summary_id": str(summary_id),
            "filename": str(row.submission_filename),
            "format": str(row.submission_format),
            "mime_type": row.submission_mime_type,
            "size_bytes": int(row.submission_size_bytes),
            "content_hash": str(row.submission_content_hash),
            "raw_content": raw_content,
            "extracted_text": extracted.text,
        },
    )
    return summary_id


def _write_material_to_temp(filename: str, fmt: str, raw: bytes) -> Path:
    suffix = Path(filename).suffix or f".{fmt}"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        return Path(tmp.name)


def _row_to_draft(orm: Session, row) -> ProjectMemoryDraftSchema:
    return ProjectMemoryDraftSchema(
        id=uuid.UUID(str(row.id)),
        project_id=uuid.UUID(str(row.project_id)),
        department_id=row.department_id,
        department_name=_department_name(orm, row.department_id),
        title=row.title,
        status=row.status,
        markdown_content=row.markdown_content,
        source_count=int(row.source_count or 0),
        document_id=uuid.UUID(str(row.approved_document_id)) if row.approved_document_id else None,
        skill_count=len(getattr(row, "skill_candidates", None) or []),
        generation_model=getattr(row, "generation_model", None),
        generation_used_fallback=bool(getattr(row, "generation_used_fallback", False)),
        created_at=str(row.created_at) if getattr(row, "created_at", None) else None,
        updated_at=str(row.updated_at) if getattr(row, "updated_at", None) else None,
    )


def _department_from_row(row) -> DepartmentSchema:
    return DepartmentSchema(
        id=str(row.id),
        name=str(row.name),
        sort_order=int(row.sort_order or 0),
        parent_id=getattr(row, "parent_id", None),
        parent_name=getattr(row, "parent_name", None),
        allows_projects=bool(getattr(row, "allows_projects", True)),
        level=int(getattr(row, "level", 1) or 1),
        is_direct=bool(getattr(row, "is_direct", False)),
    )


def _system_admin_user(request: Request, orm: Session) -> uuid.UUID:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if not is_system_admin(orm, user_id=user_id):
        raise HTTPException(status_code=403, detail="only system administrators can manage departments")
    return user_id


@router.get("/project-memory/departments", response_model=list[DepartmentSchema])
def list_project_memory_departments(
    include_groups: bool = False,
    orm: Session = Depends(get_orm_session),
) -> list[DepartmentSchema]:
    rows = orm.execute(
        text("""
            SELECT id, name, sort_order,
                   parent_id,
                   parent_name,
                   allows_projects,
                   is_direct,
                   CASE WHEN parent_id IS NULL THEN 1 ELSE 2 END AS level
            FROM (
                SELECT department.id,
                       department.name,
                       department.sort_order,
                       department.parent_id,
                       parent.name AS parent_name,
                       department.allows_projects,
                       COALESCE(department.is_direct, false) AS is_direct
                FROM public.departments department
                LEFT JOIN public.departments parent ON parent.id = department.parent_id
                WHERE CAST(:include_groups AS boolean) OR department.allows_projects
            ) department_tree
            ORDER BY
                CASE WHEN parent_id IS NULL THEN sort_order ELSE (
                    SELECT parent.sort_order
                    FROM public.departments parent
                    WHERE parent.id = department_tree.parent_id
                ) END,
                CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END,
                sort_order,
                name,
                id
        """),
        {"include_groups": include_groups},
    ).all()
    return [
        _department_from_row(row)
        for row in rows
    ]


@router.post("/project-memory/departments", response_model=DepartmentSchema, status_code=201)
def create_project_memory_department(
    request: Request,
    body: CreateDepartmentRequest,
    orm: Session = Depends(get_orm_session),
) -> DepartmentSchema:
    user_id = _system_admin_user(request, orm)

    department_id = body.id.strip().lower() if body.id else f"dept-{uuid.uuid4().hex}"
    name = " ".join(body.name.split())
    parent_id = body.parent_id.strip().lower() if body.parent_id else None
    parent_name = None
    if parent_id:
        parent = orm.execute(
            text("SELECT id, name, parent_id FROM public.departments WHERE id = :parent_id"),
            {"parent_id": parent_id},
        ).first()
        if parent is None:
            raise HTTPException(status_code=404, detail="parent department not found")
        if getattr(parent, "parent_id", None) is not None:
            raise HTTPException(status_code=400, detail="second-level departments cannot have child categories")
        parent_name = str(parent.name)
    existing = orm.execute(
        text("""
            SELECT 1
            FROM public.departments
            WHERE id = :department_id
               OR (
                   parent_id IS NOT DISTINCT FROM :parent_id
                   AND lower(BTRIM(name)) = lower(BTRIM(:name))
               )
        """),
        {"department_id": department_id, "name": name, "parent_id": parent_id},
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="department id or name already exists")

    row = orm.execute(
        text("""
            INSERT INTO public.departments (
                id, name, sort_order, parent_id, allows_projects
            )
            VALUES (
                :department_id,
                :name,
                COALESCE((
                    SELECT max(sort_order) + 1
                    FROM public.departments
                    WHERE parent_id IS NOT DISTINCT FROM :parent_id
                ), 1),
                :parent_id,
                CAST(:allows_projects AS boolean)
            )
            RETURNING id, name, sort_order, parent_id, allows_projects,
                      COALESCE(is_direct, false) AS is_direct,
                      CASE WHEN parent_id IS NULL THEN 1 ELSE 2 END AS level
        """),
        {
            "department_id": department_id,
            "name": name,
            "parent_id": parent_id,
            "parent_name": parent_name,
            "allows_projects": bool(parent_id),
        },
    ).first()
    if parent_id is None:
        direct_department_id = f"direct-{hashlib.md5(department_id.encode('utf-8')).hexdigest()}"
        orm.execute(
            text("""
                INSERT INTO public.departments (
                    id, name, sort_order, parent_id, allows_projects, is_direct
                )
                VALUES (
                    :department_id,
                    :name,
                    COALESCE((
                        SELECT max(sort_order) + 1
                        FROM public.departments
                        WHERE parent_id = :parent_id
                    ), 1),
                    :parent_id,
                    CAST(:allows_projects AS boolean),
                    CAST(:is_direct AS boolean)
                )
                ON CONFLICT (id) DO UPDATE
                SET name = EXCLUDED.name,
                    parent_id = EXCLUDED.parent_id,
                    allows_projects = true,
                    is_direct = true
            """),
            {
                "department_id": direct_department_id,
                "name": "直属分级",
                "parent_id": department_id,
                "allows_projects": True,
                "is_direct": True,
            },
        )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="create_department",
        resource_type="department",
        resource_id=department_id,
        metadata={"name": name, "parent_id": parent_id},
        request=request,
    )
    return DepartmentSchema(
        id=str(row.id),
        name=str(row.name),
        sort_order=int(row.sort_order or 0),
        parent_id=getattr(row, "parent_id", parent_id),
        parent_name=parent_name,
        allows_projects=bool(getattr(row, "allows_projects", bool(parent_id))),
        level=int(getattr(row, "level", 2 if parent_id else 1)),
        is_direct=bool(getattr(row, "is_direct", False)),
    )


@router.patch("/project-memory/departments/{department_id}", response_model=DepartmentSchema)
def update_project_memory_department(
    request: Request,
    department_id: str,
    body: UpdateDepartmentRequest,
    orm: Session = Depends(get_orm_session),
) -> DepartmentSchema:
    user_id = _system_admin_user(request, orm)
    name = " ".join(body.name.split())
    current = orm.execute(
        text("SELECT id, parent_id, is_direct FROM public.departments WHERE id = :department_id"),
        {"department_id": department_id},
    ).first()
    if current is None:
        raise HTTPException(status_code=404, detail="department not found")
    if bool(getattr(current, "is_direct", False)):
        raise HTTPException(
            status_code=409,
            detail="the generated direct category cannot be renamed, moved, or disabled",
        )
    parent_id = getattr(current, "parent_id", None)
    if parent_id is not None and "parent_id" in body.model_fields_set:
        if not body.parent_id:
            raise HTTPException(status_code=400, detail="second-level departments must keep a root parent")
        parent = orm.execute(
            text("SELECT id, name, parent_id FROM public.departments WHERE id = :parent_id"),
            {"parent_id": body.parent_id},
        ).first()
        if parent is None:
            raise HTTPException(status_code=404, detail="parent department not found")
        if getattr(parent, "parent_id", None) is not None:
            raise HTTPException(status_code=400, detail="second-level departments can only move under a root category")
        parent_id = str(parent.id)
    row = orm.execute(
        text("""
            UPDATE public.departments department
            SET name = :name,
                sort_order = :sort_order,
                parent_id = :parent_id
            WHERE department.id = :department_id
            RETURNING department.id, department.name, department.sort_order,
                      department.parent_id,
                      (SELECT parent.name FROM public.departments parent WHERE parent.id = department.parent_id) AS parent_name,
                      department.allows_projects,
                      CASE WHEN department.parent_id IS NULL THEN 1 ELSE 2 END AS level
        """),
        {
            "department_id": department_id,
            "name": name,
            "sort_order": body.sort_order,
            "parent_id": parent_id,
        },
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="department not found")
    orm.commit()
    record_audit(
        orm, user_id=user_id, action="update_department", resource_type="department",
        resource_id=department_id,
        metadata={"name": name, "sort_order": body.sort_order, "parent_id": parent_id},
        request=request,
    )
    return _department_from_row(row)


@router.put("/project-memory/departments/reorder", response_model=list[DepartmentSchema])
def reorder_project_memory_departments(
    request: Request,
    body: ReorderDepartmentsRequest,
    orm: Session = Depends(get_orm_session),
) -> list[DepartmentSchema]:
    user_id = _system_admin_user(request, orm)
    parent_id = body.parent_id.strip().lower() if body.parent_id else None
    department_ids = [department_id.strip().lower() for department_id in body.department_ids]
    if any(not department_id for department_id in department_ids):
        raise HTTPException(status_code=400, detail="department ids cannot be empty")
    if len(set(department_ids)) != len(department_ids):
        raise HTTPException(status_code=400, detail="department ids cannot contain duplicates")

    rows = orm.execute(
        text("""
            SELECT department.id, department.name, department.sort_order,
                   department.parent_id, parent.name AS parent_name,
                   department.allows_projects,
                   COALESCE(department.is_direct, false) AS is_direct,
                   CASE WHEN department.parent_id IS NULL THEN 1 ELSE 2 END AS level
            FROM public.departments department
            LEFT JOIN public.departments parent ON parent.id = department.parent_id
            WHERE department.parent_id IS NOT DISTINCT FROM :parent_id
            ORDER BY department.sort_order, department.name, department.id
            FOR UPDATE OF department
        """),
        {"parent_id": parent_id},
    ).all()
    current_by_id = {str(row.id): row for row in rows}
    if set(department_ids) != set(current_by_id):
        raise HTTPException(
            status_code=409,
            detail="department order must contain every category from the same parent exactly once",
        )

    ordered: list[DepartmentSchema] = []
    for sort_order, department_id in enumerate(department_ids, start=1):
        orm.execute(
            text("""
                UPDATE public.departments
                SET sort_order = :sort_order
                WHERE id = :department_id
                  AND parent_id IS NOT DISTINCT FROM :parent_id
            """),
            {
                "department_id": department_id,
                "parent_id": parent_id,
                "sort_order": sort_order,
            },
        )
        ordered.append(
            _department_from_row(current_by_id[department_id]).model_copy(
                update={"sort_order": sort_order},
            )
        )

    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="reorder_departments",
        resource_type="department",
        resource_id=parent_id or "root",
        metadata={"parent_id": parent_id, "department_ids": department_ids},
        request=request,
    )
    return ordered


@router.delete("/project-memory/departments/{department_id}", status_code=204)
def delete_project_memory_department(
    request: Request,
    department_id: str,
    orm: Session = Depends(get_orm_session),
):
    user_id = _system_admin_user(request, orm)
    usage = orm.execute(
        text("""
            SELECT
                COALESCE(current_department.is_direct, false) AS is_direct,
                current_department.parent_id,
                (SELECT COUNT(*) FROM public.departments
                 WHERE parent_id = :department_id AND NOT is_direct)::int AS custom_child_count,
                (SELECT COUNT(*) FROM public.departments
                 WHERE parent_id = :department_id AND is_direct)::int AS direct_child_count,
                (SELECT COUNT(*) FROM public.projects project
                 JOIN public.departments direct_child
                   ON direct_child.id = project.department_id
                  AND direct_child.parent_id = :department_id
                  AND direct_child.is_direct)::int AS direct_project_count,
                (SELECT COUNT(*) FROM public.project_creation_requests request_row
                 JOIN public.departments direct_child
                   ON direct_child.id = request_row.department_id
                  AND direct_child.parent_id = :department_id
                  AND direct_child.is_direct)::int AS direct_request_count,
                (SELECT COUNT(*) FROM public.projects WHERE department_id = :department_id)::int AS project_count,
                (SELECT COUNT(*) FROM public.project_creation_requests
                 WHERE department_id = :department_id)::int AS request_count
            FROM public.departments current_department
            WHERE current_department.id = :department_id
        """),
        {"department_id": department_id},
    ).first()
    if usage is None:
        raise HTTPException(status_code=404, detail="department not found")
    if usage and bool(getattr(usage, "is_direct", False)):
        raise HTTPException(
            status_code=409,
            detail="the generated direct category cannot be deleted",
        )
    if usage and (
        usage.custom_child_count
        or usage.direct_project_count
        or usage.direct_request_count
        or usage.project_count
        or usage.request_count
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "department cannot be deleted while it has child categories, projects, "
                "or project requests"
            ),
        )
    row = orm.execute(
        text("DELETE FROM public.departments WHERE id = :department_id RETURNING id, name"),
        {"department_id": department_id},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="department not found")
    orm.commit()
    record_audit(
        orm, user_id=user_id, action="delete_department", resource_type="department",
        resource_id=department_id, metadata={"name": row.name}, request=request,
    )
    return None


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
    project = orm.execute(
        text("SELECT name, department_id FROM public.projects WHERE id = :project_id"),
        {"project_id": str(project_id)},
    ).first()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    pending = orm.execute(
        text("""
            SELECT id
            FROM public.project_memory_submissions
            WHERE project_id = :project_id
              AND submission_type = 'project_repository'
              AND status = 'pending_review'
        """),
        {"project_id": str(project_id)},
    ).first()
    if pending is not None:
        raise HTTPException(status_code=409, detail="a repository change is already pending review")

    submission_id = uuid.uuid4()
    draft_id = uuid.uuid4()
    git_url = str(body.git_url)
    try:
        orm.execute(
            text("""
            INSERT INTO public.project_memory_submissions (
                id, project_id, submission_type, payload, status, created_by_user_id
            )
            VALUES (
                :submission_id, :project_id, 'project_repository',
                CAST(:payload AS jsonb), 'pending_review', :user_id
            )
            """),
            {
                "submission_id": str(submission_id),
                "project_id": str(project_id),
                "payload": json.dumps({"git_url": git_url, "git_branch": body.git_branch}),
                "user_id": str(user_id),
            },
        )
    except IntegrityError as error:
        orm.rollback()
        raise HTTPException(status_code=409, detail="a repository change is already pending review") from error
    orm.execute(
        text("""
            INSERT INTO public.project_memory_drafts (
                id, project_id, department_id, title, status, template_version,
                markdown_content, source_count, created_by_user_id, submission_id
            ) VALUES (
                :draft_id, :project_id, :department_id, :title, 'pending_review',
                'project-repository-submission-v1', :markdown_content, 0,
                :user_id, :submission_id
            )
        """),
        {
            "draft_id": str(draft_id),
            "project_id": str(project_id),
            "department_id": str(project.department_id),
            "title": f"{project.name} GitHub 仓库地址审批",
            "markdown_content": (
                f"# GitHub 仓库地址审批\n\n- 项目：{project.name}\n"
                f"- 仓库：{git_url}\n- 分支：{body.git_branch}\n"
            ),
            "user_id": str(user_id),
            "submission_id": str(submission_id),
        },
    )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="project_memory_repository_upsert",
        resource_type="project",
        resource_id=str(project_id),
        metadata={
            "git_url": git_url,
            "git_branch": body.git_branch,
            "submission_id": str(submission_id),
            "draft_id": str(draft_id),
        },
        request=request,
    )
    return ProjectRepositorySchema(
        project_id=project_id,
        git_url=git_url,
        git_branch=body.git_branch,
        status="pending_review",
        draft_id=draft_id,
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
    return ProjectRepositorySchema(project_id=project_id, status="approved", **repository)


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

    department_name = _department_name(orm, department_id)
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
                      skill_candidates, generation_model, generation_used_fallback,
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
    return _row_to_draft(orm, row)


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
                   skill_candidates, generation_model, generation_used_fallback,
                   created_at::text, updated_at::text
            FROM public.project_memory_drafts
            WHERE project_id = :project_id
            ORDER BY created_at DESC
        """),
        {"project_id": str(project_id)},
    ).all()
    return [_row_to_draft(orm, row) for row in rows]


@router.get(
    "/project-memory/review-queue",
    response_model=list[ProjectMemoryReviewQueueItemSchema],
)
def list_project_memory_review_queue(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> list[ProjectMemoryReviewQueueItemSchema]:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    global_reviewer = _is_global_project_reviewer(orm, user_id)
    rows = orm.execute(
        text("""
            SELECT draft.id::text,
                   draft.project_id::text,
                   project.name AS project_name,
                   draft.department_id,
                   department.name AS department_name,
                   CASE
                       WHEN parent.name IS NULL THEN department.name
                       ELSE parent.name || ' / ' || department.name
                   END AS department_path,
                   draft.title,
                   draft.status,
                   draft.markdown_content,
                   draft.source_count,
                   COALESCE(submission.submission_type, 'project_material') AS review_kind,
                   submission.payload AS submission_payload,
                   draft.created_by_user_id::text AS uploader_user_id,
                   split_part(uploader_auth.email, '@', 1) AS uploader_username,
                   uploader.nickname AS uploader_nickname,
                   COALESCE(
                       NULLIF(BTRIM(uploader.nickname), ''),
                       NULLIF(BTRIM(uploader.full_name), ''),
                       split_part(uploader_auth.email, '@', 1),
                       '未知成员'
                   ) AS uploader_display_name,
                   CASE
                       WHEN submission.submission_type = 'meeting_summary'
                           THEN ARRAY[submission.filename]
                       WHEN submission.submission_type = 'project_repository'
                           THEN ARRAY[]::text[]
                       ELSE COALESCE(
                           array_agg(file.filename ORDER BY file.created_at, file.filename)
                               FILTER (WHERE file.id IS NOT NULL AND file.included = true),
                           ARRAY[]::text[]
                       )
                   END AS file_names,
                   CASE
                       WHEN submission.submission_type = 'meeting_summary'
                           THEN COALESCE(submission.size_bytes, 0)
                       WHEN submission.submission_type = 'project_repository'
                           THEN 0
                       ELSE COALESCE(
                           SUM(file.size_bytes) FILTER (WHERE file.id IS NOT NULL AND file.included = true),
                           0
                       )
                   END AS total_size_bytes,
                   draft.created_at::text,
                   draft.updated_at::text
            FROM public.project_memory_drafts draft
            JOIN public.projects project ON project.id = draft.project_id
            JOIN public.departments department ON department.id = draft.department_id
            LEFT JOIN public.departments parent ON parent.id = department.parent_id
            LEFT JOIN auth.users uploader_auth ON uploader_auth.id = draft.created_by_user_id
            LEFT JOIN public.users uploader ON uploader.id = draft.created_by_user_id
            LEFT JOIN public.project_memory_submissions submission ON submission.id = draft.submission_id
            LEFT JOIN public.project_material_intake_files file ON file.intake_id = draft.intake_id
            WHERE draft.status = 'pending_review'
              AND (
                  CAST(:global_reviewer AS boolean)
                  OR EXISTS (
                      SELECT 1
                      FROM public.project_members pm
                      WHERE pm.project_id = draft.project_id
                        AND pm.user_id = :user_id
                        AND pm.role::text IN ('owner', 'admin')
                  )
              )
            GROUP BY draft.id, project.name, department.name, parent.name,
                     uploader_auth.email, uploader.nickname, uploader.full_name,
                     submission.submission_type, submission.payload,
                     submission.filename, submission.size_bytes
            ORDER BY draft.created_at ASC, project.name, draft.id
        """),
        {"global_reviewer": global_reviewer, "user_id": str(user_id)},
    ).all()
    return [
        ProjectMemoryReviewQueueItemSchema(
            id=uuid.UUID(str(row.id)),
            project_id=uuid.UUID(str(row.project_id)),
            project_name=str(row.project_name),
            department_id=str(row.department_id),
            department_name=str(row.department_name),
            department_path=str(row.department_path),
            title=str(row.title),
            status=row.status,
            markdown_content=str(row.markdown_content),
            source_count=int(row.source_count or 0),
            review_kind=getattr(row, "review_kind", "project_material") or "project_material",
            uploader=ReviewQueueUploaderSchema(
                user_id=(uuid.UUID(str(row.uploader_user_id)) if row.uploader_user_id else None),
                username=row.uploader_username,
                nickname=row.uploader_nickname,
                display_name=str(row.uploader_display_name),
            ),
            file_names=list(row.file_names or []),
            total_size_bytes=int(row.total_size_bytes or 0),
            repository_url=(
                str((getattr(row, "submission_payload", None) or {}).get("git_url"))
                if (getattr(row, "submission_payload", None) or {}).get("git_url")
                else None
            ),
            repository_branch=(
                str((getattr(row, "submission_payload", None) or {}).get("git_branch"))
                if (getattr(row, "submission_payload", None) or {}).get("git_branch")
                else None
            ),
            meeting_date=(
                str((getattr(row, "submission_payload", None) or {}).get("meeting_date"))
                if (getattr(row, "submission_payload", None) or {}).get("meeting_date")
                else None
            ),
            created_at=str(row.created_at) if row.created_at else None,
            updated_at=str(row.updated_at) if row.updated_at else None,
        )
        for row in rows
    ]


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
            SELECT draft.id::text, draft.project_id::text, draft.department_id,
                   draft.status, draft.markdown_content, draft.title,
                   draft.template_version, draft.intake_id::text, draft.skill_candidates,
                   draft.created_by_user_id::text, draft.submission_id::text,
                   draft.approved_document_id::text,
                   submission.submission_type,
                   submission.approved_resource_id::text,
                   submission.payload AS submission_payload,
                   submission.filename AS submission_filename,
                   submission.format AS submission_format,
                   submission.mime_type AS submission_mime_type,
                   submission.size_bytes AS submission_size_bytes,
                   submission.content_hash AS submission_content_hash,
                   submission.raw_content AS submission_raw_content
            FROM public.project_memory_drafts draft
            LEFT JOIN public.project_memory_submissions submission
                   ON submission.id = draft.submission_id
            WHERE draft.id = :draft_id
            FOR UPDATE OF draft
        """),
        {"draft_id": str(draft_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project memory draft not found")
    project_id = uuid.UUID(str(row.project_id))
    _require_project_reviewer(orm, user_id=user_id, project_id=project_id)
    if row.status != "pending_review":
        repeated_status = "approved" if body.decision == "approve" else "rejected"
        if row.status == repeated_status:
            approved_resource_id = getattr(row, "approved_resource_id", None)
            if not approved_resource_id and getattr(row, "submission_id", None):
                refreshed_submission = orm.execute(
                    text("""
                        SELECT approved_resource_id::text AS approved_resource_id
                        FROM public.project_memory_submissions
                        WHERE id = :submission_id
                    """),
                    {"submission_id": str(row.submission_id)},
                ).first()
                if refreshed_submission is not None:
                    approved_resource_id = refreshed_submission.approved_resource_id
            return ReviewDraftResponse(
                id=draft_id,
                status=row.status,
                document_id=(
                    uuid.UUID(str(row.approved_document_id))
                    if getattr(row, "approved_document_id", None)
                    else None
                ),
                resource_id=(
                    uuid.UUID(str(approved_resource_id))
                    if approved_resource_id
                    else None
                ),
            )
        raise HTTPException(status_code=409, detail=f"draft already {row.status}")

    resource_id: uuid.UUID | None = None
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
        if getattr(row, "intake_id", None):
            orm.execute(
                text("""
                    UPDATE public.project_material_intakes
                    SET status = 'rejected', updated_at = now()
                    WHERE id = :intake_id
                """),
                {"intake_id": str(row.intake_id)},
            )
            if getattr(row, "template_version", None) == "project-material-original-v1":
                orm.execute(
                    text("""
                        UPDATE public.project_material_intake_files
                        SET raw_content = ''::bytea, extracted_text = ''
                        WHERE intake_id = :intake_id AND document_id IS NULL
                    """),
                    {"intake_id": str(row.intake_id)},
                )
        if getattr(row, "submission_id", None):
            orm.execute(
                text("""
                    UPDATE public.project_memory_submissions
                    SET status = 'rejected', reviewed_by_user_id = :user_id,
                        review_comment = :comment, reviewed_at = now(),
                        raw_content = NULL, updated_at = now()
                    WHERE id = :submission_id
                """),
                {
                    "submission_id": str(row.submission_id),
                    "user_id": str(user_id),
                    "comment": body.comment,
                },
            )
        orm.commit()
        status: DraftStatus = "rejected"
        document_id = None
        chunk_count = 0
        wiki_page_count = 0
    else:
        intake_id = getattr(row, "intake_id", None)
        submission_type = getattr(row, "submission_type", None)
        if submission_type == "meeting_summary":
            resource_id = _publish_meeting_submission(
                orm,
                draft_id=draft_id,
                project_id=project_id,
                row=row,
            )
            document_id = None
            chunk_count = 0
            wiki_page_count = 0
            orm.execute(
                text("""
                    UPDATE public.project_memory_submissions
                    SET status = 'approved', approved_resource_id = :resource_id,
                        reviewed_by_user_id = :user_id, review_comment = :comment,
                        reviewed_at = now(), raw_content = NULL, updated_at = now()
                    WHERE id = :submission_id
                """),
                {
                    "submission_id": str(row.submission_id),
                    "resource_id": str(resource_id),
                    "user_id": str(user_id),
                    "comment": body.comment,
                },
            )
        elif submission_type == "project_repository":
            payload = _submission_payload(row.submission_payload)
            git_url = str(payload.get("git_url") or "").strip()
            git_branch = str(payload.get("git_branch") or "").strip()
            if not git_url or not git_branch:
                raise HTTPException(status_code=500, detail="pending repository metadata is invalid")
            orm.execute(
                text("""
                    INSERT INTO public.project_repositories (
                        project_id, git_url, git_branch, created_by_user_id, updated_at
                    ) VALUES (:project_id, :git_url, :git_branch, :created_by, now())
                    ON CONFLICT (project_id) DO UPDATE SET
                        git_url = excluded.git_url,
                        git_branch = excluded.git_branch,
                        updated_at = now()
                """),
                {
                    "project_id": str(project_id),
                    "git_url": git_url,
                    "git_branch": git_branch,
                    "created_by": str(row.created_by_user_id or user_id),
                },
            )
            resource_id = project_id
            document_id = None
            chunk_count = 0
            wiki_page_count = 0
            orm.execute(
                text("""
                    UPDATE public.project_memory_submissions
                    SET status = 'approved', approved_resource_id = :resource_id,
                        reviewed_by_user_id = :user_id, review_comment = :comment,
                        reviewed_at = now(), updated_at = now()
                    WHERE id = :submission_id
                """),
                {
                    "submission_id": str(row.submission_id),
                    "resource_id": str(project_id),
                    "user_id": str(user_id),
                    "comment": body.comment,
                },
            )
        elif intake_id and getattr(row, "template_version", None) == "project-material-original-v1":
            material_rows = orm.execute(
                text("""
                    SELECT id::text, filename, format, size_bytes, content_hash,
                           raw_content, storage_key, recommendation, included
                    FROM public.project_material_intake_files
                    WHERE intake_id = :intake_id
                      AND included = true
                      AND recommendation = 'keep'
                      AND document_id IS NULL
                    ORDER BY created_at, filename
                """),
                {"intake_id": str(intake_id)},
            ).all()
            if not material_rows:
                raise HTTPException(status_code=500, detail="approved original material files are missing")
            ingested: list[tuple[object, uuid.UUID, int]] = []
            uploaded_by_user_id = uuid.UUID(str(row.created_by_user_id or user_id))
            for material in material_rows:
                stored_path = (
                    resolve_storage_key(str(material.storage_key))
                    if getattr(material, "storage_key", None)
                    else None
                )
                temp_path = stored_path or _write_material_to_temp(
                    str(material.filename),
                    str(material.format),
                    bytes(material.raw_content),
                )
                try:
                    result = ingest_file(
                        temp_path,
                        project_id=project_id,
                        display_name=str(material.filename),
                        created_by_user_id=uploaded_by_user_id,
                    )
                finally:
                    if stored_path is None:
                        temp_path.unlink(missing_ok=True)
                if result.error:
                    raise HTTPException(status_code=500, detail=f"original material ingest failed: {result.error}")
                ingested.append((material, result.document_id, int(result.chunk_count or 0)))

            for material, ingested_document_id, _ in ingested:
                orm.execute(
                    text("""
                        UPDATE public.documents
                        SET department_id = :department_id,
                            memory_type = 'raw_project_material',
                            memory_draft_id = :draft_id,
                            template_version = 'project-material-original-v1'
                        WHERE id = :document_id
                    """),
                    {
                        "department_id": row.department_id,
                        "draft_id": str(draft_id),
                        "document_id": str(ingested_document_id),
                    },
                )
                orm.execute(
                    text("""
                        UPDATE public.project_material_intake_files
                        SET document_id = :document_id
                        WHERE id = :file_id
                    """),
                    {"document_id": str(ingested_document_id), "file_id": str(material.id)},
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
                        "document_id": str(ingested_document_id),
                        "draft_id": str(draft_id),
                        "user_id": str(uploaded_by_user_id),
                        "content_hash": str(material.content_hash),
                        "file_id": str(material.id),
                    },
                )
            document_id = ingested[0][1]
            chunk_count = sum(item[2] for item in ingested)
            wiki_page_count = 0
            orm.execute(
                text("""
                    UPDATE public.project_material_intakes
                    SET status = 'approved', updated_at = now()
                    WHERE id = :intake_id
                """),
                {"intake_id": str(intake_id)},
            )
        elif intake_id:
            document_rows = orm.execute(
                text("""
                    SELECT id::text, memory_type
                    FROM public.documents
                    WHERE memory_draft_id = :draft_id
                      AND memory_type IN ('raw_project_material', 'curated_project_source')
                    ORDER BY CASE WHEN memory_type = 'curated_project_source' THEN 0 ELSE 1 END,
                             created_at
                """),
                {"draft_id": str(draft_id)},
            ).all()
            if not document_rows:
                raise HTTPException(status_code=500, detail="confirmed knowledge documents are missing")
            curated_row = next(
                (item for item in document_rows if item.memory_type == "curated_project_source"),
                document_rows[0],
            )
            document_id = uuid.UUID(str(curated_row.id))
            raw_skills = getattr(row, "skill_candidates", None) or []
            if isinstance(raw_skills, str):
                raw_skills = json.loads(raw_skills)
            candidates = build_skill_candidates(
                raw_skills if isinstance(raw_skills, list) else [],
                source_document_ids=[str(item.id) for item in document_rows],
            )
            page_ids = publish_approved_candidates(
                orm,
                project_id=project_id,
                candidates=candidates,
                approved_by_user_id=user_id,
            )
            wiki_page_count = len(page_ids)
            chunk_count = 0
            orm.execute(
                text("""
                    UPDATE public.project_material_intakes
                    SET status = 'approved', updated_at = now()
                    WHERE id = :intake_id
                """),
                {"intake_id": str(intake_id)},
            )
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
            wiki_page_count = 0
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
                "document_id": str(document_id) if document_id is not None else None,
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
        resource_id=resource_id,
        chunk_count=chunk_count,
        wiki_page_count=wiki_page_count,
    )
