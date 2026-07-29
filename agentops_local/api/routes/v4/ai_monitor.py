from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.rag.audit import record_audit
from agentops.rag.authz import AuthzError, current_user_id, require_member
from agentops.workday.identity import derive_employee_identity


router = APIRouter(route_class=AuthenticatedRoute)
logger = logging.getLogger(__name__)

ComponentName = Literal[
    "cc_switch",
    "chatgpt_web_extension",
    "browser_shortcut",
    "chatgpt_desktop",
]
ComponentStatus = Literal[
    "installed",
    "missing",
    "unknown",
    "unsupported",
    "error",
]

EXPECTED_COMPONENTS: tuple[ComponentName, ...] = (
    "cc_switch",
    "chatgpt_web_extension",
    "browser_shortcut",
    "chatgpt_desktop",
)


class AIMonitorComponentReport(BaseModel):
    name: ComponentName
    status: ComponentStatus
    version: str | None = Field(None, max_length=100)
    last_seen_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AIMonitorDeviceRegisterRequest(BaseModel):
    project_id: uuid.UUID
    device_id: str = Field(..., min_length=3, max_length=200)
    device_name: str | None = Field(None, max_length=200)
    installer_version: str | None = Field(None, max_length=100)
    os: str | None = Field(None, max_length=500)
    components: list[AIMonitorComponentReport] = Field(default_factory=list, max_length=20)


class AIMonitorDeviceRegisterResponse(BaseModel):
    project_id: uuid.UUID
    employee_id: str
    employee_name: str
    device_id: str
    components: dict[str, AIMonitorComponentReport]
    last_seen_at: datetime


class AIMonitorDeviceStatus(BaseModel):
    device_id: str
    device_name: str | None
    employee_id: str
    employee_name: str
    installer_version: str | None
    os: str | None
    components: dict[str, AIMonitorComponentReport]
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class AIMonitorStatusResponse(BaseModel):
    project_id: uuid.UUID | None = None
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    employee_id: str
    employee_name: str | None = None
    summary: dict[str, ComponentStatus]
    devices: list[AIMonitorDeviceStatus]


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


def _resolve_employee(orm: Session, user_id: uuid.UUID) -> tuple[str, str]:
    profile = _profile_for_user(orm, user_id)
    if profile is None or not profile.email:
        raise HTTPException(status_code=404, detail="user profile not found")
    return derive_employee_identity(
        user_id=user_id,
        email=profile.email,
        full_name=profile.full_name,
    )


def _component_map(
    components: list[AIMonitorComponentReport],
    *,
    seen_at: datetime,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for component in components:
        item = component.model_dump(mode="json")
        item["last_seen_at"] = (
            component.last_seen_at or seen_at
        ).isoformat()
        result[component.name] = item
    return result


def _normalize_components(value: Any) -> dict[str, AIMonitorComponentReport]:
    if value is None:
        raw: dict[str, Any] = {}
    elif isinstance(value, str):
        raw = json.loads(value)
    else:
        raw = dict(value)
    return {
        name: AIMonitorComponentReport.model_validate(payload)
        for name, payload in raw.items()
    }


def _status_summary(devices: list[AIMonitorDeviceStatus]) -> dict[str, ComponentStatus]:
    summary: dict[str, ComponentStatus] = {
        component: "missing" for component in EXPECTED_COMPONENTS
    }
    rank = {
        "missing": 0,
        "unknown": 1,
        "unsupported": 2,
        "error": 3,
        "installed": 4,
    }
    for device in devices:
        for name, component in device.components.items():
            if name not in summary:
                continue
            if rank[component.status] >= rank[summary[name]]:
                summary[name] = component.status
    return summary


def _record_monitor_audit(
    orm: Session,
    request: Request,
    *,
    user_id: uuid.UUID,
    action: str,
    project_id: uuid.UUID | None = None,
    result_status: str,
    employee_id: str | None = None,
    device_id: str | None = None,
) -> None:
    metadata: dict[str, Any] = {"result_status": result_status}
    if project_id:
        metadata["project_id"] = str(project_id)
    if employee_id:
        metadata["employee_id"] = employee_id
    if device_id:
        metadata["device_id"] = device_id
    record_audit(
        orm,
        user_id=user_id,
        action=action,
        resource_type="project" if project_id else "ai_monitor",
        resource_id=str(project_id) if project_id else employee_id,
        metadata=metadata,
        request=request,
    )


@router.post(
    "/ai-monitor/devices/register",
    response_model=AIMonitorDeviceRegisterResponse,
)
def register_ai_monitor_device(
    request: Request,
    body: AIMonitorDeviceRegisterRequest,
    orm: Session = Depends(get_orm_session),
) -> AIMonitorDeviceRegisterResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    try:
        require_member(orm, user_id=user_id, project_id=body.project_id)
    except AuthzError as error:
        _record_monitor_audit(
            orm,
            request,
            user_id=user_id,
            action="ai_monitor_device_register",
            project_id=body.project_id,
            result_status="forbidden",
            device_id=body.device_id,
        )
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    employee_id, employee_name = _resolve_employee(orm, user_id)
    seen_at = datetime.now(timezone.utc)
    components = _component_map(body.components, seen_at=seen_at)
    try:
        orm.execute(
            text("""
                INSERT INTO public.ai_monitor_devices (
                    project_id, user_id, employee_id, employee_name,
                    device_id, device_name, installer_version, os,
                    components, last_seen_at
                )
                VALUES (
                    :project_id, :user_id, :employee_id, :employee_name,
                    :device_id, :device_name, :installer_version, :os,
                    CAST(:components AS jsonb), :last_seen_at
                )
                ON CONFLICT (project_id, employee_id, device_id)
                DO UPDATE SET
                    user_id = excluded.user_id,
                    employee_name = excluded.employee_name,
                    device_name = excluded.device_name,
                    installer_version = excluded.installer_version,
                    os = excluded.os,
                    components = public.ai_monitor_devices.components || excluded.components,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = now()
            """),
            {
                "project_id": str(body.project_id),
                "user_id": str(user_id),
                "employee_id": employee_id,
                "employee_name": employee_name,
                "device_id": body.device_id,
                "device_name": body.device_name,
                "installer_version": body.installer_version,
                "os": body.os,
                "components": _json_dumps(components),
                "last_seen_at": seen_at,
            },
        )
        orm.commit()
    except Exception as error:
        logger.exception("AI Monitor device register failed")
        try:
            orm.rollback()
        except Exception:
            pass
        _record_monitor_audit(
            orm,
            request,
            user_id=user_id,
            action="ai_monitor_device_register",
            project_id=body.project_id,
            result_status="service_error",
            employee_id=employee_id,
            device_id=body.device_id,
        )
        raise HTTPException(status_code=503, detail="ai monitor device register unavailable") from error

    _record_monitor_audit(
        orm,
        request,
        user_id=user_id,
        action="ai_monitor_device_register",
        project_id=body.project_id,
        result_status="ok",
        employee_id=employee_id,
        device_id=body.device_id,
    )
    return AIMonitorDeviceRegisterResponse(
        project_id=body.project_id,
        employee_id=employee_id,
        employee_name=employee_name,
        device_id=body.device_id,
        components=_normalize_components(components),
        last_seen_at=seen_at,
    )


def _row_to_device(row) -> AIMonitorDeviceStatus:
    return AIMonitorDeviceStatus(
        device_id=row.device_id,
        device_name=row.device_name,
        employee_id=row.employee_id,
        employee_name=row.employee_name,
        installer_version=row.installer_version,
        os=row.os,
        components=_normalize_components(row.components),
        last_seen_at=row.last_seen_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _visible_project_ids(orm: Session, *, user_id: uuid.UUID) -> list[uuid.UUID]:
    rows = orm.execute(
        text("""
            SELECT project_id::text AS project_id
            FROM public.project_members
            WHERE user_id = :user_id
            ORDER BY project_id
        """),
        {"user_id": str(user_id)},
    ).all()
    return [uuid.UUID(row.project_id) for row in rows]


@router.get(
    "/ai-monitor/status",
    response_model=AIMonitorStatusResponse,
)
def get_ai_monitor_overall_status(
    request: Request,
    employee_id: str | None = Query(None, min_length=1, max_length=200),
    orm: Session = Depends(get_orm_session),
) -> AIMonitorStatusResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    project_ids = _visible_project_ids(orm, user_id=user_id)
    resolved_employee_id = employee_id
    employee_name = None
    if not resolved_employee_id:
        resolved_employee_id, employee_name = _resolve_employee(orm, user_id)

    devices: list[AIMonitorDeviceStatus] = []
    if project_ids:
        rows = orm.execute(
            text("""
                SELECT
                    device_id,
                    device_name,
                    employee_id,
                    employee_name,
                    installer_version,
                    os,
                    components,
                    max(last_seen_at) AS last_seen_at,
                    min(created_at) AS created_at,
                    max(updated_at) AS updated_at
                FROM public.ai_monitor_devices
                WHERE project_id = ANY(CAST(:project_ids AS uuid[]))
                  AND employee_id = :employee_id
                GROUP BY
                    device_id,
                    device_name,
                    employee_id,
                    employee_name,
                    installer_version,
                    os,
                    components
                ORDER BY max(last_seen_at) DESC, max(updated_at) DESC
            """),
            {
                "project_ids": [str(project_id) for project_id in project_ids],
                "employee_id": resolved_employee_id,
            },
        ).all()
        devices = [_row_to_device(row) for row in rows]
    if employee_name is None and devices:
        employee_name = devices[0].employee_name

    _record_monitor_audit(
        orm,
        request,
        user_id=user_id,
        action="ai_monitor_status",
        result_status="ok",
        employee_id=resolved_employee_id,
    )
    return AIMonitorStatusResponse(
        project_id=None,
        project_ids=project_ids,
        employee_id=resolved_employee_id,
        employee_name=employee_name,
        summary=_status_summary(devices),
        devices=devices,
    )


@router.get(
    "/ai-monitor/status/{project_id}",
    response_model=AIMonitorStatusResponse,
)
def get_ai_monitor_status(
    request: Request,
    project_id: uuid.UUID,
    employee_id: str | None = Query(None, min_length=1, max_length=200),
    orm: Session = Depends(get_orm_session),
) -> AIMonitorStatusResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    try:
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        _record_monitor_audit(
            orm,
            request,
            user_id=user_id,
            action="ai_monitor_status",
            project_id=project_id,
            result_status="forbidden",
            employee_id=employee_id,
        )
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    resolved_employee_id = employee_id
    employee_name = None
    if not resolved_employee_id:
        resolved_employee_id, employee_name = _resolve_employee(orm, user_id)

    rows = orm.execute(
        text("""
            SELECT
                device_id,
                device_name,
                employee_id,
                employee_name,
                installer_version,
                os,
                components,
                last_seen_at,
                created_at,
                updated_at
            FROM public.ai_monitor_devices
            WHERE project_id = :project_id
              AND employee_id = :employee_id
            ORDER BY last_seen_at DESC, updated_at DESC
        """),
        {
            "project_id": str(project_id),
            "employee_id": resolved_employee_id,
        },
    ).all()
    devices = [_row_to_device(row) for row in rows]
    if employee_name is None and devices:
        employee_name = devices[0].employee_name
    _record_monitor_audit(
        orm,
        request,
        user_id=user_id,
        action="ai_monitor_status",
        project_id=project_id,
        result_status="ok",
        employee_id=resolved_employee_id,
    )
    return AIMonitorStatusResponse(
        project_id=project_id,
        project_ids=[project_id],
        employee_id=resolved_employee_id,
        employee_name=employee_name,
        summary=_status_summary(devices),
        devices=devices,
    )
