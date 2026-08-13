"""
Project management endpoints.

  POST   /v4/projects                      create project (org must exist)
  GET    /v4/projects                      list projects user can see
  PATCH  /v4/projects/{id}                 update project lifecycle fields
  DELETE /v4/projects/{id}                 delete project (admin+ only)
  POST   /v4/projects/{id}/members         add/update member (admin+ only)
  DELETE /v4/projects/{id}/members/{uid}   remove member (admin+ only)
  POST   /v4/projects/{id}/members/{uid}/password reset member password (admin+ only)

Authorization is project-scoped (see agentops.rag.authz):
  - create: caller must be owner/admin of the target org (we look up the
    project by its org_id and require org-level ownership via user_orgs)
  - list: any logged-in user sees projects where they are a direct member
  - add/remove member: project admin+
"""
from __future__ import annotations

import threading
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.common.orm import get_orm_session, session_scope
from agentops.auth.middleware import AuthenticatedRoute
from agentops.rag.audit import record_audit
from agentops.rag.authz import (
    AuthzError,
    ROLE_RANK,
    current_user_id,
    is_system_admin,
    require_admin,
    require_member,
)


router = APIRouter(route_class=AuthenticatedRoute)


class CreateProjectRequest(BaseModel):
    org_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    environment: str = Field("development", pattern="^(development|staging|production)$")
    department_id: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    completed_at: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class CreateProjectRequestSubmission(BaseModel):
    org_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    environment: str = Field("development", pattern="^(development|staging|production)$")
    department_id: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    completed_at: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(..., min_length=1, max_length=2000)


class ReviewProjectRequest(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    comment: str = Field("", max_length=2000)


class ProjectCreationRequestSchema(BaseModel):
    id: uuid.UUID
    requester_id: uuid.UUID
    requester_username: str
    org_id: uuid.UUID
    org_name: str
    name: str
    environment: str
    department_id: str
    department_name: str
    completed_at: Optional[str] = None
    reason: str
    status: str
    review_comment: Optional[str] = None
    reviewed_by_user_id: Optional[uuid.UUID] = None
    created_project_id: Optional[uuid.UUID] = None
    created_at: str
    reviewed_at: Optional[str] = None


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    completed_at: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    department_id: Optional[str] = Field(None, pattern=r"^[a-z][a-z0-9_-]{1,39}$")


class CreateProjectDepartmentMigrationRequest(BaseModel):
    target_department_id: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    expected_source_department_id: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    migrate_knowledge_base: bool = True
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=120)


class ProjectDepartmentMigrationSchema(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_department_id: str
    target_department_id: str
    status: str
    current_step: str
    progress: int
    raw_material_count: int = 0
    wiki_page_count: int = 0
    meeting_record_count: int = 0
    documents_updated: int = 0
    material_intakes_updated: int = 0
    memory_drafts_updated: int = 0
    pending_requests_updated: int = 0
    verified: bool = False
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProjectSchema(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    environment: str
    department_id: str = "research-direct"
    role: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class AddMemberRequest(BaseModel):
    user_id: Optional[uuid.UUID] = None
    identifier: Optional[str] = Field(None, min_length=1, max_length=320)
    role: str = Field("developer", pattern="^(business_user|developer|admin|owner)$")


class MemberSchema(BaseModel):
    user_id: uuid.UUID
    email: str
    username: str
    nickname: Optional[str] = None
    display_name: str
    role: str


class MemberOptionSchema(BaseModel):
    user_id: uuid.UUID
    email: str
    username: str
    nickname: Optional[str] = None
    display_name: str


class ResetMemberPasswordRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class ResetMemberPasswordResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    status: str = "updated"


class RenameMemberUsernameRequest(BaseModel):
    username: str = Field(..., pattern=r"^[a-z0-9][a-z0-9._-]{1,62}$")


def _user_org_role(orm: Session, *, user_id: uuid.UUID, org_id: uuid.UUID) -> Optional[str]:
    if is_system_admin(orm, user_id=user_id):
        return "owner"
    row = orm.execute(
        text("SELECT role::text AS role FROM public.user_orgs WHERE user_id=:u AND org_id=:o"),
        {"u": str(user_id), "o": str(org_id)},
    ).first()
    return row.role if row else None


def _normalize_user_identifier(identifier: str) -> str:
    value = identifier.strip().lower()
    if not value:
        raise HTTPException(status_code=400, detail="member identifier is required")
    if "@" not in value:
        value = f"{value}@local.dev"
    return value


def _display_name_from_email(email: str) -> str:
    return email.split("@", 1)[0]


def _require_project_department(
    orm: Session,
    *,
    department_id: str,
    missing_status_code: int = 400,
):
    department = orm.execute(
        text("""
            SELECT id, parent_id, allows_projects
            FROM public.departments
            WHERE id = :department_id
        """),
        {"department_id": department_id},
    ).first()
    if department is None:
        raise HTTPException(status_code=missing_status_code, detail="department not found")
    is_root_category = hasattr(department, "parent_id") and department.parent_id is None
    if is_root_category or not bool(getattr(department, "allows_projects", True)):
        raise HTTPException(
            status_code=400,
            detail="projects can only be assigned to a project category",
        )
    return department


def _resolve_target_user(orm: Session, body: AddMemberRequest):
    if body.user_id is not None:
        target = orm.execute(
            text("""
                SELECT au.id::text AS id, au.email
                FROM auth.users au
                JOIN public.users pu ON pu.id = au.id
                WHERE au.id = :u
                  AND COALESCE(pu.is_active, true)
                  AND lower(au.email) NOT LIKE '%@agentops.local'
            """),
            {"u": str(body.user_id)},
        ).first()
        if target is None:
            raise HTTPException(status_code=404, detail="active team member not found")
        return target
    if body.identifier:
        candidate = body.identifier.strip()
        user_id_param = None
        if "@" not in candidate and len(candidate) == 36:
            try:
                uuid.UUID(candidate)
                user_id_param = candidate
            except ValueError:
                pass
        email = _normalize_user_identifier(candidate)
        if user_id_param:
            target = orm.execute(
                text("""
                    SELECT au.id::text AS id, au.email
                    FROM auth.users au
                    JOIN public.users pu ON pu.id = au.id
                    WHERE (lower(au.email) = lower(:email)
                       OR au.id = CAST(:user_id AS uuid))
                      AND COALESCE(pu.is_active, true)
                      AND lower(au.email) NOT LIKE '%@agentops.local'
                """),
                {"email": email, "user_id": user_id_param},
            ).first()
        else:
            target = orm.execute(
                text("""
                    SELECT au.id::text AS id, au.email
                    FROM auth.users au
                    JOIN public.users pu ON pu.id = au.id
                    WHERE lower(au.email) = lower(:email)
                      AND COALESCE(pu.is_active, true)
                      AND lower(au.email) NOT LIKE '%@agentops.local'
                """),
                {"email": email},
            ).first()
        if target is None:
            raise HTTPException(status_code=404, detail="active team member not found")
        return target
    raise HTTPException(status_code=400, detail="user_id or identifier is required")


def _project_from_row(row) -> ProjectSchema:
    return ProjectSchema(
        id=uuid.UUID(row.id),
        org_id=uuid.UUID(row.org_id),
        name=row.name,
        environment=row.environment,
        department_id=row.department_id,
        role=getattr(row, "role", None),
        created_at=getattr(row, "created_at", None),
        completed_at=getattr(row, "completed_at", None),
    )


def _department_migration_from_row(row) -> ProjectDepartmentMigrationSchema:
    return ProjectDepartmentMigrationSchema(
        id=uuid.UUID(str(row.id)),
        project_id=uuid.UUID(str(row.project_id)),
        source_department_id=str(row.source_department_id),
        target_department_id=str(row.target_department_id),
        status=str(row.status),
        current_step=str(row.current_step),
        progress=int(row.progress or 0),
        raw_material_count=int(row.raw_material_count or 0),
        wiki_page_count=int(row.wiki_page_count or 0),
        meeting_record_count=int(row.meeting_record_count or 0),
        documents_updated=int(row.documents_updated or 0),
        material_intakes_updated=int(row.material_intakes_updated or 0),
        memory_drafts_updated=int(row.memory_drafts_updated or 0),
        pending_requests_updated=int(row.pending_requests_updated or 0),
        verified=bool(row.verified),
        error_message=getattr(row, "error_message", None),
        created_at=getattr(row, "created_at", None),
        started_at=getattr(row, "started_at", None),
        completed_at=getattr(row, "completed_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


def _department_migration_select_sql(*, where_sql: str, for_update: bool = False) -> str:
    lock_sql = " FOR UPDATE" if for_update else ""
    return f"""
        SELECT id::text AS id, project_id::text AS project_id,
               source_department_id, target_department_id, status, current_step,
               progress, raw_material_count, wiki_page_count, meeting_record_count,
               documents_updated, material_intakes_updated, memory_drafts_updated,
               pending_requests_updated, verified, error_message,
               created_at::text AS created_at, started_at::text AS started_at,
               completed_at::text AS completed_at, updated_at::text AS updated_at
        FROM public.project_department_migrations
        WHERE {where_sql}{lock_sql}
    """


def _get_department_migration(
    orm: Session,
    *,
    migration_id: uuid.UUID,
    project_id: Optional[uuid.UUID] = None,
    for_update: bool = False,
):
    where_sql = "id = :migration_id"
    params = {"migration_id": str(migration_id)}
    if project_id is not None:
        where_sql += " AND project_id = :project_id"
        params["project_id"] = str(project_id)
    row = orm.execute(
        text(_department_migration_select_sql(where_sql=where_sql, for_update=for_update)),
        params,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project department migration not found")
    return row


def _project_request_from_row(row) -> ProjectCreationRequestSchema:
    return ProjectCreationRequestSchema(
        id=uuid.UUID(row.id),
        requester_id=uuid.UUID(row.requester_id),
        requester_username=row.requester_username,
        org_id=uuid.UUID(row.org_id),
        org_name=row.org_name,
        name=row.name,
        environment=row.environment,
        department_id=row.department_id,
        department_name=row.department_name,
        completed_at=getattr(row, "completed_at", None),
        reason=row.reason,
        status=row.status,
        review_comment=getattr(row, "review_comment", None),
        reviewed_by_user_id=(
            uuid.UUID(row.reviewed_by_user_id)
            if getattr(row, "reviewed_by_user_id", None)
            else None
        ),
        created_project_id=(
            uuid.UUID(row.created_project_id)
            if getattr(row, "created_project_id", None)
            else None
        ),
        created_at=row.created_at,
        reviewed_at=getattr(row, "reviewed_at", None),
    )


def _project_request_select_sql(*, where_sql: str, for_update: bool = False) -> str:
    lock_sql = " FOR UPDATE OF request_row" if for_update else ""
    return f"""
        SELECT request_row.id::text AS id,
               request_row.requester_id::text AS requester_id,
               split_part(requester.email, '@', 1) AS requester_username,
               request_row.org_id::text AS org_id,
               org.name AS org_name,
               request_row.name,
               request_row.environment::text AS environment,
               request_row.department_id,
               CASE
                   WHEN parent_department.id IS NULL THEN department.name
                   ELSE parent_department.name || ' / ' || department.name
               END AS department_name,
               request_row.completed_at::text AS completed_at,
               request_row.reason,
               request_row.status,
               request_row.review_comment,
               request_row.reviewed_by_user_id::text AS reviewed_by_user_id,
               request_row.created_project_id::text AS created_project_id,
               request_row.created_at::text AS created_at,
               request_row.reviewed_at::text AS reviewed_at
        FROM public.project_creation_requests request_row
        JOIN auth.users requester ON requester.id = request_row.requester_id
        JOIN public.orgs org ON org.id = request_row.org_id
        JOIN public.departments department ON department.id = request_row.department_id
        LEFT JOIN public.departments parent_department ON parent_department.id = department.parent_id
        WHERE {where_sql}{lock_sql}
    """


def _get_project_request(
    orm: Session,
    *,
    request_id: uuid.UUID,
    for_update: bool = False,
):
    row = orm.execute(
        text(_project_request_select_sql(where_sql="request_row.id = :request_id", for_update=for_update)),
        {"request_id": str(request_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project creation request not found")
    return row


def _get_project(orm: Session, *, project_id: uuid.UUID):
    row = orm.execute(
        text("""
            SELECT id::text AS id, org_id::text AS org_id, name, environment::text,
                   COALESCE(department_id, 'research') AS department_id,
                   created_at::text AS created_at, completed_at::text AS completed_at
            FROM public.projects
            WHERE id = :p
        """),
        {"p": str(project_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return row


def _record_project_audit(
    orm: Session,
    *,
    request: Request,
    caller_id: uuid.UUID,
    action: str,
    project_id: uuid.UUID,
    project_name: str | None = None,
    metadata: Optional[dict] = None,
) -> None:
    meta = {"project_id": str(project_id), "result_status": "ok"}
    if project_name:
        meta["project_name"] = project_name
    if metadata:
        meta.update(metadata)
    record_audit(
        orm,
        user_id=caller_id,
        action=action,
        resource_type="project",
        resource_id=str(project_id),
        metadata=meta,
        request=request,
    )


def _get_project_member(orm: Session, *, project_id: uuid.UUID, user_id: uuid.UUID):
    row = orm.execute(
        text("""
            SELECT pm.user_id::text AS user_id, au.email,
                   split_part(au.email, '@', 1) AS username,
                   pu.nickname,
                   COALESCE(NULLIF(BTRIM(pu.nickname), ''), au.email) AS display_name,
                   pm.role::text
            FROM public.project_members pm
            JOIN auth.users au ON au.id = pm.user_id
            LEFT JOIN public.users pu ON pu.id = pm.user_id
            WHERE pm.project_id = :p AND pm.user_id = :u
        """),
        {"p": str(project_id), "u": str(user_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project member not found")
    return row


def _record_member_audit(
    orm: Session,
    *,
    request: Request,
    caller_id: uuid.UUID,
    action: str,
    project_id: uuid.UUID,
    target_user_id: uuid.UUID,
    target_email: str | None = None,
    role: str | None = None,
    extra_metadata: Optional[dict] = None,
) -> None:
    metadata = {
        "project_id": str(project_id),
        "target_user_id": str(target_user_id),
        "result_status": "ok",
    }
    if target_email:
        metadata["target_email"] = target_email
    if role:
        metadata["role"] = role
    if extra_metadata:
        metadata.update(extra_metadata)
    record_audit(
        orm,
        user_id=caller_id,
        action=action,
        resource_type="project",
        resource_id=str(project_id),
        metadata=metadata,
        request=request,
    )


def _row_count(result) -> int:
    return max(int(getattr(result, "rowcount", 0) or 0), 0)


def _synchronize_project_department_metadata(
    orm: Session,
    *,
    project_id: uuid.UUID,
    target_department_id: str,
) -> tuple[int, int, int, int]:
    documents_updated = _row_count(orm.execute(
        text("""
            UPDATE public.documents
            SET department_id = :target_department_id
            WHERE project_id = :project_id
              AND department_id IS DISTINCT FROM :target_department_id
        """),
        {
            "project_id": str(project_id),
            "target_department_id": target_department_id,
        },
    ))
    intakes_updated = _row_count(orm.execute(
        text("""
            UPDATE public.project_material_intakes
            SET department_id = :target_department_id, updated_at = now()
            WHERE project_id = :project_id
              AND department_id IS DISTINCT FROM :target_department_id
        """),
        {
            "project_id": str(project_id),
            "target_department_id": target_department_id,
        },
    ))
    drafts_updated = _row_count(orm.execute(
        text("""
            UPDATE public.project_memory_drafts
            SET department_id = :target_department_id, updated_at = now()
            WHERE project_id = :project_id
              AND department_id IS DISTINCT FROM :target_department_id
        """),
        {
            "project_id": str(project_id),
            "target_department_id": target_department_id,
        },
    ))
    project_requests_updated = _row_count(orm.execute(
        text("""
            UPDATE public.project_creation_requests
            SET department_id = :target_department_id, updated_at = now()
            WHERE created_project_id = :project_id
              AND department_id IS DISTINCT FROM :target_department_id
        """),
        {
            "project_id": str(project_id),
            "target_department_id": target_department_id,
        },
    ))
    return (
        documents_updated,
        intakes_updated,
        drafts_updated,
        project_requests_updated,
    )


def _count_project_assets(orm: Session, *, project_id: uuid.UUID) -> tuple[int, int, int]:
    raw_materials = orm.execute(
        text("""
            SELECT COUNT(*)::int AS count
            FROM public.project_material_documents
            WHERE project_id = :project_id
        """),
        {"project_id": str(project_id)},
    ).first()
    wiki_pages = orm.execute(
        text("""
            SELECT COUNT(*)::int AS count
            FROM public.project_wiki_pages
            WHERE project_id = :project_id
        """),
        {"project_id": str(project_id)},
    ).first()
    meetings = orm.execute(
        text("""
            SELECT COUNT(*)::int AS count
            FROM public.meeting_summaries
            WHERE project_id = :project_id
        """),
        {"project_id": str(project_id)},
    ).first()
    return (
        int(getattr(raw_materials, "count", 0) or 0),
        int(getattr(wiki_pages, "count", 0) or 0),
        int(getattr(meetings, "count", 0) or 0),
    )


def _run_department_migration(orm: Session, migration_id: uuid.UUID) -> None:
    job = _get_department_migration(orm, migration_id=migration_id, for_update=True)
    if job.status == "completed":
        return
    if job.status not in {"queued", "failed"}:
        raise HTTPException(status_code=409, detail="project department migration is already running")

    orm.execute(
        text("""
            UPDATE public.project_department_migrations
            SET status = 'running', current_step = 'inventory', progress = 10,
                started_at = COALESCE(started_at, now()), completed_at = NULL,
                error_message = NULL, updated_at = now()
            WHERE id = :migration_id
        """),
        {"migration_id": str(migration_id)},
    )
    orm.commit()
    project = orm.execute(
        text("""
            SELECT id::text AS id, department_id
            FROM public.projects
            WHERE id = :project_id
        """),
        {"project_id": str(job.project_id)},
    ).first()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if str(project.department_id) not in {
        str(job.source_department_id),
        str(job.target_department_id),
    }:
        raise HTTPException(status_code=409, detail="project category changed during migration")

    orm.execute(
        text("""
            UPDATE public.project_department_migrations
            SET current_step = 'syncing_metadata', progress = 55, updated_at = now()
            WHERE id = :migration_id
        """),
        {"migration_id": str(migration_id)},
    )
    orm.commit()
    project = orm.execute(
        text("""
            SELECT id::text AS id, department_id
            FROM public.projects
            WHERE id = :project_id
            FOR UPDATE
        """),
        {"project_id": str(job.project_id)},
    ).first()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if str(project.department_id) not in {
        str(job.source_department_id),
        str(job.target_department_id),
    }:
        raise HTTPException(status_code=409, detail="project category changed during migration")
    orm.execute(
        text("""
            UPDATE public.projects
            SET department_id = :target_department_id
            WHERE id = :project_id
        """),
        {
            "project_id": str(job.project_id),
            "target_department_id": job.target_department_id,
        },
    )
    (
        documents_updated,
        intakes_updated,
        drafts_updated,
        pending_requests_updated,
    ) = _synchronize_project_department_metadata(
        orm,
        project_id=uuid.UUID(str(job.project_id)),
        target_department_id=str(job.target_department_id),
    )
    inventory = _count_project_assets(orm, project_id=uuid.UUID(str(job.project_id)))
    mismatches = orm.execute(
        text("""
            SELECT (
                SELECT COUNT(*) FROM public.documents
                WHERE project_id = :project_id
                  AND department_id IS DISTINCT FROM :target_department_id
            ) + (
                SELECT COUNT(*) FROM public.project_material_intakes
                WHERE project_id = :project_id
                  AND department_id IS DISTINCT FROM :target_department_id
            ) + (
                SELECT COUNT(*) FROM public.project_memory_drafts
                WHERE project_id = :project_id
                  AND department_id IS DISTINCT FROM :target_department_id
            ) + (
                SELECT COUNT(*) FROM public.project_creation_requests
                WHERE created_project_id = :project_id
                  AND department_id IS DISTINCT FROM :target_department_id
            ) AS count
        """),
        {
            "project_id": str(job.project_id),
            "target_department_id": job.target_department_id,
        },
    ).first()
    verified = int(getattr(mismatches, "count", 0) or 0) == 0 and inventory == (
        int(job.raw_material_count or 0),
        int(job.wiki_page_count or 0),
        int(job.meeting_record_count or 0),
    )
    if not verified:
        raise RuntimeError("project knowledge inventory changed during category migration")

    orm.execute(
        text("""
            UPDATE public.project_department_migrations
            SET status = 'completed', current_step = 'completed', progress = 100,
                documents_updated = :documents_updated,
                material_intakes_updated = :material_intakes_updated,
                memory_drafts_updated = :memory_drafts_updated,
                pending_requests_updated = :pending_requests_updated,
                verified = true, completed_at = now(), updated_at = now()
            WHERE id = :migration_id
        """),
        {
            "migration_id": str(migration_id),
            "documents_updated": documents_updated,
            "material_intakes_updated": intakes_updated,
            "memory_drafts_updated": drafts_updated,
            "pending_requests_updated": pending_requests_updated,
        },
    )
    orm.commit()


def _run_department_migration_in_background(migration_id: uuid.UUID) -> None:
    try:
        with session_scope() as orm:
            _run_department_migration(orm, migration_id)
    except Exception as error:
        try:
            with session_scope() as orm:
                orm.execute(
                    text("""
                        UPDATE public.project_department_migrations
                        SET status = 'failed', current_step = 'failed',
                            error_message = :error_message, updated_at = now()
                        WHERE id = :migration_id AND status <> 'completed'
                    """),
                    {
                        "migration_id": str(migration_id),
                        "error_message": str(error)[:2000],
                    },
                )
        except Exception:
            pass


def _dispatch_department_migration(migration_id: uuid.UUID) -> None:
    threading.Thread(
        target=_run_department_migration_in_background,
        args=(migration_id,),
        name=f"project-department-migration-{migration_id}",
        daemon=True,
    ).start()


@router.post("/projects", response_model=ProjectSchema, status_code=201)
def create_project(
    request: Request,
    body: CreateProjectRequest,
    orm: Session = Depends(get_orm_session),
) -> ProjectSchema:
    """Create a project under an org. Caller must be owner/admin of the org."""
    try:
        user_id = current_user_id(request)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    org_role = _user_org_role(orm, user_id=user_id, org_id=body.org_id)
    if org_role is None or ROLE_RANK.get(org_role, -1) < ROLE_RANK["admin"]:
        raise HTTPException(status_code=403, detail=f"need admin+ in target org; you are {org_role}")

    # Confirm org exists
    org_row = orm.execute(
        text("SELECT id FROM public.orgs WHERE id=:o"), {"o": str(body.org_id)}
    ).first()
    if org_row is None:
        raise HTTPException(status_code=404, detail="org not found")

    _require_project_department(orm, department_id=body.department_id)

    # Insert
    new_id = uuid.uuid4()
    api_key = uuid.uuid4()
    created = orm.execute(
        text("""
            INSERT INTO public.projects (id, org_id, api_key, name, environment, department_id, completed_at)
            VALUES (:id, :org, :key, :name, CAST(:env AS environment), :department_id, CAST(:completed_at AS date))
            RETURNING created_at::text AS created_at, completed_at::text AS completed_at
        """),
        {"id": str(new_id), "org": str(body.org_id), "key": str(api_key),
         "name": body.name, "env": body.environment, "department_id": body.department_id,
         "completed_at": body.completed_at},
    ).first()
    orm.commit()

    # Auto-add caller as project owner
    orm.execute(
        text("""
            INSERT INTO public.project_members (project_id, user_id, role)
            VALUES (:p, :u, 'owner')
            ON CONFLICT DO NOTHING
        """),
        {"p": str(new_id), "u": str(user_id)},
    )
    orm.commit()
    _record_project_audit(
        orm,
        request=request,
        caller_id=user_id,
        action="create_project",
        project_id=new_id,
        project_name=body.name,
    )

    return ProjectSchema(id=new_id, org_id=body.org_id, name=body.name,
                        environment=body.environment, department_id=body.department_id,
                        created_at=created.created_at if created else None,
                        completed_at=created.completed_at if created else body.completed_at)


@router.post("/project-requests", response_model=ProjectCreationRequestSchema, status_code=201)
def create_project_request(
    request: Request,
    body: CreateProjectRequestSubmission,
    orm: Session = Depends(get_orm_session),
) -> ProjectCreationRequestSchema:
    """Submit a project creation request without granting project creation rights."""
    try:
        user_id = current_user_id(request)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    organization_access = orm.execute(
        text("""
            SELECT true AS allowed
            WHERE EXISTS (
                SELECT 1
                FROM public.user_orgs user_org
                WHERE user_org.user_id = :user_id
                  AND user_org.org_id = :org_id
            ) OR EXISTS (
                SELECT 1
                FROM public.project_members project_member
                JOIN public.projects project ON project.id = project_member.project_id
                WHERE project_member.user_id = :user_id
                  AND project.org_id = :org_id
            )
        """),
        {"user_id": str(user_id), "org_id": str(body.org_id)},
    ).first()
    if organization_access is None:
        raise HTTPException(status_code=403, detail="you can only request projects in your organization")

    _require_project_department(orm, department_id=body.department_id)

    duplicate = orm.execute(
        text("""
            SELECT id
            FROM public.project_creation_requests
            WHERE requester_id = :requester_id
              AND org_id = :org_id
              AND lower(btrim(name)) = lower(btrim(:name))
              AND status = 'pending'
        """),
        {"requester_id": str(user_id), "org_id": str(body.org_id), "name": body.name.strip()},
    ).first()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="an identical project request is already pending")

    request_id = uuid.uuid4()
    orm.execute(
        text("""
            INSERT INTO public.project_creation_requests (
                id, requester_id, org_id, name, environment,
                department_id, completed_at, reason
            )
            VALUES (
                :id, :requester_id, :org_id, :name, CAST(:environment AS environment),
                :department_id, CAST(:completed_at AS date), :reason
            )
        """),
        {
            "id": str(request_id),
            "requester_id": str(user_id),
            "org_id": str(body.org_id),
            "name": body.name.strip(),
            "environment": body.environment,
            "department_id": body.department_id,
            "completed_at": body.completed_at,
            "reason": body.reason.strip(),
        },
    )
    orm.commit()
    created = _get_project_request(orm, request_id=request_id)
    record_audit(
        orm,
        user_id=user_id,
        action="request_project_creation",
        resource_type="project_creation_request",
        resource_id=str(request_id),
        metadata={
            "org_id": str(body.org_id),
            "department_id": body.department_id,
            "project_name": body.name.strip(),
            "result_status": "pending",
        },
        request=request,
    )
    return _project_request_from_row(created)


@router.get("/project-requests", response_model=list[ProjectCreationRequestSchema])
def list_project_requests(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> list[ProjectCreationRequestSchema]:
    """Return all requests to system admins and only the caller's requests otherwise."""
    try:
        user_id = current_user_id(request)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    if is_system_admin(orm, user_id=user_id):
        where_sql = "TRUE"
        params = {}
    else:
        where_sql = "request_row.requester_id = :requester_id"
        params = {"requester_id": str(user_id)}
    rows = orm.execute(
        text(
            _project_request_select_sql(where_sql=where_sql)
            + " ORDER BY CASE request_row.status WHEN 'pending' THEN 0 ELSE 1 END, request_row.created_at DESC"
        ),
        params,
    ).all()
    return [_project_request_from_row(row) for row in rows]


@router.post(
    "/project-requests/{request_id}/review",
    response_model=ProjectCreationRequestSchema,
)
def review_project_request(
    request: Request,
    request_id: uuid.UUID,
    body: ReviewProjectRequest,
    orm: Session = Depends(get_orm_session),
) -> ProjectCreationRequestSchema:
    """Approve or reject a pending request. Only system administrators may review."""
    try:
        reviewer_id = current_user_id(request)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    if not is_system_admin(orm, user_id=reviewer_id):
        raise HTTPException(status_code=403, detail="only system administrators can review project requests")

    pending = _get_project_request(orm, request_id=request_id, for_update=True)
    if pending.status != "pending":
        raise HTTPException(status_code=409, detail="project creation request has already been reviewed")

    status = "approved" if body.decision == "approve" else "rejected"
    created_project_id: Optional[uuid.UUID] = None
    if body.decision == "approve":
        _require_project_department(orm, department_id=pending.department_id)
        existing = orm.execute(
            text("""
                SELECT id
                FROM public.projects
                WHERE org_id = :org_id AND lower(btrim(name)) = lower(btrim(:name))
            """),
            {"org_id": pending.org_id, "name": pending.name},
        ).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail="a project with this name already exists in the organization")

        created_project_id = uuid.uuid4()
        orm.execute(
            text("""
                INSERT INTO public.projects (
                    id, org_id, api_key, name, environment, department_id, completed_at
                )
                VALUES (
                    :id, :org_id, :api_key, :name, CAST(:environment AS environment),
                    :department_id, CAST(:completed_at AS date)
                )
                RETURNING created_at::text AS created_at, completed_at::text AS completed_at
            """),
            {
                "id": str(created_project_id),
                "org_id": pending.org_id,
                "api_key": str(uuid.uuid4()),
                "name": pending.name,
                "environment": pending.environment,
                "department_id": pending.department_id,
                "completed_at": pending.completed_at,
            },
        ).first()
        orm.execute(
            text("""
                INSERT INTO public.project_members (project_id, user_id, role)
                VALUES (:project_id, :user_id, 'owner')
                ON CONFLICT (project_id, user_id)
                DO UPDATE SET role = 'owner'
            """),
            {"project_id": str(created_project_id), "user_id": pending.requester_id},
        )

    orm.execute(
        text("""
            UPDATE public.project_creation_requests
            SET status = :status,
                review_comment = NULLIF(btrim(:review_comment), ''),
                reviewed_by_user_id = :reviewer_id,
                created_project_id = CAST(:created_project_id AS uuid),
                reviewed_at = now(),
                updated_at = now()
            WHERE id = :request_id
        """),
        {
            "status": status,
            "review_comment": body.comment,
            "reviewer_id": str(reviewer_id),
            "created_project_id": str(created_project_id) if created_project_id else None,
            "request_id": str(request_id),
        },
    )
    orm.commit()
    reviewed = _get_project_request(orm, request_id=request_id)
    record_audit(
        orm,
        user_id=reviewer_id,
        action="review_project_creation",
        resource_type="project_creation_request",
        resource_id=str(request_id),
        metadata={
            "decision": body.decision,
            "requester_id": pending.requester_id,
            "project_name": pending.name,
            "created_project_id": str(created_project_id) if created_project_id else None,
            "result_status": status,
        },
        request=request,
    )
    return _project_request_from_row(reviewed)


@router.get("/projects", response_model=List[ProjectSchema])
def list_projects(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> List[ProjectSchema]:
    """List projects the caller can access through project membership."""
    try:
        user_id = current_user_id(request)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    rows = orm.execute(
        text("""
            SELECT p.id::text AS id, p.org_id::text AS org_id, p.name,
                   p.environment::text, COALESCE(p.department_id, 'research') AS department_id,
                   p.created_at::text AS created_at, p.completed_at::text AS completed_at,
                   pm.role::text AS role
            FROM public.projects p
            JOIN public.project_members pm ON pm.project_id = p.id
            WHERE pm.user_id = :u
            ORDER BY
                CASE WHEN p.completed_at IS NULL THEN 0 ELSE 1 END,
                p.name,
                p.id
        """),
        {"u": str(user_id)},
    ).all()
    return [_project_from_row(r) for r in rows]


@router.get("/projects/catalog", response_model=List[ProjectSchema])
def list_project_catalog(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> List[ProjectSchema]:
    """List every project for authenticated read-only catalogue pages."""
    try:
        user_id = current_user_id(request)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    rows = orm.execute(
        text("""
            SELECT p.id::text AS id, p.org_id::text AS org_id, p.name,
                   p.environment::text, COALESCE(p.department_id, 'research') AS department_id,
                   p.created_at::text AS created_at, p.completed_at::text AS completed_at,
                   CASE
                       WHEN COALESCE(admin_user.is_system_admin, false) THEN 'owner'
                       ELSE pm.role::text
                   END AS role
            FROM public.projects p
            LEFT JOIN public.users admin_user
              ON admin_user.id = :u
            LEFT JOIN public.project_members pm
              ON pm.project_id = p.id
             AND pm.user_id = :u
            WHERE EXISTS (
                SELECT 1
                FROM public.project_members catalog_member
                WHERE catalog_member.project_id = p.id
            )
            ORDER BY
                CASE WHEN p.completed_at IS NULL THEN 0 ELSE 1 END,
                p.name,
                p.id
        """),
        {"u": str(user_id)},
    ).all()
    return [_project_from_row(r) for r in rows]


@router.post(
    "/projects/{project_id}/department-migrations",
    response_model=ProjectDepartmentMigrationSchema,
    status_code=202,
)
def start_project_department_migration(
    request: Request,
    project_id: uuid.UUID,
    body: CreateProjectDepartmentMigrationRequest,
    orm: Session = Depends(get_orm_session),
) -> ProjectDepartmentMigrationSchema:
    try:
        caller_id = current_user_id(request)
        require_admin(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if not body.migrate_knowledge_base:
        raise HTTPException(
            status_code=400,
            detail="knowledge base migration confirmation is required",
        )
    _require_project_department(
        orm,
        department_id=body.target_department_id,
        missing_status_code=404,
    )

    if body.idempotency_key:
        existing = orm.execute(
            text(_department_migration_select_sql(
                where_sql=(
                    "project_id = :project_id AND requested_by_user_id = :caller_id "
                    "AND idempotency_key = :idempotency_key"
                )
            )),
            {
                "project_id": str(project_id),
                "caller_id": str(caller_id),
                "idempotency_key": body.idempotency_key,
            },
        ).first()
        if existing is not None:
            return _department_migration_from_row(existing)

    project = orm.execute(
        text("""
            SELECT id::text AS id, org_id::text AS org_id, name, environment::text,
                   department_id, created_at::text AS created_at,
                   completed_at::text AS completed_at
            FROM public.projects
            WHERE id = :project_id
            FOR UPDATE
        """),
        {"project_id": str(project_id)},
    ).first()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    source_department_id = str(project.department_id)
    if source_department_id != body.expected_source_department_id:
        raise HTTPException(
            status_code=409,
            detail="project category changed; refresh before starting migration",
        )
    if source_department_id == body.target_department_id:
        raise HTTPException(status_code=409, detail="project already belongs to target category")

    active = orm.execute(
        text(_department_migration_select_sql(
            where_sql="project_id = :project_id AND status IN ('queued', 'running')"
        )),
        {"project_id": str(project_id)},
    ).first()
    if active is not None:
        raise HTTPException(status_code=409, detail="project already has an active category migration")

    raw_material_count, wiki_page_count, meeting_record_count = _count_project_assets(
        orm,
        project_id=project_id,
    )
    migration_id = uuid.uuid4()
    orm.execute(
        text("""
            INSERT INTO public.project_department_migrations (
                id, project_id, source_department_id, target_department_id,
                requested_by_user_id, idempotency_key, status, current_step,
                progress, raw_material_count, wiki_page_count, meeting_record_count
            )
            VALUES (
                :migration_id, :project_id, :source_department_id, :target_department_id,
                :caller_id, :idempotency_key, 'queued', 'queued', 0,
                :raw_material_count, :wiki_page_count, :meeting_record_count
            )
        """),
        {
            "migration_id": str(migration_id),
            "project_id": str(project_id),
            "source_department_id": source_department_id,
            "target_department_id": body.target_department_id,
            "caller_id": str(caller_id),
            "idempotency_key": body.idempotency_key,
            "raw_material_count": raw_material_count,
            "wiki_page_count": wiki_page_count,
            "meeting_record_count": meeting_record_count,
        },
    )
    orm.commit()
    job = _get_department_migration(orm, migration_id=migration_id, project_id=project_id)
    _dispatch_department_migration(migration_id)
    record_audit(
        orm,
        user_id=caller_id,
        action="project_department_migration",
        resource_type="project_department_migration",
        resource_id=str(migration_id),
        metadata={
            "project_id": str(project_id),
            "source_department_id": source_department_id,
            "target_department_id": body.target_department_id,
            "raw_material_count": raw_material_count,
            "wiki_page_count": wiki_page_count,
            "meeting_record_count": meeting_record_count,
        },
        request=request,
    )
    return _department_migration_from_row(job)


@router.get(
    "/projects/{project_id}/department-migrations/{migration_id}",
    response_model=ProjectDepartmentMigrationSchema,
)
def get_project_department_migration(
    request: Request,
    project_id: uuid.UUID,
    migration_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> ProjectDepartmentMigrationSchema:
    try:
        caller_id = current_user_id(request)
        require_admin(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return _department_migration_from_row(
        _get_department_migration(
            orm,
            migration_id=migration_id,
            project_id=project_id,
        )
    )


@router.patch("/projects/{project_id}", response_model=ProjectSchema)
def update_project(
    request: Request,
    project_id: uuid.UUID,
    body: UpdateProjectRequest,
    orm: Session = Depends(get_orm_session),
) -> ProjectSchema:
    """Update project lifecycle fields. Caller must be admin+ on the project."""
    try:
        caller_id = current_user_id(request)
        require_admin(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    fields = body.model_fields_set
    if not fields:
        raise HTTPException(status_code=400, detail="no project fields to update")

    updates = []
    params = {"p": str(project_id)}
    if "name" in fields:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="project name is required")
        updates.append("name = :name")
        params["name"] = name
    if "completed_at" in fields:
        updates.append("completed_at = CAST(:completed_at AS date)")
        params["completed_at"] = body.completed_at
    if "department_id" in fields:
        department_id = body.department_id or ""
        if not department_id:
            raise HTTPException(status_code=400, detail="department_id is required")
        _require_project_department(
            orm,
            department_id=department_id,
            missing_status_code=404,
        )
        updates.append("department_id = :department_id")
        params["department_id"] = department_id

    row = orm.execute(
        text(f"""
            UPDATE public.projects
            SET {", ".join(updates)}
            WHERE id = :p
            RETURNING id::text AS id, org_id::text AS org_id, name, environment::text,
                      COALESCE(department_id, 'research') AS department_id,
                      created_at::text AS created_at, completed_at::text AS completed_at
        """),
        params,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    if "department_id" in fields:
        _synchronize_project_department_metadata(
            orm,
            project_id=project_id,
            target_department_id=str(row.department_id),
        )
    orm.commit()
    _record_project_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="update_project",
        project_id=project_id,
        project_name=row.name,
        metadata={"updated_fields": sorted(fields)},
    )
    return _project_from_row(row)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    request: Request,
    project_id: uuid.UUID,
    confirm_name: str = Query(..., min_length=1, max_length=200),
    orm: Session = Depends(get_orm_session),
):
    """Delete a project and its dependent project data. Caller must be admin+."""
    try:
        caller_id = current_user_id(request)
        require_admin(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    project = _get_project(orm, project_id=project_id)
    if confirm_name.strip() != project.name:
        raise HTTPException(status_code=409, detail="project name confirmation does not match")
    orm.execute(
        text("DELETE FROM public.projects WHERE id = :p"),
        {"p": str(project_id)},
    )
    orm.commit()
    _record_project_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="delete_project",
        project_id=project_id,
        project_name=project.name,
    )
    return None


@router.get("/projects/{project_id}/member-options", response_model=List[MemberOptionSchema])
def list_member_options(
    request: Request,
    project_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> List[MemberOptionSchema]:
    """List active team members who are not yet assigned to the project."""
    try:
        caller_id = current_user_id(request)
        require_admin(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    rows = orm.execute(
        text("""
            SELECT au.id::text AS user_id,
                   au.email,
                   split_part(au.email, '@', 1) AS username,
                   pu.nickname,
                   COALESCE(
                       NULLIF(BTRIM(pu.nickname), ''),
                       NULLIF(BTRIM(pu.full_name), ''),
                       split_part(au.email, '@', 1)
                   ) AS display_name
            FROM auth.users au
            JOIN public.users pu ON pu.id = au.id
            WHERE COALESCE(pu.is_active, true)
              AND lower(au.email) NOT LIKE '%@agentops.local'
              AND NOT EXISTS (
                  SELECT 1
                  FROM public.project_members existing
                  WHERE existing.project_id = :project_id
                    AND existing.user_id = au.id
              )
            ORDER BY display_name, au.email
        """),
        {"project_id": str(project_id)},
    ).all()
    return [
        MemberOptionSchema(
            user_id=uuid.UUID(row.user_id),
            email=row.email,
            username=row.username,
            nickname=row.nickname,
            display_name=row.display_name,
        )
        for row in rows
    ]


@router.post("/projects/{project_id}/members", response_model=MemberSchema, status_code=201)
def add_member(
    request: Request,
    project_id: uuid.UUID,
    body: AddMemberRequest,
    orm: Session = Depends(get_orm_session),
) -> MemberSchema:
    """Add or update a project member. Caller must be admin+ on the project."""
    try:
        user_id = current_user_id(request)
        require_admin(orm, user_id=user_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    target = _resolve_target_user(orm, body)
    target_user_id = uuid.UUID(str(target.id))

    orm.execute(
        text("""
            INSERT INTO public.project_members (project_id, user_id, role)
            VALUES (:p, :u, CAST(:r AS org_roles))
            ON CONFLICT (project_id, user_id)
            DO UPDATE SET role = EXCLUDED.role
        """),
        {"p": str(project_id), "u": str(target_user_id), "r": body.role},
    )
    orm.commit()

    _record_member_audit(
        orm,
        request=request,
        caller_id=user_id,
        action="add_member",
        project_id=project_id,
        target_user_id=target_user_id,
        target_email=target.email,
        role=body.role,
    )

    return MemberSchema(
        user_id=target_user_id,
        email=target.email,
        username=_display_name_from_email(target.email),
        nickname=None,
        display_name=_display_name_from_email(target.email),
        role=body.role,
    )


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
def remove_member(
    request: Request,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
):
    """Remove a member from a project. Caller must be admin+ on the project."""
    try:
        caller_id = current_user_id(request)
        require_admin(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    if caller_id == user_id:
        raise HTTPException(status_code=400, detail="cannot remove yourself from the project")

    target = _get_project_member(orm, project_id=project_id, user_id=user_id)
    orm.execute(
        text("DELETE FROM public.project_members WHERE project_id=:p AND user_id=:u"),
        {"p": str(project_id), "u": str(user_id)},
    )
    orm.commit()
    _record_member_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="remove_member",
        project_id=project_id,
        target_user_id=user_id,
        target_email=target.email,
        role=target.role,
    )
    return None


@router.post("/projects/{project_id}/members/{user_id}/password", response_model=ResetMemberPasswordResponse)
def reset_member_password(
    request: Request,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: ResetMemberPasswordRequest,
    orm: Session = Depends(get_orm_session),
) -> ResetMemberPasswordResponse:
    """Reset a project member's login password. Caller must be admin+ on the project."""
    try:
        caller_id = current_user_id(request)
        require_admin(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    target = _get_project_member(orm, project_id=project_id, user_id=user_id)
    orm.execute(
        text("""
            UPDATE auth.users
            SET encrypted_password = crypt(:password, gen_salt('bf')),
                recovery_token = '',
                recovery_sent_at = NULL,
                reauthentication_token = '',
                reauthentication_sent_at = NULL,
                updated_at = now()
            WHERE id = :u
        """),
        {"u": str(user_id), "password": body.password},
    )
    orm.execute(
        text("DELETE FROM auth.sessions WHERE user_id = :u"),
        {"u": str(user_id)},
    )
    orm.commit()
    _record_member_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="reset_member_password",
        project_id=project_id,
        target_user_id=user_id,
        target_email=target.email,
        role=target.role,
    )
    return ResetMemberPasswordResponse(user_id=user_id, email=target.email)


@router.patch("/projects/{project_id}/members/{user_id}/username", response_model=MemberSchema)
def rename_member_username(
    request: Request,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RenameMemberUsernameRequest,
    orm: Session = Depends(get_orm_session),
) -> MemberSchema:
    """Rename a local member login while preserving the user's stable identity."""
    try:
        caller_id = current_user_id(request)
        require_admin(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    target = _get_project_member(orm, project_id=project_id, user_id=user_id)
    old_email = str(target.email).strip().lower()
    if not old_email.endswith("@local.dev"):
        raise HTTPException(status_code=400, detail="only @local.dev usernames can be renamed")

    new_username = body.username.strip().lower()
    new_email = f"{new_username}@local.dev"
    conflict = orm.execute(
        text("SELECT id FROM auth.users WHERE lower(email)=lower(:email) AND id<>:u"),
        {"email": new_email, "u": str(user_id)},
    ).first()
    if conflict is not None:
        raise HTTPException(status_code=409, detail="username already exists")

    orm.execute(
        text("""
            UPDATE auth.users
            SET email = :email,
                email_change = '',
                email_change_token_new = '',
                email_change_token_current = '',
                updated_at = now()
            WHERE id = :u
        """),
        {"email": new_email, "u": str(user_id)},
    )
    orm.execute(
        text("UPDATE public.users SET email=:email WHERE id=:u"),
        {"email": new_email, "u": str(user_id)},
    )
    orm.execute(
        text("UPDATE public.user_orgs SET user_email=:email WHERE user_id=:u"),
        {"email": new_email, "u": str(user_id)},
    )
    orm.execute(
        text("""
            UPDATE auth.identities
            SET identity_data = jsonb_set(
                    COALESCE(identity_data, '{}'::jsonb),
                    '{email}',
                    to_jsonb(CAST(:email AS text)),
                    true
                ),
                updated_at = now()
            WHERE user_id = :u
              AND provider = 'email'
        """),
        {"email": new_email, "u": str(user_id)},
    )
    orm.execute(
        text("DELETE FROM auth.sessions WHERE user_id = :u"),
        {"u": str(user_id)},
    )
    orm.commit()
    _record_member_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="rename_member_username",
        project_id=project_id,
        target_user_id=user_id,
        target_email=new_email,
        role=target.role,
        extra_metadata={
            "old_username": old_email.split("@", 1)[0],
            "new_username": new_username,
        },
    )
    return MemberSchema(
        user_id=user_id,
        email=new_email,
        username=new_username,
        nickname=getattr(target, "nickname", None),
        display_name=getattr(target, "nickname", None) or new_username,
        role=target.role,
    )


@router.get("/projects/{project_id}/members", response_model=List[MemberSchema])
def list_members(
    request: Request,
    project_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> List[MemberSchema]:
    """List members for project members or a SmartBrain system administrator."""
    try:
        caller_id = current_user_id(request)
        require_member(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    rows = orm.execute(
        text("""
            SELECT pm.user_id::text AS user_id,
                   au.email,
                   split_part(au.email, '@', 1) AS username,
                   pu.nickname,
                   COALESCE(NULLIF(BTRIM(pu.nickname), ''), au.email) AS display_name,
                   pm.role::text
            FROM public.project_members pm
            JOIN auth.users au ON au.id = pm.user_id
            LEFT JOIN public.users pu ON pu.id = pm.user_id
            WHERE pm.project_id = :p
            ORDER BY pm.role DESC, display_name, au.email
        """),
        {"p": str(project_id)},
    ).all()
    return [
        MemberSchema(
            user_id=uuid.UUID(r.user_id),
            email=r.email,
            username=r.username,
            nickname=r.nickname,
            display_name=r.display_name,
            role=r.role,
        )
        for r in rows
    ]


class DocumentRowSchema(BaseModel):
    id: uuid.UUID
    filename: str
    display_name: str
    format: str
    size_bytes: int
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    created_at: str


@router.get("/projects/{project_id}/documents", response_model=List[DocumentRowSchema])
def list_project_documents(
    request: Request,
    project_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> List[DocumentRowSchema]:
    """List documents in a project. Caller must be a member."""
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    rows = orm.execute(
        text("""
            SELECT id::text, filename, display_name, format, size_bytes,
                   status, error_message, chunk_count, created_at::text
            FROM public.documents
            WHERE project_id = :p
            ORDER BY created_at DESC
        """),
        {"p": str(project_id)},
    ).all()
    return [
        DocumentRowSchema(
            id=uuid.UUID(r.id),
            filename=r.filename,
            display_name=r.display_name,
            format=r.format,
            size_bytes=r.size_bytes,
            status=r.status,
            chunk_count=r.chunk_count,
            error_message=r.error_message,
            created_at=r.created_at,
        )
        for r in rows
    ]
