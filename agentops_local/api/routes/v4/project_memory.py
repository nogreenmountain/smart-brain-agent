from __future__ import annotations

import hashlib
import json
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
from agentops.project_memory.publish import build_skill_candidates
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
    skill_count: int = 0
    generation_model: str | None = None
    generation_used_fallback: bool = False
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
    wiki_page_count: int = 0


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
            SELECT id::text, project_id::text, department_id, status, markdown_content, title,
                   template_version, intake_id::text, skill_candidates, created_by_user_id::text
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
        orm.commit()
        status: DraftStatus = "rejected"
        document_id = None
        chunk_count = 0
        wiki_page_count = 0
    else:
        intake_id = getattr(row, "intake_id", None)
        if intake_id and getattr(row, "template_version", None) == "project-material-original-v1":
            material_rows = orm.execute(
                text("""
                    SELECT id::text, filename, format, size_bytes, content_hash,
                           raw_content, recommendation, included
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
                temp_path = _write_material_to_temp(
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
        wiki_page_count=wiki_page_count,
    )
