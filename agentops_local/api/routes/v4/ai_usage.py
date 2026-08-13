from __future__ import annotations

import json
import hashlib
import logging
import secrets
import uuid
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.ai_usage.access import (
    UsageAccessError,
    is_employee_account_email,
    resolve_employee_scope,
    validate_date_range,
)
from agentops.ai_usage.domain import (
    AuthoritativeUsageDaily,
    UsageMessage,
    UsageRecord,
    UsageSummary,
    build_usage_summary,
    build_usage_summary_with_authoritative_source,
    cc_switch_total_tokens,
)
from agentops.ai_usage.reporting import build_report_prompt, generate_usage_report
from agentops.api.db.clickhouse_client import get_clickhouse
from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.rag.audit import record_audit
from agentops.rag.authz import AuthzError, current_user_id, is_system_admin, require_member
from agentops.workday.domain import business_day_utc_bounds
from agentops.workday.identity import derive_employee_identity
from agentops.api.routes.v4.ai_chat import _device_claims


router = APIRouter(route_class=AuthenticatedRoute)
device_router = APIRouter()
logger = logging.getLogger(__name__)

AIUsageSource = Literal[
    "cc_switch",
    "chatgpt_web",
    "chatgpt_desktop",
    "openai_compliance",
    "smartbrain",
]
AIUsageMode = Literal["self", "admin", "statistics"]

CONVERSATION_SYNC_GRACE_PERIOD = timedelta(minutes=15)
SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))
SHARED_SESSION_ACTIVATION_TTL = timedelta(minutes=10)
SHARED_SESSION_MIN_DURATION = timedelta(minutes=5)
SHARED_SESSION_MAX_DURATION = timedelta(hours=24)

DEPARTMENTS = (
    ("research", "研发"),
    ("marketing", "市场"),
    ("business", "业务"),
)


class UsageDepartmentOption(BaseModel):
    id: str
    name: str


class UsageProjectOption(BaseModel):
    id: uuid.UUID
    name: str
    department_id: str


class UsageEmployeeOption(BaseModel):
    id: str
    name: str
    email: str
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    detail_visible_to_admin: bool = False


class UsageOptionsResponse(BaseModel):
    mode: AIUsageMode
    current_employee: UsageEmployeeOption
    departments: list[UsageDepartmentOption]
    projects: list[UsageProjectOption]
    employees: list[UsageEmployeeOption]


class UsageMessageResponse(BaseModel):
    role: str
    content: str
    token_count: int | None = None
    created_at: datetime | None = None


class UsageRecordResponse(BaseModel):
    id: str
    record_type: Literal["chat", "trace"]
    project_id: uuid.UUID
    project_name: str
    employee_id: str
    employee_name: str
    source: str
    title: str
    started_at: datetime
    ended_at: datetime | None = None
    task_id: str
    task_title: str | None = None
    model: str | None = None
    status: str
    duration_ms: int | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    error_count: int
    trace_id: str | None = None
    message_count: int
    messages: list[UsageMessageResponse] | None = None


class UsageDailyPoint(BaseModel):
    date: date
    record_count: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    error_count: int


class UsageHourlyPoint(BaseModel):
    hour: int
    record_count: int
    total_tokens: int


class UsageSourcePoint(BaseModel):
    source: str
    record_count: int
    total_tokens: int


class UsageSummaryResponse(BaseModel):
    start_date: date
    end_date: date
    period_days: int
    active_days: int
    record_count: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    average_tokens_per_day: float
    error_count: int
    total_cost: float
    daily_usage: list[UsageDailyPoint]
    hourly_usage: list[UsageHourlyPoint]
    source_usage: list[UsageSourcePoint]


class UsageLeaderboardMember(BaseModel):
    rank: int
    employee_id: str
    employee_name: str
    account: str
    total_tokens: int
    request_count: int
    active_days: int
    average_tokens_per_day: float
    average_tokens_per_request: float
    share_percent: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    error_count: int
    total_cost: float
    official_cc_switch: bool


class UsageLeaderboardDailyPoint(BaseModel):
    date: date
    total_tokens: int
    request_count: int
    active_users: int


class UsageLeaderboardDistributionPoint(BaseModel):
    key: str
    label: str
    total_tokens: int
    request_count: int
    percentage: float


class UsageLeaderboardResponse(BaseModel):
    start_date: date
    end_date: date
    period_days: int
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    total_tokens: int
    request_count: int
    active_users: int
    active_days: int
    average_tokens_per_user: float
    official_cc_switch_users: int
    members: list[UsageLeaderboardMember]
    daily_usage: list[UsageLeaderboardDailyPoint]
    source_usage: list[UsageLeaderboardDistributionPoint]
    app_usage: list[UsageLeaderboardDistributionPoint]
    token_usage: list[UsageLeaderboardDistributionPoint]
    model_usage: list[UsageLeaderboardDistributionPoint]
    privacy_notice: str = "仅展示聚合统计，不包含对话、Prompt、回复或个人工作日志。"


class UsageQueryResponse(BaseModel):
    mode: AIUsageMode
    employee: UsageEmployeeOption
    projects: list[UsageProjectOption]
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    summary: UsageSummaryResponse
    records: list[UsageRecordResponse]
    has_more: bool
    warnings: list[str]
    detail_visible: bool = True


class CCSwitchUsageRowInput(BaseModel):
    usage_date: date
    app_type: str = Field(..., min_length=1, max_length=40)
    provider_id: str = Field(..., min_length=1, max_length=200)
    model: str = Field(..., min_length=1, max_length=200)
    request_model: str = Field("", max_length=200)
    pricing_model: str = Field("", max_length=200)
    request_count: int = Field(0, ge=0)
    success_count: int = Field(0, ge=0)
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    cache_read_tokens: int = Field(0, ge=0)
    cache_creation_tokens: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)
    total_cost_usd: float = Field(0, ge=0)
    input_token_semantics: int = Field(0, ge=0)


class CCSwitchUsageSyncRequest(BaseModel):
    project_id: uuid.UUID
    device_id: str = Field(..., min_length=1, max_length=200)
    sync_protocol_version: int = Field(1, ge=1)
    trigger: Literal["automatic", "manual"] = "automatic"
    request_id: uuid.UUID | None = None
    range_start: date
    range_end: date
    attempted_at: datetime
    cc_switch_running: bool
    status: Literal["ok", "not_running", "error"]
    source_table: Literal["usage_daily_rollups", "proxy_request_logs"] | None = None
    rows: list[CCSwitchUsageRowInput] = Field(default_factory=list, max_length=5000)
    request_count: int = Field(0, ge=0)
    success_count: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)
    error_message: str | None = Field(None, max_length=1000)


class CCSwitchUsageSyncResponse(BaseModel):
    status: Literal["ok", "not_running", "error"]
    employee_id: str
    employee_name: str
    device_id: str
    trigger: Literal["automatic", "manual"]
    request_id: uuid.UUID | None = None
    range_start: date
    range_end: date
    row_count: int
    request_count: int
    total_tokens: int
    attempted_at: datetime
    synced_at: datetime | None = None
    error_message: str | None = None


SharedSessionStopMode = Literal["default_19", "custom", "manual_only"]
SharedSessionStatus = Literal[
    "starting",
    "active",
    "finalizing",
    "pending_sync",
    "finalized",
    "cancelled",
    "expired",
]


class SharedSessionStartRequest(BaseModel):
    project_id: uuid.UUID
    stop_mode: SharedSessionStopMode = "default_19"
    scheduled_stop_at: datetime | None = None


class SharedSessionScheduleRequest(BaseModel):
    stop_mode: SharedSessionStopMode
    scheduled_stop_at: datetime | None = None


class SharedSessionStopRequest(BaseModel):
    reason: Literal["manual", "replaced_by_next_user"] = "manual"


class SharedSessionResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    target_employee_id: str
    target_employee_name: str
    device_id: str | None = None
    stop_mode: SharedSessionStopMode
    stop_reason: str | None = None
    status: SharedSessionStatus
    requested_at: datetime
    started_at: datetime | None = None
    scheduled_stop_at: datetime
    actual_stop_at: datetime | None = None
    request_count: int = 0
    total_tokens: int = 0
    finalized_at: datetime | None = None
    error_message: str | None = None
    activation_token: str | None = None


class SharedSessionDeviceActivateRequest(BaseModel):
    session_id: uuid.UUID
    activation_token: str = Field(..., min_length=32, max_length=200)
    device_id: str = Field(..., min_length=3, max_length=200)
    started_at: datetime
    start_watermark: str | None = Field(None, max_length=200)


class SharedSessionDeviceCommandRequest(BaseModel):
    session_id: uuid.UUID
    activation_token: str = Field(..., min_length=32, max_length=200)
    device_id: str = Field(..., min_length=3, max_length=200)
    checked_at: datetime


class SharedSessionDeviceCommandResponse(BaseModel):
    action: Literal["continue", "stop"]
    scheduled_stop_at: datetime
    stop_at: datetime | None = None
    stop_reason: str | None = None


class SharedSessionRequestInput(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=500)
    requested_at: datetime
    app_type: str = Field(..., min_length=1, max_length=40)
    provider_id: str = Field(..., min_length=1, max_length=200)
    model: str = Field(..., min_length=1, max_length=200)
    request_model: str = Field("", max_length=200)
    pricing_model: str = Field("", max_length=200)
    status_code: int = Field(0, ge=0, le=999)
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    cache_read_tokens: int = Field(0, ge=0)
    cache_creation_tokens: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)
    total_cost_usd: float = Field(0, ge=0)
    input_token_semantics: int = Field(0, ge=0)


class SharedSessionDeviceFinalizeRequest(BaseModel):
    session_id: uuid.UUID
    activation_token: str = Field(..., min_length=32, max_length=200)
    device_id: str = Field(..., min_length=3, max_length=200)
    stopped_at: datetime
    stop_reason: Literal[
        "manual",
        "scheduled",
        "replaced_by_next_user",
        "admin_forced",
        "safety_timeout",
    ]
    requests: list[SharedSessionRequestInput] = Field(default_factory=list, max_length=10000)


class CCSwitchUsageSyncStatusResponse(BaseModel):
    status: Literal["never", "ok", "not_running", "error"]
    employee_id: str
    employee_name: str
    device_id: str | None = None
    trigger: Literal["automatic", "manual"] | None = None
    request_id: uuid.UUID | None = None
    range_start: date | None = None
    range_end: date | None = None
    row_count: int = 0
    request_count: int = 0
    total_tokens: int = 0
    attempted_at: datetime | None = None
    synced_at: datetime | None = None
    cc_switch_running: bool | None = None
    error_message: str | None = None


class UsageReportRequest(BaseModel):
    employee_id: str = Field(..., min_length=1, max_length=200)
    start_date: date
    end_date: date
    source: AIUsageSource | None = None


class UsageReportResponse(BaseModel):
    employee: UsageEmployeeOption
    summary: UsageSummaryResponse
    high_frequency_periods: list[str]
    report: str
    model: str
    generated_at: datetime


class DailyWorkItemResponse(BaseModel):
    title: str
    problem: str
    actions: list[str]
    result: str
    artifacts: list[str]
    validation: list[str]


class DailyWorkLogResponse(BaseModel):
    id: uuid.UUID
    work_date: date
    employee_id: str
    employee_name: str
    report_markdown: str
    work_items: list[DailyWorkItemResponse]
    source_count: int
    model: str
    generated_at: datetime


class DailyWorkLogListResponse(BaseModel):
    employee: UsageEmployeeOption
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    items: list[DailyWorkLogResponse]


def resolve_shared_session_stop_at(
    *,
    stop_mode: SharedSessionStopMode,
    scheduled_stop_at: datetime | None,
    now: datetime | None = None,
) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if stop_mode == "default_19":
        local = current.astimezone(SHANGHAI_TIMEZONE)
        candidate = local.replace(hour=19, minute=0, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    if stop_mode == "manual_only":
        return current + SHARED_SESSION_MAX_DURATION
    if scheduled_stop_at is None:
        raise HTTPException(status_code=422, detail="scheduled_stop_at is required")
    if scheduled_stop_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="scheduled_stop_at must include timezone")
    candidate = scheduled_stop_at.astimezone(timezone.utc)
    if candidate < current + SHARED_SESSION_MIN_DURATION:
        raise HTTPException(status_code=422, detail="scheduled stop must be at least 5 minutes later")
    if candidate > current + SHARED_SESSION_MAX_DURATION:
        raise HTTPException(status_code=422, detail="scheduled stop must be within 24 hours")
    return candidate


def _shared_token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _shared_session_response(row, *, activation_token: str | None = None) -> SharedSessionResponse:
    return SharedSessionResponse(
        id=row.id,
        project_id=row.project_id,
        target_employee_id=row.target_employee_id,
        target_employee_name=row.target_employee_name,
        device_id=getattr(row, "device_id", None),
        stop_mode=row.stop_mode,
        stop_reason=getattr(row, "stop_reason", None),
        status=row.status,
        requested_at=row.requested_at,
        started_at=getattr(row, "started_at", None),
        scheduled_stop_at=row.scheduled_stop_at,
        actual_stop_at=getattr(row, "actual_stop_at", None),
        request_count=int(getattr(row, "request_count", 0) or 0),
        total_tokens=int(getattr(row, "total_tokens", 0) or 0),
        finalized_at=getattr(row, "finalized_at", None),
        error_message=getattr(row, "error_message", None),
        activation_token=activation_token,
    )


def _get_shared_session(
    orm: Session,
    *,
    session_id: uuid.UUID | None = None,
    target_user_id: uuid.UUID | None = None,
):
    conditions = []
    params: dict[str, str] = {}
    if session_id:
        conditions.append("id = :session_id")
        params["session_id"] = str(session_id)
    if target_user_id:
        conditions.append("target_user_id = :target_user_id")
        params["target_user_id"] = str(target_user_id)
    where = " AND ".join(conditions) or "true"
    return orm.execute(
        text(f"""
            SELECT id, project_id, target_user_id,
                   target_employee_id, target_employee_name,
                   device_id, stop_mode, stop_reason, status,
                   activation_token_hash, activation_expires_at,
                   requested_at, started_at, scheduled_stop_at,
                   actual_stop_at, request_count, total_tokens,
                   finalized_at, error_message
            FROM public.cc_switch_attribution_sessions
            WHERE {where}
            ORDER BY requested_at DESC
            LIMIT 1
        """),
        params,
    ).first()


def _verify_shared_device_session(
    row,
    *,
    activation_token: str,
    device_id: str,
    claims: dict[str, Any],
) -> None:
    if row is None:
        raise HTTPException(status_code=404, detail="shared session not found")
    if str(row.project_id) != str(claims["project_id"]):
        raise HTTPException(status_code=403, detail="project is outside the device scope")
    if not secrets.compare_digest(row.activation_token_hash, _shared_token_hash(activation_token)):
        raise HTTPException(status_code=401, detail="shared session activation token is invalid")
    expires_at = row.activation_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if row.status == "starting" and datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=410, detail="shared session activation token expired")
    if row.device_id and row.device_id != device_id:
        raise HTTPException(status_code=409, detail="shared session belongs to another device")


def _shared_session_audit(
    orm: Session,
    request: Request,
    *,
    user_id: uuid.UUID,
    action: str,
    row,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_audit(
        orm,
        user_id=user_id,
        action=action,
        resource_type="ai_usage",
        resource_id=str(row.id),
        metadata={
            "project_id": str(row.project_id),
            "employee_id": row.target_employee_id,
            "device_id": getattr(row, "device_id", None),
            **(metadata or {}),
        },
        request=request,
    )


def _profile_for_user(orm: Session, user_id: uuid.UUID):
    return orm.execute(
        text("""
            SELECT au.email, pu.full_name, pu.nickname,
                   COALESCE(pu.ai_detail_visible_to_admin, false) AS ai_detail_visible_to_admin
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE au.id = :uid
        """),
        {"uid": str(user_id)},
    ).first()


def _current_employee(orm: Session, user_id: uuid.UUID) -> UsageEmployeeOption:
    profile = _profile_for_user(orm, user_id)
    if profile is None or not profile.email:
        raise HTTPException(status_code=404, detail="user profile not found")
    employee_id, employee_name = derive_employee_identity(
        user_id=user_id,
        email=profile.email,
        full_name=getattr(profile, "nickname", None) or profile.full_name,
    )
    return UsageEmployeeOption(
        id=employee_id,
        name=employee_name,
        email=profile.email,
        project_ids=[],
        detail_visible_to_admin=bool(getattr(profile, "ai_detail_visible_to_admin", False)),
    )


def _is_org_admin(orm: Session, user_id: uuid.UUID) -> bool:
    if is_system_admin(orm, user_id=user_id):
        return True
    return orm.execute(
        text("""
            SELECT 1
            FROM public.user_orgs uo
            JOIN public.projects p ON p.org_id = uo.org_id
            JOIN public.project_members pm
              ON pm.project_id = p.id
             AND pm.user_id = uo.user_id
            WHERE uo.user_id = :uid
              AND uo.role::text IN ('owner', 'admin')
              AND pm.role::text IN ('owner', 'admin')
            LIMIT 1
        """),
        {"uid": str(user_id)},
    ).first() is not None


def _available_projects(
    orm: Session,
    *,
    user_id: uuid.UUID,
    is_admin: bool,
) -> list[UsageProjectOption]:
    if is_admin:
        rows = orm.execute(
            text("""
                SELECT DISTINCT p.id, p.name,
                       COALESCE(p.department_id, 'research') AS department_id
                FROM public.projects p
                WHERE EXISTS (
                    SELECT 1
                    FROM public.users system_admin
                    WHERE system_admin.id = :uid
                      AND COALESCE(system_admin.is_system_admin, false)
                ) OR EXISTS (
                    SELECT 1
                    FROM public.user_orgs uo
                    WHERE uo.org_id = p.org_id
                      AND uo.user_id = :uid
                      AND uo.role::text IN ('owner', 'admin')
                )
                ORDER BY department_id, p.name
            """),
            {"uid": str(user_id)},
        ).all()
    else:
        rows = orm.execute(
            text("""
                SELECT p.id, p.name,
                       COALESCE(p.department_id, 'research') AS department_id
                FROM public.projects p
                JOIN public.project_members pm ON pm.project_id = p.id
                WHERE pm.user_id = :uid
                ORDER BY department_id, p.name
            """),
            {"uid": str(user_id)},
        ).all()
    return [
        UsageProjectOption(
            id=row.id,
            name=row.name,
            department_id=row.department_id,
        )
        for row in rows
    ]


def _bind_list(values: list[str], prefix: str) -> tuple[str, dict[str, str]]:
    parameters = {f"{prefix}_{index}": value for index, value in enumerate(values)}
    return ", ".join(f":{name}" for name in parameters), parameters


def _employee_option_maps(
    orm: Session,
) -> tuple[dict[str, UsageEmployeeOption], dict[str, UsageEmployeeOption]]:
    rows = orm.execute(
        text("""
            SELECT au.id AS user_id, au.email, pu.full_name, pu.nickname,
                   COALESCE(pu.ai_detail_visible_to_admin, false) AS ai_detail_visible_to_admin
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE au.email IS NOT NULL
            ORDER BY COALESCE(NULLIF(BTRIM(pu.nickname), ''), pu.full_name, au.email), au.email
        """),
    ).all()
    employees_by_employee_id: dict[str, UsageEmployeeOption] = {}
    employees_by_user_id: dict[str, UsageEmployeeOption] = {}
    for row in rows:
        if not is_employee_account_email(row.email):
            continue
        employee_id, employee_name = derive_employee_identity(
            user_id=row.user_id,
            email=row.email,
            full_name=getattr(row, "nickname", None) or row.full_name,
        )
        if employee_id not in employees_by_employee_id:
            employees_by_employee_id[employee_id] = UsageEmployeeOption(
                id=employee_id,
                name=employee_name,
                email=row.email,
                project_ids=[],
                detail_visible_to_admin=bool(getattr(row, "ai_detail_visible_to_admin", False)),
            )
        employees_by_user_id[str(row.user_id)] = employees_by_employee_id[employee_id]
    return employees_by_employee_id, employees_by_user_id


def _employee_options(
    orm: Session,
) -> list[UsageEmployeeOption]:
    employees, _ = _employee_option_maps(orm)
    return sorted(employees.values(), key=lambda item: (item.name, item.email))


def _usage_options(
    orm: Session,
    user_id: uuid.UUID,
) -> UsageOptionsResponse:
    is_admin = _is_org_admin(orm, user_id)
    current = _current_employee(orm, user_id)
    employees = _employee_options(orm)
    return UsageOptionsResponse(
        mode="admin" if is_admin else "statistics",
        current_employee=current,
        departments=[UsageDepartmentOption(id=item[0], name=item[1]) for item in DEPARTMENTS],
        projects=[],
        employees=employees,
    )


def _raise_access(error: UsageAccessError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _resolve_scope(
    orm: Session,
    *,
    user_id: uuid.UUID,
    department_id: str | None,
    project_id: uuid.UUID | None,
    requested_employee_id: str | None,
) -> tuple[AIUsageMode, UsageEmployeeOption, list[UsageProjectOption]]:
    options = _usage_options(orm, user_id)

    if options.mode == "admin":
        try:
            employee_id = resolve_employee_scope(
                is_admin=True,
                own_employee_id=options.current_employee.id,
                requested_employee_id=requested_employee_id,
            )
        except UsageAccessError as error:
            _raise_access(error)
    else:
        employee_id = requested_employee_id or options.current_employee.id

    employee = next(
        (
            item
            for item in options.employees
            if item.id == employee_id
        ),
        None,
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="employee account not found")
    return options.mode, employee, []


def _resolve_daily_log_scope(
    orm: Session,
    *,
    user_id: uuid.UUID,
    requested_employee_id: str | None,
) -> tuple[Literal["self", "admin"], UsageEmployeeOption, list[UsageProjectOption]]:
    options = _usage_options(orm, user_id)
    if options.mode != "admin":
        if requested_employee_id and requested_employee_id != options.current_employee.id:
            raise HTTPException(
                status_code=403,
                detail="AI work logs are visible only to the employee and administrators",
            )
        return "self", options.current_employee, []

    try:
        employee_id = resolve_employee_scope(
            is_admin=True,
            own_employee_id=options.current_employee.id,
            requested_employee_id=requested_employee_id,
        )
    except UsageAccessError as error:
        _raise_access(error)
    employee = next((item for item in options.employees if item.id == employee_id), None)
    if employee is None:
        raise HTTPException(status_code=404, detail="employee account not found")
    return "admin", employee, []


def _can_view_detailed_records(
    mode: AIUsageMode,
    current: UsageEmployeeOption,
    employee: UsageEmployeeOption,
) -> bool:
    if current.id == employee.id:
        return True
    return mode == "admin" and employee.detail_visible_to_admin


def _chat_records(
    orm: Session,
    *,
    employee_id: str,
    start_utc: datetime,
    end_utc: datetime,
    source: AIUsageSource | None,
) -> list[UsageRecord]:
    params = {
        "employee_id": employee_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    source_condition = ""
    if source:
        source_condition = "AND s.source = :source"
        params["source"] = source
    rows = orm.execute(
        text(f"""
            SELECT s.id, s.project_id, COALESCE(p.name, 'AI Monitor') AS project_name,
                   s.employee_id, s.employee_name,
                   s.source, s.title, s.task_id, s.task_title, s.model,
                   s.status, s.started_at, s.ended_at, s.duration_ms,
                   s.prompt_tokens, s.completion_tokens, s.total_tokens,
                   s.cost, s.error_count, s.trace_id,
                   (SELECT count(*)::int FROM public.ai_chat_messages m
                    WHERE m.session_id = s.id) AS message_count
            FROM public.ai_chat_sessions s
            LEFT JOIN public.projects p ON p.id = s.project_id
            WHERE s.employee_id = :employee_id
              AND s.started_at >= :start_utc
              AND s.started_at < :end_utc
              {source_condition}
            ORDER BY s.started_at DESC
        """),
        params,
    ).all()
    return [
        UsageRecord(
            id=str(row.id),
            record_type="chat",
            project_id=str(row.project_id),
            project_name=row.project_name or "AI Monitor",
            employee_id=row.employee_id,
            employee_name=row.employee_name,
            source=row.source,
            title=row.title or row.task_title or "未命名 AI 会话",
            started_at=row.started_at,
            ended_at=row.ended_at,
            task_id=row.task_id,
            task_title=row.task_title,
            model=row.model,
            status=row.status,
            duration_ms=row.duration_ms,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            total_tokens=row.total_tokens,
            cost=float(row.cost or 0),
            error_count=row.error_count,
            trace_id=row.trace_id,
            message_count=row.message_count,
        )
        for row in rows
    ]


def _trace_records(
    clickhouse: Any,
    *,
    employee_id: str,
    start_utc: datetime,
    end_utc: datetime,
    source: AIUsageSource | None,
) -> list[UsageRecord]:
    if source and source != "cc_switch":
        return []
    parameters: dict[str, Any] = {
        "employee_id": employee_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }

    employee_expr = "coalesce(nullIf(SpanAttributes['agentops.employee.id'], ''), nullIf(ResourceAttributes['agentops.employee.id'], ''))"
    employee_name_expr = "coalesce(nullIf(SpanAttributes['agentops.employee.name'], ''), nullIf(ResourceAttributes['agentops.employee.name'], ''), '')"
    task_id_expr = "coalesce(nullIf(SpanAttributes['agentops.task.id'], ''), nullIf(ResourceAttributes['agentops.task.id'], ''), '')"
    task_title_expr = "coalesce(nullIf(SpanAttributes['agentops.task.title'], ''), nullIf(ResourceAttributes['agentops.task.title'], ''), '')"
    model_expr = "coalesce(nullIf(SpanAttributes['gen_ai.response.model'], ''), nullIf(SpanAttributes['gen_ai.request.model'], ''), nullIf(SpanAttributes['llm.model'], ''), nullIf(SpanAttributes['model'], ''), '')"
    prompt_expr = "toUInt64OrZero(coalesce(nullIf(SpanAttributes['gen_ai.usage.prompt_tokens'], ''), nullIf(SpanAttributes['gen_ai.usage.input_tokens'], ''), nullIf(SpanAttributes['input_tokens'], ''), '0'))"
    completion_expr = "toUInt64OrZero(coalesce(nullIf(SpanAttributes['gen_ai.usage.completion_tokens'], ''), nullIf(SpanAttributes['gen_ai.usage.output_tokens'], ''), nullIf(SpanAttributes['output_tokens'], ''), '0'))"
    total_expr = f"if(toUInt64OrZero(SpanAttributes['gen_ai.usage.total_tokens']) > 0, toUInt64OrZero(SpanAttributes['gen_ai.usage.total_tokens']), {prompt_expr} + {completion_expr} + toUInt64OrZero(SpanAttributes['gen_ai.usage.reasoning_tokens']) + toUInt64OrZero(SpanAttributes['gen_ai.usage.cache_read_input_tokens']))"
    codex_prompt_expr = "toUInt64OrZero(SpanAttributes['codex.turn.token_usage.input_tokens'])"
    codex_completion_expr = "toUInt64OrZero(SpanAttributes['codex.turn.token_usage.output_tokens'])"
    codex_total_expr = "toUInt64OrZero(SpanAttributes['codex.turn.token_usage.total_tokens'])"
    turn_id_expr = "coalesce(nullIf(SpanAttributes['turn.id'], ''), nullIf(SpanAttributes['turn_id'], ''), '')"
    source_application_expr = "coalesce(nullIf(SpanAttributes['source.application'], ''), '')"
    meaningful_expr = f"""(
        SpanName = 'session_task.turn'
        OR {total_expr} > 0
        OR {codex_total_expr} > 0
        OR {task_id_expr} != ''
        OR SpanAttributes['gen_ai.operation.name'] != ''
        OR SpanAttributes['gen_ai.operation'] != ''
        OR SpanAttributes['gen_ai.tool.name'] != ''
        OR SpanAttributes['tool.name'] != ''
        OR lower(SpanAttributes['agentops.span.kind']) IN ('llm', 'tool')
    )"""
    cost_expr = "toFloat64OrZero(coalesce(nullIf(SpanAttributes['gen_ai.usage.total_cost'], ''), nullIf(SpanAttributes['llm.cost'], ''), '0'))"
    sql = f"""
        SELECT
            toString(project_id) AS project_id,
            TraceId AS trace_id,
            min(Timestamp) AS started_at,
            max(Timestamp) AS ended_at,
            any({employee_name_expr}) AS employee_name,
            anyIf({task_id_expr}, {task_id_expr} != '') AS task_id,
            anyIf({task_title_expr}, {task_title_expr} != '') AS task_title,
            anyIf({turn_id_expr}, {turn_id_expr} != '') AS turn_id,
            anyIf({source_application_expr}, {source_application_expr} != '') AS source_application,
            arrayStringConcat(groupUniqArrayIf({model_expr}, {model_expr} != ''), ', ') AS model,
            if(max({codex_prompt_expr}) > 0, max({codex_prompt_expr}), sum({prompt_expr})) AS prompt_tokens,
            if(max({codex_completion_expr}) > 0, max({codex_completion_expr}), sum({completion_expr})) AS completion_tokens,
            if(max({codex_total_expr}) > 0, max({codex_total_expr}), sum({total_expr})) AS total_tokens,
            sum({cost_expr}) AS cost,
            countIf(upper(StatusCode) = 'ERROR') AS error_count,
            count() AS span_count,
            countIf({meaningful_expr}) AS meaningful_span_count
        FROM otel_traces
        WHERE Timestamp >= %(start_utc)s
          AND Timestamp < %(end_utc)s
          AND {employee_expr} = %(employee_id)s
        GROUP BY project_id, TraceId
        HAVING meaningful_span_count > 0
        ORDER BY started_at DESC
    """
    result = clickhouse.query(sql, parameters=parameters)
    records = []
    for row in result.named_results():
        project_id = str(row["project_id"])
        started_at = row["started_at"]
        ended_at = row["ended_at"]
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=timezone.utc)
        task_id = str(row.get("task_id") or "unassigned")
        task_title = str(row.get("task_title") or "") or None
        trace_id = str(row["trace_id"])
        model = str(row.get("model") or "") or None
        is_codex_turn = bool(row.get("turn_id")) or row.get("source_application") == "codex"
        title = task_title or (
            f"Codex 对话 · {model}" if is_codex_turn and model else "Codex 对话"
        )
        records.append(
            UsageRecord(
                id=f"trace:{trace_id}",
                record_type="trace",
                project_id=project_id,
                project_name="AI Monitor",
                employee_id=employee_id,
                employee_name=str(row.get("employee_name") or employee_id),
                source="cc_switch",
                title=title if is_codex_turn else task_title or f"AI 调用 {trace_id[:12]}",
                started_at=started_at,
                ended_at=ended_at,
                task_id=task_id,
                task_title=task_title,
                model=model,
                status="error" if int(row.get("error_count") or 0) else "ok",
                duration_ms=max(int((ended_at - started_at).total_seconds() * 1000), 0),
                prompt_tokens=int(row.get("prompt_tokens") or 0),
                completion_tokens=int(row.get("completion_tokens") or 0),
                total_tokens=int(row.get("total_tokens") or 0),
                cost=float(row.get("cost") or 0),
                error_count=int(row.get("error_count") or 0),
                trace_id=trace_id,
                message_count=int(row.get("span_count") or 0),
            )
        )
    return records


def _attach_messages(
    orm: Session,
    records: list[UsageRecord],
) -> list[UsageRecord]:
    chat_ids = [item.id for item in records if item.record_type == "chat"]
    if not chat_ids:
        return records
    placeholders, params = _bind_list(chat_ids, "session")
    rows = orm.execute(
        text(f"""
            SELECT session_id, role, content, token_count,
                   COALESCE(message_created_at, created_at) AS created_at
            FROM public.ai_chat_messages
            WHERE session_id IN ({placeholders})
            ORDER BY session_id, sequence_index
        """),
        params,
    ).all()
    messages: dict[str, list[UsageMessage]] = {}
    for row in rows:
        messages.setdefault(str(row.session_id), []).append(
            UsageMessage(
                role=row.role,
                content=row.content,
                token_count=row.token_count,
                created_at=row.created_at,
            )
        )
    return [
        replace(item, messages=tuple(messages.get(item.id, [])))
        if item.record_type == "chat"
        else item
        for item in records
    ]


def _merge_synced_conversations(
    chat_records: list[UsageRecord],
    trace_records: list[UsageRecord],
) -> tuple[list[UsageRecord], list[UsageRecord]]:
    padding = timedelta(seconds=90)

    def overlaps(chat: UsageRecord, trace: UsageRecord) -> bool:
        if chat.source != "cc_switch":
            return False
        if chat.trace_id and chat.trace_id == trace.trace_id:
            return True
        chat_end = chat.ended_at or chat.started_at
        trace_end = trace.ended_at or trace.started_at
        return (
            trace.started_at <= chat_end + padding
            and trace_end >= chat.started_at - padding
        )

    suppressed_trace_indexes: set[int] = set()
    merged_chats: list[UsageRecord] = []
    for chat in chat_records:
        candidates = [
            (index, trace)
            for index, trace in enumerate(trace_records)
            if overlaps(chat, trace)
        ]
        for index, _ in candidates:
            suppressed_trace_indexes.add(index)
        if not candidates:
            merged_chats.append(chat)
            continue
        _, trace = min(
            candidates,
            key=lambda item: (
                1
                if chat.model
                and item[1].model
                and chat.model.casefold() != item[1].model.casefold()
                else 0,
                abs((item[1].started_at - chat.started_at).total_seconds()),
            ),
        )
        merged_chats.append(
            replace(
                chat,
                model=chat.model or trace.model,
                prompt_tokens=chat.prompt_tokens or trace.prompt_tokens,
                completion_tokens=(
                    chat.completion_tokens or trace.completion_tokens
                ),
                total_tokens=chat.total_tokens or trace.total_tokens,
                cost=chat.cost or trace.cost,
                error_count=max(chat.error_count, trace.error_count),
                trace_id=chat.trace_id or trace.trace_id,
            )
        )
    remaining_traces = [
        trace
        for index, trace in enumerate(trace_records)
        if index not in suppressed_trace_indexes
    ]
    return merged_chats, remaining_traces


def _has_stale_unsynced_trace(
    chat_records: list[UsageRecord],
    trace_records: list[UsageRecord],
) -> bool:
    if not trace_records:
        return False
    synced_chats = [item for item in chat_records if item.source == "cc_switch"]
    if not synced_chats:
        return True
    latest_sync = max(item.ended_at or item.started_at for item in synced_chats)
    latest_trace = max(item.ended_at or item.started_at for item in trace_records)
    return latest_trace > latest_sync + CONVERSATION_SYNC_GRACE_PERIOD


def _cc_switch_authoritative_daily(
    orm: Session,
    *,
    employee_id: str,
    start_date: date,
    end_date: date,
    include_personal: bool = True,
) -> list[AuthoritativeUsageDaily]:
    rows = []
    if include_personal:
        rows = orm.execute(
            text("""
            SELECT
                usage_date,
                sum(request_count)::bigint AS request_count,
                sum(
                    CASE
                        WHEN input_token_semantics = 2 THEN input_tokens
                        WHEN app_type IN ('codex', 'gemini')
                             AND input_token_semantics = 1
                             AND input_tokens >= cache_read_tokens + cache_creation_tokens
                        THEN input_tokens - cache_read_tokens - cache_creation_tokens
                        WHEN app_type IN ('codex', 'gemini')
                             AND input_token_semantics = 0
                             AND input_tokens >= cache_read_tokens
                        THEN input_tokens - cache_read_tokens
                        ELSE input_tokens
                    END
                )::bigint AS input_tokens,
                sum(output_tokens)::bigint AS output_tokens,
                sum(cache_read_tokens)::bigint AS cache_read_tokens,
                sum(cache_creation_tokens)::bigint AS cache_creation_tokens,
                sum(total_tokens)::bigint AS total_tokens,
                sum(GREATEST(request_count - success_count, 0))::bigint
                    AS error_count,
                sum(total_cost_usd)::double precision AS total_cost
            FROM public.cc_switch_usage_daily
            WHERE employee_id = :employee_id
              AND usage_date >= :start_date
              AND usage_date <= :end_date
            GROUP BY usage_date
            ORDER BY usage_date
            """),
            {
                "employee_id": employee_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        ).all()
    daily = [
        AuthoritativeUsageDaily(
            usage_date=row.usage_date,
            request_count=int(row.request_count or 0),
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            cache_read_tokens=int(row.cache_read_tokens or 0),
            cache_creation_tokens=int(row.cache_creation_tokens or 0),
            total_tokens=int(row.total_tokens or 0),
            error_count=int(row.error_count or 0),
            total_cost=float(row.total_cost or 0),
        )
        for row in rows
    ]
    shared_rows = orm.execute(
        text("""
            SELECT usage_date,
                   count(*)::bigint AS request_count,
                   sum(
                       CASE
                           WHEN input_token_semantics = 2 THEN input_tokens
                           WHEN lower(app_type) IN ('codex', 'gemini')
                                AND input_token_semantics = 1
                                AND input_tokens >= cache_read_tokens + cache_creation_tokens
                           THEN input_tokens - cache_read_tokens - cache_creation_tokens
                           WHEN lower(app_type) IN ('codex', 'gemini')
                                AND input_token_semantics = 0
                                AND input_tokens >= cache_read_tokens
                           THEN input_tokens - cache_read_tokens
                           ELSE input_tokens
                       END
                   )::bigint AS input_tokens,
                   sum(output_tokens)::bigint AS output_tokens,
                   sum(cache_read_tokens)::bigint AS cache_read_tokens,
                   sum(cache_creation_tokens)::bigint AS cache_creation_tokens,
                   sum(total_tokens)::bigint AS total_tokens,
                   count(*) FILTER (WHERE status_code < 200 OR status_code >= 400)::bigint AS error_count,
                   sum(total_cost_usd)::double precision AS total_cost
            FROM public.cc_switch_attributed_requests
            WHERE target_employee_id = :employee_id
              AND usage_date >= :start_date
              AND usage_date <= :end_date
            GROUP BY usage_date
            ORDER BY usage_date
        """),
        {
            "employee_id": employee_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    ).all()
    combined: dict[date, AuthoritativeUsageDaily] = {
        item.usage_date: item for item in daily
    }
    for row in shared_rows:
        current = combined.get(row.usage_date)
        combined[row.usage_date] = AuthoritativeUsageDaily(
            usage_date=row.usage_date,
            request_count=int(row.request_count or 0) + (current.request_count if current else 0),
            input_tokens=int(row.input_tokens or 0) + (current.input_tokens if current else 0),
            output_tokens=int(row.output_tokens or 0) + (current.output_tokens if current else 0),
            cache_read_tokens=int(row.cache_read_tokens or 0) + (current.cache_read_tokens if current else 0),
            cache_creation_tokens=int(row.cache_creation_tokens or 0) + (current.cache_creation_tokens if current else 0),
            total_tokens=int(row.total_tokens or 0) + (current.total_tokens if current else 0),
            error_count=int(row.error_count or 0) + (current.error_count if current else 0),
            total_cost=float(row.total_cost or 0) + (current.total_cost if current else 0),
        )
    return [combined[item] for item in sorted(combined)]


def _shared_cc_switch_records(
    orm: Session,
    *,
    employee_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> list[UsageRecord]:
    rows = orm.execute(
        text("""
            SELECT s.id, s.project_id, p.name AS project_name,
                   s.target_employee_id, s.target_employee_name,
                   s.started_at, s.actual_stop_at,
                   s.request_count, s.input_tokens, s.output_tokens,
                   s.cache_read_tokens, s.cache_creation_tokens,
                   s.total_tokens, s.total_cost_usd,
                   count(*) FILTER (WHERE r.status_code < 200 OR r.status_code >= 400)::bigint
                       AS error_count,
                   CASE WHEN count(DISTINCT r.model) = 1 THEN max(r.model)
                        ELSE 'multiple' END AS model
            FROM public.cc_switch_attribution_sessions s
            JOIN public.projects p ON p.id = s.project_id
            LEFT JOIN public.cc_switch_attributed_requests r ON r.session_id = s.id
            WHERE s.target_employee_id = :employee_id
              AND s.status = 'finalized'
              AND s.started_at < :end_utc
              AND COALESCE(s.actual_stop_at, s.finalized_at) >= :start_utc
            GROUP BY s.id, p.name
            ORDER BY s.started_at DESC
        """),
        {"employee_id": employee_id, "start_utc": start_utc, "end_utc": end_utc},
    ).all()
    return [
        UsageRecord(
            id=f"shared:{row.id}",
            record_type="chat",
            project_id=str(row.project_id),
            project_name=str(row.project_name),
            employee_id=str(row.target_employee_id),
            employee_name=str(row.target_employee_name),
            source="cc_switch",
            title="公用电脑临时会话",
            started_at=row.started_at,
            ended_at=row.actual_stop_at,
            task_id="shared-device",
            task_title="公用电脑临时记录",
            model=row.model,
            status="ok" if int(row.error_count or 0) == 0 else "partial",
            prompt_tokens=int(row.input_tokens or 0)
            + int(row.cache_read_tokens or 0)
            + int(row.cache_creation_tokens or 0),
            completion_tokens=int(row.output_tokens or 0),
            total_tokens=int(row.total_tokens or 0),
            cost=float(row.total_cost_usd or 0),
            error_count=int(row.error_count or 0),
            message_count=0,
        )
        for row in rows
    ]


def _cc_switch_has_authoritative_coverage(
    orm: Session,
    *,
    employee_id: str,
    start_date: date,
    end_date: date,
) -> bool:
    row = orm.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM public.cc_switch_usage_sync_status
                WHERE employee_id = :employee_id
                  AND status = 'ok'
                  AND range_start <= :start_date
                  AND range_end >= :end_date
            ) AS covered
        """),
        {
            "employee_id": employee_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    ).first()
    return bool(getattr(row, "covered", False))


def _collect_usage(
    orm: Session,
    clickhouse: Any,
    *,
    employee: UsageEmployeeOption,
    start_date: date,
    end_date: date,
    source: AIUsageSource | None,
    record_limit: int,
    include_messages: bool,
) -> tuple[UsageSummary, list[UsageRecord], bool, list[str]]:
    start_utc, _ = business_day_utc_bounds(start_date)
    _, end_utc = business_day_utc_bounds(end_date)
    chat_records = _chat_records(
        orm,
        employee_id=employee.id,
        start_utc=start_utc,
        end_utc=end_utc,
        source=source,
    )
    shared_records = (
        _shared_cc_switch_records(
            orm,
            employee_id=employee.id,
            start_utc=start_utc,
            end_utc=end_utc,
        )
        if source in {None, "cc_switch"}
        else []
    )
    warnings: list[str] = []
    try:
        trace_records = _trace_records(
            clickhouse,
            employee_id=employee.id,
            start_utc=start_utc,
            end_utc=end_utc,
            source=source,
        )
    except Exception:
        logger.exception("AI usage ClickHouse query failed")
        trace_records = []
        warnings.append("Trace 指标暂时不可用，当前结果仅包含已同步的聊天会话")

    chat_records, trace_records = _merge_synced_conversations(
        chat_records,
        trace_records,
    )
    all_records = sorted(
        [
            replace(item, employee_name=employee.name)
            for item in [*chat_records, *trace_records, *shared_records]
        ],
        key=lambda item: item.started_at,
        reverse=True,
    )
    authoritative_daily = []
    authoritative_available = bool(shared_records)
    if source in {None, "cc_switch"}:
        personal_coverage = _cc_switch_has_authoritative_coverage(
            orm,
            employee_id=employee.id,
            start_date=start_date,
            end_date=end_date,
        )
        authoritative_daily = _cc_switch_authoritative_daily(
            orm,
            employee_id=employee.id,
            start_date=start_date,
            end_date=end_date,
            include_personal=personal_coverage,
        )
        authoritative_available = authoritative_available or personal_coverage
    summary = build_usage_summary_with_authoritative_source(
        all_records,
        authoritative_source="cc_switch",
        authoritative_daily=authoritative_daily,
        authoritative_available=authoritative_available,
        start_date=start_date,
        end_date=end_date,
    )
    has_more = len(all_records) > record_limit
    visible_records = all_records[:record_limit]
    if include_messages:
        visible_records = _attach_messages(orm, visible_records)
    if _has_stale_unsynced_trace(chat_records, trace_records):
        warnings.append(
            "检测到尚未完成正文同步的 CC Switch 记录，请确认员工端对话同步组件在线。"
        )
    if authoritative_available:
        warnings.append(
            "CC Switch Token 总量来自 AI Monitor 同步的本机官方统计；Trace 和对话仅用于展示工作明细。"
        )
    return summary, visible_records, has_more, warnings


def _summary_response(summary: UsageSummary) -> UsageSummaryResponse:
    return UsageSummaryResponse.model_validate(asdict(summary))


def _record_response(record: UsageRecord) -> UsageRecordResponse:
    payload = asdict(record)
    payload["total_tokens"] = record.effective_total_tokens
    return UsageRecordResponse.model_validate(payload)


def _audit(
    orm: Session,
    request: Request,
    *,
    user_id: uuid.UUID,
    action: str,
    employee_id: str,
    projects: list[UsageProjectOption],
    start_date: date,
    end_date: date,
    result_status: str,
) -> None:
    record_audit(
        orm,
        user_id=user_id,
        action=action,
        resource_type="ai_usage",
        resource_id=employee_id,
        metadata={
            "employee_id": employee_id,
            "project_ids": [str(item.id) for item in projects],
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "result_status": result_status,
        },
        request=request,
    )


_LEADERBOARD_SOURCE_LABELS = {
    "cc_switch": "CC Switch",
    "chatgpt_web": "ChatGPT Web",
    "chatgpt_desktop": "ChatGPT Desktop",
    "openai_compliance": "OpenAI Compliance",
    "smartbrain": "智慧大脑",
}

_LEADERBOARD_APP_LABELS = {
    "codex": "Codex",
    "claude": "Claude",
    "gemini": "Gemini",
    "cc_switch_fallback": "其他 CC Switch",
    "chatgpt_web": "ChatGPT Web",
    "chatgpt_desktop": "ChatGPT Desktop",
    "openai_compliance": "OpenAI Compliance",
    "smartbrain": "智慧大脑",
    "unknown": "其他应用",
}


def _leaderboard_distribution(
    values: dict[str, dict[str, int]],
    *,
    labels: dict[str, str] | None = None,
) -> list[UsageLeaderboardDistributionPoint]:
    denominator = sum(max(int(item["total_tokens"]), 0) for item in values.values())
    rows = sorted(
        values.items(),
        key=lambda item: (-int(item[1]["total_tokens"]), item[0]),
    )
    return [
        UsageLeaderboardDistributionPoint(
            key=key,
            label=(labels or {}).get(key, key),
            total_tokens=max(int(value["total_tokens"]), 0),
            request_count=max(int(value.get("request_count", 0)), 0),
            percentage=round(
                max(int(value["total_tokens"]), 0) * 100 / denominator,
                2,
            ) if denominator else 0.0,
        )
        for key, value in rows
        if int(value["total_tokens"]) > 0
    ]


@router.post("/ai-usage/shared-sessions/start", response_model=SharedSessionResponse)
def start_shared_session(
    request: Request,
    body: SharedSessionStartRequest,
    orm: Session = Depends(get_orm_session),
) -> SharedSessionResponse:
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=body.project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    employee = _current_employee(orm, user_id)
    existing = orm.execute(
        text("""
            SELECT id
            FROM public.cc_switch_attribution_sessions
            WHERE target_user_id = :target_user_id
              AND status IN ('starting', 'active', 'finalizing', 'pending_sync')
            LIMIT 1
        """),
        {"target_user_id": str(user_id)},
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="this member already has an active shared session")
    now = datetime.now(timezone.utc)
    stop_at = resolve_shared_session_stop_at(
        stop_mode=body.stop_mode,
        scheduled_stop_at=body.scheduled_stop_at,
        now=now,
    )
    activation_token = secrets.token_urlsafe(32)
    row = orm.execute(
        text("""
            INSERT INTO public.cc_switch_attribution_sessions (
                project_id, target_user_id,
                target_employee_id, target_employee_name,
                stop_mode, activation_token_hash,
                activation_expires_at, requested_at, scheduled_stop_at
            ) VALUES (
                :project_id, :target_user_id,
                :target_employee_id, :target_employee_name,
                :stop_mode, :activation_token_hash,
                :activation_expires_at, :requested_at, :scheduled_stop_at
            )
            RETURNING id, project_id, target_user_id,
                      target_employee_id, target_employee_name,
                      device_id, stop_mode, stop_reason, status,
                      activation_token_hash, activation_expires_at,
                      requested_at, started_at, scheduled_stop_at,
                      actual_stop_at, request_count, total_tokens,
                      finalized_at, error_message
        """),
        {
            "project_id": str(body.project_id),
            "target_user_id": str(user_id),
            "target_employee_id": employee.id,
            "target_employee_name": employee.name,
            "stop_mode": body.stop_mode,
            "activation_token_hash": _shared_token_hash(activation_token),
            "activation_expires_at": now + SHARED_SESSION_ACTIVATION_TTL,
            "requested_at": now,
            "scheduled_stop_at": stop_at,
        },
    ).first()
    orm.commit()
    _shared_session_audit(
        orm,
        request,
        user_id=user_id,
        action="ai_shared_session_start",
        row=row,
        metadata={"stop_mode": body.stop_mode, "scheduled_stop_at": stop_at.isoformat()},
    )
    return _shared_session_response(row, activation_token=activation_token)


@router.get("/ai-usage/shared-sessions/current", response_model=SharedSessionResponse | None)
def get_current_shared_session(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> SharedSessionResponse | None:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    row = orm.execute(
        text("""
            SELECT id, project_id, target_user_id,
                   target_employee_id, target_employee_name,
                   device_id, stop_mode, stop_reason, status,
                   activation_token_hash, activation_expires_at,
                   requested_at, started_at, scheduled_stop_at,
                   actual_stop_at, request_count, total_tokens,
                   finalized_at, error_message
            FROM public.cc_switch_attribution_sessions
            WHERE target_user_id = :target_user_id
              AND status IN ('starting', 'active', 'finalizing', 'pending_sync')
            ORDER BY requested_at DESC
            LIMIT 1
        """),
        {"target_user_id": str(user_id)},
    ).first()
    return _shared_session_response(row) if row else None


@router.get(
    "/ai-usage/shared-sessions/{session_id}",
    response_model=SharedSessionResponse,
)
def get_shared_session(
    request: Request,
    session_id: uuid.UUID,
    orm: Session = Depends(get_orm_session),
) -> SharedSessionResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    row = _get_shared_session(orm, session_id=session_id, target_user_id=user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="shared session not found")
    return _shared_session_response(row)


@router.patch(
    "/ai-usage/shared-sessions/{session_id}/schedule",
    response_model=SharedSessionResponse,
)
def update_shared_session_schedule(
    request: Request,
    session_id: uuid.UUID,
    body: SharedSessionScheduleRequest,
    orm: Session = Depends(get_orm_session),
) -> SharedSessionResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    existing = _get_shared_session(orm, session_id=session_id, target_user_id=user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="shared session not found")
    if existing.status not in {"starting", "active"}:
        raise HTTPException(status_code=409, detail="shared session can no longer be rescheduled")
    stop_at = resolve_shared_session_stop_at(
        stop_mode=body.stop_mode,
        scheduled_stop_at=body.scheduled_stop_at,
    )
    row = orm.execute(
        text("""
            UPDATE public.cc_switch_attribution_sessions
            SET stop_mode = :stop_mode,
                scheduled_stop_at = :scheduled_stop_at,
                updated_at = now()
            WHERE id = :session_id
            RETURNING id, project_id, target_user_id,
                      target_employee_id, target_employee_name,
                      device_id, stop_mode, stop_reason, status,
                      activation_token_hash, activation_expires_at,
                      requested_at, started_at, scheduled_stop_at,
                      actual_stop_at, request_count, total_tokens,
                      finalized_at, error_message
        """),
        {
            "session_id": str(session_id),
            "stop_mode": body.stop_mode,
            "scheduled_stop_at": stop_at,
        },
    ).first()
    orm.commit()
    _shared_session_audit(
        orm,
        request,
        user_id=user_id,
        action="ai_shared_session_schedule",
        row=row,
        metadata={"stop_mode": body.stop_mode, "scheduled_stop_at": stop_at.isoformat()},
    )
    return _shared_session_response(row)


@router.post(
    "/ai-usage/shared-sessions/{session_id}/stop",
    response_model=SharedSessionResponse,
)
def stop_shared_session(
    request: Request,
    session_id: uuid.UUID,
    body: SharedSessionStopRequest,
    orm: Session = Depends(get_orm_session),
) -> SharedSessionResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    existing = _get_shared_session(orm, session_id=session_id, target_user_id=user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="shared session not found")
    if existing.status not in {"starting", "active", "pending_sync"}:
        raise HTTPException(status_code=409, detail="shared session is already stopped")
    stopped_at = datetime.now(timezone.utc)
    status = "finalizing" if existing.device_id else "cancelled"
    row = orm.execute(
        text("""
            UPDATE public.cc_switch_attribution_sessions
            SET status = :status, stop_reason = :stop_reason,
                actual_stop_at = :actual_stop_at, updated_at = now()
            WHERE id = :session_id
            RETURNING id, project_id, target_user_id,
                      target_employee_id, target_employee_name,
                      device_id, stop_mode, stop_reason, status,
                      activation_token_hash, activation_expires_at,
                      requested_at, started_at, scheduled_stop_at,
                      actual_stop_at, request_count, total_tokens,
                      finalized_at, error_message
        """),
        {
            "session_id": str(session_id),
            "status": status,
            "stop_reason": body.reason,
            "actual_stop_at": stopped_at,
        },
    ).first()
    orm.commit()
    _shared_session_audit(
        orm,
        request,
        user_id=user_id,
        action="ai_shared_session_stop",
        row=row,
        metadata={"stop_reason": body.reason},
    )
    return _shared_session_response(row)


def _build_ai_usage_leaderboard(
    orm: Session,
    *,
    start_date: date,
    end_date: date,
) -> UsageLeaderboardResponse:
    employees, employees_by_user_id = _employee_option_maps(orm)
    coverage_rows = orm.execute(
        text("""
            SELECT user_id,
                   employee_id,
                   bool_or(
                       status = 'ok'
                       AND range_start <= :start_date
                       AND range_end >= :end_date
                   ) AS covered
            FROM public.cc_switch_usage_sync_status
            GROUP BY user_id, employee_id
        """),
        {"start_date": start_date, "end_date": end_date},
    ).all()
    covered: dict[str, bool] = {}
    for row in coverage_rows:
        option = employees_by_user_id.get(str(getattr(row, "user_id", "")))
        employee_id = option.id if option else str(row.employee_id)
        covered[employee_id] = covered.get(employee_id, False) or bool(row.covered)

    official_rows = orm.execute(
        text("""
            SELECT user_id,
                   employee_id,
                   max(employee_name) AS employee_name,
                   usage_date,
                   lower(COALESCE(NULLIF(app_type, ''), 'unknown')) AS app_type,
                   COALESCE(NULLIF(model, ''), 'unknown') AS model,
                   sum(request_count)::bigint AS request_count,
                   sum(
                       CASE
                           WHEN input_token_semantics = 2 THEN input_tokens
                           WHEN lower(app_type) IN ('codex', 'gemini')
                                AND input_token_semantics = 1
                                AND input_tokens >= cache_read_tokens + cache_creation_tokens
                           THEN input_tokens - cache_read_tokens - cache_creation_tokens
                           WHEN lower(app_type) IN ('codex', 'gemini')
                                AND input_token_semantics = 0
                                AND input_tokens >= cache_read_tokens
                           THEN input_tokens - cache_read_tokens
                           ELSE input_tokens
                       END
                   )::bigint AS input_tokens,
                   sum(output_tokens)::bigint AS output_tokens,
                   sum(cache_read_tokens)::bigint AS cache_read_tokens,
                   sum(cache_creation_tokens)::bigint AS cache_creation_tokens,
                   sum(
                       CASE
                           WHEN input_token_semantics = 2 THEN input_tokens
                           WHEN lower(app_type) IN ('codex', 'gemini')
                                AND input_token_semantics = 1
                                AND input_tokens >= cache_read_tokens + cache_creation_tokens
                           THEN input_tokens - cache_read_tokens - cache_creation_tokens
                           WHEN lower(app_type) IN ('codex', 'gemini')
                                AND input_token_semantics = 0
                                AND input_tokens >= cache_read_tokens
                           THEN input_tokens - cache_read_tokens
                           ELSE input_tokens
                       END
                       + output_tokens
                       + cache_read_tokens
                       + cache_creation_tokens
                   )::bigint AS total_tokens,
                   sum(GREATEST(request_count - success_count, 0))::bigint AS error_count,
                   sum(total_cost_usd)::double precision AS total_cost
            FROM public.cc_switch_usage_daily
            WHERE usage_date >= :start_date
              AND usage_date <= :end_date
            GROUP BY user_id, employee_id, usage_date, app_type, model
            ORDER BY employee_id, usage_date
        """),
        {"start_date": start_date, "end_date": end_date},
    ).all()
    shared_rows = orm.execute(
        text("""
            SELECT target_user_id AS user_id,
                   target_employee_id AS employee_id,
                   max(target_employee_name) AS employee_name,
                   usage_date,
                   lower(COALESCE(NULLIF(app_type, ''), 'unknown')) AS app_type,
                   COALESCE(NULLIF(model, ''), 'unknown') AS model,
                   count(*)::bigint AS request_count,
                   sum(
                       CASE
                           WHEN input_token_semantics = 2 THEN input_tokens
                           WHEN lower(app_type) IN ('codex', 'gemini')
                                AND input_token_semantics = 1
                                AND input_tokens >= cache_read_tokens + cache_creation_tokens
                           THEN input_tokens - cache_read_tokens - cache_creation_tokens
                           WHEN lower(app_type) IN ('codex', 'gemini')
                                AND input_token_semantics = 0
                                AND input_tokens >= cache_read_tokens
                           THEN input_tokens - cache_read_tokens
                           ELSE input_tokens
                       END
                   )::bigint AS input_tokens,
                   sum(output_tokens)::bigint AS output_tokens,
                   sum(cache_read_tokens)::bigint AS cache_read_tokens,
                   sum(cache_creation_tokens)::bigint AS cache_creation_tokens,
                   sum(total_tokens)::bigint AS total_tokens,
                   count(*) FILTER (WHERE status_code < 200 OR status_code >= 400)::bigint AS error_count,
                   sum(total_cost_usd)::double precision AS total_cost
            FROM public.cc_switch_attributed_requests
            WHERE usage_date >= :start_date
              AND usage_date <= :end_date
            GROUP BY target_user_id, target_employee_id, usage_date, app_type, model
            ORDER BY target_employee_id, usage_date
        """),
        {"start_date": start_date, "end_date": end_date},
    ).all()
    session_rows = orm.execute(
        text("""
            SELECT user_id,
                   employee_id,
                   max(employee_name) AS employee_name,
                   (started_at AT TIME ZONE 'Asia/Shanghai')::date AS usage_date,
                   source,
                   COALESCE(NULLIF(model, ''), 'unknown') AS model,
                   count(*)::bigint AS request_count,
                   sum(prompt_tokens)::bigint AS input_tokens,
                   sum(completion_tokens)::bigint AS output_tokens,
                   sum(total_tokens)::bigint AS total_tokens,
                   sum(error_count)::bigint AS error_count,
                   sum(cost)::double precision AS total_cost
            FROM public.ai_chat_sessions
            WHERE started_at >= (CAST(:start_date AS date) - interval '8 hours')
              AND started_at < ((CAST(:end_date AS date) + interval '1 day') - interval '8 hours')
            GROUP BY user_id,
                     employee_id,
                     (started_at AT TIME ZONE 'Asia/Shanghai')::date,
                     source,
                     model
            ORDER BY employee_id, usage_date
        """),
        {"start_date": start_date, "end_date": end_date},
    ).all()

    members: dict[str, dict[str, Any]] = {}
    daily: dict[date, dict[str, Any]] = {}
    source_usage: dict[str, dict[str, int]] = {}
    app_usage: dict[str, dict[str, int]] = {}
    model_usage: dict[str, dict[str, int]] = {}
    token_usage: dict[str, dict[str, int]] = {
        "input": {"total_tokens": 0, "request_count": 0},
        "output": {"total_tokens": 0, "request_count": 0},
        "cache_read": {"total_tokens": 0, "request_count": 0},
        "cache_creation": {"total_tokens": 0, "request_count": 0},
        "other": {"total_tokens": 0, "request_count": 0},
    }
    official_seen: set[str] = set()

    def add_distribution(
        target: dict[str, dict[str, int]],
        key: str,
        total_tokens: int,
        request_count: int,
    ) -> None:
        item = target.setdefault(key, {"total_tokens": 0, "request_count": 0})
        item["total_tokens"] += total_tokens
        item["request_count"] += request_count

    def add_row(
        *,
        user_id: uuid.UUID | str | None,
        employee_id: str,
        employee_name: str,
        usage_date: date,
        source: str,
        app: str,
        model: str,
        request_count: int,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
        total_tokens: int,
        error_count: int,
        total_cost: float,
        is_official: bool,
    ) -> None:
        option = employees_by_user_id.get(str(user_id)) if user_id else None
        option = option or employees.get(employee_id)
        canonical_employee_id = option.id if option else employee_id
        member = members.setdefault(
            canonical_employee_id,
            {
                "employee_id": canonical_employee_id,
                "employee_name": option.name if option else employee_name or employee_id,
                "account": option.email.split("@", 1)[0] if option else employee_id,
                "total_tokens": 0,
                "request_count": 0,
                "days": set(),
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "error_count": 0,
                "total_cost": 0.0,
            },
        )
        member["total_tokens"] += total_tokens
        member["request_count"] += request_count
        member["days"].add(usage_date)
        member["input_tokens"] += input_tokens
        member["output_tokens"] += output_tokens
        member["cache_read_tokens"] += cache_read_tokens
        member["cache_creation_tokens"] += cache_creation_tokens
        member["error_count"] += error_count
        member["total_cost"] += total_cost
        if is_official:
            official_seen.add(canonical_employee_id)

        day = daily.setdefault(
            usage_date,
            {"total_tokens": 0, "request_count": 0, "users": set()},
        )
        day["total_tokens"] += total_tokens
        day["request_count"] += request_count
        day["users"].add(canonical_employee_id)
        add_distribution(source_usage, source, total_tokens, request_count)
        add_distribution(app_usage, app, total_tokens, request_count)
        add_distribution(model_usage, model or "unknown", total_tokens, request_count)
        token_usage["input"]["total_tokens"] += input_tokens
        token_usage["output"]["total_tokens"] += output_tokens
        token_usage["cache_read"]["total_tokens"] += cache_read_tokens
        token_usage["cache_creation"]["total_tokens"] += cache_creation_tokens
        known_tokens = input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens
        token_usage["other"]["total_tokens"] += max(total_tokens - known_tokens, 0)

    for row in official_rows:
        employee_id = str(row.employee_id)
        option = employees_by_user_id.get(str(getattr(row, "user_id", "")))
        canonical_employee_id = option.id if option else employee_id
        if not covered.get(canonical_employee_id, False):
            continue
        add_row(
            user_id=getattr(row, "user_id", None),
            employee_id=employee_id,
            employee_name=str(row.employee_name or employee_id),
            usage_date=row.usage_date,
            source="cc_switch",
            app=str(row.app_type or "unknown"),
            model=str(row.model or "unknown"),
            request_count=int(row.request_count or 0),
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            cache_read_tokens=int(row.cache_read_tokens or 0),
            cache_creation_tokens=int(row.cache_creation_tokens or 0),
            total_tokens=int(row.total_tokens or 0),
            error_count=int(row.error_count or 0),
            total_cost=float(row.total_cost or 0),
            is_official=True,
        )

    for row in shared_rows:
        add_row(
            user_id=getattr(row, "user_id", None),
            employee_id=str(row.employee_id),
            employee_name=str(row.employee_name or row.employee_id),
            usage_date=row.usage_date,
            source="cc_switch",
            app=str(row.app_type or "unknown"),
            model=str(row.model or "unknown"),
            request_count=int(row.request_count or 0),
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            cache_read_tokens=int(row.cache_read_tokens or 0),
            cache_creation_tokens=int(row.cache_creation_tokens or 0),
            total_tokens=int(row.total_tokens or 0),
            error_count=int(row.error_count or 0),
            total_cost=float(row.total_cost or 0),
            is_official=False,
        )

    for row in session_rows:
        employee_id = str(row.employee_id)
        option = employees_by_user_id.get(str(getattr(row, "user_id", "")))
        canonical_employee_id = option.id if option else employee_id
        source = str(row.source or "unknown")
        if source == "cc_switch" and covered.get(canonical_employee_id, False):
            continue
        add_row(
            user_id=getattr(row, "user_id", None),
            employee_id=employee_id,
            employee_name=str(row.employee_name or employee_id),
            usage_date=row.usage_date,
            source=source,
            app="cc_switch_fallback" if source == "cc_switch" else source,
            model=str(row.model or "unknown"),
            request_count=int(row.request_count or 0),
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            cache_read_tokens=0,
            cache_creation_tokens=0,
            total_tokens=int(row.total_tokens or 0),
            error_count=int(row.error_count or 0),
            total_cost=float(row.total_cost or 0),
            is_official=False,
        )

    member_values = [item for item in members.values() if int(item["total_tokens"]) > 0]
    member_values.sort(
        key=lambda item: (
            -int(item["total_tokens"]),
            -int(item["request_count"]),
            str(item["employee_name"]),
        )
    )
    total_tokens = sum(int(item["total_tokens"]) for item in member_values)
    request_count = sum(int(item["request_count"]) for item in member_values)
    member_rows = [
        UsageLeaderboardMember(
            rank=index,
            employee_id=str(item["employee_id"]),
            employee_name=str(item["employee_name"]),
            account=str(item["account"]),
            total_tokens=int(item["total_tokens"]),
            request_count=int(item["request_count"]),
            active_days=len(item["days"]),
            average_tokens_per_day=round(
                int(item["total_tokens"]) / max(len(item["days"]), 1),
                2,
            ),
            average_tokens_per_request=round(
                int(item["total_tokens"]) / max(int(item["request_count"]), 1),
                2,
            ),
            share_percent=round(int(item["total_tokens"]) * 100 / total_tokens, 2)
            if total_tokens else 0.0,
            input_tokens=int(item["input_tokens"]),
            output_tokens=int(item["output_tokens"]),
            cache_read_tokens=int(item["cache_read_tokens"]),
            cache_creation_tokens=int(item["cache_creation_tokens"]),
            error_count=int(item["error_count"]),
            total_cost=round(float(item["total_cost"]), 6),
            official_cc_switch=str(item["employee_id"]) in official_seen,
        )
        for index, item in enumerate(member_values, start=1)
    ]
    daily_rows = [
        UsageLeaderboardDailyPoint(
            date=usage_date,
            total_tokens=int(item["total_tokens"]),
            request_count=int(item["request_count"]),
            active_users=len(item["users"]),
        )
        for usage_date, item in sorted(daily.items())
    ]
    period_days = (end_date - start_date).days + 1
    return UsageLeaderboardResponse(
        start_date=start_date,
        end_date=end_date,
        period_days=period_days,
        total_tokens=total_tokens,
        request_count=request_count,
        active_users=len(member_rows),
        active_days=len(daily_rows),
        average_tokens_per_user=round(total_tokens / max(len(member_rows), 1), 2),
        official_cc_switch_users=len(official_seen),
        members=member_rows,
        daily_usage=daily_rows,
        source_usage=_leaderboard_distribution(
            source_usage,
            labels=_LEADERBOARD_SOURCE_LABELS,
        ),
        app_usage=_leaderboard_distribution(
            app_usage,
            labels=_LEADERBOARD_APP_LABELS,
        ),
        token_usage=_leaderboard_distribution(
            token_usage,
            labels={
                "input": "新鲜输入",
                "output": "模型输出",
                "cache_read": "缓存读取",
                "cache_creation": "缓存写入",
                "other": "其他 Token",
            },
        ),
        model_usage=_leaderboard_distribution(model_usage),
    )


@device_router.post(
    "/ai-usage/cc-switch-sync/device-ingest",
    response_model=CCSwitchUsageSyncResponse,
)
def device_ingest_cc_switch_usage(
    request: Request,
    body: CCSwitchUsageSyncRequest,
    orm: Session = Depends(get_orm_session),
) -> CCSwitchUsageSyncResponse:
    claims = _device_claims(request)
    if str(body.project_id) != str(claims["project_id"]):
        raise HTTPException(
            status_code=403,
            detail="device credential does not belong to this project",
        )
    if body.range_end < body.range_start:
        raise HTTPException(status_code=422, detail="range_end must not precede range_start")
    if (body.range_end - body.range_start).days > 3650:
        raise HTTPException(status_code=422, detail="sync range is too large")
    if body.status == "ok" and body.sync_protocol_version < 2:
        raise HTTPException(
            status_code=409,
            detail="AI Monitor r16 or newer is required for CC Switch usage sync",
        )
    if body.status == "ok" and not body.cc_switch_running:
        raise HTTPException(status_code=422, detail="CC Switch must be running for a successful sync")
    if any(
        row.usage_date < body.range_start or row.usage_date > body.range_end
        for row in body.rows
    ):
        raise HTTPException(status_code=422, detail="usage row falls outside the declared range")
    normalized_rows = [
        (
            row,
            cc_switch_total_tokens(
                app_type=row.app_type,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                cache_read_tokens=row.cache_read_tokens,
                cache_creation_tokens=row.cache_creation_tokens,
                input_token_semantics=row.input_token_semantics,
            ),
        )
        for row in body.rows
    ]
    normalized_total_tokens = (
        sum(total_tokens for _, total_tokens in normalized_rows)
        if body.status == "ok"
        else body.total_tokens
    )

    user_id = uuid.UUID(str(claims["sub"]))
    employee_id = str(claims.get("employee_id") or "").strip()
    employee_name = str(claims.get("employee_name") or employee_id).strip()
    if not employee_id:
        raise HTTPException(status_code=401, detail="device credential has no employee identity")
    synced_at = datetime.now(timezone.utc)
    try:
        if body.status == "ok":
            orm.execute(
                text("""
                    DELETE FROM public.cc_switch_usage_daily
                    WHERE user_id = :user_id
                      AND device_id = :device_id
                      AND usage_date >= :range_start
                      AND usage_date <= :range_end
                """),
                {
                    "user_id": str(user_id),
                    "device_id": body.device_id,
                    "range_start": body.range_start,
                    "range_end": body.range_end,
                },
            )
            for row, total_tokens in normalized_rows:
                orm.execute(
                    text("""
                        INSERT INTO public.cc_switch_usage_daily (
                            project_id, user_id, employee_id, employee_name,
                            device_id, usage_date, app_type, provider_id,
                            model, request_model, pricing_model,
                            request_count, success_count,
                            input_tokens, output_tokens,
                            cache_read_tokens, cache_creation_tokens,
                            total_tokens, total_cost_usd,
                            input_token_semantics, source_table, synced_at
                        ) VALUES (
                            :project_id, :user_id, :employee_id, :employee_name,
                            :device_id, :usage_date, :app_type, :provider_id,
                            :model, :request_model, :pricing_model,
                            :request_count, :success_count,
                            :input_tokens, :output_tokens,
                            :cache_read_tokens, :cache_creation_tokens,
                            :total_tokens, :total_cost_usd,
                            :input_token_semantics, :source_table, :synced_at
                        )
                        ON CONFLICT (
                            user_id, device_id, usage_date, app_type,
                            provider_id, model, request_model, pricing_model
                        ) DO UPDATE SET
                            project_id = excluded.project_id,
                            employee_id = excluded.employee_id,
                            employee_name = excluded.employee_name,
                            request_count = excluded.request_count,
                            success_count = excluded.success_count,
                            input_tokens = excluded.input_tokens,
                            output_tokens = excluded.output_tokens,
                            cache_read_tokens = excluded.cache_read_tokens,
                            cache_creation_tokens = excluded.cache_creation_tokens,
                            total_tokens = excluded.total_tokens,
                            total_cost_usd = excluded.total_cost_usd,
                            input_token_semantics = excluded.input_token_semantics,
                            source_table = excluded.source_table,
                            synced_at = excluded.synced_at,
                            updated_at = now()
                    """),
                    {
                        "project_id": str(body.project_id),
                        "user_id": str(user_id),
                        "employee_id": employee_id,
                        "employee_name": employee_name,
                        "device_id": body.device_id,
                        "usage_date": row.usage_date,
                        "app_type": row.app_type,
                        "provider_id": row.provider_id,
                        "model": row.model,
                        "request_model": row.request_model,
                        "pricing_model": row.pricing_model,
                        "request_count": row.request_count,
                        "success_count": row.success_count,
                        "input_tokens": row.input_tokens,
                        "output_tokens": row.output_tokens,
                        "cache_read_tokens": row.cache_read_tokens,
                        "cache_creation_tokens": row.cache_creation_tokens,
                        "total_tokens": total_tokens,
                        "total_cost_usd": row.total_cost_usd,
                        "input_token_semantics": row.input_token_semantics,
                        "source_table": body.source_table,
                        "synced_at": synced_at,
                    },
                )
        status_row = orm.execute(
            text("""
                INSERT INTO public.cc_switch_usage_sync_status (
                    project_id, user_id, employee_id, employee_name,
                    device_id, trigger, request_id,
                    range_start, range_end, status,
                    cc_switch_running, source_table,
                    row_count, request_count, total_tokens,
                    attempted_at, last_success_at, error_message
                ) VALUES (
                    :project_id, :user_id, :employee_id, :employee_name,
                    :device_id, :trigger, :request_id,
                    :range_start, :range_end, :status,
                    :cc_switch_running, :source_table,
                    :row_count, :request_count, :total_tokens,
                    :attempted_at,
                    CASE WHEN :status = 'ok' THEN :synced_at ELSE NULL END,
                    :error_message
                )
                ON CONFLICT (user_id, device_id)
                DO UPDATE SET
                    project_id = excluded.project_id,
                    employee_id = excluded.employee_id,
                    employee_name = excluded.employee_name,
                    trigger = excluded.trigger,
                    request_id = excluded.request_id,
                    range_start = excluded.range_start,
                    range_end = excluded.range_end,
                    status = excluded.status,
                    cc_switch_running = excluded.cc_switch_running,
                    source_table = excluded.source_table,
                    row_count = excluded.row_count,
                    request_count = excluded.request_count,
                    total_tokens = excluded.total_tokens,
                    attempted_at = excluded.attempted_at,
                    last_success_at = CASE
                        WHEN excluded.status = 'ok' THEN excluded.last_success_at
                        ELSE public.cc_switch_usage_sync_status.last_success_at
                    END,
                    error_message = excluded.error_message,
                    updated_at = now()
                RETURNING last_success_at AS synced_at
            """),
            {
                "project_id": str(body.project_id),
                "user_id": str(user_id),
                "employee_id": employee_id,
                "employee_name": employee_name,
                "device_id": body.device_id,
                "trigger": body.trigger,
                "request_id": str(body.request_id) if body.request_id else None,
                "range_start": body.range_start,
                "range_end": body.range_end,
                "status": body.status,
                "cc_switch_running": body.cc_switch_running,
                "source_table": body.source_table,
                "row_count": len(body.rows),
                "request_count": body.request_count,
                "total_tokens": normalized_total_tokens,
                "attempted_at": body.attempted_at,
                "synced_at": synced_at,
                "error_message": body.error_message,
            },
        ).first()
        orm.commit()
    except Exception as error:
        logger.exception("CC Switch usage device ingest failed")
        try:
            orm.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="CC Switch usage sync unavailable") from error

    record_audit(
        orm,
        user_id=user_id,
        action="ai_usage_sync",
        resource_type="ai_usage",
        resource_id=employee_id,
        metadata={
            "result_status": body.status,
            "trigger": body.trigger,
            "sync_protocol_version": body.sync_protocol_version,
            "device_id": body.device_id,
            "range_start": body.range_start.isoformat(),
            "range_end": body.range_end.isoformat(),
            "row_count": len(body.rows),
            "request_count": body.request_count,
            "total_tokens": normalized_total_tokens,
        },
        request=request,
    )
    return CCSwitchUsageSyncResponse(
        status=body.status,
        employee_id=employee_id,
        employee_name=employee_name,
        device_id=body.device_id,
        trigger=body.trigger,
        request_id=body.request_id,
        range_start=body.range_start,
        range_end=body.range_end,
        row_count=len(body.rows),
        request_count=body.request_count,
        total_tokens=normalized_total_tokens,
        attempted_at=body.attempted_at,
        synced_at=getattr(status_row, "synced_at", None),
        error_message=body.error_message,
    )


@device_router.post(
    "/ai-usage/shared-sessions/device-activate",
    response_model=SharedSessionResponse,
)
def device_activate_shared_session(
    request: Request,
    body: SharedSessionDeviceActivateRequest,
    orm: Session = Depends(get_orm_session),
) -> SharedSessionResponse:
    claims = _device_claims(request)
    row = _get_shared_session(orm, session_id=body.session_id)
    _verify_shared_device_session(
        row,
        activation_token=body.activation_token,
        device_id=body.device_id,
        claims=claims,
    )
    if row.status != "starting":
        raise HTTPException(status_code=409, detail="shared session is not waiting for activation")
    try:
        updated = orm.execute(
            text("""
                UPDATE public.cc_switch_attribution_sessions
                SET device_id = :device_id, started_at = :started_at,
                    start_watermark = :start_watermark,
                    status = 'active', updated_at = now()
                WHERE id = :session_id
                RETURNING id, project_id, target_user_id,
                          target_employee_id, target_employee_name,
                          device_id, stop_mode, stop_reason, status,
                          activation_token_hash, activation_expires_at,
                          requested_at, started_at, scheduled_stop_at,
                          actual_stop_at, request_count, total_tokens,
                          finalized_at, error_message
            """),
            {
                "session_id": str(body.session_id),
                "device_id": body.device_id,
                "started_at": body.started_at,
                "start_watermark": body.start_watermark,
            },
        ).first()
        orm.commit()
    except Exception as error:
        try:
            orm.rollback()
        except Exception:
            pass
        if "uq_cc_switch_attribution_active_device" in str(error):
            try:
                orm.execute(
                    text("""
                        UPDATE public.cc_switch_attribution_sessions
                        SET status = 'cancelled',
                            error_message = 'this shared device already has an active session',
                            updated_at = now()
                        WHERE id = :session_id AND status = 'starting'
                    """),
                    {"session_id": str(body.session_id)},
                )
                orm.commit()
            except Exception:
                try:
                    orm.rollback()
                except Exception:
                    pass
            raise HTTPException(status_code=409, detail="this shared device already has an active session") from error
        raise
    return _shared_session_response(updated)


@device_router.post(
    "/ai-usage/shared-sessions/device-command",
    response_model=SharedSessionDeviceCommandResponse,
)
def device_shared_session_command(
    request: Request,
    body: SharedSessionDeviceCommandRequest,
    orm: Session = Depends(get_orm_session),
) -> SharedSessionDeviceCommandResponse:
    claims = _device_claims(request)
    row = _get_shared_session(orm, session_id=body.session_id)
    _verify_shared_device_session(
        row,
        activation_token=body.activation_token,
        device_id=body.device_id,
        claims=claims,
    )
    if row.status == "active" and body.checked_at >= row.scheduled_stop_at:
        reason = "safety_timeout" if row.stop_mode == "manual_only" else "scheduled"
        stop_at = row.scheduled_stop_at
        orm.execute(
            text("""
                UPDATE public.cc_switch_attribution_sessions
                SET status = 'finalizing', stop_reason = :stop_reason,
                    actual_stop_at = :stop_at, updated_at = now()
                WHERE id = :session_id AND status = 'active'
            """),
            {"session_id": str(row.id), "stop_reason": reason, "stop_at": stop_at},
        )
        orm.commit()
        return SharedSessionDeviceCommandResponse(
            action="stop",
            scheduled_stop_at=row.scheduled_stop_at,
            stop_at=stop_at,
            stop_reason=reason,
        )
    if row.status in {"finalizing", "pending_sync"}:
        return SharedSessionDeviceCommandResponse(
            action="stop",
            scheduled_stop_at=row.scheduled_stop_at,
            stop_at=row.actual_stop_at or row.scheduled_stop_at,
            stop_reason=row.stop_reason or "manual",
        )
    if row.status != "active":
        raise HTTPException(status_code=409, detail="shared session is not active")
    return SharedSessionDeviceCommandResponse(
        action="continue",
        scheduled_stop_at=row.scheduled_stop_at,
    )


@device_router.post(
    "/ai-usage/shared-sessions/device-finalize",
    response_model=SharedSessionResponse,
)
def device_finalize_shared_session(
    request: Request,
    body: SharedSessionDeviceFinalizeRequest,
    orm: Session = Depends(get_orm_session),
) -> SharedSessionResponse:
    claims = _device_claims(request)
    row = _get_shared_session(orm, session_id=body.session_id)
    _verify_shared_device_session(
        row,
        activation_token=body.activation_token,
        device_id=body.device_id,
        claims=claims,
    )
    if row.status == "finalized":
        return _shared_session_response(row)
    if row.status not in {"active", "finalizing", "pending_sync"}:
        raise HTTPException(status_code=409, detail="shared session cannot be finalized")
    stopped_at = row.actual_stop_at or body.stopped_at
    if row.started_at is None or stopped_at <= row.started_at:
        raise HTTPException(status_code=422, detail="shared session time range is invalid")
    if any(
        request_row.requested_at < row.started_at
        or request_row.requested_at > stopped_at
        for request_row in body.requests
    ):
        raise HTTPException(status_code=422, detail="shared request falls outside the session")
    totals = {
        "request_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
    }
    try:
        for request_row in body.requests:
            total_tokens = cc_switch_total_tokens(
                app_type=request_row.app_type.lower(),
                input_tokens=request_row.input_tokens,
                output_tokens=request_row.output_tokens,
                cache_read_tokens=request_row.cache_read_tokens,
                cache_creation_tokens=request_row.cache_creation_tokens,
                input_token_semantics=request_row.input_token_semantics,
            )
            inserted = orm.execute(
                text("""
                    INSERT INTO public.cc_switch_attributed_requests (
                        session_id, project_id, target_user_id,
                        target_employee_id, target_employee_name,
                        device_id, request_id, requested_at, usage_date,
                        app_type, provider_id, model, request_model,
                        pricing_model, status_code,
                        input_tokens, output_tokens,
                        cache_read_tokens, cache_creation_tokens,
                        total_tokens, total_cost_usd, input_token_semantics
                    ) VALUES (
                        :session_id, :project_id, :target_user_id,
                        :target_employee_id, :target_employee_name,
                        :device_id, :request_id, :requested_at,
                        (:requested_at AT TIME ZONE 'Asia/Shanghai')::date,
                        :app_type, :provider_id, :model, :request_model,
                        :pricing_model, :status_code,
                        :input_tokens, :output_tokens,
                        :cache_read_tokens, :cache_creation_tokens,
                        :total_tokens, :total_cost_usd, :input_token_semantics
                    )
                    ON CONFLICT (device_id, request_id) DO NOTHING
                    RETURNING total_tokens
                """),
                {
                    "session_id": str(row.id),
                    "project_id": str(row.project_id),
                    "target_user_id": str(row.target_user_id),
                    "target_employee_id": row.target_employee_id,
                    "target_employee_name": row.target_employee_name,
                    "device_id": body.device_id,
                    "request_id": request_row.request_id,
                    "requested_at": request_row.requested_at,
                    "app_type": request_row.app_type.lower(),
                    "provider_id": request_row.provider_id,
                    "model": request_row.model,
                    "request_model": request_row.request_model,
                    "pricing_model": request_row.pricing_model,
                    "status_code": request_row.status_code,
                    "input_tokens": request_row.input_tokens,
                    "output_tokens": request_row.output_tokens,
                    "cache_read_tokens": request_row.cache_read_tokens,
                    "cache_creation_tokens": request_row.cache_creation_tokens,
                    "total_tokens": total_tokens,
                    "total_cost_usd": request_row.total_cost_usd,
                    "input_token_semantics": request_row.input_token_semantics,
                },
            ).first()
            if inserted is None:
                continue
            totals["request_count"] += 1
            totals["input_tokens"] += request_row.input_tokens
            totals["output_tokens"] += request_row.output_tokens
            totals["cache_read_tokens"] += request_row.cache_read_tokens
            totals["cache_creation_tokens"] += request_row.cache_creation_tokens
            totals["total_tokens"] += total_tokens
            totals["total_cost_usd"] += request_row.total_cost_usd
        aggregate = orm.execute(
            text("""
                SELECT count(*)::bigint AS request_count,
                       COALESCE(sum(input_tokens), 0)::bigint AS input_tokens,
                       COALESCE(sum(output_tokens), 0)::bigint AS output_tokens,
                       COALESCE(sum(cache_read_tokens), 0)::bigint AS cache_read_tokens,
                       COALESCE(sum(cache_creation_tokens), 0)::bigint AS cache_creation_tokens,
                       COALESCE(sum(total_tokens), 0)::bigint AS total_tokens,
                       COALESCE(sum(total_cost_usd), 0)::double precision AS total_cost_usd
                FROM public.cc_switch_attributed_requests
                WHERE session_id = :session_id
            """),
            {"session_id": str(row.id)},
        ).first()
        totals = {
            "request_count": int(aggregate.request_count or 0),
            "input_tokens": int(aggregate.input_tokens or 0),
            "output_tokens": int(aggregate.output_tokens or 0),
            "cache_read_tokens": int(aggregate.cache_read_tokens or 0),
            "cache_creation_tokens": int(aggregate.cache_creation_tokens or 0),
            "total_tokens": int(aggregate.total_tokens or 0),
            "total_cost_usd": float(aggregate.total_cost_usd or 0),
        }
        finalized_at = datetime.now(timezone.utc)
        updated = orm.execute(
            text("""
                UPDATE public.cc_switch_attribution_sessions
                SET status = 'finalized', stop_reason = :stop_reason,
                    actual_stop_at = :stopped_at,
                    request_count = :request_count,
                    input_tokens = :input_tokens,
                    output_tokens = :output_tokens,
                    cache_read_tokens = :cache_read_tokens,
                    cache_creation_tokens = :cache_creation_tokens,
                    total_tokens = :total_tokens,
                    total_cost_usd = :total_cost_usd,
                    finalized_at = :finalized_at,
                    error_message = NULL, updated_at = now()
                WHERE id = :session_id
                RETURNING id, project_id, target_user_id,
                          target_employee_id, target_employee_name,
                          device_id, stop_mode, stop_reason, status,
                          activation_token_hash, activation_expires_at,
                          requested_at, started_at, scheduled_stop_at,
                          actual_stop_at, request_count, total_tokens,
                          finalized_at, error_message
            """),
            {
                "session_id": str(row.id),
                "stop_reason": body.stop_reason,
                "stopped_at": stopped_at,
                **totals,
                "finalized_at": finalized_at,
            },
        ).first()
        orm.commit()
    except Exception as error:
        try:
            orm.rollback()
            orm.execute(
                text("""
                    UPDATE public.cc_switch_attribution_sessions
                    SET status = 'pending_sync', error_message = :error_message,
                        updated_at = now()
                    WHERE id = :session_id
                """),
                {"session_id": str(row.id), "error_message": str(error)[:1000]},
            )
            orm.commit()
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="shared session finalization unavailable") from error
    _shared_session_audit(
        orm,
        request,
        user_id=uuid.UUID(str(row.target_user_id)),
        action="ai_shared_session_finalize",
        row=updated,
        metadata={"request_count": totals["request_count"], "total_tokens": totals["total_tokens"]},
    )
    return _shared_session_response(updated)


@router.get(
    "/ai-usage/cc-switch-sync/status",
    response_model=CCSwitchUsageSyncStatusResponse,
)
def get_cc_switch_usage_sync_status(
    request: Request,
    request_id: uuid.UUID | None = Query(None),
    orm: Session = Depends(get_orm_session),
) -> CCSwitchUsageSyncStatusResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    employee = _current_employee(orm, user_id)
    condition = "AND request_id = :request_id" if request_id else ""
    params: dict[str, Any] = {"user_id": str(user_id)}
    if request_id:
        params["request_id"] = str(request_id)
    row = orm.execute(
        text(f"""
            SELECT
                device_id, trigger, request_id, range_start, range_end,
                status, cc_switch_running, row_count, request_count,
                total_tokens, attempted_at, last_success_at, error_message
            FROM public.cc_switch_usage_sync_status
            WHERE user_id = :user_id
              {condition}
            ORDER BY attempted_at DESC
            LIMIT 1
        """),
        params,
    ).first()
    if row is None:
        return CCSwitchUsageSyncStatusResponse(
            status="never",
            employee_id=employee.id,
            employee_name=employee.name,
            request_id=request_id,
        )
    return CCSwitchUsageSyncStatusResponse(
        status=row.status,
        employee_id=employee.id,
        employee_name=employee.name,
        device_id=row.device_id,
        trigger=row.trigger,
        request_id=row.request_id,
        range_start=row.range_start,
        range_end=row.range_end,
        row_count=int(row.row_count or 0),
        request_count=int(row.request_count or 0),
        total_tokens=int(row.total_tokens or 0),
        attempted_at=row.attempted_at,
        synced_at=row.last_success_at,
        cc_switch_running=row.cc_switch_running,
        error_message=row.error_message,
    )


@router.get("/ai-usage/options", response_model=UsageOptionsResponse)
def get_ai_usage_options(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> UsageOptionsResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return _usage_options(orm, user_id)


@router.get("/ai-usage/leaderboard", response_model=UsageLeaderboardResponse)
def get_ai_usage_leaderboard(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    orm: Session = Depends(get_orm_session),
) -> UsageLeaderboardResponse:
    try:
        validate_date_range(start_date, end_date)
    except UsageAccessError as error:
        _raise_access(error)
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    result = _build_ai_usage_leaderboard(
        orm,
        start_date=start_date,
        end_date=end_date,
    )
    _audit(
        orm,
        request,
        user_id=user_id,
        action="ai_usage_view",
        employee_id="leaderboard",
        projects=[],
        start_date=start_date,
        end_date=end_date,
        result_status="ok" if result.total_tokens else "no_data",
    )
    return result


@router.get("/ai-usage/records", response_model=UsageQueryResponse)
def get_ai_usage_records(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    department_id: str | None = Query(None, pattern="^(research|marketing|business)$"),
    project_id: uuid.UUID | None = Query(None),
    employee_id: str | None = Query(None, min_length=1, max_length=200),
    source: AIUsageSource | None = Query(None),
    include_messages: bool = Query(True),
    limit: int = Query(100, ge=1, le=200),
    orm: Session = Depends(get_orm_session),
    clickhouse=Depends(get_clickhouse),
) -> UsageQueryResponse:
    try:
        validate_date_range(start_date, end_date)
    except UsageAccessError as error:
        _raise_access(error)
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    mode, employee, projects = _resolve_scope(
        orm,
        user_id=user_id,
        department_id=department_id,
        project_id=project_id,
        requested_employee_id=employee_id,
    )
    options = _usage_options(orm, user_id)
    detail_visible = _can_view_detailed_records(mode, options.current_employee, employee)
    summary, records, has_more, warnings = _collect_usage(
        orm,
        clickhouse,
        employee=employee,
        start_date=start_date,
        end_date=end_date,
        source=source,
        record_limit=limit,
        include_messages=include_messages and detail_visible,
    )
    if not detail_visible:
        records = []
        has_more = False
        if mode == "admin":
            warnings.append("该成员未向管理员公开详细 AI 工作记录；当前仅显示 Token 统计。")
        else:
            warnings.append("当前仅显示 Token 统计；其他成员的具体对话和 AI 工作日志仅本人及管理员可见。")
    _audit(
        orm,
        request,
        user_id=user_id,
        action="ai_usage_view",
        employee_id=employee.id,
        projects=projects,
        start_date=start_date,
        end_date=end_date,
        result_status="ok" if summary.record_count else "no_data",
    )
    return UsageQueryResponse(
        mode=mode,
        employee=employee,
        projects=projects,
        summary=_summary_response(summary),
        records=[_record_response(item) for item in records],
        has_more=has_more,
        warnings=warnings,
        detail_visible=detail_visible,
    )


@router.get("/ai-usage/daily-logs", response_model=DailyWorkLogListResponse)
def get_ai_daily_work_logs(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    employee_id: str | None = Query(None, min_length=1, max_length=200),
    orm: Session = Depends(get_orm_session),
) -> DailyWorkLogListResponse:
    try:
        validate_date_range(start_date, end_date)
    except UsageAccessError as error:
        _raise_access(error)
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    _, employee, projects = _resolve_daily_log_scope(
        orm,
        user_id=user_id,
        requested_employee_id=employee_id,
    )
    rows = orm.execute(
        text("""
            SELECT id, work_date, employee_id, employee_name,
                   report_markdown, work_items, source_count, model, generated_at
            FROM public.ai_daily_work_logs
            WHERE employee_id = :employee_id
              AND work_date >= :start_date
              AND work_date <= :end_date
              AND status = 'ready'
            ORDER BY work_date DESC
        """),
        {
            "employee_id": employee.id,
            "start_date": start_date,
            "end_date": end_date,
        },
    ).all()
    items = []
    for row in rows:
        work_items = row.work_items
        if isinstance(work_items, str):
            work_items = json.loads(work_items)
        items.append(
            DailyWorkLogResponse(
                id=row.id,
                work_date=row.work_date,
                employee_id=row.employee_id,
                employee_name=employee.name,
                report_markdown=row.report_markdown,
                work_items=work_items or [],
                source_count=row.source_count,
                model=row.model,
                generated_at=row.generated_at,
            )
        )
    _audit(
        orm,
        request,
        user_id=user_id,
        action="ai_usage_view",
        employee_id=employee.id,
        projects=projects,
        start_date=start_date,
        end_date=end_date,
        result_status="ok" if items else "no_data",
    )
    return DailyWorkLogListResponse(employee=employee, items=items)


def _high_frequency_periods(summary: UsageSummary) -> list[str]:
    populated = [
        item
        for item in summary.hourly_usage
        if item.record_count or item.total_tokens
    ]
    populated.sort(key=lambda item: (-item.total_tokens, -item.record_count, item.hour))
    return [
        f"{item.hour:02d}:00-{(item.hour + 1) % 24:02d}:00"
        for item in populated[:3]
    ]


@router.post("/ai-usage/report", response_model=UsageReportResponse)
def create_ai_usage_report(
    request: Request,
    body: UsageReportRequest,
    orm: Session = Depends(get_orm_session),
    clickhouse=Depends(get_clickhouse),
) -> UsageReportResponse:
    try:
        validate_date_range(body.start_date, body.end_date)
    except UsageAccessError as error:
        _raise_access(error)
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if not _is_org_admin(orm, user_id):
        raise HTTPException(status_code=403, detail="only administrators can generate AI usage reports")

    mode, employee, projects = _resolve_scope(
        orm,
        user_id=user_id,
        department_id=None,
        project_id=None,
        requested_employee_id=body.employee_id,
    )
    if mode != "admin":
        raise HTTPException(status_code=403, detail="only administrators can generate AI usage reports")
    options = _usage_options(orm, user_id)
    if not _can_view_detailed_records(mode, options.current_employee, employee):
        raise HTTPException(status_code=403, detail="member has not shared detailed AI records with administrators")
    summary, records, _, _ = _collect_usage(
        orm,
        clickhouse,
        employee=employee,
        start_date=body.start_date,
        end_date=body.end_date,
        source=body.source,
        record_limit=100,
        include_messages=True,
    )
    if summary.record_count == 0:
        raise HTTPException(status_code=422, detail="no AI usage records in the selected period")
    prompt = build_report_prompt(
        employee_name=employee.name,
        scope_name="全部 AI 使用记录",
        summary=summary,
        records=records,
    )
    try:
        report_text = generate_usage_report(prompt)
    except Exception as error:
        logger.exception("AI usage report generation failed")
        _audit(
            orm,
            request,
            user_id=user_id,
            action="ai_usage_report",
            employee_id=employee.id,
            projects=projects,
            start_date=body.start_date,
            end_date=body.end_date,
            result_status="service_error",
        )
        raise HTTPException(status_code=503, detail="AI usage report model is unavailable") from error

    _audit(
        orm,
        request,
        user_id=user_id,
        action="ai_usage_report",
        employee_id=employee.id,
        projects=projects,
        start_date=body.start_date,
        end_date=body.end_date,
        result_status="ok",
    )
    import os

    return UsageReportResponse(
        employee=employee,
        summary=_summary_response(summary),
        high_frequency_periods=_high_frequency_periods(summary),
        report=report_text,
        model=os.getenv("AI_USAGE_REPORT_MODEL", os.getenv("RAG_LLM_MODEL", "MiniMax-M3")),
        generated_at=datetime.now(timezone.utc),
    )
