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
                    status="pending_review",
                    summary="项目成员才能访问。",
                    proposed_markdown="# 权限口径\n\n项目成员才能访问。",
                    usefulness=0.95,
                    confidence=0.96,
                    contradiction=False,
                    source_ids=["document:doc-1"],
                    link_titles=["项目权限"],
                    reason_code="governed_page_type",
                )
            )
        return _Result()

    def commit(self):
        self.commits += 1


class ProjectWikiRouteTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
