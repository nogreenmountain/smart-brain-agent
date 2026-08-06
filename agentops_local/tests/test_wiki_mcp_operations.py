from __future__ import annotations

import importlib.util
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_module():
    path = Path(__file__).parents[1] / "wiki_mcp" / "operations.py"
    spec = importlib.util.spec_from_file_location("wiki_mcp_operations_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Orm:
    def __init__(self, projects=None, user=None):
        self.projects = projects or []
        self.user = user
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "FROM public.project_members" in sql and "JOIN public.projects" in sql:
            return _Result(rows=self.projects)
        if "FROM auth.users" in sql:
            return _Result(row=self.user)
        return _Result()


class WikiMcpOperationsTests(unittest.TestCase):
    def test_search_uses_only_accessible_project_and_returns_compact_hits(self) -> None:
        module = _load_module()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        orm = _Orm([SimpleNamespace(id=str(project_id), name="SmartBrain", role="developer")])

        @contextmanager
        def session_factory():
            yield orm

        service = module.WikiOperations(session_factory=session_factory)
        hit = SimpleNamespace(
            page_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
            title="Deployment rollback",
            page_type="troubleshooting",
            memory_kind="failure_case",
            tags=["deploy"],
            summary="Rollback when health checks fail.",
            matched_excerpt="Health check failed after rollout.",
            score=0.93,
            usefulness=0.95,
            confidence=0.9,
            verification_status="verified",
            current_version=2,
            updated_at="2026-08-03T04:00:00+00:00",
        )

        with (
            patch.object(module, "require_member", return_value=None) as require_member,
            patch.object(module, "query_search_wiki", return_value=[hit]),
        ):
            result = service.search(
                user_id=user_id,
                query="rollback",
                project_id=None,
            )

        require_member.assert_called_once_with(orm, user_id=user_id, project_id=project_id)
        self.assertEqual(result["project_id"], str(project_id))
        self.assertEqual(result["items"][0]["page_id"], str(hit.page_id))
        self.assertEqual(result["items"][0]["memory_kind"], "failure_case")

    def test_search_requires_project_when_user_has_multiple_projects(self) -> None:
        module = _load_module()
        orm = _Orm([
            SimpleNamespace(id="00000000-0000-0000-0000-000000000010", name="A", role="owner"),
            SimpleNamespace(id="00000000-0000-0000-0000-000000000011", name="B", role="developer"),
        ])

        @contextmanager
        def session_factory():
            yield orm

        service = module.WikiOperations(session_factory=session_factory)
        with self.assertRaisesRegex(ValueError, "project_id"):
            service.search(
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                query="deployment",
                project_id=None,
            )

    def test_proposal_requires_scope_and_enters_pending_review(self) -> None:
        module = _load_module()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        change_id = uuid.UUID("00000000-0000-0000-0000-000000000040")
        orm = _Orm(user=SimpleNamespace(
            user_id=str(user_id),
            email="uploader@local.dev",
            name="上传人昵称",
        ))

        @contextmanager
        def session_factory():
            yield orm

        service = module.WikiOperations(session_factory=session_factory)
        with self.assertRaisesRegex(PermissionError, "wiki:propose"):
            service.propose(
                user_id=user_id,
                scopes=["wiki:read"],
                project_id=str(project_id),
                title="Rollback checklist",
                memory_kind="checklist",
                content="# Rollback checklist\n\n1. Stop rollout",
            )

        with (
            patch.object(module, "require_member", return_value=None),
            patch.object(module, "create_memory_proposal", return_value=change_id) as create,
        ):
            result = service.propose(
                user_id=user_id,
                scopes=["wiki:read", "wiki:propose"],
                project_id=str(project_id),
                title="Rollback checklist",
                memory_kind="checklist",
                content="# Rollback checklist\n\n1. Stop rollout",
            )

        create.assert_called_once()
        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(result["change_id"], str(change_id))
        self.assertEqual(result["uploaded_by"]["user_id"], str(user_id))
        self.assertEqual(result["uploaded_by"]["name"], "上传人昵称")
        self.assertEqual(result["uploaded_by"]["email"], "uploader@local.dev")


if __name__ == "__main__":
    unittest.main()
