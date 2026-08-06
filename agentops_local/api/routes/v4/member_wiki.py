from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.member_wiki.access import (
    MemberAccessContext,
    MemberIdentity,
    MemberWikiAccessError,
    load_member_access_context,
    resolve_member_scope,
)
from agentops.member_wiki.query import (
    MemberExperienceHit,
    get_member_experience,
    search_member_experiences,
)
from agentops.rag.audit import record_audit
from agentops.rag.authz import AuthzError, current_user_id


router = APIRouter(tags=["member-wiki"], route_class=AuthenticatedRoute)


class MemberWikiMemberResponse(BaseModel):
    user_id: str
    employee_id: str
    name: str
    email: str


class MemberWikiOptionsResponse(BaseModel):
    mode: Literal["self", "admin"]
    current_member: MemberWikiMemberResponse
    members: list[MemberWikiMemberResponse]


class MemberWikiExperienceResponse(BaseModel):
    id: uuid.UUID
    employee_id: str
    employee_name: str
    experience_key: str
    title: str
    task_type: str
    outcome: str
    summary: str
    markdown_content: str
    tags: list[str]
    tools: list[str]
    confidence: float
    first_observed: date
    last_observed: date
    observation_count: int
    current_version: int
    updated_at: datetime
    lexical_score: float = 0
    vector_score: float | None = None


class MemberWikiSummaryResponse(BaseModel):
    experience_count: int
    success_count: int
    failure_count: int
    latest_observed: date | None


class MemberWikiRunResponse(BaseModel):
    id: uuid.UUID
    status: str
    cutoff_at: datetime
    updated_member_count: int
    session_count: int
    experience_count: int
    completed_at: datetime | None


class MemberWikiOverviewResponse(BaseModel):
    mode: Literal["self", "admin"]
    member: MemberWikiMemberResponse
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    summary: MemberWikiSummaryResponse
    experiences: list[MemberWikiExperienceResponse]
    latest_run: MemberWikiRunResponse | None


def _member_response(value: MemberIdentity) -> MemberWikiMemberResponse:
    return MemberWikiMemberResponse(
        user_id=value.user_id,
        employee_id=value.employee_id,
        name=value.name,
        email=value.email,
    )


def _hit_response(
    value: MemberExperienceHit,
    *,
    employee_name: str | None = None,
) -> MemberWikiExperienceResponse:
    return MemberWikiExperienceResponse(
        id=value.id,
        employee_id=value.employee_id,
        employee_name=employee_name or value.employee_name,
        experience_key=value.experience_key,
        title=value.title,
        task_type=value.task_type,
        outcome=value.outcome,
        summary=value.summary,
        markdown_content=value.markdown_content,
        tags=value.tags,
        tools=value.tools,
        confidence=value.confidence,
        first_observed=value.first_observed,
        last_observed=value.last_observed,
        observation_count=value.observation_count,
        current_version=value.current_version,
        updated_at=value.updated_at,
        lexical_score=value.lexical_score,
        vector_score=value.vector_score,
    )


def _current_user(request: Request) -> uuid.UUID:
    try:
        return current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _raise_access(error: MemberWikiAccessError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _latest_run(orm: Session) -> MemberWikiRunResponse | None:
    row = orm.execute(
        text("""
            SELECT id::text, status, cutoff_at, updated_member_count,
                   session_count, experience_count, completed_at
            FROM public.member_wiki_runs
            WHERE status = 'completed'
            ORDER BY completed_at DESC NULLS LAST, started_at DESC
            LIMIT 1
        """),
    ).first()
    if row is None:
        return None
    return MemberWikiRunResponse(
        id=uuid.UUID(str(row.id)),
        status=str(row.status),
        cutoff_at=row.cutoff_at,
        updated_member_count=int(row.updated_member_count),
        session_count=int(row.session_count),
        experience_count=int(row.experience_count),
        completed_at=row.completed_at,
    )


@router.get("/member-wiki/options", response_model=MemberWikiOptionsResponse)
def get_member_wiki_options(
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> MemberWikiOptionsResponse:
    context = load_member_access_context(orm, user_id=_current_user(request))
    return MemberWikiOptionsResponse(
        mode="admin" if context.is_admin else "self",
        current_member=_member_response(context.current),
        members=[_member_response(item) for item in context.accessible_members],
    )


@router.get("/member-wiki/overview", response_model=MemberWikiOverviewResponse)
def get_member_wiki_overview(
    request: Request,
    employee_id: str | None = Query(None, min_length=1, max_length=200),
    query: str = Query("", max_length=500),
    task_type: str | None = Query(None, max_length=40),
    outcome: str | None = Query(None, pattern="^(success|partial|failure)$"),
    tag: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=100),
    orm: Session = Depends(get_orm_session),
) -> MemberWikiOverviewResponse:
    user_id = _current_user(request)
    context = load_member_access_context(orm, user_id=user_id)
    try:
        member = resolve_member_scope(
            is_admin=context.is_admin,
            current=context.current,
            accessible_members=context.accessible_members,
            requested_member=employee_id,
        )
    except MemberWikiAccessError as error:
        _raise_access(error)
    hits = search_member_experiences(
        orm,
        employee_ids=[member.employee_id],
        query=query,
        tags=[tag] if tag else None,
        outcome=outcome,
        task_type=task_type,
        limit=limit,
        query_embedding=None,
    )
    success_count = sum(item.outcome == "success" for item in hits)
    failure_count = sum(item.outcome == "failure" for item in hits)
    latest_observed = max((item.last_observed for item in hits), default=None)
    record_audit(
        orm,
        user_id=user_id,
        action="member_wiki_view",
        resource_type="member_wiki",
        resource_id=member.employee_id,
        metadata={
            "result_count": len(hits),
            "has_query": bool(query.strip()),
            "mode": "admin" if context.is_admin else "self",
        },
        request=request,
    )
    return MemberWikiOverviewResponse(
        mode="admin" if context.is_admin else "self",
        member=_member_response(member),
        summary=MemberWikiSummaryResponse(
            experience_count=len(hits),
            success_count=success_count,
            failure_count=failure_count,
            latest_observed=latest_observed,
        ),
        experiences=[_hit_response(item, employee_name=member.name) for item in hits],
        latest_run=_latest_run(orm),
    )


@router.get(
    "/member-wiki/experiences/{experience_id}",
    response_model=MemberWikiExperienceResponse,
)
def read_member_wiki_experience(
    experience_id: uuid.UUID,
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> MemberWikiExperienceResponse:
    user_id = _current_user(request)
    context = load_member_access_context(orm, user_id=user_id)
    employee_ids = [
        item.employee_id for item in context.accessible_members
    ] if context.is_admin else [context.current.employee_id]
    item = get_member_experience(
        orm,
        experience_id=experience_id,
        employee_ids=employee_ids,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="member Wiki experience not found")
    record_audit(
        orm,
        user_id=user_id,
        action="member_wiki_view",
        resource_type="member_wiki_experience",
        resource_id=str(experience_id),
        metadata={"employee_id": item.employee_id},
        request=request,
    )
    return _hit_response(item)
