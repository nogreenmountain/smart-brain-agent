from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
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
        "workday_enrollment_route_under_test",
        route_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load route module from {route_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


route = _load_route_module()


class _Result:
    def __init__(self, row) -> None:
        self.row = row

    def first(self):
        return self.row


class _Orm:
    def __init__(self, row) -> None:
        self.row = row

    def execute(self, statement, params):
        return _Result(self.row)


class WorkdayEnrollmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        self.project_id = uuid.UUID(
            "f9505558-d67d-462f-b77e-6b9550458a2b"
        )
        self.body = route.WorkdayEnrollmentRequest(project_id=self.project_id)
        self.orm = _Orm(
            SimpleNamespace(
                email="test1@local.dev",
                full_name="Test Employee 1",
            )
        )

    def test_enrollment_identity_is_bound_to_authenticated_account(self) -> None:
        with (
            patch.object(
                route,
                "current_user_id",
                return_value=self.user_id,
            ),
            patch.object(route, "require_member") as require_member,
            patch.object(
                route,
                "mint_telemetry_token",
                return_value="header.payload.signature",
            ) as mint,
            patch.object(route, "record_audit") as audit,
            patch.dict(
                os.environ,
                {
                    "JWT_SECRET_KEY": "test-secret-with-at-least-32-characters",
                    "WORKDAY_COLLECTOR_ENDPOINT": "http://192.168.1.40:4318",
                    "WORKDAY_ENROLLMENT_TOKEN_DAYS": "30",
                },
            ),
        ):
            response = route.enroll_workday(
                request=object(),
                body=self.body,
                orm=self.orm,
            )

        require_member.assert_not_called()
        self.assertEqual(response.employee_id, "test1")
        self.assertEqual(response.employee_name, "Test Employee 1")
        self.assertEqual(
            response.collector_endpoint,
            "http://192.168.1.40:4318",
        )
        self.assertNotIn("password", response.model_dump())
        self.assertNotIn("email", response.model_dump())
        self.assertEqual(
            response.device_ingest_token,
            "header.payload.signature",
        )
        mint.assert_called_once()
        self.assertEqual(mint.call_args.kwargs["employee_id"], "test1")
        self.assertEqual(
            mint.call_args.kwargs["subject_user_id"],
            str(self.user_id),
        )
        self.assertIn(
            "Bearer header.payload.signature",
            response.claude_common_config["env"][
                "OTEL_EXPORTER_OTLP_HEADERS"
            ],
        )
        self.assertIn(
            "Bearer header.payload.signature",
            response.codex_common_config,
        )
        audit.assert_called_once()
        self.assertEqual(
            audit.call_args.kwargs["action"],
            "workday_enroll",
        )

    def test_project_membership_is_not_required_for_ai_monitor_enrollment(
        self,
    ) -> None:
        with (
            patch.object(
                route,
                "current_user_id",
                return_value=self.user_id,
            ),
            patch.object(
                route,
                "require_member",
                side_effect=AuthzError(403, "not a member"),
            ),
            patch.object(
                route,
                "mint_telemetry_token",
                return_value="header.payload.signature",
            ) as mint,
            patch.object(route, "record_audit"),
            patch.dict(
                os.environ,
                {
                    "JWT_SECRET_KEY": "test-secret-with-at-least-32-characters",
                    "WORKDAY_COLLECTOR_ENDPOINT": "http://192.168.1.40:4318",
                    "WORKDAY_ENROLLMENT_TOKEN_DAYS": "30",
                },
            ),
        ):
            response = route.enroll_workday(
                request=object(),
                body=self.body,
                orm=self.orm,
            )

        self.assertEqual(response.employee_id, "test1")
        mint.assert_called_once()

    def test_unusual_email_uses_stable_non_email_employee_id(self) -> None:
        employee_id, employee_name = route.derive_employee_identity(
            user_id=self.user_id,
            email="name+team@example.com",
            full_name=None,
        )

        self.assertEqual(employee_id, f"user-{self.user_id}")
        self.assertEqual(employee_name, "name+team")
        self.assertNotIn("@", employee_id)


if __name__ == "__main__":
    unittest.main()
