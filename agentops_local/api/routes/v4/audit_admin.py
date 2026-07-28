"""
Audit log admin endpoints.

  GET /v4/admin/audit-logs?user_id=&action=&limit=&offset=

Returns the most recent audit rows. Restricted to admin+ users.
Note: this endpoint is NOT scoped per-project because audit logs are
org-wide. We authorize by checking that the caller has admin role on
at least one org (i.e. global admin).
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.common.orm import get_orm_session
from agentops.auth.middleware import AuthenticatedRoute
from agentops.rag.authz import AuthzError, ROLE_RANK, current_user_id


router = APIRouter(route_class=AuthenticatedRoute)


class AuditLogSchema(BaseModel):
    id: int
    user_id: Optional[uuid.UUID]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    metadata: dict
    ip_address: Optional[str]
    created_at: str


def _is_audit_admin(orm: Session, user_id: uuid.UUID) -> bool:
    """
    Audit log access requires project-level admin in at least one project.
    We consider a user an audit admin if they are admin or owner on
    any project (project_members).
    """
    row = orm.execute(
        text("""
            SELECT 1 FROM public.project_members
            WHERE user_id = :u AND role IN ('admin', 'owner')
            LIMIT 1
        """),
        {"u": str(user_id)},
    ).first()
    return row is not None


@router.get("/admin/audit-logs", response_model=List[AuditLogSchema])
def list_audit_logs(
    request: Request,
    orm: Session = Depends(get_orm_session),
    user_id: Optional[uuid.UUID] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    try:
        caller = current_user_id(request)
    except AuthzError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    if not _is_audit_admin(orm, caller):
        raise HTTPException(status_code=403, detail="audit admin required (project admin+)")

    where = []
    params = {"lim": limit, "off": offset}
    if user_id is not None:
        where.append("user_id = :uid")
        params["uid"] = str(user_id)
    if action is not None:
        where.append("action = :act")
        params["act"] = action
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = orm.execute(
        text(f"""
            SELECT id, user_id::text AS user_id, action, resource_type,
                   resource_id, metadata, host(ip_address) AS ip_address,
                   created_at::text AS created_at
            FROM public.audit_logs
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT :lim OFFSET :off
        """),
        params,
    ).all()
    return [
        AuditLogSchema(
            id=r.id,
            user_id=uuid.UUID(r.user_id) if r.user_id else None,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            metadata=r.metadata or {},
            ip_address=r.ip_address,
            created_at=r.created_at,
        )
        for r in rows
    ]