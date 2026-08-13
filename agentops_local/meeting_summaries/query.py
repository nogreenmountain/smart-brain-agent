from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

try:
    from sqlalchemy import text
except ModuleNotFoundError:
    def text(value: str) -> str:
        return value


@dataclass(frozen=True)
class MeetingSummaryHit:
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    title: str
    meeting_date: date | str
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
    created_at: datetime | str
    updated_at: datetime | str
    lexical_score: float
    vector_score: float | None


def _vector_literal(value: list[float] | None) -> str | None:
    if value is None:
        return None
    return json.dumps([float(item) for item in value], separators=(",", ":"))


def _map(row) -> MeetingSummaryHit:
    return MeetingSummaryHit(
        id=uuid.UUID(str(row.id)),
        project_id=uuid.UUID(str(row.project_id)),
        project_name=str(row.project_name),
        title=str(row.title),
        meeting_date=row.meeting_date,
        participant_user_ids=[uuid.UUID(str(item)) for item in (row.participant_user_ids or [])],
        participants=list(row.participants or []),
        tags=list(row.tags or []),
        summary_markdown=str(row.summary_markdown),
        decisions=list(row.decisions or []),
        action_items=list(row.action_items or []),
        source_filename=str(row.source_filename) if row.source_filename else None,
        source_format=str(row.source_format) if row.source_format else None,
        source_size_bytes=int(row.source_size_bytes) if row.source_size_bytes is not None else None,
        created_by=uuid.UUID(str(row.created_by)),
        created_by_name=str(row.created_by_name or ""),
        created_at=row.created_at,
        updated_at=row.updated_at,
        lexical_score=float(row.lexical_score or 0),
        vector_score=float(row.vector_score) if row.vector_score is not None else None,
    )


def search_meeting_summaries(
    orm,
    *,
    project_ids: list[uuid.UUID],
    query: str = "",
    tags: list[str] | None = None,
    meeting_date_from: date | None = None,
    meeting_date_to: date | None = None,
    limit: int = 50,
    query_embedding: list[float] | None = None,
) -> list[MeetingSummaryHit]:
    if not project_ids:
        return []
    cleaned_query = str(query or "").strip()
    filters = ["ms.project_id = ANY(CAST(:project_ids AS uuid[]))"]
    params: dict[str, Any] = {
        "project_ids": [str(item) for item in project_ids],
        "query": cleaned_query,
        "query_like": f"%{cleaned_query}%",
        "limit": min(max(int(limit), 1), 100),
    }
    if cleaned_query:
        semantic = " OR ms.embedding IS NOT NULL" if query_embedding is not None else ""
        filters.append(
            "(ms.title ILIKE :query_like OR ms.summary_markdown ILIKE :query_like "
            f"OR array_to_string(ms.participants, ' ') ILIKE :query_like{semantic})"
        )
    if tags:
        filters.append("ms.tags && CAST(:tags AS text[])")
        params["tags"] = tags
    if meeting_date_from:
        filters.append("ms.meeting_date >= :meeting_date_from")
        params["meeting_date_from"] = meeting_date_from
    if meeting_date_to:
        filters.append("ms.meeting_date <= :meeting_date_to")
        params["meeting_date_to"] = meeting_date_to

    lexical = """CASE WHEN :query = '' THEN 0.0 ELSE GREATEST(
        similarity(ms.title, :query),
        CASE WHEN ms.title ILIKE :query_like THEN 1.0 ELSE 0.0 END,
        CASE WHEN ms.summary_markdown ILIKE :query_like THEN 0.75 ELSE 0.0 END,
        CASE WHEN array_to_string(ms.participants, ' ') ILIKE :query_like THEN 0.6 ELSE 0.0 END
    ) END"""
    if query_embedding is not None:
        vector = "CASE WHEN ms.embedding IS NULL THEN NULL ELSE 1 - (ms.embedding <=> CAST(:query_embedding AS vector(1024))) END"
        score = f"(COALESCE(({vector}), 0.0) * 0.65 + ({lexical}) * 0.35)"
        params["query_embedding"] = _vector_literal(query_embedding)
    else:
        vector = "NULL::double precision"
        score = lexical

    rows = orm.execute(
        text(f"""
            SELECT ms.id::text, ms.project_id::text, p.name AS project_name,
                   ms.title, ms.meeting_date, ms.participant_user_ids,
                   ms.participants, ms.tags,
                   ms.summary_markdown, ms.decisions, ms.action_items,
                   COALESCE(mf.filename, ms.source_filename) AS source_filename,
                   mf.format AS source_format, mf.size_bytes AS source_size_bytes,
                   ms.created_by::text,
                   COALESCE(u.full_name, au.email, ms.created_by::text) AS created_by_name,
                   ms.created_at, ms.updated_at,
                   ({lexical}) AS lexical_score, ({vector}) AS vector_score
            FROM public.meeting_summaries ms
            LEFT JOIN public.meeting_summary_files mf ON mf.meeting_summary_id = ms.id
            JOIN public.projects p ON p.id = ms.project_id
            LEFT JOIN public.users u ON u.id = ms.created_by
            LEFT JOIN auth.users au ON au.id = ms.created_by
            WHERE {' AND '.join(filters)}
            ORDER BY ({score}) DESC, ms.meeting_date DESC, ms.created_at DESC
            LIMIT :limit
        """),
        params,
    ).all()
    return [_map(row) for row in rows]


def get_meeting_summary(
    orm,
    *,
    summary_id: uuid.UUID,
    project_ids: list[uuid.UUID],
) -> MeetingSummaryHit | None:
    if not project_ids:
        return None
    rows = orm.execute(
        text("""
            SELECT ms.id::text, ms.project_id::text, p.name AS project_name,
                   ms.title, ms.meeting_date, ms.participant_user_ids,
                   ms.participants, ms.tags,
                   ms.summary_markdown, ms.decisions, ms.action_items,
                   COALESCE(mf.filename, ms.source_filename) AS source_filename,
                   mf.format AS source_format, mf.size_bytes AS source_size_bytes,
                   ms.created_by::text,
                   COALESCE(u.full_name, au.email, ms.created_by::text) AS created_by_name,
                   ms.created_at, ms.updated_at,
                   0.0 AS lexical_score, NULL::double precision AS vector_score
            FROM public.meeting_summaries ms
            LEFT JOIN public.meeting_summary_files mf ON mf.meeting_summary_id = ms.id
            JOIN public.projects p ON p.id = ms.project_id
            LEFT JOIN public.users u ON u.id = ms.created_by
            LEFT JOIN auth.users au ON au.id = ms.created_by
            WHERE ms.id = :summary_id
              AND ms.project_id = ANY(CAST(:project_ids AS uuid[]))
        """),
        {"summary_id": str(summary_id), "project_ids": [str(item) for item in project_ids]},
    ).all()
    return _map(rows[0]) if rows else None
