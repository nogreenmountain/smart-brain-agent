from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from agentops.rag.authz import AuthzError


def _load_route_module():
    route_path = Path(
        os.environ.get(
            "AI_MONITOR_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "ai_monitor.py",
        )
    )
    spec = importlib.util.spec_from_file_location(
        "ai_monitor_route_under_test",
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
    def __init__(self, *, row=None, rows=None) -> None:
        self.row = row
        self.rows = rows or []

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Orm:
    def __init__(
        self,
        *,
        profile=None,
        employee_profiles=None,
        rows=None,
        system_admin: bool = False,
        org_admin: bool = False,
    ) -> None:
        self.profile = profile
        self.employee_profiles = employee_profiles or []
        self.rows = rows or []
        self.system_admin = system_admin
        self.org_admin = org_admin
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})
        self.calls.append((sql, payload))
        if "WHERE au.id = :uid" in sql:
            return _Result(row=self.profile)
        if "SELECT au.id AS user_id" in sql and "FROM auth.users" in sql:
            return _Result(rows=self.employee_profiles)
        if "SELECT COALESCE(is_system_admin" in sql:
            return _Result(
                row=SimpleNamespace(is_system_admin=True) if self.system_admin else None
            )
        if "FROM public.user_orgs" in sql:
            return _Result(row=SimpleNamespace(allowed=1) if self.org_admin else None)
        if "FROM public.ai_monitor_devices" in sql:
            return _Result(rows=self.rows)
        if "FROM public.project_members" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(project_id="f9505558-d67d-462f-b77e-6b9550458a2b"),
                    SimpleNamespace(project_id="00000000-0000-0000-0000-000000000099"),
                ]
            )
        return _Result()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class AIMonitorRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        self.project_id = uuid.UUID("f9505558-d67d-462f-b77e-6b9550458a2b")
        self.profile = SimpleNamespace(email="test1@local.dev", full_name="研发一号")
        self.orm = _Orm(profile=self.profile)
        self.body = route.AIMonitorDeviceRegisterRequest(
            project_id=self.project_id,
            device_id="device-001",
            device_name="研发电脑-001",
            installer_version="2026-07-27",
            os="Windows",
            components=[
                route.AIMonitorComponentReport(
                    name="cc_switch",
                    status="installed",
                    version="3.12.2",
                ),
                route.AIMonitorComponentReport(
                    name="chatgpt_web_extension",
                    status="installed",
                    version="0.1.0",
                ),
            ],
        )

    def test_register_derives_employee_and_upserts_device(self) -> None:
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(route, "require_member") as require_member,
            patch.object(route, "record_audit") as audit,
        ):
            response = route.register_ai_monitor_device(
                request=object(),
                body=self.body,
                orm=self.orm,
            )

        require_member.assert_not_called()
        self.assertEqual(response.employee_id, "test1")
        self.assertEqual(response.device_id, "device-001")
        self.assertEqual(response.components["cc_switch"].status, "installed")
        self.assertEqual(self.orm.commits, 1)
        upsert = [
            params
            for sql, params in self.orm.calls
            if "INSERT INTO public.ai_monitor_devices" in sql
        ][0]
        self.assertEqual(upsert["employee_id"], "test1")
        self.assertEqual(upsert["user_id"], str(self.user_id))
        self.assertIn("cc_switch", upsert["components"])
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "ai_monitor_device_register")

    def test_project_membership_is_not_required_to_register_device(self) -> None:
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(
                route,
                "require_member",
                side_effect=AuthzError(403, "not a member"),
            ),
            patch.object(route, "record_audit") as audit,
        ):
            response = route.register_ai_monitor_device(
                request=object(),
                body=self.body,
                orm=self.orm,
            )

        self.assertEqual(response.employee_id, "test1")
        self.assertTrue(
            any("INSERT INTO public.ai_monitor_devices" in sql for sql, _ in self.orm.calls)
        )
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["metadata"]["result_status"], "ok")

    def test_status_lists_devices_and_live_components(self) -> None:
        row = SimpleNamespace(
            device_id="device-001",
            device_name="研发电脑-001",
            employee_id="test1",
            employee_name="研发一号",
            installer_version="2026-07-27",
            os="Windows",
            components={
                "cc_switch": {
                    "name": "cc_switch",
                    "status": "installed",
                    "version": "3.12.2",
                    "last_seen_at": "2026-07-27T04:00:00+00:00",
                    "details": {},
                }
            },
            last_seen_at=datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
            created_at=datetime(2026, 7, 27, 3, 50, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
        )
        orm = _Orm(profile=self.profile, rows=[row])
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(route, "require_member"),
            patch.object(route, "record_audit"),
        ):
            response = route.get_ai_monitor_status(
                request=object(),
                project_id=self.project_id,
                employee_id="test1",
                orm=orm,
            )

        self.assertEqual(response.project_id, self.project_id)
        self.assertEqual(response.employee_id, "test1")
        self.assertEqual(len(response.devices), 1)
        self.assertEqual(response.devices[0].components["cc_switch"].status, "installed")
        self.assertEqual(response.summary["cc_switch"], "installed")
        self.assertEqual(response.summary["chatgpt_web_extension"], "missing")

    def test_overall_status_lists_employee_devices_without_project_filter(self) -> None:
        row = SimpleNamespace(
            project_id="f9505558-d67d-462f-b77e-6b9550458a2b",
            device_id="device-001",
            device_name="研发电脑-001",
            employee_id="test1",
            employee_name="研发一号",
            installer_version="2026-07-27",
            os="Windows",
            components={
                "cc_switch": {
                    "name": "cc_switch",
                    "status": "installed",
                    "version": "3.12.2",
                    "last_seen_at": "2026-07-27T04:00:00+00:00",
                    "details": {},
                }
            },
            last_seen_at=datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
            created_at=datetime(2026, 7, 27, 3, 50, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
        )
        orm = _Orm(profile=self.profile, rows=[row])
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(route, "require_member") as require_member,
            patch.object(route, "record_audit") as audit,
        ):
            response = route.get_ai_monitor_overall_status(
                request=object(),
                employee_id="test1",
                orm=orm,
            )

        require_member.assert_not_called()
        self.assertIsNone(response.project_id)
        self.assertEqual([str(project_id) for project_id in response.project_ids], [
            "f9505558-d67d-462f-b77e-6b9550458a2b",
            "00000000-0000-0000-0000-000000000099",
        ])
        self.assertEqual(len(response.devices), 1)
        device_sql = [sql for sql, _ in orm.calls if "FROM public.ai_monitor_devices" in sql][0]
        self.assertNotIn("project_id = ANY", device_sql)
        self.assertIn("WHERE employee_id = :employee_id", device_sql)
        self.assertEqual(response.summary["cc_switch"], "installed")
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "ai_monitor_status")
        self.assertEqual(audit.call_args.kwargs["resource_type"], "ai_monitor")

    def test_regular_member_cannot_query_another_employee_status(self) -> None:
        orm = _Orm(
            profile=self.profile,
            employee_profiles=[
                SimpleNamespace(
                    user_id=self.user_id,
                    email="test1@local.dev",
                    full_name="研发一号",
                    nickname=None,
                ),
                SimpleNamespace(
                    user_id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
                    email="test2@local.dev",
                    full_name="研发二号",
                    nickname=None,
                ),
            ],
        )
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(route, "record_audit"),
            self.assertRaises(HTTPException) as raised,
        ):
            route.get_ai_monitor_overall_status(
                request=object(),
                employee_id="test2",
                orm=orm,
            )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse(
            any("FROM public.ai_monitor_devices" in sql for sql, _ in orm.calls)
        )

    def test_regular_member_can_query_own_status(self) -> None:
        orm = _Orm(profile=self.profile)
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(route, "record_audit"),
        ):
            response = route.get_ai_monitor_overall_status(
                request=object(),
                employee_id="test1",
                orm=orm,
            )

        self.assertEqual(response.employee_id, "test1")

    def test_system_admin_can_query_another_known_employee_status(self) -> None:
        orm = _Orm(
            profile=self.profile,
            employee_profiles=[
                SimpleNamespace(
                    user_id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
                    email="test2@local.dev",
                    full_name="研发二号",
                    nickname=None,
                )
            ],
            system_admin=True,
        )
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(route, "record_audit"),
        ):
            response = route.get_ai_monitor_overall_status(
                request=object(),
                employee_id="test2",
                orm=orm,
            )

        self.assertEqual(response.employee_id, "test2")
        self.assertEqual(response.employee_name, "研发二号")

    def test_system_admin_gets_not_found_for_unknown_employee(self) -> None:
        orm = _Orm(
            profile=self.profile,
            employee_profiles=[],
            system_admin=True,
        )
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(route, "record_audit"),
            self.assertRaises(HTTPException) as raised,
        ):
            route.get_ai_monitor_overall_status(
                request=object(),
                employee_id="missing-employee",
                orm=orm,
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertFalse(
            any("FROM public.ai_monitor_devices" in sql for sql, _ in orm.calls)
        )


if __name__ == "__main__":
    unittest.main()
