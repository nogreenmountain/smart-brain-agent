"""SmartBrain-wide team member lifecycle management."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.rag.audit import record_audit
from agentops.rag.authz import AuthzError, current_user_id, is_system_admin


router = APIRouter(route_class=AuthenticatedRoute)


class TeamMemberSchema(BaseModel):
    user_id: uuid.UUID
    email: str
    username: str
    nickname: Optional[str] = None
    display_name: str
    is_active: bool
    is_system_admin: bool
    project_count: int = 0
    created_at: Optional[str] = None
    deactivated_at: Optional[str] = None


class CreateTeamMemberRequest(BaseModel):
    username: str = Field(..., pattern=r"^[a-z0-9][a-z0-9._-]{1,62}$")
    nickname: Optional[str] = Field(None, max_length=80)
    password: str = Field(..., min_length=6, max_length=128)


class RenameTeamMemberUsernameRequest(BaseModel):
    username: str = Field(..., pattern=r"^[a-z0-9][a-z0-9._-]{1,62}$")


class ResetTeamMemberPasswordRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class ResetTeamMemberPasswordResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    status: str = "updated"


def _require_system_admin(request: Request, orm: Session) -> uuid.UUID:
    try:
        caller_id = current_user_id(request)
    except AuthzError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    if not is_system_admin(orm, user_id=caller_id):
        raise HTTPException(status_code=403, detail="system administrator access required")
    return caller_id


def _team_member_from_row(row, **overrides) -> TeamMemberSchema:
    values = {
        "user_id": uuid.UUID(str(row.user_id)),
        "email": str(row.email),
        "username": str(row.username),
        "nickname": getattr(row, "nickname", None),
        "display_name": str(getattr(row, "display_name", None) or row.username),
        "is_active": bool(getattr(row, "is_active", True)),
        "is_system_admin": bool(getattr(row, "is_system_admin", False)),
        "project_count": int(getattr(row, "project_count", 0) or 0),
        "created_at": getattr(row, "created_at", None),
        "deactivated_at": getattr(row, "deactivated_at", None),
    }
    values.update(overrides)
    return TeamMemberSchema(**values)


def _get_team_member(orm: Session, *, user_id: uuid.UUID):
    row = orm.execute(
        text("""
            SELECT au.id::text AS user_id,
                   au.email,
                   split_part(au.email, '@', 1) AS username,
                   pu.nickname,
                   COALESCE(NULLIF(BTRIM(pu.nickname), ''), split_part(au.email, '@', 1)) AS display_name,
                   COALESCE(pu.is_active, true) AS is_active,
                   COALESCE(pu.is_system_admin, false) AS is_system_admin,
                   COUNT(pm.project_id)::int AS project_count,
                   au.created_at::text AS created_at,
                   pu.deactivated_at::text AS deactivated_at
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            LEFT JOIN public.project_members pm ON pm.user_id = au.id
            WHERE au.id = :user_id
            GROUP BY au.id, au.email, pu.nickname, pu.is_active,
                     pu.is_system_admin, pu.deactivated_at
        """),
        {"user_id": str(user_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="team member not found")
    return row


def _record_team_audit(
    orm: Session,
    *,
    request: Request,
    caller_id: uuid.UUID,
    action: str,
    target_user_id: uuid.UUID,
    target_email: str,
    metadata: Optional[dict] = None,
) -> None:
    details = {
        "target_user_id": str(target_user_id),
        "target_email": target_email,
        "result_status": "ok",
    }
    if metadata:
        details.update(metadata)
    record_audit(
        orm,
        user_id=caller_id,
        action=action,
        resource_type="team_member",
        resource_id=str(target_user_id),
        metadata=details,
        request=request,
    )


@router.get("/team-members", response_model=List[TeamMemberSchema])
def list_team_members(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> List[TeamMemberSchema]:
    _require_system_admin(request, orm)
    rows = orm.execute(
        text("""
            SELECT au.id::text AS user_id,
                   au.email,
                   split_part(au.email, '@', 1) AS username,
                   pu.nickname,
                   COALESCE(NULLIF(BTRIM(pu.nickname), ''), split_part(au.email, '@', 1)) AS display_name,
                   COALESCE(pu.is_active, true) AS is_active,
                   COALESCE(pu.is_system_admin, false) AS is_system_admin,
                   COUNT(pm.project_id)::int AS project_count,
                   au.created_at::text AS created_at,
                   pu.deactivated_at::text AS deactivated_at
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            LEFT JOIN public.project_members pm ON pm.user_id = au.id
            GROUP BY au.id, au.email, pu.nickname, pu.is_active,
                     pu.is_system_admin, pu.deactivated_at
            ORDER BY COALESCE(pu.is_active, true) DESC,
                     COALESCE(NULLIF(BTRIM(pu.nickname), ''), split_part(au.email, '@', 1)),
                     au.email
        """),
        {},
    ).all()
    return [_team_member_from_row(row) for row in rows]


@router.post("/team-members", response_model=TeamMemberSchema, status_code=201)
def create_team_member(
    request: Request,
    body: CreateTeamMemberRequest,
    orm: Session = Depends(get_orm_session),
) -> TeamMemberSchema:
    caller_id = _require_system_admin(request, orm)
    username = body.username.strip().lower()
    email = f"{username}@local.dev"
    nickname = (body.nickname or "").strip() or None
    conflict = orm.execute(
        text("""
            SELECT au.id, COALESCE(pu.is_active, true) AS is_active
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE lower(au.email) = lower(:email)
        """),
        {"email": email},
    ).first()
    if conflict is not None:
        detail = "username already exists"
        if not bool(getattr(conflict, "is_active", True)):
            detail = "username belongs to a disabled member; restore that member instead"
        raise HTTPException(status_code=409, detail=detail)

    user_id = uuid.uuid4()
    full_name = nickname or username
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
                '00000000-0000-0000-0000-000000000000', CAST(:user_id AS uuid),
                'authenticated', 'authenticated', CAST(:email AS text),
                crypt(CAST(:password AS text), gen_salt('bf')), now(), '', '', '', '', '',
                0, '', '{"provider":"email","providers":["email"]}'::jsonb,
                jsonb_build_object('full_name', CAST(:full_name AS text)), NULL,
                now(), now(), FALSE, FALSE
            )
            RETURNING id::text AS id, email, created_at::text AS created_at
        """),
        {
            "user_id": str(user_id),
            "email": email,
            "password": body.password,
            "full_name": full_name,
        },
    ).first()
    if created is None:
        raise HTTPException(status_code=503, detail="failed to create team member")
    orm.execute(
        text("""
            INSERT INTO auth.identities (
                provider_id, user_id, identity_data, provider,
                last_sign_in_at, created_at, updated_at
            )
            VALUES (
                CAST(:user_id AS text), CAST(:user_id AS uuid),
                jsonb_build_object(
                    'sub', CAST(:user_id AS text), 'email', CAST(:email AS text),
                    'email_verified', true, 'phone_verified', false
                ),
                'email', now(), now(), now()
            )
            ON CONFLICT (provider_id, provider) DO NOTHING
        """),
        {"user_id": str(user_id), "email": email},
    )
    orm.execute(
        text("""
            INSERT INTO public.users (id, email, full_name, nickname, is_active)
            VALUES (:user_id, :email, :full_name, :nickname, true)
            ON CONFLICT (id) DO UPDATE
            SET email = EXCLUDED.email,
                full_name = EXCLUDED.full_name,
                nickname = EXCLUDED.nickname,
                is_active = true,
                deactivated_at = NULL,
                deactivated_by_user_id = NULL
        """),
        {
            "user_id": str(user_id),
            "email": email,
            "full_name": full_name,
            "nickname": nickname,
        },
    )
    orm.commit()
    _record_team_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="create_team_member",
        target_user_id=user_id,
        target_email=email,
    )
    return TeamMemberSchema(
        user_id=user_id,
        email=email,
        username=username,
        nickname=nickname,
        display_name=nickname or username,
        is_active=True,
        is_system_admin=False,
        project_count=0,
        created_at=getattr(created, "created_at", None),
    )


@router.delete("/team-members/{user_id}", status_code=204)
def deactivate_team_member(
    request: Request,
    user_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
):
    caller_id = _require_system_admin(request, orm)
    if caller_id == user_id:
        raise HTTPException(status_code=400, detail="cannot deactivate your own account")
    target = _get_team_member(orm, user_id=user_id)
    if bool(target.is_system_admin):
        raise HTTPException(status_code=400, detail="system administrators cannot be deactivated here")
    if not bool(target.is_active):
        raise HTTPException(status_code=409, detail="team member is already disabled")

    orm.execute(
        text("DELETE FROM public.project_members WHERE user_id = :user_id"),
        {"user_id": str(user_id)},
    )
    orm.execute(
        text("""
            UPDATE public.users
            SET is_active = false,
                deactivated_at = now(),
                deactivated_by_user_id = :caller_id
            WHERE id = :user_id
        """),
        {"caller_id": str(caller_id), "user_id": str(user_id)},
    )
    orm.execute(
        text("""
            UPDATE auth.users
            SET banned_until = 'infinity'::timestamptz,
                updated_at = now()
            WHERE id = :user_id
        """),
        {"user_id": str(user_id)},
    )
    orm.execute(
        text("DELETE FROM auth.sessions WHERE user_id = :user_id"),
        {"user_id": str(user_id)},
    )
    orm.execute(
        text("DELETE FROM public.wiki_mcp_tokens WHERE user_id = :user_id"),
        {"user_id": str(user_id)},
    )
    orm.commit()
    _record_team_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="deactivate_team_member",
        target_user_id=user_id,
        target_email=target.email,
        metadata={"removed_project_count": int(target.project_count or 0)},
    )
    return None


@router.post("/team-members/{user_id}/reactivate", response_model=TeamMemberSchema)
def reactivate_team_member(
    request: Request,
    user_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> TeamMemberSchema:
    caller_id = _require_system_admin(request, orm)
    target = _get_team_member(orm, user_id=user_id)
    if bool(target.is_active):
        raise HTTPException(status_code=409, detail="team member is already active")
    orm.execute(
        text("""
            UPDATE public.users
            SET is_active = true,
                deactivated_at = NULL,
                deactivated_by_user_id = NULL
            WHERE id = :user_id
        """),
        {"user_id": str(user_id)},
    )
    orm.execute(
        text("""
            UPDATE auth.users
            SET banned_until = NULL,
                updated_at = now()
            WHERE id = :user_id
        """),
        {"user_id": str(user_id)},
    )
    orm.commit()
    _record_team_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="reactivate_team_member",
        target_user_id=user_id,
        target_email=target.email,
    )
    return _team_member_from_row(
        target,
        is_active=True,
        project_count=0,
        deactivated_at=None,
    )


@router.patch("/team-members/{user_id}/username", response_model=TeamMemberSchema)
def rename_team_member_username(
    request: Request,
    user_id: uuid.UUID,
    body: RenameTeamMemberUsernameRequest,
    orm: Session = Depends(get_orm_session),
) -> TeamMemberSchema:
    caller_id = _require_system_admin(request, orm)
    target = _get_team_member(orm, user_id=user_id)
    old_email = str(target.email).strip().lower()
    if not old_email.endswith("@local.dev"):
        raise HTTPException(status_code=400, detail="only @local.dev usernames can be renamed")
    username = body.username.strip().lower()
    email = f"{username}@local.dev"
    conflict = orm.execute(
        text("SELECT id FROM auth.users WHERE lower(email)=lower(:email) AND id<>:user_id"),
        {"email": email, "user_id": str(user_id)},
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
            WHERE id = :user_id
        """),
        {"email": email, "user_id": str(user_id)},
    )
    orm.execute(
        text("UPDATE public.users SET email = :email WHERE id = :user_id"),
        {"email": email, "user_id": str(user_id)},
    )
    orm.execute(
        text("UPDATE public.user_orgs SET user_email = :email WHERE user_id = :user_id"),
        {"email": email, "user_id": str(user_id)},
    )
    orm.execute(
        text("""
            UPDATE auth.identities
            SET identity_data = jsonb_set(
                    COALESCE(identity_data, '{}'::jsonb),
                    '{email}', to_jsonb(CAST(:email AS text)), true
                ),
                updated_at = now()
            WHERE user_id = :user_id AND provider = 'email'
        """),
        {"email": email, "user_id": str(user_id)},
    )
    orm.execute(
        text("DELETE FROM auth.sessions WHERE user_id = :user_id"),
        {"user_id": str(user_id)},
    )
    orm.commit()
    _record_team_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="rename_team_member_username",
        target_user_id=user_id,
        target_email=email,
        metadata={
            "old_username": old_email.split("@", 1)[0],
            "new_username": username,
        },
    )
    return _team_member_from_row(target, email=email, username=username)


@router.post("/team-members/{user_id}/password", response_model=ResetTeamMemberPasswordResponse)
def reset_team_member_password(
    request: Request,
    user_id: uuid.UUID,
    body: ResetTeamMemberPasswordRequest,
    orm: Session = Depends(get_orm_session),
) -> ResetTeamMemberPasswordResponse:
    caller_id = _require_system_admin(request, orm)
    target = _get_team_member(orm, user_id=user_id)
    orm.execute(
        text("""
            UPDATE auth.users
            SET encrypted_password = crypt(:password, gen_salt('bf')),
                recovery_token = '',
                recovery_sent_at = NULL,
                reauthentication_token = '',
                reauthentication_sent_at = NULL,
                updated_at = now()
            WHERE id = :user_id
        """),
        {"user_id": str(user_id), "password": body.password},
    )
    orm.execute(
        text("DELETE FROM auth.sessions WHERE user_id = :user_id"),
        {"user_id": str(user_id)},
    )
    orm.commit()
    _record_team_audit(
        orm,
        request=request,
        caller_id=caller_id,
        action="reset_team_member_password",
        target_user_id=user_id,
        target_email=target.email,
    )
    return ResetTeamMemberPasswordResponse(user_id=user_id, email=target.email)
