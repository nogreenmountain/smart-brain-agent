from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_route():
    path = Path(
        os.environ.get(
            "PROJECT_WIKI_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "project_wiki.py",
        )
    )
    spec = importlib.util.spec_from_file_location("project_wiki_route_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _Orm:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.calls.append((sql, values))
        if "SELECT name FROM public.projects" in sql:
            return _Result(SimpleNamespace(name="智慧大脑"))
        if "FROM public.project_wiki_changes" in sql and "FOR UPDATE" in sql:
            return _Result(
                SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000040",
                    run_id="00000000-0000-0000-0000-000000000099",
                    project_id="00000000-0000-0000-0000-000000000010",
                    page_key="decision-abc",
                    title="权限口径",
                    page_type="decision",
                    memory_kind="decision_record",
                    tags=["permissions", "installation"],
                    valid_from="2026-08-03",
                    valid_until=None,
                    status="pending_review",
                    summary="项目成员才能访问。",
                    proposed_markdown="# 权限口径\n\n项目成员才能访问。",
                    usefulness=0.95,
                    confidence=0.96,
                    contradiction=False,
                    source_ids=["document:doc-1"],
                    link_titles=["项目权限"],
                    reason_code="mcp_proposal",
                    triggered_by_user_id="00000000-0000-0000-0000-000000000002",
                )
            )
        return _Result()

    def commit(self):
        self.commits += 1


class _TokenOrm(_Orm):
    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.calls.append((sql, values))
        if "INSERT INTO public.wiki_mcp_tokens" in sql:
            return _Result(SimpleNamespace(
                id="00000000-0000-0000-0000-000000000050",
                created_at="2026-08-03T04:00:00+00:00",
                expires_at="2026-11-01T04:00:00+00:00",
            ))
        return _Result()


class ProjectWikiRouteTests(unittest.TestCase):
    def test_overview_allows_any_authenticated_user(self) -> None:
        route = _load_route()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        class ReadOrm:
            def execute(self, statement, params=None):
                sql = str(statement)
                if "FROM public.project_wiki_compile_runs" in sql:
                    return _Result()
                if "SELECT count(*) FROM public.project_wiki_pages" in sql:
                    return _Result(SimpleNamespace(
                        page_count=0,
                        pending_count=0,
                        source_count=0,
                        link_count=0,
                    ))
                return _Result(rows=[])

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "_project", return_value=SimpleNamespace(
                id=project_id,
                name="Global Project",
                department_id="research",
            )),
            patch.object(route, "_can_review", return_value=False),
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.get_wiki_overview(
                request=SimpleNamespace(state=SimpleNamespace()),
                project_id=project_id,
                orm=ReadOrm(),
            )

        self.assertEqual(response.project.name, "Global Project")
        self.assertFalse(response.permissions["can_review"])

    def test_compile_requires_project_admin_and_returns_counts(self) -> None:
        route = _load_route()
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        result = SimpleNamespace(
            run_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
            source_count=4,
            candidate_count=3,
            auto_applied_count=1,
            pending_review_count=1,
            discarded_count=1,
            model="MiniMax-M3",
        )

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_admin", return_value=None) as require_admin,
            patch.object(route, "compile_project_wiki", return_value=result) as compile_wiki,
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.compile_wiki_now(
                request=SimpleNamespace(state=SimpleNamespace()),
                body=route.CompileWikiRequest(project_id=project_id),
                orm=orm,
            )

        require_admin.assert_called_once_with(orm, user_id=user_id, project_id=project_id)
        compile_wiki.assert_called_once()
        self.assertEqual(response.auto_applied_count, 1)
        self.assertEqual(response.pending_review_count, 1)
        self.assertEqual(response.discarded_count, 1)

    def test_reject_pending_change_does_not_apply_page(self) -> None:
        route = _load_route()
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        change_id = uuid.UUID("00000000-0000-0000-0000-000000000040")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "_apply_candidate") as apply_candidate,
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.review_wiki_change(
                request=SimpleNamespace(state=SimpleNamespace()),
                change_id=change_id,
                body=route.ReviewWikiChangeRequest(decision="reject", comment="证据不足"),
                orm=orm,
            )

        apply_candidate.assert_not_called()
        self.assertEqual(response.status, "rejected")
        self.assertTrue(any("status = 'rejected'" in sql for sql, _ in orm.calls))

    def test_approve_pending_change_preserves_memory_metadata(self) -> None:
        route = _load_route()
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        change_id = uuid.UUID("00000000-0000-0000-0000-000000000040")
        page_id = uuid.UUID("00000000-0000-0000-0000-000000000041")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "_apply_candidate", return_value=page_id) as apply_candidate,
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.review_wiki_change(
                request=SimpleNamespace(state=SimpleNamespace()),
                change_id=change_id,
                body=route.ReviewWikiChangeRequest(decision="approve", comment="approved"),
                orm=orm,
            )

        candidate = apply_candidate.call_args.kwargs["candidate"]
        self.assertEqual(candidate.memory_kind, "decision_record")
        self.assertEqual(candidate.tags, ["permissions", "installation"])
        self.assertEqual(candidate.valid_from, "2026-08-03")
        self.assertEqual(
            apply_candidate.call_args.kwargs["created_by_user_id"],
            uuid.UUID("00000000-0000-0000-0000-000000000002"),
        )
        self.assertEqual(response.status, "applied")
        self.assertEqual(response.page_id, page_id)

    def test_change_response_exposes_uploader_identity(self) -> None:
        route = _load_route()
        response = route._change_from_row(SimpleNamespace(
            id="00000000-0000-0000-0000-000000000040",
            title="MCP 提案",
            page_type="note",
            memory_kind="reference",
            tags=[],
            reason_code="mcp_proposal",
            status="pending_review",
            summary="",
            proposed_markdown="# MCP 提案",
            usefulness=0.8,
            confidence=0.75,
            contradiction=False,
            source_ids=[],
            link_titles=[],
            uploaded_by={
                "user_id": "00000000-0000-0000-0000-000000000002",
                "name": "唐伟翔",
                "email": "tangweixiang@local.dev",
            },
            created_at="2026-08-06T00:00:00+00:00",
        ))

        self.assertEqual(response.uploaded_by.name, "唐伟翔")
        self.assertEqual(response.uploaded_by.email, "tangweixiang@local.dev")

    def test_create_mcp_token_returns_secret_once_and_persists_only_hash(self) -> None:
        route = _load_route()
        orm = _TokenOrm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "_mcp_token_secret", return_value="server-secret"),
            patch.object(route, "issue_token", return_value=("sbmcp_visible-once", "stored-digest")),
        ):
            response = route.create_mcp_token(
                request=SimpleNamespace(state=SimpleNamespace()),
                body=route.CreateMcpTokenRequest(
                    name="Codex",
                    scopes=["wiki:read", "wiki:propose"],
                    expires_days=90,
                ),
                orm=orm,
            )

        self.assertEqual(response.token, "sbmcp_visible-once")
        insert_params = next(values for sql, values in orm.calls if "INSERT INTO public.wiki_mcp_tokens" in sql)
        self.assertEqual(insert_params["token_hash"], "stored-digest")
        self.assertNotIn("sbmcp_visible-once", insert_params.values())


if __name__ == "__main__":
    unittest.main()
