"""Authenticated profile endpoints for the current SmartBrain user."""
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


router = APIRouter(route_class=AuthenticatedRoute)


class OrgMembership(BaseModel):
    org_id: uuid.UUID
    org_name: str
    role: str


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    nickname: Optional[str] = None
    display_name: str
    ai_detail_visible_to_admin: bool = False
    avatar_url: Optional[str] = None
    memberships: List[OrgMembership] = Field(default_factory=list)


class UpdateProfileRequest(BaseModel):
    nickname: Optional[str] = Field(None, max_length=80)
    ai_detail_visible_to_admin: Optional[bool] = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=6, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


class PasswordChangeResponse(BaseModel):
    status: str = "updated"


def _session_user_id(request: Request) -> uuid.UUID:
    session = getattr(request.state, "session", None)
    if session is None or not getattr(session, "user_id", None):
        raise HTTPException(status_code=401, detail="not authenticated")
    return uuid.UUID(str(session.user_id))


def _profile_row(orm: Session, *, user_id: uuid.UUID):
    row = orm.execute(
        text("""
            SELECT
                au.id::text AS user_id,
                au.email AS email,
                pu.full_name AS full_name,
                pu.nickname AS nickname,
                COALESCE(NULLIF(BTRIM(pu.nickname), ''), au.email) AS display_name,
                COALESCE(pu.ai_detail_visible_to_admin, false) AS ai_detail_visible_to_admin,
                pu.avatar_url AS avatar_url
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE au.id = :uid
        """),
        {"uid": str(user_id)},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="user not found")
    return row


def _me_response(orm: Session, *, user_id: uuid.UUID) -> MeResponse:
    row = _profile_row(orm, user_id=user_id)
    memberships: List[OrgMembership] = []
    mem_rows = orm.execute(
        text("""
            SELECT uo.org_id::text AS org_id, o.name AS org_name, uo.role::text AS role
            FROM public.user_orgs uo
            JOIN public.orgs o ON o.id = uo.org_id
            WHERE uo.user_id = :uid
            ORDER BY o.name
        """),
        {"uid": str(user_id)},
    ).all()
    for item in mem_rows:
        memberships.append(
            OrgMembership(
                org_id=uuid.UUID(item.org_id),
                org_name=item.org_name,
                role=item.role,
            )
        )
    return MeResponse(
        user_id=uuid.UUID(row.user_id),
        email=row.email,
        full_name=row.full_name,
        nickname=row.nickname,
        display_name=row.display_name,
        ai_detail_visible_to_admin=bool(getattr(row, "ai_detail_visible_to_admin", False)),
        avatar_url=row.avatar_url,
        memberships=memberships,
    )


@router.get("/auth/me", response_model=MeResponse)
def auth_me(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> MeResponse:
    return _me_response(orm, user_id=_session_user_id(request))


@router.patch("/auth/me/profile", response_model=MeResponse)
def update_profile(
    request: Request,
    body: UpdateProfileRequest,
    orm: Session = Depends(get_orm_session),
) -> MeResponse:
    user_id = _session_user_id(request)
    nickname = " ".join((body.nickname or "").split())[:80] or None
    orm.execute(
        text("""
            INSERT INTO public.users (id, nickname, ai_detail_visible_to_admin)
            VALUES (:uid, :nickname, COALESCE(:ai_detail_visible_to_admin, false))
            ON CONFLICT (id)
            DO UPDATE SET
                nickname = EXCLUDED.nickname,
                ai_detail_visible_to_admin = COALESCE(
                    :ai_detail_visible_to_admin,
                    public.users.ai_detail_visible_to_admin
                )
        """),
        {
            "uid": str(user_id),
            "nickname": nickname,
            "ai_detail_visible_to_admin": body.ai_detail_visible_to_admin,
        },
    )
    orm.execute(
        text("""
            UPDATE auth.users
            SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
                || jsonb_build_object('nickname', CAST(:nickname AS text)),
                updated_at = now()
            WHERE id = :uid
        """),
        {"uid": str(user_id), "nickname": nickname},
    )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="update_profile",
        resource_type="user_profile",
        resource_id=str(user_id),
        metadata={
            "nickname_set": nickname is not None,
            "ai_detail_visible_to_admin": body.ai_detail_visible_to_admin,
        },
        request=request,
    )
    return _me_response(orm, user_id=user_id)


@router.post("/auth/me/password", response_model=PasswordChangeResponse)
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    orm: Session = Depends(get_orm_session),
) -> PasswordChangeResponse:
    user_id = _session_user_id(request)
    verified = orm.execute(
        text("""
            SELECT 1 AS ok
            FROM auth.users
            WHERE id = :uid
              AND encrypted_password = crypt(
                    CAST(:current_password AS text), encrypted_password
                  )
        """),
        {"uid": str(user_id), "current_password": body.current_password},
    ).first()
    if verified is None:
        raise HTTPException(status_code=400, detail="current password is incorrect")

    orm.execute(
        text("""
            UPDATE auth.users
            SET encrypted_password = crypt(
                    CAST(:new_password AS text), gen_salt('bf')
                ),
                updated_at = now()
            WHERE id = :uid
        """),
        {"uid": str(user_id), "new_password": body.new_password},
    )
    orm.commit()
    record_audit(
        orm,
        user_id=user_id,
        action="change_password",
        resource_type="user_profile",
        resource_id=str(user_id),
        metadata={"result": "updated"},
        request=request,
    )
    return PasswordChangeResponse()
