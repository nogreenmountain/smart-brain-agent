from __future__ import annotations

import importlib.util
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_route():
    path = Path(__file__).parents[1] / "api" / "routes" / "v4" / "ai_usage.py"
    spec = importlib.util.spec_from_file_location("ai_usage_privacy_route_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def all(self):
        return self._rows


class AIUsagePrivacyTests(unittest.TestCase):
    def test_employee_options_use_nickname_and_expose_privacy_preference(self) -> None:
        route = _load_route()

        class Orm:
            def execute(self, statement, params=None):
                sql = str(statement)
                if "WHERE au.id = :uid" in sql:
                    return _Result(row=SimpleNamespace(
                        email="tangweixiang@local.dev",
                        full_name="tangweixiang",
                        nickname="唐伟翔",
                        ai_detail_visible_to_admin=True,
                    ))
                return _Result(rows=[SimpleNamespace(
                    user_id=uuid.uuid4(),
                    email="tangweixiang@local.dev",
                    full_name="tangweixiang",
                    nickname="唐伟翔",
                    ai_detail_visible_to_admin=True,
                )])

        current = route._current_employee(Orm(), uuid.uuid4())
        employees = route._employee_options(Orm())

        self.assertEqual(current.name, "唐伟翔")
        self.assertTrue(current.detail_visible_to_admin)
        self.assertEqual(employees[0].name, "唐伟翔")

    def test_admin_detail_visibility_requires_member_opt_in(self) -> None:
        route = _load_route()
        current = route.UsageEmployeeOption(
            id="hanshangbo",
            name="韩尚博",
            email="hanshangbo@local.dev",
            detail_visible_to_admin=False,
        )
        private_member = route.UsageEmployeeOption(
            id="tangweixiang",
            name="唐伟翔",
            email="tangweixiang@local.dev",
            detail_visible_to_admin=False,
        )
        public_member = private_member.model_copy(update={"detail_visible_to_admin": True})

        self.assertTrue(route._can_view_detailed_records("self", current, current))
        self.assertFalse(route._can_view_detailed_records("admin", current, private_member))
        self.assertTrue(route._can_view_detailed_records("admin", current, public_member))

    def test_statistics_view_never_exposes_another_members_details(self) -> None:
        route = _load_route()
        current = route.UsageEmployeeOption(
            id="test1", name="Test 1", email="test1@local.dev"
        )
        public_member = route.UsageEmployeeOption(
            id="test2",
            name="Test 2",
            email="test2@local.dev",
            detail_visible_to_admin=True,
        )

        self.assertFalse(
            route._can_view_detailed_records("statistics", current, public_member)
        )

    def test_regular_user_can_resolve_another_member_for_statistics_only(self) -> None:
        route = _load_route()
        user_id = uuid.uuid4()
        current = route.UsageEmployeeOption(
            id="test1", name="Test 1", email="test1@local.dev"
        )
        other = route.UsageEmployeeOption(
            id="test2", name="Test 2", email="test2@local.dev"
        )
        options = route.UsageOptionsResponse(
            mode="statistics",
            current_employee=current,
            departments=[],
            projects=[],
            employees=[current, other],
        )

        with patch.object(route, "_usage_options", return_value=options):
            mode, employee, projects = route._resolve_scope(
                object(),
                user_id=user_id,
                department_id=None,
                project_id=None,
                requested_employee_id="test2",
            )

        self.assertEqual(mode, "statistics")
        self.assertEqual(employee.id, "test2")
        self.assertEqual(projects, [])

    def test_regular_user_cannot_resolve_another_members_daily_log(self) -> None:
        route = _load_route()
        user_id = uuid.uuid4()
        current = route.UsageEmployeeOption(
            id="test1", name="Test 1", email="test1@local.dev"
        )
        other = route.UsageEmployeeOption(
            id="test2", name="Test 2", email="test2@local.dev"
        )
        options = route.UsageOptionsResponse(
            mode="statistics",
            current_employee=current,
            departments=[],
            projects=[],
            employees=[current, other],
        )

        with patch.object(route, "_usage_options", return_value=options):
            with self.assertRaises(route.HTTPException) as raised:
                route._resolve_daily_log_scope(
                    object(),
                    user_id=user_id,
                    requested_employee_id="test2",
                )

        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
