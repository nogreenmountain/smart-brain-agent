from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    from sqlalchemy import text
except ModuleNotFoundError:  # Standalone unit tests do not install SQLAlchemy.
    def text(value: str) -> str:
        return value

try:
    from agentops.rag.search import search as rag_search
except ModuleNotFoundError:  # Standalone unit tests patch the semantic helper.
    rag_search = None


EXAMPLE_KINDS = {
    "any": ["failure_case", "success_case", "retrospective"],
    "failure": ["failure_case"],
    "success": ["success_case"],
}


@dataclass(frozen=True)
class WikiPageRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    page_type: str
    memory_kind: str
    tags: list[str]
    summary: str
    markdown_content: str
    usefulness: float
    confidence: float
    verification_status: str
    current_version: int
    updated_at: str
    valid_from: str | None = None
    valid_until: str | None = None


@dataclass(frozen=True)
class WikiSearchHit:
    page_id: uuid.UUID
    title: str
    page_type: str
    memory_kind: str
    tags: list[str]
    summary: str
    matched_excerpt: str
    score: float
    usefulness: float
    confidence: float
    verification_status: str
    current_version: int
    updated_at: str


def _excerpt(value: str, limit: int = 320) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _array_params(values: list[str] | None) -> list[str] | None:
    cleaned = [str(item).strip() for item in (values or []) if str(item).strip()]
    return cleaned or None


def _keyword_page_scores(
    orm,
    *,
    query: str,
    project_id: uuid.UUID,
    memory_kinds: list[str] | None,
    tags: list[str] | None,
    updated_after: datetime | None,
    verified_only: bool,
    limit: int,
) -> dict[uuid.UUID, tuple[float, str]]:
    rows = orm.execute(
        text("""
            SELECT id::text,
                   CASE
                     WHEN lower(title) = lower(:query) THEN 1.0
                     WHEN title ILIKE :pattern THEN 0.92
                     WHEN summary ILIKE :pattern THEN 0.78
                     WHEN array_to_string(tags, ' ') ILIKE :pattern THEN 0.75
                     ELSE 0.62
                   END AS score,
                   CASE
                     WHEN summary ILIKE :pattern THEN summary
                     ELSE left(markdown_content, 500)
                   END AS excerpt
            FROM public.project_wiki_pages
            WHERE project_id = :project_id
              AND status = 'active'
              AND (
                title ILIKE :pattern OR summary ILIKE :pattern OR
                markdown_content ILIKE :pattern OR
                array_to_string(tags, ' ') ILIKE :pattern
              )
              AND (CAST(:memory_kinds AS text[]) IS NULL OR memory_kind = ANY(CAST(:memory_kinds AS text[])))
              AND (CAST(:tags AS text[]) IS NULL OR tags && CAST(:tags AS text[]))
              AND (CAST(:updated_after AS timestamptz) IS NULL OR updated_at >= CAST(:updated_after AS timestamptz))
              AND (:verified_only = false OR verification_status = 'verified')
            ORDER BY score DESC, updated_at DESC
            LIMIT :limit
        """),
        {
            "query": query.strip(),
            "pattern": f"%{query.strip()}%",
            "project_id": str(project_id),
            "memory_kinds": _array_params(memory_kinds),
            "tags": _array_params(tags),
            "updated_after": updated_after,
            "verified_only": verified_only,
            "limit": max(limit * 3, 20),
        },
    ).all()
    return {
        uuid.UUID(str(row.id)): (float(row.score), _excerpt(row.excerpt))
        for row in rows
    }


def _semantic_page_scores(
    orm,
    *,
    query: str,
    project_id: uuid.UUID,
    limit: int,
) -> dict[uuid.UUID, tuple[float, str]]:
    if rag_search is None:
        return {}
    hits = rag_search(
        orm,
        query=query,
        project_id=project_id,
        k=max(limit * 4, 20),
        retrieval_version="v2-hybrid",
    )
    document_ids = list({str(hit.document_id) for hit in hits})
    if not document_ids:
        return {}
    rows = orm.execute(
        text("""
            SELECT id::text, document_id::text
            FROM public.project_wiki_pages
            WHERE project_id = :project_id AND status = 'active'
              AND document_id = ANY(CAST(:document_ids AS uuid[]))
        """),
        {"project_id": str(project_id), "document_ids": document_ids},
    ).all()
    page_by_document = {str(row.document_id): uuid.UUID(str(row.id)) for row in rows}
    result: dict[uuid.UUID, tuple[float, str]] = {}
    for hit in hits:
        page_id = page_by_document.get(str(hit.document_id))
        if page_id is None:
            continue
        score = max(0.0, min(1.0, float(hit.score or 0.0)))
        previous = result.get(page_id)
        if previous is None or score > previous[0]:
            result[page_id] = (score, _excerpt(hit.content))
    return result


def _load_pages(
    orm,
    *,
    page_ids: list[uuid.UUID],
    project_id: uuid.UUID,
    memory_kinds: list[str] | None,
    tags: list[str] | None,
    updated_after: datetime | None,
    verified_only: bool,
) -> dict[uuid.UUID, WikiPageRecord]:
    if not page_ids:
        return {}
    rows = orm.execute(
        text("""
            SELECT id::text, project_id::text, title, page_type, memory_kind,
                   tags, summary, markdown_content, usefulness, confidence,
                   verification_status, current_version, valid_from::text,
                   valid_until::text, updated_at::text
            FROM public.project_wiki_pages
            WHERE id = ANY(CAST(:page_ids AS uuid[]))
              AND project_id = :project_id AND status = 'active'
              AND (CAST(:memory_kinds AS text[]) IS NULL OR memory_kind = ANY(CAST(:memory_kinds AS text[])))
              AND (CAST(:tags AS text[]) IS NULL OR tags && CAST(:tags AS text[]))
              AND (CAST(:updated_after AS timestamptz) IS NULL OR updated_at >= CAST(:updated_after AS timestamptz))
              AND (:verified_only = false OR verification_status = 'verified')
        """),
        {
            "page_ids": [str(item) for item in page_ids],
            "project_id": str(project_id),
            "memory_kinds": _array_params(memory_kinds),
            "tags": _array_params(tags),
            "updated_after": updated_after,
            "verified_only": verified_only,
        },
    ).all()
    return {
        uuid.UUID(str(row.id)): WikiPageRecord(
            id=uuid.UUID(str(row.id)),
            project_id=uuid.UUID(str(row.project_id)),
            title=str(row.title),
            page_type=str(row.page_type),
            memory_kind=str(row.memory_kind),
            tags=[str(item) for item in (row.tags or [])],
            summary=str(row.summary or ""),
            markdown_content=str(row.markdown_content),
            usefulness=float(row.usefulness),
            confidence=float(row.confidence),
            verification_status=str(row.verification_status),
            current_version=int(row.current_version),
            valid_from=str(row.valid_from) if row.valid_from else None,
            valid_until=str(row.valid_until) if row.valid_until else None,
            updated_at=str(row.updated_at),
        )
        for row in rows
    }


def search_wiki(
    orm,
    *,
    query: str,
    project_id: uuid.UUID,
    memory_kinds: list[str] | None = None,
    tags: list[str] | None = None,
    updated_after: datetime | None = None,
    verified_only: bool = False,
    limit: int = 8,
) -> list[WikiSearchHit]:
    value = query.strip()
    if not value:
        return []
    bounded_limit = max(1, min(int(limit), 20))
    keyword = _keyword_page_scores(
        orm,
        query=value,
        project_id=project_id,
        memory_kinds=memory_kinds,
        tags=tags,
        updated_after=updated_after,
        verified_only=verified_only,
        limit=bounded_limit,
    )
    semantic = _semantic_page_scores(
        orm,
        query=value,
        project_id=project_id,
        limit=bounded_limit,
    )
    page_ids = list(set(keyword) | set(semantic))
    pages = _load_pages(
        orm,
        page_ids=page_ids,
        project_id=project_id,
        memory_kinds=memory_kinds,
        tags=tags,
        updated_after=updated_after,
        verified_only=verified_only,
    )
    results: list[WikiSearchHit] = []
    for page_id, page in pages.items():
        keyword_score, keyword_excerpt = keyword.get(page_id, (0.0, ""))
        semantic_score, semantic_excerpt = semantic.get(page_id, (0.0, ""))
        high, low = sorted((keyword_score, semantic_score), reverse=True)
        score = 0.62 * high + 0.28 * low
        if page.verification_status == "verified":
            score += 0.06
        score += 0.02 * page.usefulness + 0.02 * page.confidence
        results.append(WikiSearchHit(
            page_id=page_id,
            title=page.title,
            page_type=page.page_type,
            memory_kind=page.memory_kind,
            tags=page.tags,
            summary=page.summary,
            matched_excerpt=_excerpt(keyword_excerpt or semantic_excerpt or page.summary or page.markdown_content),
            score=round(min(score, 1.0), 4),
            usefulness=page.usefulness,
            confidence=page.confidence,
            verification_status=page.verification_status,
            current_version=page.current_version,
            updated_at=page.updated_at,
        ))
    return sorted(results, key=lambda item: (item.score, item.updated_at), reverse=True)[:bounded_limit]


def get_examples(
    orm,
    *,
    topic: str,
    project_id: uuid.UUID,
    outcome: str = "any",
    limit: int = 8,
) -> list[WikiSearchHit]:
    kinds = EXAMPLE_KINDS.get(outcome, EXAMPLE_KINDS["any"])
    return search_wiki(
        orm,
        query=topic,
        project_id=project_id,
        memory_kinds=kinds,
        limit=limit,
    )


def get_page(orm, *, page_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any] | None:
    row = orm.execute(
        text("""
            SELECT p.id::text, p.project_id::text, p.page_key, p.title,
                   p.page_type, p.memory_kind, p.tags, p.summary,
                   p.markdown_content, p.usefulness, p.confidence,
                   p.verification_status, p.current_version,
                   p.valid_from::text, p.valid_until::text,
                   p.created_at::text, p.updated_at::text,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object(
                       'source_type', s.source_type, 'source_id', s.source_id,
                       'locator', s.locator) ORDER BY s.source_type, s.source_id)
                       FROM public.project_wiki_page_sources s
                       WHERE s.page_id = p.id), '[]'::jsonb) AS sources,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object(
                       'node_id', l.to_page_id::text, 'title', l.to_title,
                       'relation', l.relation) ORDER BY l.to_title)
                       FROM public.project_wiki_links l
                       WHERE l.from_page_id = p.id), '[]'::jsonb) AS links
            FROM public.project_wiki_pages p
            WHERE p.id = :page_id AND p.project_id = :project_id
              AND p.status = 'active'
        """),
        {"page_id": str(page_id), "project_id": str(project_id)},
    ).mappings().first()
    return dict(row) if row else None


def get_related_nodes(
    orm,
    *,
    node_id: uuid.UUID,
    project_id: uuid.UUID,
    relation: str | None = None,
    depth: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = orm.execute(
        text("""
            WITH RECURSIVE graph AS (
                SELECT CASE WHEN l.from_page_id = :node_id THEN l.to_page_id ELSE l.from_page_id END AS node_id,
                       l.relation, 1 AS depth
                FROM public.project_wiki_links l
                JOIN public.project_wiki_pages source ON source.id = l.from_page_id
                WHERE source.project_id = :project_id
                  AND l.to_page_id IS NOT NULL
                  AND (l.from_page_id = :node_id OR l.to_page_id = :node_id)
                  AND (CAST(:relation AS text) IS NULL OR l.relation = CAST(:relation AS text))
                UNION
                SELECT CASE WHEN l.from_page_id = graph.node_id THEN l.to_page_id ELSE l.from_page_id END,
                       l.relation, graph.depth + 1
                FROM graph
                JOIN public.project_wiki_links l
                  ON l.from_page_id = graph.node_id OR l.to_page_id = graph.node_id
                WHERE graph.depth < :depth AND l.to_page_id IS NOT NULL
            )
            SELECT DISTINCT ON (p.id) p.id::text AS node_id, p.title,
                   p.page_type, p.memory_kind, p.summary,
                   p.verification_status, p.current_version,
                   p.updated_at::text, graph.relation, graph.depth
            FROM graph
            JOIN public.project_wiki_pages p ON p.id = graph.node_id
            WHERE p.project_id = :project_id AND p.status = 'active'
              AND p.id <> :node_id
            ORDER BY p.id, graph.depth, p.updated_at DESC
            LIMIT :limit
        """),
        {
            "node_id": str(node_id),
            "project_id": str(project_id),
            "relation": relation,
            "depth": max(1, min(int(depth), 2)),
            "limit": max(1, min(int(limit), 50)),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def get_recent_updates(
    orm,
    *,
    project_id: uuid.UUID,
    since: datetime | None = None,
    memory_kinds: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = orm.execute(
        text("""
            SELECT id::text AS page_id, title, page_type, memory_kind, tags,
                   summary, verification_status, current_version,
                   updated_at::text
            FROM public.project_wiki_pages
            WHERE project_id = :project_id AND status = 'active'
              AND (CAST(:since AS timestamptz) IS NULL OR updated_at >= CAST(:since AS timestamptz))
              AND (CAST(:memory_kinds AS text[]) IS NULL OR memory_kind = ANY(CAST(:memory_kinds AS text[])))
            ORDER BY updated_at DESC
            LIMIT :limit
        """),
        {
            "project_id": str(project_id),
            "since": since,
            "memory_kinds": _array_params(memory_kinds),
            "limit": max(1, min(int(limit), 50)),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def get_decision_records(
    orm,
    *,
    project_id: uuid.UUID,
    topic: str | None = None,
    limit: int = 20,
) -> list[WikiSearchHit] | list[dict[str, Any]]:
    if topic and topic.strip():
        return search_wiki(
            orm,
            query=topic,
            project_id=project_id,
            memory_kinds=["decision_record", "strategy"],
            limit=limit,
        )
    return get_recent_updates(
        orm,
        project_id=project_id,
        memory_kinds=["decision_record", "strategy"],
        limit=limit,
    )
