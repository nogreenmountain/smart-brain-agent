from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_orm_session
from agentops.meeting_summaries.domain import build_meeting_markdown
from agentops.meeting_summaries.query import (
    MeetingSummaryHit,
    get_meeting_summary,
    search_meeting_summaries,
)
from agentops.project_memory.intake import MAX_FILE_BYTES
from agentops.project_memory.parsers import SUPPORTED_FORMATS, extract_text
from agentops.rag.audit import record_audit
from agentops.rag.authz import AuthzError, current_user_id, require_member


router = APIRouter(tags=["meeting-summaries"], route_class=AuthenticatedRoute)


class MeetingSummaryResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    title: str
    meeting_date: date
    participant_user_ids: list[uuid.UUID]
    participants: list[str]
    tags: list[str]
    summary_markdown: str
    decisions: list[str]
    action_items: list[str]
    source_filename: str | None
    source_format: str | None
    source_size_bytes: int | None
    created_by: uuid.UUID
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    lexical_score: float = 0
    vector_score: float | None = None


class MeetingSummaryListResponse(BaseModel):
    items: list[MeetingSummaryResponse]


class MeetingSubmissionResponse(BaseModel):
    id: uuid.UUID
    draft_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    status: str = "pending_review"


class MeetingParticipantOption(BaseModel):
    user_id: uuid.UUID
    email: str
    username: str
    nickname: str | None = None
    display_name: str


@dataclass(frozen=True)
class MeetingFile:
    filename: str
    format: str
    mime_type: str | None
    raw_content: bytes
    content_hash: str


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


def _participant_ids(value: str) -> list[uuid.UUID]:
    try:
        raw = json.loads(value)
    except (json.JSONDecodeError, TypeError) as error:
        raise HTTPException(status_code=422, detail="participant_user_ids must be a JSON array") from error
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=422, detail="at least one participant must be selected")
    if len(raw) > 200:
        raise HTTPException(status_code=422, detail="no more than 200 participants may be selected")
    result: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    try:
        for item in raw:
            parsed = uuid.UUID(str(item))
            if parsed not in seen:
                seen.add(parsed)
                result.append(parsed)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail="participant_user_ids must contain UUIDs") from error
    return result


def _require_existing_project(orm: Session, *, project_id: uuid.UUID):
    row = orm.execute(
        text("SELECT id, name, department_id FROM public.projects WHERE id = :project_id"),
        {"project_id": str(project_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return row


def _active_team_participants(
    orm: Session,
    *,
    participant_ids: list[uuid.UUID],
) -> list[str]:
    rows = orm.execute(
        text("""
            SELECT au.id::text AS user_id, au.email,
                   COALESCE(
                       NULLIF(BTRIM(pu.nickname), ''),
                       NULLIF(BTRIM(pu.full_name), ''),
                       split_part(au.email, '@', 1),
                       au.id::text
                   ) AS display_name
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE COALESCE(pu.is_active, true) = true
              AND au.id = ANY(CAST(:participant_user_ids AS uuid[]))
        """),
        {
            "participant_user_ids": [str(item) for item in participant_ids],
        },
    ).all()
    names = {uuid.UUID(str(row.user_id)): str(row.display_name) for row in rows}
    missing = [str(item) for item in participant_ids if item not in names]
    if missing:
        raise HTTPException(
            status_code=422,
            detail="all selected participants must be active team members",
        )
    return [names[item] for item in participant_ids]


async def _meeting_file(upload: UploadFile | None) -> MeetingFile:
    if upload is None:
        raise HTTPException(status_code=422, detail="a meeting content file is required")
    filename = Path(upload.filename or "").name.strip()
    if not filename:
        raise HTTPException(status_code=422, detail="meeting content filename is required")
    suffix = Path(filename).suffix.lower().lstrip(".")
    fmt = "html" if suffix == "htm" else suffix
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=415, detail=f"unsupported meeting content format: {suffix or 'unknown'}")
    raw = await upload.read()
    if not raw:
        raise HTTPException(status_code=422, detail="meeting content file is empty")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="meeting content file must not exceed 20 MB")

    return MeetingFile(
        filename=filename[:255],
        format=fmt,
        mime_type=(upload.content_type or "").strip()[:255] or None,
        raw_content=raw,
        content_hash=hashlib.sha256(raw).hexdigest(),
    )


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
    _authorize(require_member, orm, user_id=user_id, project_id=project_id)
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


@router.get("/meeting-participant-options", response_model=list[MeetingParticipantOption])
def list_meeting_participant_options(
    request: Request,
    query: str = Query("", max_length=100),
    limit: int = Query(100, ge=1, le=200),
    orm: Session = Depends(get_orm_session),
) -> list[MeetingParticipantOption]:
    _user(request)
    normalized_query = query.strip()
    rows = orm.execute(
        text("""
            SELECT au.id::text AS user_id,
                   au.email,
                   split_part(au.email, '@', 1) AS username,
                   NULLIF(BTRIM(pu.nickname), '') AS nickname,
                   COALESCE(
                       NULLIF(BTRIM(pu.nickname), ''),
                       NULLIF(BTRIM(pu.full_name), ''),
                       split_part(au.email, '@', 1)
                   ) AS display_name
            FROM auth.users au
            LEFT JOIN public.users pu ON pu.id = au.id
            WHERE COALESCE(pu.is_active, true) = true
              AND (
                  :query = ''
                  OR COALESCE(pu.nickname, '') ILIKE :query
                  OR COALESCE(pu.full_name, '') ILIKE :query
                  OR au.email ILIKE :query
                  OR split_part(au.email, '@', 1) ILIKE :query
              )
            ORDER BY COALESCE(
                         NULLIF(BTRIM(pu.nickname), ''),
                         NULLIF(BTRIM(pu.full_name), ''),
                         split_part(au.email, '@', 1)
                     ),
                     au.email
            LIMIT :limit
        """),
        {
            "query": f"%{normalized_query}%" if normalized_query else "",
            "limit": limit,
        },
    ).all()
    return [
        MeetingParticipantOption(
            user_id=uuid.UUID(str(row.user_id)),
            email=str(row.email),
            username=str(row.username),
            nickname=getattr(row, "nickname", None),
            display_name=str(row.display_name),
        )
        for row in rows
    ]


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
    _authorize(require_member, orm, user_id=user_id, project_id=project_id)
    item = get_meeting_summary(orm, summary_id=summary_id, project_ids=[project_id])
    if item is None:
        raise HTTPException(status_code=404, detail="meeting summary not found")
    record_audit(
        orm, user_id=user_id, action="meeting_summary_view",
        resource_type="meeting_summary", resource_id=str(summary_id), request=request,
    )
    return _response(item)


@router.get("/meeting-summaries/{summary_id}/file")
def download_meeting_file(
    summary_id: uuid.UUID,
    request: Request,
    orm: Session = Depends(get_orm_session),
) -> Response:
    row = orm.execute(
        text("""
            SELECT ms.project_id::text, mf.filename, mf.mime_type, mf.raw_content
            FROM public.meeting_summaries ms
            JOIN public.meeting_summary_files mf ON mf.meeting_summary_id = ms.id
            WHERE ms.id = :summary_id
        """),
        {"summary_id": str(summary_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="meeting content file not found")
    user_id = _user(request)
    project_id = uuid.UUID(str(row.project_id))
    _authorize(require_member, orm, user_id=user_id, project_id=project_id)
    filename = str(row.filename)
    record_audit(
        orm, user_id=user_id, action="meeting_summary_view",
        resource_type="meeting_summary_file", resource_id=str(summary_id), request=request,
    )
    return Response(
        content=bytes(row.raw_content),
        media_type=str(row.mime_type or "application/octet-stream"),
        headers={
            "Content-Disposition": f"attachment; filename=meeting; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.post("/meeting-summaries", response_model=MeetingSubmissionResponse)
async def create_meeting_summary(
    request: Request,
    project_id: uuid.UUID = Form(...),
    title: str = Form(..., min_length=1, max_length=200),
    meeting_date: date = Form(...),
    participant_user_ids: str = Form(...),
    file: UploadFile | None = File(...),
    orm: Session = Depends(get_orm_session),
) -> MeetingSubmissionResponse:
    user_id = _user(request)
    project = _require_existing_project(orm, project_id=project_id)
    if isinstance(meeting_date, str):
        try:
            meeting_date = date.fromisoformat(meeting_date)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="meeting_date must use YYYY-MM-DD") from error

    selected_ids = _participant_ids(participant_user_ids)
    participant_names = _active_team_participants(
        orm,
        participant_ids=selected_ids,
    )
    meeting_file = await _meeting_file(file)
    normalized_title = title.strip()
    submission_id = uuid.uuid4()
    draft_id = uuid.uuid4()
    payload = {
        "title": normalized_title,
        "meeting_date": meeting_date.isoformat(),
        "participant_user_ids": [str(item) for item in selected_ids],
        "participants": participant_names,
    }
    orm.execute(
        text("""
            INSERT INTO public.project_memory_submissions (
                id, project_id, submission_type, payload, filename, format,
                mime_type, size_bytes, content_hash, raw_content,
                status, created_by_user_id
            ) VALUES (
                :submission_id, :project_id, :submission_type,
                CAST(:payload AS jsonb), :filename, :format, :mime_type,
                :size_bytes, :content_hash, :raw_content,
                'pending_review', :created_by
            )
        """),
        {
            "submission_id": str(submission_id),
            "project_id": str(project_id),
            "submission_type": "meeting_summary",
            "payload": json.dumps(payload, ensure_ascii=False),
            "filename": meeting_file.filename,
            "format": meeting_file.format,
            "mime_type": meeting_file.mime_type,
            "size_bytes": len(meeting_file.raw_content),
            "content_hash": meeting_file.content_hash,
            "raw_content": meeting_file.raw_content,
            "created_by": str(user_id),
            "participant_user_ids": [str(item) for item in selected_ids],
            "participants": participant_names,
        },
    )
    orm.execute(
        text("""
            INSERT INTO public.project_memory_drafts (
                id, project_id, department_id, title, status, template_version,
                markdown_content, source_count, created_by_user_id, submission_id
            ) VALUES (
                :draft_id, :project_id, :department_id, :title, 'pending_review',
                'meeting-summary-submission-v1', :markdown_content, 1,
                :created_by, :submission_id
            )
        """),
        {
            "draft_id": str(draft_id),
            "project_id": str(project_id),
            "department_id": str(project.department_id),
            "title": f"{normalized_title} 会议记录审批",
            "markdown_content": (
                f"# 会议记录审批：{normalized_title}\n\n"
                f"- 项目：{project.name}\n- 会议日期：{meeting_date.isoformat()}\n"
                f"- 参会人：{'、'.join(participant_names)}\n- 原文件：{meeting_file.filename}\n"
            ),
            "created_by": str(user_id),
            "submission_id": str(submission_id),
        },
    )
    orm.commit()
    record_audit(
        orm, user_id=user_id, action="meeting_summary_create",
        resource_type="project_memory_draft", resource_id=str(draft_id),
        metadata={
            "project_id": str(project_id),
            "submission_id": str(submission_id),
            "participant_count": len(selected_ids),
            "source_format": meeting_file.format,
            "source_size_bytes": len(meeting_file.raw_content),
        },
        request=request,
    )
    return MeetingSubmissionResponse(
        id=submission_id,
        draft_id=draft_id,
        project_id=project_id,
        title=normalized_title,
    )
