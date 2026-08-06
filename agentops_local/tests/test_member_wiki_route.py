from __future__ import annotations

import importlib.util
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


def _load_route():
    path = Path(__file__).parents[1] / "api" / "routes" / "v4" / "member_wiki.py"
    spec = importlib.util.spec_from_file_location("member_wiki_route_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row


class _Orm:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "FROM public.member_wiki_runs" in sql:
            return _Result(types.SimpleNamespace(
                id="00000000-0000-0000-0000-000000000099",
                status="completed",
                cutoff_at="2026-08-04T13:00:00+00:00",
                updated_member_count=1,
                session_count=2,
                experience_count=1,
                completed_at="2026-08-04T13:02:00+00:00",
            ))
        return _Result()


class MemberWikiRouteTests(unittest.TestCase):
    def test_router_uses_authenticated_route(self) -> None:
        route = _load_route()
        self.assertIs(route.router.route_class, route.AuthenticatedRoute)

    def test_regular_member_requesting_another_member_is_rejected(self) -> None:
        route = _load_route()
        orm = _Orm()
        current = route.MemberIdentity(
            user_id="user-1", employee_id="test1", name="张三", email="test1@local.dev"
        )
        context = route.MemberAccessContext(
            is_admin=False, current=current, accessible_members=(current,)
        )

        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "load_member_access_context", return_value=context),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.get_member_wiki_overview(
                    request=types.SimpleNamespace(client=None),
                    employee_id="test2",
                    query="",
                    task_type=None,
                    outcome=None,
                    tag=None,
                    limit=50,
                    orm=orm,
                )
        self.assertEqual(raised.exception.status_code, 403)

    def test_admin_overview_is_scoped_to_selected_accessible_member(self) -> None:
        route = _load_route()
        orm = _Orm()
        admin = route.MemberIdentity(
            user_id="admin-1", employee_id="admin", name="管理员", email="admin@agentops.local"
        )
        member = route.MemberIdentity(
            user_id="user-1", employee_id="test1", name="张三", email="test1@local.dev"
        )
        context = route.MemberAccessContext(
            is_admin=True, current=admin, accessible_members=(member,)
        )
        hit = types.SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
            employee_id="test1", employee_name="张三",
            experience_key="deploy-dashboard", title="部署 Dashboard",
            task_type="deployment", outcome="success", summary="完成部署",
            markdown_content="# 部署 Dashboard", tags=["deployment"], tools=["Docker"],
            confidence=0.93, first_observed="2026-08-03", last_observed="2026-08-04",
            observation_count=2, current_version=2, updated_at="2026-08-04T13:00:00+00:00",
            lexical_score=0.8, vector_score=None,
        )

        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "load_member_access_context", return_value=context),
            patch.object(route, "search_member_experiences", return_value=[hit]) as search,
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.get_member_wiki_overview(
                request=types.SimpleNamespace(client=None),
                employee_id="test1",
                query="部署",
                task_type=None,
                outcome="success",
                tag="deployment",
                limit=50,
                orm=orm,
            )

        self.assertEqual(response.member.employee_id, "test1")
        self.assertEqual(response.summary.experience_count, 1)
        self.assertEqual(response.experiences[0].experience_key, "deploy-dashboard")
        self.assertEqual(search.call_args.kwargs["employee_ids"], ["test1"])


if __name__ == "__main__":
    unittest.main()
