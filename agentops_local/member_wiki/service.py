from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

try:
    from sqlalchemy import text
except ModuleNotFoundError:
    def text(value: str) -> str:
        return value

try:
    from agentops.member_wiki.compiler import (
        ExistingExperienceSummary,
        MemberWikiConversation,
        MemberWikiMessage,
        compile_experiences,
        model_name,
    )
    from agentops.member_wiki.domain import (
        MemberExperience,
        experience_from_dict,
        experience_to_dict,
        merge_experience,
        render_experience_markdown,
    )
except ModuleNotFoundError:  # Standalone unit tests.
    root = Path(__file__).parent

    def _load(name: str):
        path = root / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"member_wiki_{name}_for_service", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    _domain = _load("domain")
    _compiler = _load("compiler")
    ExistingExperienceSummary = _compiler.ExistingExperienceSummary
    MemberWikiConversation = _compiler.MemberWikiConversation
    MemberWikiMessage = _compiler.MemberWikiMessage
    compile_experiences = _compiler.compile_experiences
    model_name = _compiler.model_name
    MemberExperience = _domain.MemberExperience
    experience_from_dict = _domain.experience_from_dict
    experience_to_dict = _domain.experience_to_dict
    merge_experience = _domain.merge_experience
    render_experience_markdown = _domain.render_experience_markdown


logger = logging.getLogger(__name__)
SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


def _default_embed_text(value: str) -> list[float] | None:
    try:
        from agentops.rag.model_clients import EmbeddingServiceClient

        return EmbeddingServiceClient().embed_documents([value])[0]
    except Exception:
        logger.exception("member Wiki embedding failed; storing keyword-searchable experience")
        return None


def _embedding_literal(value: list[float] | None) -> str | None:
    if value is None:
        return None
    return json.dumps([float(item) for item in value], separators=(",", ":"))


@dataclass(frozen=True)
class MemberWikiRunResult:
    run_id: uuid.UUID
    candidate_member_count: int
    updated_member_count: int
    empty_member_count: int
    session_count: int
    experience_count: int
    failure_count: int


def _json(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _create_run(orm, cutoff: datetime) -> uuid.UUID:
    row = orm.execute(
        text("""
            INSERT INTO public.member_wiki_runs (
                cutoff_at, timezone, status, model, started_at
            ) VALUES (
                :cutoff_at, 'Asia/Shanghai', 'running', :model, now()
            )
            RETURNING id::text
        """),
        {"cutoff_at": cutoff, "model": model_name()},
    ).first()
    return uuid.UUID(str(row.id))


def _source_conversations(orm, *, cutoff: datetime) -> list[MemberWikiConversation]:
    session_limit = max(int(os.getenv("MEMBER_WIKI_SESSION_LIMIT", "500")), 1)
    rows = orm.execute(
        text("""
            WITH selected AS (
                SELECT s.id, s.employee_id, s.employee_name, s.title, s.source,
                       s.task_id, s.task_title, s.model, s.trace_id, s.started_at
                FROM public.ai_chat_sessions s
                LEFT JOIN public.member_wiki_processed_sessions processed
                  ON processed.session_id = s.id
                WHERE processed.session_id IS NULL
                  AND s.started_at < :cutoff
                  AND EXISTS (
                      SELECT 1 FROM public.ai_chat_messages source_message
                      WHERE source_message.session_id = s.id
                  )
                ORDER BY s.started_at, s.id
                LIMIT :session_limit
            )
            SELECT selected.id::text AS session_id,
                   selected.employee_id, selected.employee_name,
                   selected.title, selected.source, selected.task_id,
                   selected.task_title, selected.model, selected.trace_id,
                   selected.started_at, m.role, m.content, m.sequence_index
            FROM selected
            JOIN public.ai_chat_messages m ON m.session_id = selected.id
            ORDER BY selected.started_at, selected.id, m.sequence_index
        """),
        {"cutoff": cutoff, "session_limit": session_limit},
    ).all()
    grouped: dict[str, dict] = {}
    for row in rows:
        session_id = str(row.session_id)
        item = grouped.setdefault(session_id, {
            "employee_id": str(row.employee_id),
            "employee_name": str(row.employee_name or row.employee_id),
            "title": str(row.title or row.task_title or "AI Agent 任务"),
            "source": str(row.source or "unknown"),
            "task_id": str(row.task_id or "unassigned"),
            "task_title": str(row.task_title or row.title or "AI Agent 任务"),
            "model": str(row.model or "unknown"),
            "trace_id": str(row.trace_id) if row.trace_id else None,
            "started_at": row.started_at,
            "messages": [],
        })
        item["messages"].append(MemberWikiMessage(
            role=str(row.role),
            content=str(row.content or ""),
        ))
    return [
        MemberWikiConversation(
            session_id=session_id,
            messages=tuple(item.pop("messages")),
            **item,
        )
        for session_id, item in grouped.items()
    ]


def _existing_summaries(orm, employee_id: str) -> list[ExistingExperienceSummary]:
    rows = orm.execute(
        text("""
            SELECT experience_key, title, summary
            FROM public.member_wiki_experiences
            WHERE employee_id = :employee_id AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 40
        """),
        {"employee_id": employee_id},
    ).all()
    return [
        ExistingExperienceSummary(
            experience_key=str(row.experience_key),
            title=str(row.title),
            summary=str(row.summary or ""),
        )
        for row in rows
    ]


def _observed_date(conversation: MemberWikiConversation) -> date:
    value = conversation.started_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI).date()


def _upsert_experience(
    orm,
    *,
    run_id: uuid.UUID,
    conversation_by_id: dict[str, MemberWikiConversation],
    employee_id: str,
    employee_name: str,
    incoming: MemberExperience,
    embed_text: Callable[[str], list[float] | None],
) -> None:
    row = orm.execute(
        text("""
            SELECT id::text, structured_content, source_session_ids,
                   source_trace_ids, first_observed, last_observed,
                   observation_count, current_version
            FROM public.member_wiki_experiences
            WHERE employee_id = :employee_id
              AND experience_key = :experience_key
            FOR UPDATE
        """),
        {"employee_id": employee_id, "experience_key": incoming.experience_key},
    ).first()

    incoming_dates = [
        _observed_date(conversation_by_id[source_id])
        for source_id in incoming.source_session_ids
        if source_id in conversation_by_id
    ]
    observed = min(incoming_dates) if incoming_dates else datetime.now(SHANGHAI).date()
    trace_ids = tuple(
        dict.fromkeys(
            conversation_by_id[source_id].trace_id
            for source_id in incoming.source_session_ids
            if source_id in conversation_by_id and conversation_by_id[source_id].trace_id
        )
    )

    if row is None:
        experience = incoming
        first_observed = min(incoming_dates) if incoming_dates else observed
        last_observed = max(incoming_dates) if incoming_dates else observed
        observation_count = max(len(incoming.source_session_ids), 1)
        version = 1
        source_session_ids = incoming.source_session_ids
        source_trace_ids = trace_ids
        markdown = render_experience_markdown(
            experience,
            employee_id=employee_id,
            employee_name=employee_name,
            first_observed=first_observed,
            last_observed=last_observed,
            observation_count=observation_count,
            source_session_ids=source_session_ids,
            source_trace_ids=source_trace_ids,
        )
        embedding = _embedding_literal(embed_text(markdown))
        inserted = orm.execute(
            text("""
                INSERT INTO public.member_wiki_experiences (
                    employee_id, employee_name, experience_key, title,
                    task_type, outcome, summary, structured_content,
                    markdown_content, tags, tools, confidence,
                    first_observed, last_observed, observation_count,
                    source_session_ids, source_trace_ids, current_version,
                    embedding, embedding_model, embedding_version,
                    status, created_at, updated_at
                ) VALUES (
                    :employee_id, :employee_name, :experience_key, :title,
                    :task_type, :outcome, :summary, CAST(:structured_content AS jsonb),
                    :markdown_content, CAST(:tags AS text[]), CAST(:tools AS text[]),
                    :confidence, :first_observed, :last_observed, :observation_count,
                    CAST(:source_session_ids AS jsonb), CAST(:source_trace_ids AS jsonb),
                    1, CAST(:embedding AS vector(1024)), :embedding_model,
                    :embedding_version, 'active', now(), now()
                )
                RETURNING id::text, current_version
            """),
            {
                "employee_id": employee_id,
                "employee_name": employee_name,
                "experience_key": experience.experience_key,
                "title": experience.title,
                "task_type": experience.task_type,
                "outcome": experience.outcome,
                "summary": experience.summary,
                "structured_content": json.dumps(experience_to_dict(experience), ensure_ascii=False),
                "markdown_content": markdown,
                "tags": list(experience.tags),
                "tools": list(experience.tools),
                "confidence": experience.confidence,
                "first_observed": first_observed,
                "last_observed": last_observed,
                "observation_count": observation_count,
                "source_session_ids": json.dumps(list(source_session_ids)),
                "source_trace_ids": json.dumps(list(source_trace_ids)),
                "embedding": embedding,
                "embedding_model": os.getenv("RAG_V2_EMBEDDING_MODEL", "BAAI/bge-m3"),
                "embedding_version": os.getenv("RAG_V2_EMBEDDING_VERSION", "2026-07-21-bge-m3"),
            },
        ).first()
        experience_id = uuid.UUID(str(inserted.id))
    else:
        existing = experience_from_dict(_json(row.structured_content) or {})
        experience = merge_experience(existing, incoming)
        previous_sessions = tuple(_json(row.source_session_ids) or [])
        previous_traces = tuple(_json(row.source_trace_ids) or [])
        source_session_ids = tuple(dict.fromkeys((*previous_sessions, *experience.source_session_ids)))
        source_trace_ids = tuple(dict.fromkeys((*previous_traces, *trace_ids)))
        first_observed = min(row.first_observed, min(incoming_dates) if incoming_dates else observed)
        last_observed = max(row.last_observed, max(incoming_dates) if incoming_dates else observed)
        observation_count = int(row.observation_count) + len(
            [item for item in incoming.source_session_ids if item not in previous_sessions]
        )
        version = int(row.current_version) + 1
        markdown = render_experience_markdown(
            experience,
            employee_id=employee_id,
            employee_name=employee_name,
            first_observed=first_observed,
            last_observed=last_observed,
            observation_count=observation_count,
            source_session_ids=source_session_ids,
            source_trace_ids=source_trace_ids,
        )
        embedding = _embedding_literal(embed_text(markdown))
        experience_id = uuid.UUID(str(row.id))
        orm.execute(
            text("""
                UPDATE public.member_wiki_experiences
                SET employee_name = :employee_name, title = :title,
                    task_type = :task_type, outcome = :outcome,
                    summary = :summary, structured_content = CAST(:structured_content AS jsonb),
                    markdown_content = :markdown_content,
                    tags = CAST(:tags AS text[]), tools = CAST(:tools AS text[]),
                    confidence = :confidence, first_observed = :first_observed,
                    last_observed = :last_observed,
                    observation_count = :observation_count,
                    source_session_ids = CAST(:source_session_ids AS jsonb),
                    source_trace_ids = CAST(:source_trace_ids AS jsonb),
                    current_version = :version,
                    embedding = COALESCE(CAST(:embedding AS vector(1024)), embedding),
                    embedding_model = CASE WHEN :embedding IS NULL THEN embedding_model ELSE :embedding_model END,
                    embedding_version = CASE WHEN :embedding IS NULL THEN embedding_version ELSE :embedding_version END,
                    status = 'active', updated_at = now()
                WHERE id = :experience_id
            """),
            {
                "experience_id": str(experience_id),
                "employee_name": employee_name,
                "title": experience.title,
                "task_type": experience.task_type,
                "outcome": experience.outcome,
                "summary": experience.summary,
                "structured_content": json.dumps(experience_to_dict(experience), ensure_ascii=False),
                "markdown_content": markdown,
                "tags": list(experience.tags),
                "tools": list(experience.tools),
                "confidence": experience.confidence,
                "first_observed": first_observed,
                "last_observed": last_observed,
                "observation_count": observation_count,
                "source_session_ids": json.dumps(list(source_session_ids)),
                "source_trace_ids": json.dumps(list(source_trace_ids)),
                "version": version,
                "embedding": embedding,
                "embedding_model": os.getenv("RAG_V2_EMBEDDING_MODEL", "BAAI/bge-m3"),
                "embedding_version": os.getenv("RAG_V2_EMBEDDING_VERSION", "2026-07-21-bge-m3"),
            },
        )

    orm.execute(
        text("""
            INSERT INTO public.member_wiki_experience_versions (
                experience_id, version, run_id, structured_content,
                markdown_content, source_session_ids, created_at
            ) VALUES (
                :experience_id, :version, :run_id, CAST(:structured_content AS jsonb),
                :markdown_content, CAST(:source_session_ids AS jsonb), now()
            )
        """),
        {
            "experience_id": str(experience_id),
            "version": version,
            "run_id": str(run_id),
            "structured_content": json.dumps(experience_to_dict(experience), ensure_ascii=False),
            "markdown_content": markdown,
            "source_session_ids": json.dumps(list(incoming.source_session_ids)),
        },
    )
    for source_id in incoming.source_session_ids:
        conversation = conversation_by_id.get(source_id)
        if conversation is None:
            continue
        orm.execute(
            text("""
                INSERT INTO public.member_wiki_experience_sources (
                    experience_id, session_id, trace_id, observed_at, source, created_at
                ) VALUES (
                    :experience_id, CAST(:session_id AS uuid), :trace_id,
                    :observed_at, :source, now()
                )
                ON CONFLICT (experience_id, session_id) DO NOTHING
            """),
            {
                "experience_id": str(experience_id),
                "session_id": source_id,
                "trace_id": conversation.trace_id,
                "observed_at": conversation.started_at,
                "source": conversation.source,
            },
        )


def _mark_processed(
    orm,
    *,
    run_id: uuid.UUID,
    conversation: MemberWikiConversation,
    experience_count: int,
) -> None:
    orm.execute(
        text("""
            INSERT INTO public.member_wiki_processed_sessions (
                session_id, employee_id, run_id, observed_at,
                experience_count, processed_at
            ) VALUES (
                CAST(:session_id AS uuid), :employee_id, :run_id,
                :observed_at, :experience_count, now()
            )
            ON CONFLICT (session_id) DO NOTHING
        """),
        {
            "session_id": conversation.session_id,
            "employee_id": conversation.employee_id,
            "run_id": str(run_id),
            "observed_at": conversation.started_at,
            "experience_count": experience_count,
        },
    )


def update_member_wikis(
    orm,
    *,
    cutoff: datetime,
    generate_text: Callable[[str], str] | None = None,
    embed_text: Callable[[str], list[float] | None] | None = None,
) -> MemberWikiRunResult:
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    run_id = _create_run(orm, cutoff)
    conversations = _source_conversations(orm, cutoff=cutoff)
    employee_ids = sorted({item.employee_id for item in conversations})
    updated_members: set[str] = set()
    empty_members: set[str] = set()
    experience_count = 0
    failure_count = 0
    embedder = embed_text or _default_embed_text

    try:
        existing_by_employee = {
            employee_id: _existing_summaries(orm, employee_id)
            for employee_id in employee_ids
        }
        conversation_by_id = {item.session_id: item for item in conversations}
        for conversation in conversations:
            try:
                experiences = compile_experiences(
                    conversation,
                    existing=existing_by_employee.get(conversation.employee_id, ()),
                    generate_text=generate_text,
                )
            except Exception:
                failure_count += 1
                logger.exception(
                    "member Wiki session compilation failed; leaving session for retry: session_id=%s employee_id=%s",
                    conversation.session_id,
                    conversation.employee_id,
                )
                continue
            for experience in experiences:
                _upsert_experience(
                    orm,
                    run_id=run_id,
                    conversation_by_id=conversation_by_id,
                    employee_id=conversation.employee_id,
                    employee_name=conversation.employee_name,
                    incoming=experience,
                    embed_text=embedder,
                )
                experience_count += 1
                updated_members.add(conversation.employee_id)
                existing_by_employee.setdefault(conversation.employee_id, []).append(
                    ExistingExperienceSummary(
                        experience_key=experience.experience_key,
                        title=experience.title,
                        summary=experience.summary,
                    )
                )
            if not experiences:
                empty_members.add(conversation.employee_id)
            _mark_processed(
                orm,
                run_id=run_id,
                conversation=conversation,
                experience_count=len(experiences),
            )
        empty_members.difference_update(updated_members)
        orm.execute(
            text("""
                UPDATE public.member_wiki_runs
                SET status = 'completed', candidate_member_count = :candidate_member_count,
                    updated_member_count = :updated_member_count,
                    empty_member_count = :empty_member_count,
                    session_count = :session_count,
                    experience_count = :experience_count,
                    failure_count = :failure_count, completed_at = now()
                WHERE id = :run_id
            """),
            {
                "run_id": str(run_id),
                "candidate_member_count": len(employee_ids),
                "updated_member_count": len(updated_members),
                "empty_member_count": len(empty_members),
                "session_count": len(conversations),
                "experience_count": experience_count,
                "failure_count": failure_count,
            },
        )
        orm.commit()
    except Exception as error:
        failure_count = 1
        orm.rollback()
        logger.exception("member Wiki update failed: cutoff=%s", cutoff)
        raise error

    return MemberWikiRunResult(
        run_id=run_id,
        candidate_member_count=len(employee_ids),
        updated_member_count=len(updated_members),
        empty_member_count=len(empty_members),
        session_count=len(conversations),
        experience_count=experience_count,
        failure_count=failure_count,
    )
