from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
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
    def test_temporary_monitor_probe_contract_is_account_scoped_and_one_time(self) -> None:
        create = route.TemporaryMonitorProbeCreateResponse(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            status="pending",
            probe_token="x" * 43,
            expires_at=datetime(2026, 8, 13, 8, 5, tzinfo=timezone.utc),
        )
        confirm = route.TemporaryMonitorProbeConfirmRequest(
            probe_id=create.id,
            probe_token=create.probe_token,
            device_id="temp-device-1",
            installer_version="2026.08.13.3",
        )

        self.assertEqual(confirm.probe_id, create.id)
        self.assertTrue(hasattr(route, "create_temporary_monitor_probe"))
        self.assertTrue(hasattr(route, "confirm_temporary_monitor_probe"))

    def test_shared_session_start_requires_a_detected_probe_for_current_account(self) -> None:
        body = route.SharedSessionStartRequest(
            installation_probe_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            stop_mode="default_19",
        )
        source = Path(route.__file__).read_text(encoding="utf-8")
        start = source.split("def start_shared_session", 1)[1].split("@router.get", 1)[0]

        self.assertEqual(
            body.installation_probe_id,
            uuid.UUID("11111111-1111-1111-1111-111111111111"),
        )
        self.assertIn("cc_switch_temporary_monitor_probes", start)
        self.assertIn("detected_at IS NOT NULL", start)
        self.assertIn("target_user_id", start)

    def test_shared_session_start_request_is_member_scoped_without_project(self) -> None:
        body = route.SharedSessionStartRequest(
            installation_probe_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            stop_mode="default_19",
        )

        self.assertIsNone(body.project_id)

    def test_shared_session_records_allow_projectless_attribution(self) -> None:
        source = Path(route.__file__).read_text(encoding="utf-8")
        records = source.split("def _shared_cc_switch_records", 1)[1].split("def ", 1)[0]

        self.assertIn("LEFT JOIN public.projects", records)
        self.assertNotIn("JOIN public.projects p ON", records.replace("LEFT JOIN", ""))

    def test_device_sync_contract_exists_and_tracks_incremental_watermark(self) -> None:
        body = route.SharedSessionDeviceSyncRequest(
            session_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            activation_token="x" * 43,
            device_id="public-device-1",
            checked_at=datetime(2026, 8, 13, 8, tzinfo=timezone.utc),
            last_watermark="42",
            requests=[],
        )

        self.assertEqual(body.last_watermark, "42")
        self.assertTrue(hasattr(route, "device_sync_shared_session"))

    def test_incremental_request_storage_is_projectless_and_idempotent(self) -> None:
        source = Path(route.__file__).read_text(encoding="utf-8")
        storage = source.split("def _store_shared_session_requests", 1)[1].split(
            "@device_router.post", 1
        )[0]

        self.assertIn('"project_id": str(row.project_id) if row.project_id else None', storage)
        self.assertIn("ON CONFLICT (device_id, request_id) DO NOTHING", storage)
        self.assertIn("WHERE session_id = :session_id", storage)

    def test_finalize_reuses_incremental_storage_for_unsynced_tail(self) -> None:
        source = Path(route.__file__).read_text(encoding="utf-8")
        finalize = source.split("def device_finalize_shared_session", 1)[1].split(
            "@router.get", 1
        )[0]

        self.assertIn("_store_shared_session_requests", finalize)
        self.assertNotIn("INSERT INTO public.cc_switch_attributed_requests", finalize)

    def test_stale_starting_sessions_are_expired_before_new_session_checks(self) -> None:
        orm = _Orm()

        route._expire_stale_shared_sessions(
            orm,
            target_user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        )

        sql, params = orm.calls[0]
        self.assertIn("status = 'expired'", sql)
        self.assertIn("status = 'starting'", sql)
        self.assertIn("activation_expires_at < now()", sql)
        self.assertEqual(
            params["target_user_id"],
            "00000000-0000-0000-0000-000000000002",
        )

    def test_default_shared_session_stop_is_next_19_shanghai(self) -> None:
        before_cutoff = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        after_cutoff = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)

        same_day = route.resolve_shared_session_stop_at(
            stop_mode="default_19",
            scheduled_stop_at=None,
            now=before_cutoff,
        )
        next_day = route.resolve_shared_session_stop_at(
            stop_mode="default_19",
            scheduled_stop_at=None,
            now=after_cutoff,
        )

        self.assertEqual(same_day, datetime(2026, 8, 13, 11, 0, tzinfo=timezone.utc))
        self.assertEqual(next_day, datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc))

    def test_manual_shared_session_has_24_hour_safety_cutoff(self) -> None:
        now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)

        stop_at = route.resolve_shared_session_stop_at(
            stop_mode="manual_only",
            scheduled_stop_at=None,
            now=now,
        )

        self.assertEqual(stop_at, now + timedelta(hours=24))

    def test_custom_shared_session_stop_rejects_unsafe_ranges(self) -> None:
        now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)

        with self.assertRaises(route.HTTPException) as too_soon:
            route.resolve_shared_session_stop_at(
                stop_mode="custom",
                scheduled_stop_at=now + timedelta(minutes=4),
                now=now,
            )
        with self.assertRaises(route.HTTPException) as too_late:
            route.resolve_shared_session_stop_at(
                stop_mode="custom",
                scheduled_stop_at=now + timedelta(hours=25),
                now=now,
            )

        self.assertEqual(too_soon.exception.status_code, 422)
        self.assertEqual(too_late.exception.status_code, 422)

    def test_device_verification_uses_activation_and_device_not_installer_project(self) -> None:
        row = SimpleNamespace(
            activation_token_hash=route._shared_token_hash("x" * 43),
            activation_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            status="starting",
            device_id=None,
        )

        route._verify_shared_device_session(
            row,
            activation_token="x" * 43,
            device_id="public-device-1",
            claims={"project_id": "different-installer-project"},
        )

    def test_shared_device_activation_uses_session_token_without_personal_monitor_claims(self) -> None:
        source = Path(route.__file__).read_text(encoding="utf-8")
        activation = source.split("def device_activate_shared_session", 1)[1].split(
            "@device_router.post", 1
        )[0]
        command = source.split("def device_shared_session_command", 1)[1].split(
            "@device_router.post", 1
        )[0]
        finalize = source.split("def device_finalize_shared_session", 1)[1].split(
            "def ", 1
        )[0]

        self.assertNotIn("_device_claims(request)", activation)
        self.assertNotIn("_device_claims(request)", command)
        self.assertNotIn("_device_claims(request)", finalize)

    def test_device_command_can_replace_previous_member_at_checked_boundary(self) -> None:
        row = SimpleNamespace(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            status="active",
            stop_mode="default_19",
            scheduled_stop_at=datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
            actual_stop_at=None,
            stop_reason=None,
        )
        orm = _Orm()
        checked_at = datetime(2026, 8, 13, 8, 30, tzinfo=timezone.utc)
        body = route.SharedSessionDeviceCommandRequest(
            session_id=row.id,
            activation_token="x" * 43,
            device_id="public-device-1",
            checked_at=checked_at,
            stop_reason="replaced_by_next_user",
        )

        with (
            patch.object(route, "_device_claims", return_value={}),
            patch.object(route, "_get_shared_session", return_value=row),
            patch.object(route, "_verify_shared_device_session"),
        ):
            response = route.device_shared_session_command(
                request=SimpleNamespace(headers={}), body=body, orm=orm,
            )

        self.assertEqual(response.action, "stop")
        self.assertEqual(response.stop_at, checked_at)
        self.assertEqual(response.stop_reason, "replaced_by_next_user")
        update_params = next(params for sql, params in orm.calls if "SET status = 'finalizing'" in sql)
        self.assertEqual(update_params["stop_at"], checked_at)

    def test_repeated_stop_during_pending_sync_keeps_original_boundary(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        original_stop = datetime(2026, 8, 13, 8, 5, tzinfo=timezone.utc)
        row = SimpleNamespace(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            project_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            target_employee_id="test1",
            target_employee_name="测试成员",
            device_id="public-device-1",
            stop_mode="manual_only",
            stop_reason="manual",
            status="pending_sync",
            requested_at=datetime(2026, 8, 13, 6, tzinfo=timezone.utc),
            started_at=datetime(2026, 8, 13, 6, tzinfo=timezone.utc),
            scheduled_stop_at=datetime(2026, 8, 14, 6, tzinfo=timezone.utc),
            actual_stop_at=original_stop,
            request_count=0,
            total_tokens=0,
            finalized_at=None,
            error_message="offline",
        )
        orm = _Orm()

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "_get_shared_session", return_value=row),
        ):
            response = route.stop_shared_session(
                request=SimpleNamespace(headers={}),
                session_id=row.id,
                body=route.SharedSessionStopRequest(),
                orm=orm,
            )

        self.assertEqual(response.status, "pending_sync")
        self.assertEqual(response.actual_stop_at, original_stop)
        self.assertEqual(orm.calls, [])

    def test_successful_sync_covering_query_marks_snapshot_authoritative(self) -> None:
        class CoverageOrm:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def execute(self, statement, params=None):
                self.calls.append((str(statement), dict(params or {})))
                return _Result(row=SimpleNamespace(covered=True))

        orm = CoverageOrm()

        covered = route._cc_switch_has_authoritative_coverage(
            orm,
            employee_id="tangweixiang",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 7),
        )

        self.assertTrue(covered)
        sql, params = orm.calls[0]
        self.assertIn("public.cc_switch_usage_sync_status", sql)
        self.assertIn("status = 'ok'", sql)
        self.assertEqual(params["employee_id"], "tangweixiang")
        self.assertEqual(params["start_date"], date(2026, 8, 1))
        self.assertEqual(params["end_date"], date(2026, 8, 7))

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
            sync_protocol_version=2,
            source_table="usage_daily_rollups",
            request_count=2,
            success_count=2,
            total_tokens=1620,
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
                    input_tokens=1000,
                    output_tokens=20,
                    cache_read_tokens=600,
                    cache_creation_tokens=0,
                    total_tokens=1620,
                    total_cost_usd=0.25,
                    input_token_semantics=0,
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
        self.assertEqual(response.total_tokens, 1020)
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
        self.assertEqual(row_insert["total_tokens"], 1020)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "ai_usage_sync")

    def test_old_sync_protocol_cannot_replace_authoritative_usage(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        body = route.CCSwitchUsageSyncRequest(
            project_id=project_id,
            device_id="device-123",
            trigger="automatic",
            range_start=date(2026, 5, 10),
            range_end=date(2026, 8, 7),
            attempted_at=datetime(2026, 8, 7, 9, tzinfo=timezone.utc),
            cc_switch_running=True,
            status="ok",
            source_table="usage_daily_rollups",
            request_count=1,
            success_count=1,
            total_tokens=100,
            rows=[
                route.CCSwitchUsageRowInput(
                    usage_date=date(2026, 8, 7),
                    app_type="codex",
                    provider_id="provider-a",
                    model="gpt-5",
                    request_count=1,
                    success_count=1,
                    input_tokens=100,
                    total_tokens=100,
                )
            ],
        )
        orm = _Orm()
        claims = {
            "sub": str(user_id),
            "project_id": str(project_id),
            "employee_id": "test1",
            "employee_name": "Test 1",
        }

        with patch.object(route, "_device_claims", return_value=claims):
            with self.assertRaises(route.HTTPException) as raised:
                route.device_ingest_cc_switch_usage(
                    request=SimpleNamespace(headers={}),
                    body=body,
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(orm.calls, [])


if __name__ == "__main__":
    unittest.main()
