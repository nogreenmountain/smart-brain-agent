from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.api.db.clickhouse_client import get_clickhouse
from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.rag.audit import record_audit
from agentops.rag.authz import (
    AuthzError,
    current_user_id,
    require_member,
)
from agentops.workday.domain import aggregate_workday
from agentops.workday.identity import derive_employee_identity
from agentops.workday.presentation import build_response_payload
from agentops.workday.query import fetch_span_records
from agentops.workday.schemas import AIWorkdaySummary
from employee_telemetry.bundle import (
    build_claude_common_config,
    build_codex_common_config,
    mint_telemetry_token,
    normalize_collector_endpoint,
    secret_from_environment,
)


router = APIRouter(route_class=AuthenticatedRoute)
logger = logging.getLogger(__name__)


class WorkdayEnrollmentRequest(BaseModel):
    project_id: uuid.UUID


class WorkdayEnrollmentResponse(BaseModel):
    project_id: uuid.UUID
    employee_id: str
    employee_name: str
    collector_endpoint: str
    expires_at: datetime
    device_ingest_token: str
    claude_common_config: dict[str, dict[str, str]]
    codex_common_config: str


def _resolve_employee_for_user(
    orm: Session,
    user_id: uuid.UUID,
) -> tuple[str, str]:
    profile = orm.execute(
        text("""
            SELECT au.email, pu.full_name
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE au.id = :uid
        """),
        {"uid": str(user_id)},
    ).first()
    if profile is None or not profile.email:
        raise HTTPException(status_code=404, detail="user profile not found")
    return derive_employee_identity(
        user_id=user_id,
        email=profile.email,
        full_name=profile.full_name,
    )


def _enrollment_settings() -> tuple[str, int]:
    try:
        token_days = int(
            os.environ.get("WORKDAY_ENROLLMENT_TOKEN_DAYS", "30")
        )
    except ValueError as error:
        raise RuntimeError(
            "WORKDAY_ENROLLMENT_TOKEN_DAYS must be an integer"
        ) from error
    if not 1 <= token_days <= 90:
        raise RuntimeError(
            "WORKDAY_ENROLLMENT_TOKEN_DAYS must be between 1 and 90"
        )
    collector_endpoint = normalize_collector_endpoint(
        os.environ.get(
            "WORKDAY_COLLECTOR_ENDPOINT",
            "http://192.168.10.29:4318",
        )
    )
    return collector_endpoint, token_days


def _record_enrollment_audit(
    orm: Session,
    request: Request,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    result_status: str,
    employee_id: str | None = None,
) -> None:
    metadata: dict[str, Any] = {"result_status": result_status}
    if employee_id:
        metadata["employee_id"] = employee_id
    record_audit(
        orm,
        user_id=user_id,
        action="workday_enroll",
        resource_type="project",
        resource_id=str(project_id),
        metadata=metadata,
        request=request,
    )


@router.post(
    "/workday/enroll",
    response_model=WorkdayEnrollmentResponse,
)
def enroll_workday(
    request: Request,
    body: WorkdayEnrollmentRequest,
    orm: Session = Depends(get_orm_session),
) -> WorkdayEnrollmentResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

    employee_id, employee_name = _resolve_employee_for_user(orm, user_id)
    try:
        collector_endpoint, token_days = _enrollment_settings()
        issued_at = datetime.now(timezone.utc)
        token = mint_telemetry_token(
            secret=secret_from_environment(),
            project_id=str(body.project_id),
            employee_id=employee_id,
            employee_name=employee_name,
            expires_in_days=token_days,
            subject_user_id=str(user_id),
            issued_at=issued_at,
        )
    except (RuntimeError, ValueError) as error:
        logger.exception("Workday enrollment configuration is invalid")
        raise HTTPException(
            status_code=503,
            detail="workday enrollment is unavailable",
        ) from error

    response = WorkdayEnrollmentResponse(
        project_id=body.project_id,
        employee_id=employee_id,
        employee_name=employee_name,
        collector_endpoint=collector_endpoint,
        expires_at=issued_at + timedelta(days=token_days),
        device_ingest_token=token,
        claude_common_config=build_claude_common_config(
            employee_id=employee_id,
            employee_name=employee_name,
            collector_endpoint=collector_endpoint,
            token=token,
        ),
        codex_common_config=build_codex_common_config(
            employee_id=employee_id,
            employee_name=employee_name,
            collector_endpoint=collector_endpoint,
            token=token,
        ),
    )
    _record_enrollment_audit(
        orm,
        request,
        user_id=user_id,
        project_id=body.project_id,
        result_status="ok",
        employee_id=employee_id,
    )
    return response


def _record_workday_audit(
    orm: Session,
    request: Request,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    employee_id: str,
    work_date: date,
    include_traces: bool,
    include_replay_refs: bool,
    include_raw_metrics: bool,
    result_status: str,
) -> None:
    record_audit(
        orm,
        user_id=user_id,
        action="workday_summary",
        resource_type="project",
        resource_id=str(project_id),
        metadata={
            "employee_id": employee_id,
            "date": work_date.isoformat(),
            "include_traces": include_traces,
            "include_replay_refs": include_replay_refs,
            "include_raw_metrics": include_raw_metrics,
            "result_status": result_status,
        },
        request=request,
    )


@router.get(
    "/workday/summary/{project_id}",
    response_model=AIWorkdaySummary,
)
def get_workday_summary(
    request: Request,
    project_id: uuid.UUID,
    employee_id: str = Query(..., min_length=1, max_length=200),
    work_date: date = Query(..., alias="date"),
    include_traces: bool = Query(True),
    include_replay_refs: bool = Query(True),
    include_raw_metrics: bool = Query(True),
    orm: Session = Depends(get_orm_session),
    clickhouse=Depends(get_clickhouse),
) -> AIWorkdaySummary:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

    try:
        project_role = require_member(
            orm,
            user_id=user_id,
            project_id=project_id,
        )
    except AuthzError as error:
        _record_workday_audit(
            orm,
            request,
            user_id=user_id,
            project_id=project_id,
            employee_id=employee_id,
            work_date=work_date,
            include_traces=include_traces,
            include_replay_refs=include_replay_refs,
            include_raw_metrics=include_raw_metrics,
            result_status="forbidden",
        )
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

    if project_role.role not in {"owner", "admin"}:
        own_employee_id, _ = _resolve_employee_for_user(orm, user_id)
        if employee_id != own_employee_id:
            _record_workday_audit(
                orm,
                request,
                user_id=user_id,
                project_id=project_id,
                employee_id=employee_id,
                work_date=work_date,
                include_traces=include_traces,
                include_replay_refs=include_replay_refs,
                include_raw_metrics=include_raw_metrics,
                result_status="forbidden_employee_scope",
            )
            raise HTTPException(
                status_code=403,
                detail="regular members can only view their own AI usage records",
            )

    try:
        spans, query_warnings = fetch_span_records(
            clickhouse,
            project_id=str(project_id),
            employee_id=employee_id,
            work_date=work_date,
        )
        aggregation = aggregate_workday(
            project_id=str(project_id),
            employee_id=employee_id,
            work_date=work_date,
            spans=spans,
        )
        payload = build_response_payload(
            aggregation,
            include_traces=include_traces,
            include_replay_refs=include_replay_refs,
            include_raw_metrics=include_raw_metrics,
        )
        payload["warnings"].extend(query_warnings)
        response = AIWorkdaySummary.model_validate(payload)
    except Exception:
        logger.exception(
            "Workday summary failed for project=%s date=%s",
            project_id,
            work_date,
        )
        _record_workday_audit(
            orm,
            request,
            user_id=user_id,
            project_id=project_id,
            employee_id=employee_id,
            work_date=work_date,
            include_traces=include_traces,
            include_replay_refs=include_replay_refs,
            include_raw_metrics=include_raw_metrics,
            result_status="service_error",
        )
        raise HTTPException(
            status_code=503,
            detail="workday metrics service unavailable",
        )

    _record_workday_audit(
        orm,
        request,
        user_id=user_id,
        project_id=project_id,
        employee_id=employee_id,
        work_date=work_date,
        include_traces=include_traces,
        include_replay_refs=include_replay_refs,
        include_raw_metrics=include_raw_metrics,
        result_status=aggregation.status,
    )
    return response
