from __future__ import annotations

import os
import uuid
from contextlib import AbstractContextManager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import text

from agentops.project_wiki.query import (
    get_decision_records as query_decision_records,
    get_examples as query_examples,
    get_page as query_get_page,
    get_recent_updates as query_recent_updates,
    get_related_nodes as query_related_nodes,
    search_wiki as query_search_wiki,
)
from agentops.project_wiki.service import create_memory_proposal
from agentops.member_wiki.access import (
    MemberWikiAccessError,
    load_member_access_context,
    resolve_member_scope,
)
from agentops.member_wiki.query import (
    get_member_experience as query_get_member_experience,
    search_member_experiences,
)
from agentops.meeting_summaries.query import (
    get_meeting_summary as query_get_meeting_summary,
    search_meeting_summaries as query_search_meeting_summaries,
)
from agentops.rag.authz import require_member


SessionFactory = Callable[[], AbstractContextManager]


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "__dict__"):
        return _json_value(vars(value))
    return value


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError as error:
        raise ValueError("time filters must use ISO 8601 format") from error


def _member_hit_summary(item: Any) -> dict[str, Any]:
    return {
        "experience_id": str(item.id),
        "member_id": item.employee_id,
        "member_name": item.employee_name,
        "experience_key": item.experience_key,
        "title": item.title,
        "task_type": item.task_type,
        "outcome": item.outcome,
        "summary": item.summary,
        "tags": list(item.tags),
        "tools": list(item.tools),
        "confidence": item.confidence,
        "first_observed": str(item.first_observed),
        "last_observed": str(item.last_observed),
        "observation_count": item.observation_count,
        "current_version": item.current_version,
        "updated_at": str(item.updated_at),
        "lexical_score": item.lexical_score,
        "vector_score": item.vector_score,
    }


def _meeting_hit_summary(item: Any, *, include_markdown: bool = False) -> dict[str, Any]:
    result = {
        "meeting_summary_id": str(item.id),
        "project_id": str(item.project_id),
        "project_name": item.project_name,
        "title": item.title,
        "meeting_date": str(item.meeting_date),
        "participant_user_ids": [str(value) for value in item.participant_user_ids],
        "participants": list(item.participants),
        "tags": list(item.tags),
        "decisions": list(item.decisions),
        "action_items": list(item.action_items),
        "source_filename": item.source_filename,
        "source_format": item.source_format,
        "source_size_bytes": item.source_size_bytes,
        "created_by_name": item.created_by_name,
        "created_at": str(item.created_at),
        "updated_at": str(item.updated_at),
        "lexical_score": item.lexical_score,
        "vector_score": item.vector_score,
    }
    if include_markdown:
        result["summary_markdown"] = item.summary_markdown
    else:
        result["summary_excerpt"] = item.summary_markdown[:800]
    return result


class WikiOperations:
    def __init__(self, *, session_factory: SessionFactory) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _project_rows(orm, user_id: uuid.UUID):
        return orm.execute(
            text("""
                SELECT p.id::text, p.name, pm.role::text AS role
                FROM public.project_members pm
                JOIN public.projects p ON p.id = pm.project_id
                WHERE pm.user_id = :user_id
                ORDER BY p.name, p.id
            """),
            {"user_id": str(user_id)},
        ).all()

    def _resolve_project(
        self,
        orm,
        *,
        user_id: uuid.UUID,
        project_id: str | uuid.UUID | None,
        node_id: str | uuid.UUID | None = None,
    ) -> uuid.UUID:
        selected = project_id or os.getenv("WIKI_MCP_DEFAULT_PROJECT_ID", "").strip() or None
        if selected is None and node_id is not None:
            row = orm.execute(
                text("""
                    SELECT project_id::text
                    FROM public.project_wiki_pages
                    WHERE id = :node_id AND status = 'active'
                """),
                {"node_id": str(node_id)},
            ).first()
            selected = row.project_id if row else None
        if selected is None:
            projects = self._project_rows(orm, user_id)
            if len(projects) == 1:
                selected = projects[0].id
            elif not projects:
                raise ValueError("This account has no accessible projects")
            else:
                names = ", ".join(f"{row.name} ({row.id})" for row in projects[:8])
                raise ValueError(f"project_id is required; accessible projects: {names}")
        try:
            resolved = uuid.UUID(str(selected))
        except ValueError as error:
            raise ValueError("project_id must be a UUID") from error
        require_member(orm, user_id=user_id, project_id=resolved)
        return resolved

    def list_projects(self, *, user_id: uuid.UUID) -> dict[str, Any]:
        with self.session_factory() as orm:
            rows = self._project_rows(orm, user_id)
        return {
            "items": [
                {"project_id": str(row.id), "name": str(row.name), "role": str(row.role)}
                for row in rows
            ]
        }

    @staticmethod
    def _user_identity(orm, user_id: uuid.UUID) -> dict[str, str]:
        row = orm.execute(
            text("""
                SELECT au.id::text AS user_id, au.email,
                       COALESCE(
                           NULLIF(BTRIM(pu.nickname), ''),
                           NULLIF(BTRIM(pu.full_name), ''),
                           au.email,
                           au.id::text
                       ) AS name
                FROM auth.users au
                LEFT JOIN public.users pu ON pu.id = au.id
                WHERE au.id = :user_id
            """),
            {"user_id": str(user_id)},
        ).first()
        if row is None:
            return {"user_id": str(user_id), "name": str(user_id), "email": ""}
        return {
            "user_id": str(row.user_id),
            "name": str(row.name),
            "email": str(row.email or ""),
        }

    @staticmethod
    def _member_ids(context, member: str | None) -> tuple[list[str], dict[str, Any] | None]:
        if member:
            try:
                resolved = resolve_member_scope(
                    is_admin=context.is_admin,
                    current=context.current,
                    accessible_members=context.accessible_members,
                    requested_member=member,
                )
            except MemberWikiAccessError as error:
                raise PermissionError(error.detail) from error
            return [resolved.employee_id], _json_value(resolved)
        if context.is_admin:
            return [item.employee_id for item in context.accessible_members], None
        return [context.current.employee_id], _json_value(context.current)

    def list_member_wikis(self, *, user_id: uuid.UUID) -> dict[str, Any]:
        with self.session_factory() as orm:
            context = load_member_access_context(orm, user_id=user_id)
            member_ids = [item.employee_id for item in context.accessible_members]
            rows = []
            if member_ids:
                rows = orm.execute(
                    text("""
                        SELECT employee_id, count(*) AS experience_count,
                               max(last_observed) AS last_observed,
                               max(updated_at) AS updated_at
                        FROM public.member_wiki_experiences
                        WHERE status = 'active'
                          AND employee_id = ANY(CAST(:employee_ids AS text[]))
                        GROUP BY employee_id
                    """),
                    {"employee_ids": member_ids},
                ).all()
        counts = {str(row.employee_id): row for row in rows}
        return {
            "mode": "admin" if context.is_admin else "self",
            "items": [
                {
                    "member_id": member.employee_id,
                    "member_name": member.name,
                    "email": member.email,
                    "experience_count": int(counts[member.employee_id].experience_count)
                    if member.employee_id in counts else 0,
                    "last_observed": str(counts[member.employee_id].last_observed)
                    if member.employee_id in counts and counts[member.employee_id].last_observed else None,
                    "updated_at": str(counts[member.employee_id].updated_at)
                    if member.employee_id in counts and counts[member.employee_id].updated_at else None,
                }
                for member in context.accessible_members
            ],
        }

    @staticmethod
    def _query_embedding(query: str) -> list[float] | None:
        if not query.strip():
            return None
        try:
            from agentops.rag.model_clients import EmbeddingServiceClient

            return EmbeddingServiceClient().embed_query(query)
        except Exception:
            return None

    def search_member(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        member: str | None = None,
        tags: list[str] | None = None,
        outcome: str | None = None,
        task_type: str | None = None,
        updated_after: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        if outcome and outcome not in {"success", "partial", "failure"}:
            raise ValueError("outcome must be success, partial, or failure")
        with self.session_factory() as orm:
            context = load_member_access_context(orm, user_id=user_id)
            employee_ids, resolved_member = self._member_ids(context, member)
            items = search_member_experiences(
                orm,
                employee_ids=employee_ids,
                query=query,
                tags=tags,
                outcome=outcome,
                task_type=task_type,
                updated_after=_parse_datetime(updated_after),
                limit=limit,
                query_embedding=self._query_embedding(query),
            )
        return {
            "member": resolved_member,
            "searched_member_count": len(employee_ids),
            "items": [_member_hit_summary(item) for item in items],
        }

    def get_member_experience(
        self,
        *,
        user_id: uuid.UUID,
        experience_id: str,
    ) -> dict[str, Any]:
        try:
            parsed_id = uuid.UUID(experience_id)
        except ValueError as error:
            raise ValueError("experience_id must be a UUID") from error
        with self.session_factory() as orm:
            context = load_member_access_context(orm, user_id=user_id)
            employee_ids, _ = self._member_ids(context, None)
            item = query_get_member_experience(
                orm,
                experience_id=parsed_id,
                employee_ids=employee_ids,
            )
        if item is None:
            raise ValueError("member Wiki experience not found or not accessible")
        result = _member_hit_summary(item)
        result["markdown_content"] = item.markdown_content
        return result

    def recent_member_experience(
        self,
        *,
        user_id: uuid.UUID,
        member: str | None = None,
        since: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        with self.session_factory() as orm:
            context = load_member_access_context(orm, user_id=user_id)
            employee_ids, resolved_member = self._member_ids(context, member)
            items = search_member_experiences(
                orm,
                employee_ids=employee_ids,
                updated_after=_parse_datetime(since),
                limit=limit,
                query_embedding=None,
            )
        return {
            "member": resolved_member,
            "searched_member_count": len(employee_ids),
            "items": [_member_hit_summary(item) for item in items],
        }

    def list_meeting_summaries(
        self,
        *,
        user_id: uuid.UUID,
        project_id: str | None = None,
        since: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        parsed_since = _parse_datetime(since)
        with self.session_factory() as orm:
            resolved = self._resolve_project(orm, user_id=user_id, project_id=project_id)
            items = query_search_meeting_summaries(
                orm,
                project_ids=[resolved],
                meeting_date_from=parsed_since.date() if parsed_since else None,
                limit=limit,
            )
        return {
            "project_id": str(resolved),
            "items": [_meeting_hit_summary(item) for item in items],
        }

    def search_meeting_summaries(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        project_id: str | None = None,
        tags: list[str] | None = None,
        since: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        parsed_since = _parse_datetime(since)
        with self.session_factory() as orm:
            resolved = self._resolve_project(orm, user_id=user_id, project_id=project_id)
            items = query_search_meeting_summaries(
                orm,
                project_ids=[resolved],
                query=query,
                tags=tags,
                meeting_date_from=parsed_since.date() if parsed_since else None,
                limit=limit,
                query_embedding=self._query_embedding(query),
            )
        return {
            "project_id": str(resolved),
            "items": [_meeting_hit_summary(item) for item in items],
        }

    def get_meeting_summary(
        self,
        *,
        user_id: uuid.UUID,
        meeting_summary_id: str,
    ) -> dict[str, Any]:
        try:
            parsed_id = uuid.UUID(meeting_summary_id)
        except ValueError as error:
            raise ValueError("meeting_summary_id must be a UUID") from error
        with self.session_factory() as orm:
            row = orm.execute(
                text("SELECT project_id::text FROM public.meeting_summaries WHERE id = :id"),
                {"id": str(parsed_id)},
            ).first()
            if row is None:
                raise ValueError("meeting summary not found or not accessible")
            resolved = self._resolve_project(
                orm,
                user_id=user_id,
                project_id=str(row.project_id),
            )
            item = query_get_meeting_summary(
                orm,
                summary_id=parsed_id,
                project_ids=[resolved],
            )
        if item is None:
            raise ValueError("meeting summary not found or not accessible")
        return _meeting_hit_summary(item, include_markdown=True)

    def search(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        project_id: str | None = None,
        memory_kinds: list[str] | None = None,
        tags: list[str] | None = None,
        updated_after: str | None = None,
        verified_only: bool = False,
        limit: int = 8,
    ) -> dict[str, Any]:
        with self.session_factory() as orm:
            resolved = self._resolve_project(orm, user_id=user_id, project_id=project_id)
            items = query_search_wiki(
                orm,
                query=query,
                project_id=resolved,
                memory_kinds=memory_kinds,
                tags=tags,
                updated_after=_parse_datetime(updated_after),
                verified_only=verified_only,
                limit=limit,
            )
        return {"project_id": str(resolved), "items": _json_value(items)}

    def get_page(
        self,
        *,
        user_id: uuid.UUID,
        page_id: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            node_id = uuid.UUID(page_id)
        except ValueError as error:
            raise ValueError("page_id must be a UUID") from error
        with self.session_factory() as orm:
            resolved = self._resolve_project(
                orm,
                user_id=user_id,
                project_id=project_id,
                node_id=node_id,
            )
            page = query_get_page(orm, page_id=node_id, project_id=resolved)
        if page is None:
            raise ValueError("Wiki page not found")
        return _json_value(page)

    def related(
        self,
        *,
        user_id: uuid.UUID,
        node_id: str,
        project_id: str | None = None,
        relation: str | None = None,
        depth: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            parsed_node_id = uuid.UUID(node_id)
        except ValueError as error:
            raise ValueError("node_id must be a UUID") from error
        with self.session_factory() as orm:
            resolved = self._resolve_project(
                orm,
                user_id=user_id,
                project_id=project_id,
                node_id=parsed_node_id,
            )
            items = query_related_nodes(
                orm,
                node_id=parsed_node_id,
                project_id=resolved,
                relation=relation,
                depth=depth,
                limit=limit,
            )
        return {"project_id": str(resolved), "items": _json_value(items)}

    def recent(
        self,
        *,
        user_id: uuid.UUID,
        project_id: str | None = None,
        since: str | None = None,
        memory_kinds: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        with self.session_factory() as orm:
            resolved = self._resolve_project(orm, user_id=user_id, project_id=project_id)
            items = query_recent_updates(
                orm,
                project_id=resolved,
                since=_parse_datetime(since),
                memory_kinds=memory_kinds,
                limit=limit,
            )
        return {"project_id": str(resolved), "items": _json_value(items)}

    def decisions(
        self,
        *,
        user_id: uuid.UUID,
        project_id: str | None = None,
        topic: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        with self.session_factory() as orm:
            resolved = self._resolve_project(orm, user_id=user_id, project_id=project_id)
            items = query_decision_records(
                orm,
                project_id=resolved,
                topic=topic,
                limit=limit,
            )
        return {"project_id": str(resolved), "items": _json_value(items)}

    def examples(
        self,
        *,
        user_id: uuid.UUID,
        topic: str,
        project_id: str | None = None,
        outcome: str = "any",
        limit: int = 8,
    ) -> dict[str, Any]:
        if outcome not in {"any", "failure", "success"}:
            raise ValueError("outcome must be any, failure, or success")
        with self.session_factory() as orm:
            resolved = self._resolve_project(orm, user_id=user_id, project_id=project_id)
            items = query_examples(
                orm,
                topic=topic,
                project_id=resolved,
                outcome=outcome,
                limit=limit,
            )
        return {"project_id": str(resolved), "items": _json_value(items)}

    def propose(
        self,
        *,
        user_id: uuid.UUID,
        scopes: list[str],
        project_id: str,
        title: str,
        memory_kind: str,
        content: str,
        summary: str = "",
        tags: list[str] | None = None,
        source_page_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if "wiki:propose" not in scopes:
            raise PermissionError("This token requires the wiki:propose scope")
        source_ids: list[uuid.UUID] = []
        try:
            source_ids = [uuid.UUID(item) for item in (source_page_ids or [])]
        except ValueError as error:
            raise ValueError("source_page_ids must contain UUIDs") from error
        with self.session_factory() as orm:
            resolved = self._resolve_project(orm, user_id=user_id, project_id=project_id)
            uploaded_by = self._user_identity(orm, user_id)
            if source_ids:
                rows = orm.execute(
                    text("""
                        SELECT id::text
                        FROM public.project_wiki_pages
                        WHERE project_id = :project_id AND status = 'active'
                          AND id = ANY(CAST(:source_ids AS uuid[]))
                    """),
                    {"project_id": str(resolved), "source_ids": [str(item) for item in source_ids]},
                ).all()
                if len(rows) != len(set(source_ids)):
                    raise ValueError("Every source page must exist in the selected project")
            page_id = create_memory_proposal(
                orm,
                project_id=resolved,
                proposed_by_user_id=user_id,
                title=title,
                memory_kind=memory_kind,
                content=content,
                summary=summary,
                tags=tags,
                source_page_ids=source_ids,
            )
        return {
            "page_id": str(page_id),
            "project_id": str(resolved),
            "status": "published",
            "uploaded_by": uploaded_by,
            "message": "Memory passed safety checks and was published directly to the project Wiki.",
        }
