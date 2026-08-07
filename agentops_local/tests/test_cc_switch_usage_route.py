from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_route():
    path = Path(
        os.environ.get(
            "AI_USAGE_ROUTE_PATH",
            Path(__file__).parents[1]
            / "api"
            / "routes"
            / "v4"
            / "ai_usage.py",
        )
    )
    spec = importlib.util.spec_from_file_location(
        "cc_switch_usage_route_under_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


route = _load_route()


class _Result:
    def __init__(self, *, row=None, rows=None):
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
        self.rollbacks = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})
        self.calls.append((sql, payload))
        if "RETURNING synced_at" in sql:
            return _Result(
                row=SimpleNamespace(
                    synced_at=datetime(2026, 8, 7, 8, 1, tzinfo=timezone.utc)
                )
            )
        return _Result()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class CCSwitchUsageRouteTests(unittest.TestCase):
    def test_not_running_updates_status_without_deleting_last_good_usage(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        body = route.CCSwitchUsageSyncRequest(
            project_id=project_id,
            device_id="device-123",
            trigger="manual",
            request_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            range_start=date(2026, 8, 1),
            range_end=date(2026, 8, 7),
            attempted_at=datetime(2026, 8, 7, 8, tzinfo=timezone.utc),
            cc_switch_running=False,
            status="not_running",
            rows=[],
            request_count=0,
            success_count=0,
            total_tokens=0,
            error_message="CC Switch is not running",
        )
        orm = _Orm()
        claims = {
            "sub": str(user_id),
            "project_id": str(project_id),
            "employee_id": "test1",
            "employee_name": "Test 1",
        }

        with (
            patch.object(route, "_device_claims", return_value=claims),
            patch.object(route, "record_audit"),
        ):
            response = route.device_ingest_cc_switch_usage(
                request=SimpleNamespace(headers={}),
                body=body,
                orm=orm,
            )

        self.assertEqual(response.status, "not_running")
        usage_mutations = [
            sql
            for sql, _ in orm.calls
            if "public.cc_switch_usage_daily" in sql
        ]
        self.assertEqual(usage_mutations, [])
        self.assertTrue(
            any(
                "INSERT INTO public.cc_switch_usage_sync_status" in sql
                for sql, _ in orm.calls
            )
        )

    def test_device_ingest_replaces_device_range_and_upserts_rows(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        body = route.CCSwitchUsageSyncRequest(
            project_id=project_id,
            device_id="device-123",
            trigger="manual",
            request_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            range_start=date(2026, 8, 1),
            range_end=date(2026, 8, 7),
            attempted_at=datetime(2026, 8, 7, 8, tzinfo=timezone.utc),
            cc_switch_running=True,
            status="ok",
            source_table="usage_daily_rollups",
            request_count=2,
            success_count=2,
            total_tokens=430,
            rows=[
                route.CCSwitchUsageRowInput(
                    usage_date=date(2026, 8, 7),
                    app_type="codex",
                    provider_id="provider-a",
                    model="gpt-5",
                    request_model="gpt-5",
                    pricing_model="gpt-5",
                    request_count=2,
                    success_count=2,
                    input_tokens=100,
                    output_tokens=20,
                    cache_read_tokens=300,
                    cache_creation_tokens=10,
                    total_tokens=430,
                    total_cost_usd=0.25,
                    input_token_semantics=1,
                )
            ],
        )
        orm = _Orm()
        claims = {
            "sub": str(user_id),
            "project_id": str(project_id),
            "employee_id": "test1",
            "employee_name": "研发一号",
        }

        with (
            patch.object(route, "_device_claims", return_value=claims),
            patch.object(route, "record_audit") as audit,
        ):
            response = route.device_ingest_cc_switch_usage(
                request=SimpleNamespace(headers={}),
                body=body,
                orm=orm,
            )

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.employee_id, "test1")
        self.assertEqual(response.total_tokens, 430)
        self.assertEqual(orm.commits, 1)
        self.assertTrue(
            any(
                "DELETE FROM public.cc_switch_usage_daily" in sql
                for sql, _ in orm.calls
            )
        )
        row_insert = next(
            params
            for sql, params in orm.calls
            if "INSERT INTO public.cc_switch_usage_daily" in sql
        )
        self.assertEqual(row_insert["user_id"], str(user_id))
        self.assertEqual(row_insert["employee_id"], "test1")
        self.assertEqual(row_insert["device_id"], "device-123")
        self.assertEqual(row_insert["total_tokens"], 430)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "ai_usage_sync")


if __name__ == "__main__":
    unittest.main()
