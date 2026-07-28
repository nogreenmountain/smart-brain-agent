"""
Auth endpoints: /auth/me

Returns the currently authenticated user's id, email, and org memberships
with their roles. Sourced from request.state.session which is set by
AuthenticatedRoute's custom_route_handler. If the route is not auth-guarded,
the session will be missing and we 401 explicitly.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from agentops.common.orm import get_orm_session
from agentops.auth.middleware import AuthenticatedRoute


router = APIRouter(route_class=AuthenticatedRoute)


class OrgMembership(BaseModel):
    org_id: uuid.UUID
    org_name: str
    role: str  # owner | admin | developer | business_user


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    memberships: List[OrgMembership] = []


@router.get("/auth/me", response_model=MeResponse)
def auth_me(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> MeResponse:
    """Return the current authenticated user and their org memberships."""
    session = getattr(request.state, "session", None)
    if session is None or not getattr(session, "user_id", None):
        raise HTTPException(status_code=401, detail="not authenticated")

    user_id = session.user_id

    # Fetch user profile + auth record (raw SQL — public.users and auth.users
    # are not in the AgentOps BaseModel metadata).
    row = orm.execute(
        text("""
            SELECT
                au.id::text            AS user_id,
                au.email               AS email,
                pu.full_name           AS full_name,
                pu.avatar_url          AS avatar_url
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE au.id = :uid
        """),
        {"uid": str(user_id)},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="user not found")

    # Org memberships
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
    for r in mem_rows:
        memberships.append(OrgMembership(
            org_id=uuid.UUID(r.org_id),
            org_name=r.org_name,
            role=r.role,
        ))

    return MeResponse(
        user_id=uuid.UUID(row.user_id),
        email=row.email,
        full_name=row.full_name,
        avatar_url=row.avatar_url,
        memberships=memberships,
    )
