"""
Authorization checks for RAG endpoints.

The AgentOps permission model is:
  user --(role)--> org      via public.user_orgs
  project --belongs-to--> org  via projects.org_id
  user --(role)--> project via public.project_members  (NEW)

Roles (org_roles enum):
  owner > admin > developer > business_user

For each RAG action we map to a minimum required project role:
  - upload / delete document: developer+  (can write)
  - search / answer:          any member  (can read)
  - manage project / members: admin+      (admin in project)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


# Roles ordered by privilege (higher index = more privilege)
ROLE_RANK = {
    "business_user": 0,
    "developer": 1,
    "admin": 2,
    "owner": 3,
}


Role = Literal["owner", "admin", "developer", "business_user"]


class AuthzError(Exception):
    """Raised when a user fails an authorization check."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass
class ProjectRole:
    """The user's effective role on a project, if any."""

    project_id: uuid.UUID
    user_id: uuid.UUID
    role: Optional[Role]  # None if not a member


def is_system_admin(orm: Session, *, user_id: uuid.UUID) -> bool:
    """Return whether the user has SmartBrain-wide administrator access."""
    row = orm.execute(
        text("""
            SELECT COALESCE(is_system_admin, false) AS is_system_admin
            FROM public.users
            WHERE id = :uid
        """),
        {"uid": str(user_id)},
    ).first()
    return bool(row and row.is_system_admin)


def user_project_role(
    orm: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectRole:
    """Return the user's effective role on a project (None if not a member)."""
    if is_system_admin(orm, user_id=user_id):
        return ProjectRole(project_id=project_id, user_id=user_id, role="owner")
    row = orm.execute(
        text("""
            SELECT role::text AS role
            FROM public.project_members
            WHERE project_id = :pid AND user_id = :uid
        """),
        {"pid": str(project_id), "uid": str(user_id)},
    ).first()
    if row is None:
        return ProjectRole(project_id=project_id, user_id=user_id, role=None)
    return ProjectRole(project_id=project_id, user_id=user_id, role=row.role)


def require_member(
    orm: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectRole:
    """Caller must be a project member (any role)."""
    pr = user_project_role(orm, user_id=user_id, project_id=project_id)
    if pr.role is None:
        raise AuthzError(403, "not a member of this project")
    return pr


def require_writer(
    orm: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectRole:
    """Caller must be developer / admin / owner (can upload/delete)."""
    pr = user_project_role(orm, user_id=user_id, project_id=project_id)
    if pr.role is None:
        raise AuthzError(403, "not a member of this project")
    if ROLE_RANK.get(pr.role, -1) < ROLE_RANK["developer"]:
        raise AuthzError(403, f"role '{pr.role}' cannot write; need developer+")
    return pr


def require_admin(
    orm: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectRole:
    """Caller must be admin / owner (can manage project, add members)."""
    pr = user_project_role(orm, user_id=user_id, project_id=project_id)
    if pr.role is None:
        raise AuthzError(403, "not a member of this project")
    if ROLE_RANK.get(pr.role, -1) < ROLE_RANK["admin"]:
        raise AuthzError(403, f"role '{pr.role}' cannot manage; need admin+")
    return pr


def current_user_id(request) -> uuid.UUID:
    """
    Extract user_id from request.state.session (set by AuthenticatedRoute).
    Raises AuthzError(401) if no session.
    """
    session = getattr(request.state, "session", None)
    uid = getattr(session, "user_id", None)
    if uid is None:
        raise AuthzError(401, "not authenticated")
    return uid
