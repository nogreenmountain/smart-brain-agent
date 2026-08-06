from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Iterable

try:
    from sqlalchemy import text
except ModuleNotFoundError:
    def text(value: str) -> str:
        return value


SYSTEM_ACCOUNT_EMAILS = frozenset({"admin@agentops.local"})


class MemberWikiAccessError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class MemberIdentity:
    user_id: str
    employee_id: str
    name: str
    email: str


@dataclass(frozen=True)
class MemberAccessContext:
    is_admin: bool
    current: MemberIdentity
    accessible_members: tuple[MemberIdentity, ...]


def _identity(
    *,
    user_id: object,
    email: str,
    full_name: str | None,
    nickname: str | None = None,
) -> MemberIdentity:
    local_part = email.partition("@")[0].strip().lower()
    employee_id = local_part if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", local_part) else f"user-{user_id}"
    candidate = " ".join((nickname or full_name or local_part or employee_id).split())[:80]
    return MemberIdentity(
        user_id=str(user_id),
        employee_id=employee_id,
        name=candidate or employee_id,
        email=email,
    )


def _is_employee_email(email: str | None) -> bool:
    normalized = str(email or "").strip().lower()
    return bool(normalized) and normalized not in SYSTEM_ACCOUNT_EMAILS


def load_member_access_context(orm, *, user_id: uuid.UUID) -> MemberAccessContext:
    profile = orm.execute(
        text("""
            SELECT au.id::text AS user_id, au.email, pu.full_name, pu.nickname
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE au.id = :user_id
        """),
        {"user_id": str(user_id)},
    ).first()
    if profile is None or not profile.email:
        raise MemberWikiAccessError(404, "user profile not found")
    current = _identity(
        user_id=profile.user_id,
        email=str(profile.email),
        full_name=profile.full_name,
        nickname=getattr(profile, "nickname", None),
    )
    is_admin = orm.execute(
        text("""
            SELECT 1
            FROM public.user_orgs caller_org
            JOIN public.projects project
              ON project.org_id = caller_org.org_id
            JOIN public.project_members project_role
              ON project_role.project_id = project.id
             AND project_role.user_id = caller_org.user_id
            WHERE caller_org.user_id = :user_id
              AND caller_org.role::text IN ('owner', 'admin')
              AND project_role.role::text IN ('owner', 'admin')
            LIMIT 1
        """),
        {"user_id": str(user_id)},
    ).first() is not None

    if not is_admin:
        return MemberAccessContext(
            is_admin=False,
            current=current,
            accessible_members=(current,),
        )

    rows = orm.execute(
        text("""
            SELECT DISTINCT au.id::text AS user_id, au.email, pu.full_name, pu.nickname,
                   COALESCE(NULLIF(BTRIM(pu.nickname), ''), pu.full_name, au.email) AS sort_name
            FROM public.user_orgs caller_org
            JOIN public.projects project
              ON project.org_id = caller_org.org_id
            JOIN public.project_members caller
              ON caller.project_id = project.id
             AND caller.user_id = caller_org.user_id
            JOIN public.project_members target
              ON target.project_id = project.id
            JOIN auth.users au ON au.id = target.user_id
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE caller_org.user_id = :user_id
              AND caller_org.role::text IN ('owner', 'admin')
              AND caller.role::text IN ('owner', 'admin')
              AND au.email IS NOT NULL
            ORDER BY sort_name, au.email
        """),
        {"user_id": str(user_id)},
    ).all()
    members = tuple(
        _identity(
            user_id=row.user_id,
            email=str(row.email),
            full_name=row.full_name,
            nickname=getattr(row, "nickname", None),
        )
        for row in rows
        if _is_employee_email(row.email)
    )
    return MemberAccessContext(
        is_admin=True,
        current=current,
        accessible_members=members,
    )


def resolve_member_scope(
    *,
    is_admin: bool,
    current: MemberIdentity,
    accessible_members: Iterable[MemberIdentity],
    requested_member: str | None,
) -> MemberIdentity:
    requested = str(requested_member or "").strip().casefold()
    if not is_admin:
        own_values = {current.employee_id.casefold(), current.email.casefold(), current.name.casefold()}
        if requested and requested not in own_values:
            raise MemberWikiAccessError(403, "regular members can only read their own member Wiki")
        return current

    if not requested:
        raise MemberWikiAccessError(422, "member_id or member_name is required for administrator queries")
    for member in accessible_members:
        if requested in {
            member.employee_id.casefold(),
            member.name.casefold(),
            member.email.casefold(),
        }:
            return member
    raise MemberWikiAccessError(404, "member account not found in an organization you administer")
