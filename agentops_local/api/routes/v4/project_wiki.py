from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.project_wiki.domain import KnowledgeCandidate
from agentops.project_wiki.service import (
    _apply_candidate,
    compile_project_wiki,
)
from agentops.rag.audit import record_audit
from agentops.rag.authz import (
    AuthzError,
    current_user_id,
    require_admin,
    require_member,
)


router = APIRouter(route_class=AuthenticatedRoute)
logger = logging.getLogger(__name__)


class CompileWikiRequest(BaseModel):
    project_id: uuid.UUID


class CompileWikiResponse(BaseModel):
    run_id: uuid.UUID
    source_count: int
    candidate_count: int
    auto_applied_count: int
    pending_review_count: int
    discarded_count: int
    model: str


class WikiSourceSchema(BaseModel):
    source_type: str
    source_id: str
    locator: str | None = None


class WikiLinkSchema(BaseModel):
    to_title: str
    relation: str


class WikiPageSchema(BaseModel):
    id: uuid.UUID
    page_key: str
    title: str
    page_type: str
    summary: str
    markdown_content: str
    usefulness: float
    confidence: float
    current_version: int
    sources: list[WikiSourceSchema]
    links: list[WikiLinkSchema]
    created_at: str
    updated_at: str


class WikiChangeSchema(BaseModel):
    id: uuid.UUID
    title: str
    page_type: str
    reason_code: str
    status: str
    summary: str
    proposed_markdown: str
    usefulness: float
    confidence: float
    contradiction: bool
    source_ids: list[str]
    link_titles: list[str]
    created_at: str


class WikiRunSchema(BaseModel):
    id: uuid.UUID
    status: str
    trigger_type: str
    model: str
    source_count: int
    candidate_count: int
    auto_applied_count: int
    pending_review_count: int
    discarded_count: int
    error_message: str | None = None
    started_at: str
    completed_at: str | None = None


class WikiSummarySchema(BaseModel):
    page_count: int
    pending_review_count: int
    source_count: int
    link_count: int


class WikiProjectSchema(BaseModel):
    id: uuid.UUID
    name: str
    department_id: str


class WikiOverviewResponse(BaseModel):
    project: WikiProjectSchema
    permissions: dict[str, bool]
    summary: WikiSummarySchema
    pages: list[WikiPageSchema]
    pending_changes: list[WikiChangeSchema]
    latest_run: WikiRunSchema | None = None


class ReviewWikiChangeRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(None, max_length=2000)


class ReviewWikiChangeResponse(BaseModel):
    id: uuid.UUID
    status: Literal["applied", "rejected"]
    page_id: uuid.UUID | None = None


def _project(orm: Session, project_id: uuid.UUID):
    row = orm.execute(
        text("""
            SELECT id::text, name, department_id
            FROM public.projects
            WHERE id = :project_id
        """),
        {"project_id": str(project_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return row


def _project_name(orm: Session, project_id: uuid.UUID) -> str:
    row = orm.execute(
        text("SELECT name FROM public.projects WHERE id = :project_id"),
        {"project_id": str(project_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return str(row.name)


def _can_review(orm: Session, *, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    try:
        require_admin(orm, user_id=user_id, project_id=project_id)
        return True
    except AuthzError:
        return False


def _page_from_row(row) -> WikiPageSchema:
    return WikiPageSchema(
        id=uuid.UUID(str(row.id)),
        page_key=str(row.page_key),
        title=str(row.title),
        page_type=str(row.page_type),
        summary=str(row.summary or ""),
        markdown_content=str(row.markdown_content),
        usefulness=float(row.usefulness),
        confidence=float(row.confidence),
        current_version=int(row.current_version),
        sources=[WikiSourceSchema.model_validate(item) for item in (row.sources or [])],
        links=[WikiLinkSchema.model_validate(item) for item in (row.links or [])],
        created_at=str(row.created_at),
        updated_at=str(row.updated_at),
    )


def _change_from_row(row) -> WikiChangeSchema:
    return WikiChangeSchema(
        id=uuid.UUID(str(row.id)),
        title=str(row.title),
        page_type=str(row.page_type),
        reason_code=str(row.reason_code),
        status=str(row.status),
        summary=str(row.summary or ""),
        proposed_markdown=str(row.proposed_markdown),
        usefulness=float(row.usefulness),
        confidence=float(row.confidence),
        contradiction=bool(row.contradiction),
        source_ids=[str(item) for item in (row.source_ids or [])],
        link_titles=[str(item) for item in (row.link_titles or [])],
        created_at=str(row.created_at),
    )


def _run_from_row(row) -> WikiRunSchema | None:
    if row is None:
        return None
    return WikiRunSchema(
        id=uuid.UUID(str(row.id)),
        status=str(row.status),
        trigger_type=str(row.trigger_type),
        model=str(row.model),
        source_count=int(row.source_count or 0),
        candidate_count=int(row.candidate_count or 0),
        auto_applied_count=int(row.auto_applied_count or 0),
        pending_review_count=int(row.pending_review_count or 0),
        discarded_count=int(row.discarded_count or 0),
        error_message=str(row.error_message) if row.error_message else None,
        started_at=str(row.started_at),
        completed_at=str(row.completed_at) if row.completed_at else None,
    )


@router.post("/project-wiki/compile", response_model=CompileWikiResponse)
def compile_wiki_now(
    request: Request,
    body: CompileWikiRequest,
    orm: Session = Depends(get_orm_session),
) -> CompileWikiResponse:
    try:
        user_id = current_user_id(request)
        require_admin(orm, user_id=user_id, project_id=body.project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    project_name = _project_name(orm, body.project_id)
    try:
        result = compile_project_wiki(
            orm,
            project_id=body.project_id,
            project_name=project_name,
            triggered_by_user_id=user_id,
        )
    except Exception as error:
        logger.exception("Manual project Wiki compile failed")
        record_audit(
            orm,
            user_id=user_id,
            action="project_wiki_compile",
            resource_type="project",
            resource_id=str(body.project_id),
            metadata={"status": "failed", "error": str(error)[:500]},
            request=request,
        )
        raise HTTPException(status_code=503, detail="project Wiki compile failed") from error

    record_audit(
        orm,
        user_id=user_id,
        action="project_wiki_compile",
        resource_type="project",
        resource_id=str(body.project_id),
        metadata={
            "status": "completed",
            "run_id": str(result.run_id),
            "source_count": result.source_count,
            "auto_applied_count": result.auto_applied_count,
            "pending_review_count": result.pending_review_count,
            "discarded_count": result.discarded_count,
        },
        request=request,
    )
    return CompileWikiResponse(**result.__dict__)


@router.get("/project-wiki/overview", response_model=WikiOverviewResponse)
def get_wiki_overview(
    request: Request,
    project_id: uuid.UUID = Query(...),
    orm: Session = Depends(get_orm_session),
) -> WikiOverviewResponse:
    try:
        user_id = current_user_id(request)
        require_member(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    project = _project(orm, project_id)
    can_review = _can_review(orm, user_id=user_id, project_id=project_id)
    pages = orm.execute(
        text("""
            SELECT
                p.id::text, p.page_key, p.title, p.page_type, p.summary,
                p.markdown_content, p.usefulness, p.confidence,
                p.current_version, p.created_at::text, p.updated_at::text,
                (
                    SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'source_type', s.source_type,
                        'source_id', s.source_id,
                        'locator', s.locator
                    ) ORDER BY s.source_type, s.source_id), '[]'::jsonb)
                    FROM public.project_wiki_page_sources s
                    WHERE s.page_id = p.id
                ) AS sources,
                (
                    SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'to_title', l.to_title,
                        'relation', l.relation
                    ) ORDER BY l.to_title), '[]'::jsonb)
                    FROM public.project_wiki_links l
                    WHERE l.from_page_id = p.id
                ) AS links
            FROM public.project_wiki_pages p
            WHERE p.project_id = :project_id AND p.status = 'active'
            ORDER BY p.updated_at DESC
        """),
        {"project_id": str(project_id)},
    ).all()
    pending_rows = []
    if can_review:
        pending_rows = orm.execute(
            text("""
                SELECT id::text, title, page_type, reason_code, status, summary,
                       proposed_markdown, usefulness, confidence, contradiction,
                       source_ids, link_titles, created_at::text
                FROM public.project_wiki_changes
                WHERE project_id = :project_id AND status = 'pending_review'
                ORDER BY created_at DESC
            """),
            {"project_id": str(project_id)},
        ).all()
    latest_run_row = orm.execute(
        text("""
            SELECT id::text, status, trigger_type, model, source_count,
                   candidate_count, auto_applied_count, pending_review_count,
                   discarded_count, error_message, started_at::text,
                   completed_at::text
            FROM public.project_wiki_compile_runs
            WHERE project_id = :project_id
            ORDER BY started_at DESC
            LIMIT 1
        """),
        {"project_id": str(project_id)},
    ).first()
    count_row = orm.execute(
        text("""
            SELECT
                (SELECT count(*) FROM public.project_wiki_pages
                 WHERE project_id = :project_id AND status = 'active')::int AS page_count,
                (SELECT count(*) FROM public.project_wiki_changes
                 WHERE project_id = :project_id AND status = 'pending_review')::int AS pending_count,
                (SELECT count(*) FROM public.project_wiki_processed_sources
                 WHERE project_id = :project_id)::int AS source_count,
                (SELECT count(*) FROM public.project_wiki_links l
                 JOIN public.project_wiki_pages p ON p.id = l.from_page_id
                 WHERE p.project_id = :project_id)::int AS link_count
        """),
        {"project_id": str(project_id)},
    ).first()
    record_audit(
        orm,
        user_id=user_id,
        action="project_wiki_view",
        resource_type="project",
        resource_id=str(project_id),
        metadata={"page_count": int(getattr(count_row, "page_count", 0) or 0)},
        request=request,
    )
    return WikiOverviewResponse(
        project=WikiProjectSchema(
            id=uuid.UUID(str(project.id)),
            name=str(project.name),
            department_id=str(project.department_id),
        ),
        permissions={"can_review": can_review, "can_compile": can_review},
        summary=WikiSummarySchema(
            page_count=int(getattr(count_row, "page_count", 0) or 0),
            pending_review_count=int(getattr(count_row, "pending_count", 0) or 0),
            source_count=int(getattr(count_row, "source_count", 0) or 0),
            link_count=int(getattr(count_row, "link_count", 0) or 0),
        ),
        pages=[_page_from_row(row) for row in pages],
        pending_changes=[_change_from_row(row) for row in pending_rows],
        latest_run=_run_from_row(latest_run_row),
    )


@router.post(
    "/project-wiki/changes/{change_id}/review",
    response_model=ReviewWikiChangeResponse,
)
def review_wiki_change(
    request: Request,
    change_id: uuid.UUID,
    body: ReviewWikiChangeRequest,
    orm: Session = Depends(get_orm_session),
) -> ReviewWikiChangeResponse:
    try:
        user_id = current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    row = orm.execute(
        text("""
            SELECT id::text, run_id::text, project_id::text, page_key, title,
                   page_type, status, summary, proposed_markdown, usefulness,
                   confidence, contradiction, source_ids, link_titles, reason_code
            FROM public.project_wiki_changes
            WHERE id = :change_id
            FOR UPDATE
        """),
        {"change_id": str(change_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project Wiki change not found")
    project_id = uuid.UUID(str(row.project_id))
    try:
        require_admin(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if row.status != "pending_review":
        raise HTTPException(status_code=409, detail=f"change already {row.status}")

    page_id = None
    if body.decision == "reject":
        orm.execute(
            text("""
                UPDATE public.project_wiki_changes
                SET status = 'rejected', reviewed_by_user_id = :user_id,
                    review_comment = :comment, reviewed_at = now()
                WHERE id = :change_id
            """),
            {
                "change_id": str(change_id),
                "user_id": str(user_id),
                "comment": body.comment,
            },
        )
        orm.commit()
        status: Literal["applied", "rejected"] = "rejected"
    else:
        candidate = KnowledgeCandidate(
            title=row.title,
            page_type=row.page_type,
            summary=row.summary,
            markdown_content=row.proposed_markdown,
            usefulness=row.usefulness,
            confidence=row.confidence,
            source_ids=list(row.source_ids or []),
            link_titles=list(row.link_titles or []),
            contradiction=bool(row.contradiction),
            sensitive=False,
            ephemeral=False,
        )
        page_id = _apply_candidate(
            orm,
            run_id=uuid.UUID(str(row.run_id)),
            project_id=project_id,
            candidate=candidate,
            created_by_user_id=user_id,
            reason_code=f"review_approved:{row.reason_code}",
            change_id=change_id,
        )
        orm.execute(
            text("""
                UPDATE public.project_wiki_changes
                SET reviewed_by_user_id = :user_id, review_comment = :comment
                WHERE id = :change_id
            """),
            {
                "change_id": str(change_id),
                "user_id": str(user_id),
                "comment": body.comment,
            },
        )
        orm.commit()
        status = "applied"

    record_audit(
        orm,
        user_id=user_id,
        action="project_wiki_review",
        resource_type="project_wiki_change",
        resource_id=str(change_id),
        metadata={
            "project_id": str(project_id),
            "decision": body.decision,
            "page_id": str(page_id) if page_id else None,
        },
        request=request,
    )
    return ReviewWikiChangeResponse(id=change_id, status=status, page_id=page_id)
