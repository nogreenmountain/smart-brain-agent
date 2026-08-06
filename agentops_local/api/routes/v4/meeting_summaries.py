from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.meeting_summaries.domain import build_meeting_markdown, normalize_list
from agentops.meeting_summaries.query import (
    MeetingSummaryHit,
    get_meeting_summary,
    search_meeting_summaries,
)
from agentops.rag.audit import record_audit
from agentops.rag.authz import AuthzError, current_user_id, require_admin


router = APIRouter(tags=["meeting-summaries"], route_class=AuthenticatedRoute)
MAX_UPLOAD_BYTES = 1024 * 1024


class MeetingSummaryResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    title: str
    meeting_date: date
    participants: list[str]
    tags: list[str]
    summary_markdown: str
    decisions: list[str]
    action_items: list[str]
    source_filename: str | None
    created_by: uuid.UUID
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    lexical_score: float = 0
    vector_score: float | None = None


class MeetingSummaryListResponse(BaseModel):
    items: list[MeetingSummaryResponse]


def _response(item: MeetingSummaryHit) -> MeetingSummaryResponse:
    return MeetingSummaryResponse(**vars(item))


def _user(request: Request) -> uuid.UUID:
    try:
        return current_user_id(request)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _authorize(check, orm: Session, *, user_id: uuid.UUID, project_id: uuid.UUID) -> None:
    try:
        check(orm, user_id=user_id, project_id=project_id)
    except AuthzError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _embed_markdown(value: str) -> list[float] | None:
    try:
        from agentops.rag.model_clients import EmbeddingServiceClient

        return EmbeddingServiceClient().embed_documents([value])[0]
    except Exception:
        return None


async def _content(summary: str, file: UploadFile | None) -> tuple[str, str | None]:
    pasted = summary.strip()
    if file is None:
        if not pasted:
            raise HTTPException(status_code=422, detail="meeting summary text or a Markdown/TXT file is required")
        return pasted, None
    filename = (file.filename or "").strip()
    suffix = filename.rpartition(".")[2].lower()
    if suffix not in {"md", "txt"}:
        raise HTTPException(status_code=415, detail="only .md and .txt meeting summaries are supported")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="meeting summary file must not exceed 1 MB")
    try:
        uploaded = raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=422, detail="meeting summary file must be UTF-8") from error
    combined = "\n\n".join(item for item in (pasted, uploaded) if item)
    if not combined:
        raise HTTPException(status_code=422, detail="meeting summary file is empty")
    return combined, filename[:255]


@router.get("/meeting-summaries", response_model=MeetingSummaryListResponse)
def list_meeting_summaries(
    request: Request,
    project_id: uuid.UUID = Query(...),
    query: str = Query("", max_length=500),
    tag: str | None = Query(None, max_length=100),
    meeting_date_from: date | None = Query(None),
    meeting_date_to: date | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    orm: Session = Depends(get_orm_session),
) -> MeetingSummaryListResponse:
    user_id = _user(request)
    items = search_meeting_summaries(
        orm,
        project_ids=[project_id],
        query=query,
        tags=[tag] if tag else None,
        meeting_date_from=meeting_date_from,
        meeting_date_to=meeting_date_to,
        limit=limit,
    )
    record_audit(
        orm,
        user_id=user_id,
        action="meeting_summary_view",
        resource_type="project",
        resource_id=str(project_id),
        metadata={"result_count": len(items), "has_query": bool(query.strip())},
        request=request,
    )
    return MeetingSummaryListResponse(items=[_response(item) for item in items])


@router.get("/meeting-summaries/{summary_id}", response_model=MeetingSummaryResponse)
def read_meeting_summary(
    summary_id: uuid.UUID,
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> MeetingSummaryResponse:
    row = orm.execute(
        text("SELECT project_id::text FROM public.meeting_summaries WHERE id = :id"),
        {"id": str(summary_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="meeting summary not found")
    project_id = uuid.UUID(str(row.project_id))
    user_id = _user(request)
    item = get_meeting_summary(orm, summary_id=summary_id, project_ids=[project_id])
    if item is None:
        raise HTTPException(status_code=404, detail="meeting summary not found")
    record_audit(
        orm, user_id=user_id, action="meeting_summary_view",
        resource_type="meeting_summary", resource_id=str(summary_id), request=request,
    )
    return _response(item)


@router.post("/meeting-summaries", response_model=MeetingSummaryResponse)
async def create_meeting_summary(
    request: Request,
    project_id: uuid.UUID = Form(...),
    title: str = Form(..., min_length=1, max_length=200),
    meeting_date: date = Form(...),
    participants: str = Form(""),
    tags: str = Form(""),
    summary: str = Form(""),
    decisions: str = Form(""),
    action_items: str = Form(""),
    file: UploadFile | None = File(None),
    orm: Session = Depends(get_orm_session),
) -> MeetingSummaryResponse:
    user_id = _user(request)
    _authorize(require_admin, orm, user_id=user_id, project_id=project_id)
    if isinstance(meeting_date, str):
        try:
            meeting_date = date.fromisoformat(meeting_date)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="meeting_date must use YYYY-MM-DD") from error
    source, source_filename = await _content(summary, file)
    people = normalize_list(participants)
    normalized_tags = normalize_list(tags)
    normalized_decisions = normalize_list(decisions)
    normalized_actions = normalize_list(action_items)
    markdown = build_meeting_markdown(
        title=title,
        meeting_date=meeting_date,
        participants=people,
        tags=normalized_tags,
        summary=source,
        decisions=normalized_decisions,
        action_items=normalized_actions,
    )
    embedding = _embed_markdown(markdown)
    inserted = orm.execute(
        text("""
            INSERT INTO public.meeting_summaries (
                project_id, title, meeting_date, participants, tags,
                summary_markdown, decisions, action_items, source_filename,
                created_by, embedding, embedding_model, embedding_version
            ) VALUES (
                :project_id, :title, :meeting_date, CAST(:participants AS text[]),
                CAST(:tags AS text[]), :summary_markdown, CAST(:decisions AS text[]),
                CAST(:action_items AS text[]), :source_filename, :created_by,
                CAST(:embedding AS vector(1024)), :embedding_model, :embedding_version
            ) RETURNING id::text
        """),
        {
            "project_id": str(project_id), "title": title.strip(), "meeting_date": meeting_date,
            "participants": people, "tags": normalized_tags, "summary_markdown": markdown,
            "decisions": normalized_decisions, "action_items": normalized_actions,
            "source_filename": source_filename, "created_by": str(user_id),
            "embedding": json.dumps(embedding) if embedding is not None else None,
            "embedding_model": "BAAI/bge-m3" if embedding is not None else None,
            "embedding_version": "2026-07-21-bge-m3" if embedding is not None else None,
        },
    ).first()
    orm.commit()
    summary_id = uuid.UUID(str(inserted.id))
    item = get_meeting_summary(orm, summary_id=summary_id, project_ids=[project_id])
    if item is None:
        raise HTTPException(status_code=500, detail="meeting summary was saved but could not be read")
    record_audit(
        orm, user_id=user_id, action="meeting_summary_create",
        resource_type="meeting_summary", resource_id=str(summary_id),
        metadata={"project_id": str(project_id), "has_file": file is not None}, request=request,
    )
    return _response(item)
