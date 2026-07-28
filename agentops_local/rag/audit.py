"""
Audit logging for sensitive actions.

Design notes:
  - We log METADATA only, never the query text or document content.
  - We tolerate failures: audit logging never fails a user request.
  - We capture ip_address from request.client.host when available.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None or request.client is None:
        return None
    return request.client.host


def record_audit(
    orm: Session,
    *,
    user_id: Optional[uuid.UUID],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    """
    Insert one audit row. Never raises — failures are logged but do not
    propagate to the caller, so a broken audit table cannot break the API.
    """
    try:
        orm.execute(
            text("""
                INSERT INTO public.audit_logs
                    (user_id, action, resource_type, resource_id, metadata, ip_address)
                VALUES (:uid, :act, :rtype, :rid, CAST(:meta AS jsonb), :ip)
            """),
            {
                "uid": str(user_id) if user_id else None,
                "act": action,
                "rtype": resource_type,
                "rid": str(resource_id) if resource_id else None,
                "meta": _json_dumps(metadata or {}),
                "ip": _client_ip(request),
            },
        )
        orm.commit()
    except Exception as e:
        logger.warning("audit insert failed (action=%s): %s", action, e)
        try:
            orm.rollback()
        except Exception:
            pass


def _json_dumps(d: dict) -> str:
    import json
    return json.dumps(d, default=str, ensure_ascii=False)