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
class MemberExperienceHit:
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
    first_observed: date | str
    last_observed: date | str
    observation_count: int
    current_version: int
    updated_at: datetime | str
    lexical_score: float
    vector_score: float | None


def _vector_literal(value: list[float] | None) -> str | None:
    if value is None:
        return None
    return json.dumps([float(item) for item in value], separators=(",", ":"))


def search_member_experiences(
    orm,
    *,
    employee_ids: list[str],
    query: str = "",
    tags: list[str] | None = None,
    outcome: str | None = None,
    task_type: str | None = None,
    updated_after: datetime | None = None,
    limit: int = 8,
    query_embedding: list[float] | None = None,
) -> list[MemberExperienceHit]:
    if not employee_ids:
        return []
    cleaned_query = str(query or "").strip()
    filters = [
        "employee_id = ANY(CAST(:employee_ids AS text[]))",
        "status = 'active'",
    ]
    params: dict[str, Any] = {
        "employee_ids": employee_ids,
        "query": cleaned_query,
        "query_like": f"%{cleaned_query}%",
        "limit": min(max(int(limit), 1), 50),
    }
    if cleaned_query:
        semantic_clause = " OR embedding IS NOT NULL" if query_embedding is not None else ""
        filters.append(
            "(title ILIKE :query_like OR summary ILIKE :query_like "
            f"OR markdown_content ILIKE :query_like{semantic_clause})"
        )
    if tags:
        filters.append("tags && CAST(:tags AS text[])")
        params["tags"] = tags
    else:
        params["tags"] = []
    if outcome:
        filters.append("outcome = :outcome")
        params["outcome"] = outcome
    else:
        params["outcome"] = None
    if task_type:
        filters.append("task_type = :task_type")
        params["task_type"] = task_type
    if updated_after:
        filters.append("updated_at >= :updated_after")
        params["updated_after"] = updated_after

    lexical = """CASE WHEN :query = '' THEN 0.0 ELSE GREATEST(
        similarity(title || ' ' || summary, :query),
        CASE WHEN title ILIKE :query_like THEN 1.0 ELSE 0.0 END,
        CASE WHEN summary ILIKE :query_like THEN 0.8 ELSE 0.0 END,
        CASE WHEN markdown_content ILIKE :query_like THEN 0.6 ELSE 0.0 END
    ) END"""
    if query_embedding is not None:
        vector = "CASE WHEN embedding IS NULL THEN NULL ELSE 1 - (embedding <=> CAST(:query_embedding AS vector(1024))) END"
        score = f"(COALESCE(({vector}), 0.0) * 0.65 + ({lexical}) * 0.35)"
        params["query_embedding"] = _vector_literal(query_embedding)
    else:
        vector = "NULL::double precision"
        score = lexical

    rows = orm.execute(
        text(f"""
            SELECT id::text, employee_id, employee_name, experience_key,
                   title, task_type, outcome, summary, markdown_content,
                   tags, tools, confidence, first_observed, last_observed,
                   observation_count, current_version, updated_at,
                   ({lexical}) AS lexical_score,
                   ({vector}) AS vector_score
            FROM public.member_wiki_experiences
            WHERE {' AND '.join(filters)}
            ORDER BY ({score}) DESC, last_observed DESC, updated_at DESC
            LIMIT :limit
        """),
        params,
    ).all()
    return [
        MemberExperienceHit(
            id=uuid.UUID(str(row.id)),
            employee_id=str(row.employee_id),
            employee_name=str(row.employee_name),
            experience_key=str(row.experience_key),
            title=str(row.title),
            task_type=str(row.task_type),
            outcome=str(row.outcome),
            summary=str(row.summary or ""),
            markdown_content=str(row.markdown_content),
            tags=list(row.tags or []),
            tools=list(row.tools or []),
            confidence=float(row.confidence),
            first_observed=row.first_observed,
            last_observed=row.last_observed,
            observation_count=int(row.observation_count),
            current_version=int(row.current_version),
            updated_at=row.updated_at,
            lexical_score=float(row.lexical_score or 0),
            vector_score=float(row.vector_score) if row.vector_score is not None else None,
        )
        for row in rows
    ]


def get_member_experience(
    orm,
    *,
    experience_id: uuid.UUID,
    employee_ids: list[str],
) -> MemberExperienceHit | None:
    items = orm.execute(
        text("""
            SELECT id::text, employee_id, employee_name, experience_key,
                   title, task_type, outcome, summary, markdown_content,
                   tags, tools, confidence, first_observed, last_observed,
                   observation_count, current_version, updated_at,
                   0.0 AS lexical_score, NULL::double precision AS vector_score
            FROM public.member_wiki_experiences
            WHERE id = :experience_id AND status = 'active'
              AND employee_id = ANY(CAST(:employee_ids AS text[]))
        """),
        {"experience_id": str(experience_id), "employee_ids": employee_ids},
    ).all()
    if not items:
        return None
    row = items[0]
    return MemberExperienceHit(
        id=uuid.UUID(str(row.id)), employee_id=str(row.employee_id),
        employee_name=str(row.employee_name), experience_key=str(row.experience_key),
        title=str(row.title), task_type=str(row.task_type), outcome=str(row.outcome),
        summary=str(row.summary or ""), markdown_content=str(row.markdown_content),
        tags=list(row.tags or []), tools=list(row.tools or []), confidence=float(row.confidence),
        first_observed=row.first_observed, last_observed=row.last_observed,
        observation_count=int(row.observation_count), current_version=int(row.current_version),
        updated_at=row.updated_at, lexical_score=0.0, vector_score=None,
    )
