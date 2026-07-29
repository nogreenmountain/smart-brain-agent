from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.rag.audit import record_audit
from agentops.rag.authz import AuthzError, current_user_id, require_member
from agentops.workday.domain import business_day_utc_bounds
from agentops.workday.identity import derive_employee_identity


router = APIRouter(route_class=AuthenticatedRoute)
logger = logging.getLogger(__name__)

AIChatSource = Literal[
    "cc_switch",
    "chatgpt_web",
    "chatgpt_desktop",
    "openai_compliance",
    "smartbrain",
]
AIChatStatus = Literal["ok", "error", "partial"]
AIChatRole = Literal["user", "assistant", "system", "tool"]


class AIChatMessageInput(BaseModel):
    role: AIChatRole
    content: str = Field(..., min_length=1, max_length=100_000)
    message_id: str | None = Field(None, max_length=200)
    created_at: datetime | None = None
    token_count: int | None = Field(None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIChatIngestRequest(BaseModel):
    project_id: uuid.UUID
    source: AIChatSource
    conversation_id: str | None = Field(None, max_length=300)
    title: str | None = Field(None, max_length=500)
    task_id: str | None = Field(None, max_length=200)
    task_title: str | None = Field(None, max_length=500)
    model: str | None = Field(None, max_length=200)
    status: AIChatStatus = "ok"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = Field(None, ge=0)
    prompt_tokens: int = Field(0, ge=0)
    completion_tokens: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)
    cost: float = Field(0, ge=0)
    error_count: int = Field(0, ge=0)
    trace_id: str | None = Field(None, max_length=200)
    messages: list[AIChatMessageInput] = Field(..., min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIChatIngestResponse(BaseModel):
    session_id: uuid.UUID
    project_id: uuid.UUID
    employee_id: str
    employee_name: str
    source: AIChatSource
    message_count: int
    status: AIChatStatus


class AIChatMessage(BaseModel):
    role: AIChatRole
    content: str
    message_id: str | None = None
    created_at: datetime | None = None
    token_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIChatSession(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    employee_id: str
    employee_name: str
    source: AIChatSource
    conversation_id: str | None
    title: str | None
    task_id: str
    task_title: str | None
    model: str | None
    status: AIChatStatus
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    error_count: int
    trace_id: str | None
    message_count: int
    messages: list[AIChatMessage] | None = None
    created_at: datetime
    updated_at: datetime


class AIChatSessionListResponse(BaseModel):
    project_id: uuid.UUID
    employee_id: str | None
    date: date | None
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    sessions: list[AIChatSession]


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value or {}, default=str, ensure_ascii=False)


def _profile_for_user(orm: Session, user_id: uuid.UUID):
    return orm.execute(
        text("""
            SELECT au.email, pu.full_name
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE au.id = :uid
        """),
        {"uid": str(user_id)},
    ).first()


def _record_ai_chat_audit(
    orm: Session,
    request: Request,
    *,
    user_id: uuid.UUID,
    action: str,
    project_id: uuid.UUID,
    source: str | None,
    result_status: str,
    employee_id: str | None = None,
    session_id: uuid.UUID | None = None,
) -> None:
    metadata: dict[str, Any] = {
        "source": source,
        "result_status": result_status,
    }
    if employee_id:
        metadata["employee_id"] = employee_id
    if session_id:
        metadata["session_id"] = str(session_id)
    record_audit(
        orm,
        user_id=user_id,
        action=action,
        resource_type="project",
        resource_id=str(project_id),
        metadata=metadata,
        request=request,
    )


def _resolve_employee(orm: Session, user_id: uuid.UUID) -> tuple[str, str]:
    profile = _profile_for_user(orm, user_id)
    if profile is None or not profile.email:
        raise HTTPException(status_code=404, detail="user profile not found")
    return derive_employee_identity(
        user_id=user_id,
        email=profile.email,
        full_name=profile.full_name,
    )


def _total_tokens(body: AIChatIngestRequest) -> int:
    if body.total_tokens:
        return body.total_tokens
    return body.prompt_tokens + body.completion_tokens


def _store_chat_session(
    orm: Session,
    *,
    user_id: uuid.UUID,
    employee_id: str,
    employee_name: str,
    body: AIChatIngestRequest,
) -> uuid.UUID:
    now = datetime.now(timezone.utc)
    started_at = body.started_at or now
    task_id = body.task_id or "unassigned"
    task_title = body.task_title or ("未标记任务" if task_id == "unassigned" else None)
    existing = None
    if body.conversation_id:
        existing = orm.execute(
            text("""
                SELECT id FROM public.ai_chat_sessions
                WHERE project_id = :project_id
                  AND source = :source
                  AND employee_id = :employee_id
                  AND external_conversation_id = :conversation_id
                LIMIT 1
            """),
            {
                "project_id": str(body.project_id),
                "source": body.source,
                "employee_id": employee_id,
                "conversation_id": body.conversation_id,
            },
        ).first()

    session_id = getattr(existing, "id", None) or uuid.uuid4()
    params = {
        "id": str(session_id),
        "project_id": str(body.project_id),
        "user_id": str(user_id),
        "employee_id": employee_id,
        "employee_name": employee_name,
        "source": body.source,
        "conversation_id": body.conversation_id,
        "title": body.title,
        "task_id": task_id,
        "task_title": task_title,
        "model": body.model,
        "status": body.status,
        "started_at": started_at,
        "ended_at": body.ended_at,
        "duration_ms": body.duration_ms,
        "prompt_tokens": body.prompt_tokens,
        "completion_tokens": body.completion_tokens,
        "total_tokens": _total_tokens(body),
        "cost": body.cost,
        "error_count": body.error_count,
        "trace_id": body.trace_id,
        "metadata": _json_dumps(body.metadata),
    }
    if existing is None:
        orm.execute(
            text("""
                INSERT INTO public.ai_chat_sessions (
                    id, project_id, user_id, employee_id, employee_name,
                    source, external_conversation_id, title, task_id, task_title,
                    model, status, started_at, ended_at, duration_ms,
                    prompt_tokens, completion_tokens, total_tokens, cost,
                    error_count, trace_id, metadata
                )
                VALUES (
                    :id, :project_id, :user_id, :employee_id, :employee_name,
                    :source, :conversation_id, :title, :task_id, :task_title,
                    :model, :status, :started_at, :ended_at, :duration_ms,
                    :prompt_tokens, :completion_tokens, :total_tokens, :cost,
                    :error_count, :trace_id, CAST(:metadata AS jsonb)
                )
            """),
            params,
        )
    else:
        orm.execute(
            text("""
                UPDATE public.ai_chat_sessions
                SET user_id = :user_id,
                    employee_name = :employee_name,
                    title = :title,
                    task_id = :task_id,
                    task_title = :task_title,
                    model = :model,
                    status = :status,
                    started_at = :started_at,
                    ended_at = :ended_at,
                    duration_ms = :duration_ms,
                    prompt_tokens = :prompt_tokens,
                    completion_tokens = :completion_tokens,
                    total_tokens = :total_tokens,
                    cost = :cost,
                    error_count = :error_count,
                    trace_id = :trace_id,
                    metadata = CAST(:metadata AS jsonb),
                    updated_at = now()
                WHERE id = :id
            """),
            params,
        )

    orm.execute(
        text("DELETE FROM public.ai_chat_messages WHERE session_id = :session_id"),
        {"session_id": str(session_id)},
    )
    for index, message in enumerate(body.messages):
        orm.execute(
            text("""
                INSERT INTO public.ai_chat_messages (
                    session_id, sequence_index, role, external_message_id,
                    content, token_count, message_created_at, metadata
                )
                VALUES (
                    :session_id, :sequence_index, :role, :message_id,
                    :content, :token_count, :message_created_at,
                    CAST(:metadata AS jsonb)
                )
            """),
            {
                "session_id": str(session_id),
                "sequence_index": index,
                "role": message.role,
                "message_id": message.message_id,
                "content": message.content,
                "token_count": message.token_count,
                "message_created_at": message.created_at,
                "metadata": _json_dumps(message.metadata),
            },
        )
    orm.commit()
    return session_id


def _mark_chatgpt_web_monitor_installed(
    orm: Session,
    *,
    user_id: uuid.UUID,
    employee_id: str,
    employee_name: str,
    body: AIChatIngestRequest,
) -> None:
    if body.source != "chatgpt_web":
        return
    seen_at = datetime.now(timezone.utc)
    components = {
        "chatgpt_web_extension": {
            "name": "chatgpt_web_extension",
            "status": "installed",
            "version": None,
            "last_seen_at": seen_at.isoformat(),
            "details": {"source": "ai_chat_ingest"},
        },
        "browser_shortcut": {
            "name": "browser_shortcut",
            "status": "installed",
            "version": None,
            "last_seen_at": seen_at.isoformat(),
            "details": {"source": "ai_chat_ingest"},
        },
    }
    row = orm.execute(
        text("""
            SELECT device_id
            FROM public.ai_monitor_devices
            WHERE project_id = :project_id
              AND employee_id = :employee_id
            ORDER BY last_seen_at DESC, updated_at DESC
            LIMIT 1
        """),
        {
            "project_id": str(body.project_id),
            "employee_id": employee_id,
        },
    ).first()
    if row:
        orm.execute(
            text("""
                UPDATE public.ai_monitor_devices
                SET user_id = :user_id,
                    employee_name = :employee_name,
                    components = components || CAST(:components AS jsonb),
                    last_seen_at = :last_seen_at,
                    updated_at = now()
                WHERE project_id = :project_id
                  AND employee_id = :employee_id
                  AND device_id = :device_id
            """),
            {
                "project_id": str(body.project_id),
                "user_id": str(user_id),
                "employee_id": employee_id,
                "employee_name": employee_name,
                "device_id": row.device_id,
                "components": _json_dumps(components),
                "last_seen_at": seen_at,
            },
        )
    else:
        orm.execute(
            text("""
                INSERT INTO public.ai_monitor_devices (
                    project_id, user_id, employee_id, employee_name,
                    device_id, device_name, installer_version, os,
                    components, last_seen_at
                )
                VALUES (
                    :project_id, :user_id, :employee_id, :employee_name,
                    :device_id, :device_name, NULL, NULL,
                    CAST(:components AS jsonb), :last_seen_at
                )
                ON CONFLICT (project_id, employee_id, device_id)
                DO UPDATE SET
                    user_id = excluded.user_id,
                    employee_name = excluded.employee_name,
                    components = public.ai_monitor_devices.components || excluded.components,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = now()
            """),
            {
                "project_id": str(body.project_id),
                "user_id": str(user_id),
                "employee_id": employee_id,
                "employee_name": employee_name,
                "device_id": f"chatgpt-web-{employee_id}"[:200],
                "device_name": "ChatGPT Web AI Monitor",
                "components": _json_dumps(components),
                "last_seen_at": seen_at,
            },
        )
    orm.commit()


@router.post("/ai-chat/ingest", response_model=AIChatIngestResponse)
def ingest_ai_chat(
    request: Request,
    body: AIChatIngestRequest,
    orm: Session = Depends(get_orm_session),
) -> AIChatIngestResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    try:
        require_member(orm, user_id=user_id, project_id=body.project_id)
    except AuthzError as error:
        _record_ai_chat_audit(
            orm,
            request,
            user_id=user_id,
            action="ai_chat_ingest",
            project_id=body.project_id,
            source=body.source,
            result_status="forbidden",
        )
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    employee_id, employee_name = _resolve_employee(orm, user_id)
    try:
        session_id = _store_chat_session(
            orm,
            user_id=user_id,
            employee_id=employee_id,
            employee_name=employee_name,
            body=body,
        )
        _mark_chatgpt_web_monitor_installed(
            orm,
            user_id=user_id,
            employee_id=employee_id,
            employee_name=employee_name,
            body=body,
        )
    except Exception as error:
        logger.exception("AI chat ingest failed for project=%s", body.project_id)
        try:
            orm.rollback()
        except Exception:
            pass
        _record_ai_chat_audit(
            orm,
            request,
            user_id=user_id,
            action="ai_chat_ingest",
            project_id=body.project_id,
            source=body.source,
            result_status="service_error",
            employee_id=employee_id,
        )
        raise HTTPException(status_code=503, detail="ai chat ingest unavailable") from error

    _record_ai_chat_audit(
        orm,
        request,
        user_id=user_id,
        action="ai_chat_ingest",
        project_id=body.project_id,
        source=body.source,
        result_status="ok",
        employee_id=employee_id,
        session_id=session_id,
    )
    return AIChatIngestResponse(
        session_id=session_id,
        project_id=body.project_id,
        employee_id=employee_id,
        employee_name=employee_name,
        source=body.source,
        message_count=len(body.messages),
        status=body.status,
    )


def _row_to_session(row) -> AIChatSession:
    raw_messages = row.messages
    messages = None
    if raw_messages is not None:
        messages = [AIChatMessage.model_validate(item) for item in raw_messages]
    return AIChatSession(
        id=row.id,
        project_id=row.project_id,
        employee_id=row.employee_id,
        employee_name=row.employee_name,
        source=row.source,
        conversation_id=row.external_conversation_id,
        title=row.title,
        task_id=row.task_id,
        task_title=row.task_title,
        model=row.model,
        status=row.status,
        started_at=row.started_at,
        ended_at=row.ended_at,
        duration_ms=row.duration_ms,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        cost=float(row.cost or 0),
        error_count=row.error_count,
        trace_id=row.trace_id,
        message_count=row.message_count,
        messages=messages,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/ai-chat/sessions/{project_id}",
    response_model=AIChatSessionListResponse,
)
def list_ai_chat_sessions(
    request: Request,
    project_id: uuid.UUID,
    employee_id: str | None = Query(None, min_length=1, max_length=200),
    work_date: date | None = Query(None, alias="date"),
    source: AIChatSource | None = Query(None),
    include_messages: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    orm: Session = Depends(get_orm_session),
) -> AIChatSessionListResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    try:
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        _record_ai_chat_audit(
            orm,
            request,
            user_id=user_id,
            action="ai_chat_list",
            project_id=project_id,
            source=source,
            result_status="forbidden",
            employee_id=employee_id,
        )
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    conditions = ["s.project_id = :project_id"]
    params: dict[str, Any] = {"project_id": str(project_id), "limit": limit}
    if employee_id:
        conditions.append("s.employee_id = :employee_id")
        params["employee_id"] = employee_id
    if source:
        conditions.append("s.source = :source")
        params["source"] = source
    if work_date:
        start_utc, end_utc = business_day_utc_bounds(work_date)
        conditions.append("s.started_at >= :start_utc AND s.started_at < :end_utc")
        params["start_utc"] = start_utc
        params["end_utc"] = end_utc

    messages_sql = "NULL::jsonb AS messages"
    if include_messages:
        messages_sql = """
            (
                SELECT COALESCE(
                    jsonb_agg(
                        jsonb_build_object(
                            'role', m.role,
                            'content', m.content,
                            'message_id', m.external_message_id,
                            'created_at', m.message_created_at,
                            'token_count', m.token_count,
                            'metadata', m.metadata
                        )
                        ORDER BY m.sequence_index
                    ),
                    '[]'::jsonb
                )
                FROM public.ai_chat_messages m
                WHERE m.session_id = s.id
            ) AS messages
        """

    rows = orm.execute(
        text(f"""
            SELECT
                s.id,
                s.project_id,
                s.employee_id,
                s.employee_name,
                s.source,
                s.external_conversation_id,
                s.title,
                s.task_id,
                s.task_title,
                s.model,
                s.status,
                s.started_at,
                s.ended_at,
                s.duration_ms,
                s.prompt_tokens,
                s.completion_tokens,
                s.total_tokens,
                s.cost,
                s.error_count,
                s.trace_id,
                (
                    SELECT count(*)::int
                    FROM public.ai_chat_messages m
                    WHERE m.session_id = s.id
                ) AS message_count,
                {messages_sql},
                s.created_at,
                s.updated_at
            FROM public.ai_chat_sessions s
            WHERE {" AND ".join(conditions)}
            ORDER BY s.started_at DESC, s.created_at DESC
            LIMIT :limit
        """),
        params,
    ).all()
    _record_ai_chat_audit(
        orm,
        request,
        user_id=user_id,
        action="ai_chat_list",
        project_id=project_id,
        source=source,
        result_status="ok",
        employee_id=employee_id,
    )
    return AIChatSessionListResponse(
        project_id=project_id,
        employee_id=employee_id,
        date=work_date,
        sessions=[_row_to_session(row) for row in rows],
    )
