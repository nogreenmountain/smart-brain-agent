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
            change_id = create_memory_proposal(
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
            "change_id": str(change_id),
            "project_id": str(resolved),
            "status": "pending_review",
            "message": "Proposal created for administrator review; no Wiki page was published directly.",
        }
