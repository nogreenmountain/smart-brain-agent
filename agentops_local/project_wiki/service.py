from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from sqlalchemy import text
except ModuleNotFoundError:  # Standalone unit tests do not install SQLAlchemy.
    def text(value: str) -> str:
        return value


def _load_local_module(name: str, filename: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


try:
    from agentops.project_wiki.compiler import (
        ExistingWikiPage,
        WikiSource,
        build_compiler_prompt,
        generate_candidates,
    )
    from agentops.project_wiki.domain import KnowledgeCandidate, classify_candidate
except ModuleNotFoundError:
    _compiler = _load_local_module("project_wiki_compiler_for_service", "compiler.py")
    _domain = _load_local_module("project_wiki_domain_for_service", "domain.py")
    ExistingWikiPage = _compiler.ExistingWikiPage
    WikiSource = _compiler.WikiSource
    build_compiler_prompt = _compiler.build_compiler_prompt
    generate_candidates = _compiler.generate_candidates
    KnowledgeCandidate = _domain.KnowledgeCandidate
    classify_candidate = _domain.classify_candidate


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompileResult:
    run_id: uuid.UUID
    source_count: int
    candidate_count: int
    auto_applied_count: int
    pending_review_count: int
    discarded_count: int
    model: str


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _source_hash(source: WikiSource) -> str:
    payload = "\n".join(
        [source.source_id, source.source_type, source.title, source.content]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _processed_hashes(orm, project_id: uuid.UUID) -> dict[str, str]:
    rows = orm.execute(
        text("""
            SELECT source_id, content_hash
            FROM public.project_wiki_processed_sources
            WHERE project_id = :project_id
        """),
        {"project_id": str(project_id)},
    ).all()
    return {str(row.source_id): str(row.content_hash) for row in rows}


def _chat_sources(orm, project_id: uuid.UUID, limit: int) -> list[WikiSource]:
    rows = orm.execute(
        text("""
            SELECT
                s.id::text AS id,
                COALESCE(NULLIF(s.title, ''), NULLIF(s.task_title, ''), 'AI 会话') AS title,
                s.source,
                s.started_at,
                s.updated_at,
                COALESCE(
                    string_agg(
                        concat(upper(m.role), ': ', m.content),
                        E'\n\n' ORDER BY m.sequence_index
                    ),
                    ''
                ) AS content
            FROM public.ai_chat_sessions s
            LEFT JOIN public.ai_chat_messages m ON m.session_id = s.id
            LEFT JOIN public.project_wiki_processed_sources processed
              ON processed.project_id = s.project_id
             AND processed.source_id = concat('chat:', s.id::text)
            WHERE s.project_id = :project_id
              AND processed.observed_at IS DISTINCT FROM s.updated_at
            GROUP BY s.id
            ORDER BY s.updated_at ASC
            LIMIT :limit
        """),
        {"project_id": str(project_id), "limit": limit},
    ).all()
    return [
        WikiSource(
            source_id=f"chat:{row.id}",
            source_type="ai_chat_session",
            title=str(row.title),
            content=str(row.content or "")[:50_000],
            observed_at=row.updated_at or row.started_at or datetime.now(timezone.utc),
        )
        for row in rows
        if str(row.content or "").strip()
    ]


def _document_sources(orm, project_id: uuid.UUID, limit: int) -> list[WikiSource]:
    rows = orm.execute(
        text("""
            SELECT
                d.id::text AS id,
                COALESCE(NULLIF(d.display_name, ''), d.filename) AS title,
                d.updated_at,
                COALESCE(
                    string_agg(c.content, E'\n\n' ORDER BY c.chunk_index),
                    ''
                ) AS content
            FROM public.documents d
            JOIN public.document_chunks c ON c.document_id = d.id
            LEFT JOIN public.project_wiki_processed_sources processed
              ON processed.project_id = d.project_id
             AND processed.source_id = concat('document:', d.id::text)
            WHERE d.project_id = :project_id
              AND d.status = 'ready'
              AND COALESCE(d.memory_type, '') <> 'project_wiki_page'
              AND processed.observed_at IS DISTINCT FROM d.updated_at
            GROUP BY d.id
            ORDER BY d.updated_at ASC
            LIMIT :limit
        """),
        {"project_id": str(project_id), "limit": limit},
    ).all()
    return [
        WikiSource(
            source_id=f"document:{row.id}",
            source_type="document",
            title=str(row.title),
            content=str(row.content or "")[:80_000],
            observed_at=row.updated_at or datetime.now(timezone.utc),
        )
        for row in rows
        if str(row.content or "").strip()
    ]


def collect_incremental_sources(
    orm,
    *,
    project_id: uuid.UUID,
    limit_per_type: int = 100,
) -> list[WikiSource]:
    processed = _processed_hashes(orm, project_id)
    sources = _chat_sources(orm, project_id, limit_per_type)
    sources.extend(_document_sources(orm, project_id, limit_per_type))
    return [
        source
        for source in sources
        if processed.get(source.source_id) != _source_hash(source)
    ]


def load_existing_pages(orm, project_id: uuid.UUID) -> list[ExistingWikiPage]:
    rows = orm.execute(
        text("""
            SELECT page_key, title, page_type, summary, markdown_content
            FROM public.project_wiki_pages
            WHERE project_id = :project_id AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 200
        """),
        {"project_id": str(project_id)},
    ).all()
    return [
        ExistingWikiPage(
            page_key=str(row.page_key),
            title=str(row.title),
            page_type=str(row.page_type),
            summary=str(row.summary or ""),
            markdown_content=str(row.markdown_content or ""),
        )
        for row in rows
    ]


def _insert_compile_run(
    orm,
    *,
    project_id: uuid.UUID,
    triggered_by_user_id: uuid.UUID | None,
    model: str,
) -> uuid.UUID:
    row = orm.execute(
        text("""
            INSERT INTO public.project_wiki_compile_runs (
                project_id, status, trigger_type, triggered_by_user_id, model
            )
            VALUES (
                :project_id, 'running', :trigger_type, :user_id, :model
            )
            RETURNING id::text
        """),
        {
            "project_id": str(project_id),
            "trigger_type": "manual" if triggered_by_user_id else "scheduled",
            "user_id": str(triggered_by_user_id) if triggered_by_user_id else None,
            "model": model,
        },
    ).first()
    orm.commit()
    return uuid.UUID(str(row.id))


def _finish_compile_run(
    orm,
    *,
    run_id: uuid.UUID,
    status: str,
    source_count: int,
    candidate_count: int,
    auto_applied_count: int,
    pending_review_count: int,
    discarded_count: int,
    error_message: str | None = None,
) -> None:
    orm.execute(
        text("""
            UPDATE public.project_wiki_compile_runs
            SET status = :status,
                source_count = :source_count,
                candidate_count = :candidate_count,
                auto_applied_count = :auto_applied_count,
                pending_review_count = :pending_review_count,
                discarded_count = :discarded_count,
                error_message = :error_message,
                completed_at = now()
            WHERE id = :run_id
        """),
        {
            "run_id": str(run_id),
            "status": status,
            "source_count": source_count,
            "candidate_count": candidate_count,
            "auto_applied_count": auto_applied_count,
            "pending_review_count": pending_review_count,
            "discarded_count": discarded_count,
            "error_message": error_message,
        },
    )
    orm.commit()


def _persist_change(
    orm,
    *,
    run_id: uuid.UUID,
    project_id: uuid.UUID,
    candidate: KnowledgeCandidate,
    disposition: str,
    reason_code: str,
) -> uuid.UUID:
    status = "pending_review" if disposition == "pending_review" else "discarded"
    row = orm.execute(
        text("""
            INSERT INTO public.project_wiki_changes (
                run_id, project_id, page_key, title, page_type,
                disposition, reason_code, status, summary, proposed_markdown,
                usefulness, confidence, contradiction, source_ids, link_titles
            )
            VALUES (
                :run_id, :project_id, :page_key, :title, :page_type,
                :disposition, :reason_code, :status, :summary, :markdown,
                :usefulness, :confidence, :contradiction,
                CAST(:source_ids AS jsonb), CAST(:link_titles AS jsonb)
            )
            RETURNING id::text
        """),
        {
            "run_id": str(run_id),
            "project_id": str(project_id),
            "page_key": candidate.page_key,
            "title": candidate.title,
            "page_type": candidate.page_type,
            "disposition": disposition,
            "reason_code": reason_code,
            "status": status,
            "summary": candidate.summary,
            "markdown": candidate.markdown_content,
            "usefulness": candidate.usefulness,
            "confidence": candidate.confidence,
            "contradiction": candidate.contradiction,
            "source_ids": _json(candidate.source_ids),
            "link_titles": _json(candidate.link_titles),
        },
    ).first()
    orm.commit()
    return uuid.UUID(str(row.id))


def _render_markdown(candidate: KnowledgeCandidate) -> str:
    sources = "\n".join(f"- `{source_id}`" for source_id in candidate.source_ids)
    body = candidate.markdown_content.rstrip()
    if "## 来源" not in body:
        body += f"\n\n## 来源\n\n{sources}"
    return body + "\n"


def _apply_candidate(
    orm,
    *,
    run_id: uuid.UUID,
    project_id: uuid.UUID,
    candidate: KnowledgeCandidate,
    created_by_user_id: uuid.UUID | None,
    reason_code: str,
    change_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from agentops.project_memory.ingest import ingest_markdown_memory

    existing = orm.execute(
        text("""
            SELECT id::text, current_version, document_id::text
            FROM public.project_wiki_pages
            WHERE project_id = :project_id AND page_key = :page_key
            FOR UPDATE
        """),
        {"project_id": str(project_id), "page_key": candidate.page_key},
    ).first()
    markdown = _render_markdown(candidate)
    ingest_result = ingest_markdown_memory(
        markdown=markdown,
        project_id=project_id,
        display_name=f"Wiki - {candidate.title}.md",
        created_by_user_id=created_by_user_id,
    )
    if ingest_result.error:
        raise RuntimeError(f"project Wiki RAG ingest failed: {ingest_result.error}")

    previous_document_id = getattr(existing, "document_id", None) if existing else None
    version = int(getattr(existing, "current_version", 0) or 0) + 1
    if existing:
        page_id = uuid.UUID(str(existing.id))
        orm.execute(
            text("""
                UPDATE public.project_wiki_pages
                SET title = :title, page_type = :page_type, summary = :summary,
                    markdown_content = :markdown, usefulness = :usefulness,
                    confidence = :confidence, current_version = :version,
                    document_id = :document_id, updated_at = now()
                WHERE id = :page_id
            """),
            {
                "page_id": str(page_id),
                "title": candidate.title,
                "page_type": candidate.page_type,
                "summary": candidate.summary,
                "markdown": markdown,
                "usefulness": candidate.usefulness,
                "confidence": candidate.confidence,
                "version": version,
                "document_id": str(ingest_result.document_id),
            },
        )
    else:
        row = orm.execute(
            text("""
                INSERT INTO public.project_wiki_pages (
                    project_id, page_key, title, page_type, summary,
                    markdown_content, usefulness, confidence, current_version,
                    document_id, created_by_user_id
                )
                VALUES (
                    :project_id, :page_key, :title, :page_type, :summary,
                    :markdown, :usefulness, :confidence, :version,
                    :document_id, :user_id
                )
                RETURNING id::text
            """),
            {
                "project_id": str(project_id),
                "page_key": candidate.page_key,
                "title": candidate.title,
                "page_type": candidate.page_type,
                "summary": candidate.summary,
                "markdown": markdown,
                "usefulness": candidate.usefulness,
                "confidence": candidate.confidence,
                "version": version,
                "document_id": str(ingest_result.document_id),
                "user_id": str(created_by_user_id) if created_by_user_id else None,
            },
        ).first()
        page_id = uuid.UUID(str(row.id))

    orm.execute(
        text("""
            INSERT INTO public.project_wiki_page_versions (
                page_id, version, markdown_content, summary, source_ids,
                change_reason, created_by_user_id
            )
            VALUES (
                :page_id, :version, :markdown, :summary,
                CAST(:source_ids AS jsonb), :reason, :user_id
            )
        """),
        {
            "page_id": str(page_id),
            "version": version,
            "markdown": markdown,
            "summary": candidate.summary,
            "source_ids": _json(candidate.source_ids),
            "reason": reason_code,
            "user_id": str(created_by_user_id) if created_by_user_id else None,
        },
    )
    orm.execute(
        text("DELETE FROM public.project_wiki_page_sources WHERE page_id = :page_id"),
        {"page_id": str(page_id)},
    )
    for source_id in candidate.source_ids:
        source_type, _, raw_id = source_id.partition(":")
        orm.execute(
            text("""
                INSERT INTO public.project_wiki_page_sources (
                    page_id, source_type, source_id
                ) VALUES (:page_id, :source_type, :source_id)
            """),
            {
                "page_id": str(page_id),
                "source_type": source_type,
                "source_id": raw_id or source_id,
            },
        )
    orm.execute(
        text("DELETE FROM public.project_wiki_links WHERE from_page_id = :page_id"),
        {"page_id": str(page_id)},
    )
    for title in candidate.link_titles:
        orm.execute(
            text("""
                INSERT INTO public.project_wiki_links (from_page_id, to_title, relation)
                VALUES (:page_id, :to_title, 'related')
            """),
            {"page_id": str(page_id), "to_title": title},
        )
    orm.execute(
        text("""
            UPDATE public.documents
            SET memory_type = 'project_wiki_page'
            WHERE id = :document_id
        """),
        {"document_id": str(ingest_result.document_id)},
    )
    if previous_document_id and str(previous_document_id) != str(ingest_result.document_id):
        orm.execute(
            text("DELETE FROM public.documents WHERE id = :document_id"),
            {"document_id": str(previous_document_id)},
        )

    if change_id:
        orm.execute(
            text("""
                UPDATE public.project_wiki_changes
                SET status = 'applied', page_id = :page_id, reviewed_at = now()
                WHERE id = :change_id
            """),
            {"change_id": str(change_id), "page_id": str(page_id)},
        )
    else:
        orm.execute(
            text("""
                INSERT INTO public.project_wiki_changes (
                    run_id, project_id, page_key, title, page_type,
                    disposition, reason_code, status, summary, proposed_markdown,
                    usefulness, confidence, contradiction, source_ids, link_titles,
                    page_id
                )
                VALUES (
                    :run_id, :project_id, :page_key, :title, :page_type,
                    'auto_apply', :reason_code, 'applied', :summary, :markdown,
                    :usefulness, :confidence, :contradiction,
                    CAST(:source_ids AS jsonb), CAST(:link_titles AS jsonb), :page_id
                )
            """),
            {
                "run_id": str(run_id),
                "project_id": str(project_id),
                "page_key": candidate.page_key,
                "title": candidate.title,
                "page_type": candidate.page_type,
                "reason_code": reason_code,
                "summary": candidate.summary,
                "markdown": markdown,
                "usefulness": candidate.usefulness,
                "confidence": candidate.confidence,
                "contradiction": candidate.contradiction,
                "source_ids": _json(candidate.source_ids),
                "link_titles": _json(candidate.link_titles),
                "page_id": str(page_id),
            },
        )
    orm.commit()
    return page_id


def _mark_sources_processed(
    orm,
    *,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    sources: list[WikiSource],
) -> None:
    for source in sources:
        orm.execute(
            text("""
                INSERT INTO public.project_wiki_processed_sources (
                    project_id, source_id, source_type, content_hash,
                    observed_at, last_run_id, processed_at
                )
                VALUES (
                    :project_id, :source_id, :source_type, :content_hash,
                    :observed_at, :run_id, now()
                )
                ON CONFLICT (project_id, source_id)
                DO UPDATE SET
                    source_type = excluded.source_type,
                    content_hash = excluded.content_hash,
                    observed_at = excluded.observed_at,
                    last_run_id = excluded.last_run_id,
                    processed_at = now()
            """),
            {
                "project_id": str(project_id),
                "source_id": source.source_id,
                "source_type": source.source_type,
                "content_hash": _source_hash(source),
                "observed_at": source.observed_at,
                "run_id": str(run_id),
            },
        )
    orm.commit()


def compile_project_wiki(
    orm,
    *,
    project_id: uuid.UUID,
    project_name: str,
    triggered_by_user_id: uuid.UUID | None,
) -> CompileResult:
    import os

    model = os.getenv("PROJECT_WIKI_MODEL", os.getenv("RAG_LLM_MODEL", "MiniMax-M3"))
    run_id = _insert_compile_run(
        orm,
        project_id=project_id,
        triggered_by_user_id=triggered_by_user_id,
        model=model,
    )
    source_count = candidate_count = auto_count = pending_count = discarded_count = 0
    try:
        limit_per_type = max(
            1,
            min(100, int(os.getenv("PROJECT_WIKI_SOURCE_LIMIT_PER_TYPE", "10"))),
        )
        sources = collect_incremental_sources(
            orm,
            project_id=project_id,
            limit_per_type=limit_per_type,
        )
        source_count = len(sources)
        if not sources:
            _finish_compile_run(
                orm,
                run_id=run_id,
                status="completed",
                source_count=0,
                candidate_count=0,
                auto_applied_count=0,
                pending_review_count=0,
                discarded_count=0,
            )
            return CompileResult(run_id, 0, 0, 0, 0, 0, model)

        existing_pages = load_existing_pages(orm, project_id)
        prompt = build_compiler_prompt(
            project_name=project_name,
            sources=sources,
            existing_pages=existing_pages,
        )
        candidates = generate_candidates(prompt)
        candidate_count = len(candidates)
        valid_source_ids = {source.source_id for source in sources}
        for candidate in candidates:
            candidate.source_ids = [
                source_id for source_id in candidate.source_ids if source_id in valid_source_ids
            ]
            decision = classify_candidate(candidate)
            if decision.disposition == "auto_apply":
                _apply_candidate(
                    orm,
                    run_id=run_id,
                    project_id=project_id,
                    candidate=candidate,
                    created_by_user_id=triggered_by_user_id,
                    reason_code=decision.reason_code,
                )
                auto_count += 1
            else:
                _persist_change(
                    orm,
                    run_id=run_id,
                    project_id=project_id,
                    candidate=candidate,
                    disposition=decision.disposition,
                    reason_code=decision.reason_code,
                )
                if decision.disposition == "pending_review":
                    pending_count += 1
                else:
                    discarded_count += 1

        _mark_sources_processed(
            orm,
            project_id=project_id,
            run_id=run_id,
            sources=sources,
        )
        _finish_compile_run(
            orm,
            run_id=run_id,
            status="completed",
            source_count=source_count,
            candidate_count=candidate_count,
            auto_applied_count=auto_count,
            pending_review_count=pending_count,
            discarded_count=discarded_count,
        )
    except Exception as error:
        logger.exception("Project Wiki compile failed for project=%s", project_id)
        try:
            orm.rollback()
        except Exception:
            pass
        _finish_compile_run(
            orm,
            run_id=run_id,
            status="failed",
            source_count=source_count,
            candidate_count=candidate_count,
            auto_applied_count=auto_count,
            pending_review_count=pending_count,
            discarded_count=discarded_count,
            error_message=str(error)[:2000],
        )
        raise

    return CompileResult(
        run_id=run_id,
        source_count=source_count,
        candidate_count=candidate_count,
        auto_applied_count=auto_count,
        pending_review_count=pending_count,
        discarded_count=discarded_count,
        model=model,
    )
