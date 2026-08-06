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

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.common.orm import get_orm_session
from agentops.auth.middleware import AuthenticatedRoute
from agentops.rag.audit import record_audit
from agentops.rag.authz import (
    AuthzError,
    ROLE_RANK,
    current_user_id,
    require_admin,
    require_member,
)


router = APIRouter(route_class=AuthenticatedRoute)
DEFAULT_NEW_MEMBER_PASSWORD = "123456"


class CreateProjectRequest(BaseModel):
    org_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    environment: str = Field("development", pattern="^(development|staging|production)$")
    department_id: str = Field("research", pattern="^(research|marketing|business)$")
    completed_at: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    completed_at: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ProjectSchema(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    environment: str
    department_id: str = "research"
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
    nickname: Optional[str] = None
    display_name: str
    role: str


class ResetMemberPasswordRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class ResetMemberPasswordResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    status: str = "updated"


def _user_org_role(orm: Session, *, user_id: uuid.UUID, org_id: uuid.UUID) -> Optional[str]:
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


def _create_local_login_user(orm: Session, *, email: str):
    user_id = uuid.uuid4()
    full_name = _display_name_from_email(email)
    created = orm.execute(
        text("""
            INSERT INTO auth.users (
                instance_id, id, aud, role, email, encrypted_password,
                email_confirmed_at, confirmation_token, recovery_token,
                email_change_token_new, email_change, email_change_token_current,
                email_change_confirm_status, reauthentication_token,
                raw_app_meta_data, raw_user_meta_data, is_super_admin,
                created_at, updated_at, is_sso_user, is_anonymous
            )
            VALUES (
                '00000000-0000-0000-0000-000000000000',
                CAST(:user_id AS uuid),
                'authenticated',
                'authenticated',
                CAST(:email AS text),
                crypt(CAST(:password AS text), gen_salt('bf')),
                now(),
                '',
                '',
                '',
                '',
                '',
                0,
                '',
                '{"provider":"email","providers":["email"]}'::jsonb,
                jsonb_build_object('full_name', CAST(:full_name AS text)),
                NULL,
                now(),
                now(),
                FALSE,
                FALSE
            )
            RETURNING id::text AS id, email
        """),
        {
            "user_id": str(user_id),
            "email": email,
            "password": DEFAULT_NEW_MEMBER_PASSWORD,
            "full_name": full_name,
        },
    ).first()
    if created is None:
        raise HTTPException(status_code=503, detail="failed to create user")
    orm.execute(
        text("""
            INSERT INTO auth.identities (
                provider_id, user_id, identity_data, provider,
                last_sign_in_at, created_at, updated_at
            )
            VALUES (
                CAST(:user_id AS text),
                CAST(:user_id AS uuid),
                jsonb_build_object(
                    'sub', CAST(:user_id AS text),
                    'email', CAST(:email AS text),
                    'email_verified', true,
                    'phone_verified', false
                ),
                'email',
                now(),
                now(),
                now()
            )
            ON CONFLICT (provider_id, provider) DO NOTHING
        """),
        {"user_id": str(user_id), "email": email},
    )
    orm.execute(
        text("""
            INSERT INTO public.users (id, email, full_name)
            VALUES (:user_id, :email, :full_name)
            ON CONFLICT (id)
            DO UPDATE SET email = EXCLUDED.email
        """),
        {"user_id": str(user_id), "email": email, "full_name": full_name},
    )
    return created


def _resolve_target_user(orm: Session, body: AddMemberRequest):
    if body.user_id is not None:
        target = orm.execute(
            text("SELECT id::text AS id, email FROM auth.users WHERE id=:u"),
            {"u": str(body.user_id)},
        ).first()
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
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
                    SELECT id::text AS id, email
                    FROM auth.users
                    WHERE lower(email) = lower(:email)
                       OR id = CAST(:user_id AS uuid)
                """),
                {"email": email, "user_id": user_id_param},
            ).first()
        else:
            target = orm.execute(
                text("""
                    SELECT id::text AS id, email
                    FROM auth.users
                    WHERE lower(email) = lower(:email)
                """),
                {"email": email},
            ).first()
        if target is None:
            if user_id_param:
                raise HTTPException(status_code=404, detail="user not found")
            target = _create_local_login_user(orm, email=email)
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
            SELECT pm.user_id::text AS user_id, au.email, pm.role::text
            FROM public.project_members pm
            JOIN auth.users au ON au.id = pm.user_id
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
    record_audit(
        orm,
        user_id=caller_id,
        action=action,
        resource_type="project",
        resource_id=str(project_id),
        metadata=metadata,
        request=request,
    )


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
            ORDER BY p.name, p.id
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
                   pm.role::text AS role
            FROM public.projects p
            LEFT JOIN public.project_members pm
              ON pm.project_id = p.id
             AND pm.user_id = :u
            ORDER BY p.name, p.id
        """),
        {"u": str(user_id)},
    ).all()
    return [_project_from_row(r) for r in rows]


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
    orm: Session = Depends(get_orm_session),
):
    """Delete a project and its dependent project data. Caller must be admin+."""
    try:
        caller_id = current_user_id(request)
        require_admin(orm, user_id=caller_id, project_id=project_id)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    project = _get_project(orm, project_id=project_id)
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
        nickname=None,
        display_name=target.email,
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


@router.get("/projects/{project_id}/members", response_model=List[MemberSchema])
def list_members(
    request: Request,
    project_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> List[MemberSchema]:
    """List members of a project for any authenticated user."""
    try:
        current_user_id(request)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    rows = orm.execute(
        text("""
            SELECT pm.user_id::text AS user_id,
                   au.email,
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
