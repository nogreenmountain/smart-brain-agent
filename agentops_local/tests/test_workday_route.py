from __future__ import annotations

import importlib.util
import os
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from agentops.rag.authz import AuthzError


def _load_route_module():
    route_path = Path(
        os.environ.get(
            "WORKDAY_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "workday.py",
        )
    )
    spec = importlib.util.spec_from_file_location(
        "workday_route_under_test",
        route_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load route module from {route_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


route = _load_route_module()


class WorkdayRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        self.user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        self.common = {
            "request": object(),
            "project_id": self.project_id,
            "employee_id": "employee-001",
            "work_date": date(2026, 7, 20),
            "include_traces": True,
            "include_replay_refs": True,
            "include_raw_metrics": True,
            "orm": object(),
            "clickhouse": object(),
        }

    def test_forbidden_project_access_is_audited(self) -> None:
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(
                route,
                "require_member",
                side_effect=AuthzError(403, "not a member"),
            ),
            patch.object(route, "_record_workday_audit") as audit,
        ):
            with self.assertRaises(HTTPException) as raised:
                route.get_workday_summary(**self.common)

        self.assertEqual(raised.exception.status_code, 403)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["result_status"], "forbidden")

    def test_aggregation_failure_is_audited_and_returns_service_error(self) -> None:
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(
                route,
                "require_member",
                return_value=SimpleNamespace(role="admin"),
            ),
            patch.object(route, "fetch_span_records", return_value=([], ())),
            patch.object(
                route,
                "aggregate_workday",
                side_effect=RuntimeError("aggregation failed"),
            ),
            patch.object(route, "_record_workday_audit") as audit,
        ):
            with self.assertRaises(HTTPException) as raised:
                route.get_workday_summary(**self.common)

        self.assertEqual(raised.exception.status_code, 503)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["result_status"], "service_error")

    def test_regular_member_cannot_request_another_employee_summary(self) -> None:
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(
                route,
                "require_member",
                return_value=SimpleNamespace(role="developer"),
            ),
            patch.object(
                route,
                "_resolve_employee_for_user",
                return_value=("employee-self", "Employee Self"),
            ),
            patch.object(route, "_record_workday_audit") as audit,
        ):
            with self.assertRaises(HTTPException) as raised:
                route.get_workday_summary(**self.common)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(
            audit.call_args.kwargs["result_status"],
            "forbidden_employee_scope",
        )


if __name__ == "__main__":
    unittest.main()
