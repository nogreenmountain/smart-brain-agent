from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from employee_telemetry.shared_cc_switch_session import (
    collect_session_requests,
    poll_session,
    start_session,
)


class SharedCCSwitchSessionTests(unittest.TestCase):
    def test_collects_only_requests_inside_session_and_keeps_request_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "cc-switch.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """
                    CREATE TABLE proxy_request_logs (
                        request_id TEXT PRIMARY KEY,
                        provider_id TEXT NOT NULL,
                        app_type TEXT NOT NULL,
                        model TEXT NOT NULL,
                        request_model TEXT,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                        cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
                        total_cost_usd TEXT NOT NULL DEFAULT '0',
                        status_code INTEGER NOT NULL,
                        created_at INTEGER NOT NULL,
                        pricing_model TEXT,
                        input_token_semantics INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                start_ms = int(datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc).timestamp() * 1000)
                connection.executemany(
                    """
                    INSERT INTO proxy_request_logs (
                        request_id, provider_id, app_type, model,
                        request_model, input_tokens, output_tokens,
                        cache_read_tokens, cache_creation_tokens,
                        total_cost_usd, status_code, created_at,
                        pricing_model, input_token_semantics
                    ) VALUES (?, 'provider-a', 'codex', 'gpt-5', 'gpt-5',
                              ?, 10, 30, 5, '0.1', 200, ?, 'gpt-5', 1)
                    """,
                    [
                        ("before", 100, start_ms - 1),
                        ("inside", 200, start_ms + 1000),
                        ("after", 300, start_ms + 3_601_000),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = collect_session_requests(
                database,
                started_at=datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc),
                stopped_at=datetime(2026, 8, 13, 7, 0, tzinfo=timezone.utc),
            )

        self.assertEqual([row.request_id for row in rows], ["inside"])
        self.assertEqual(rows[0].total_tokens, 210)

    def test_requires_proxy_request_logs_for_accurate_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "cc-switch.db"
            sqlite3.connect(database).close()

            with self.assertRaisesRegex(RuntimeError, "proxy_request_logs"):
                collect_session_requests(
                    database,
                    started_at=datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc),
                    stopped_at=datetime(2026, 8, 13, 7, 0, tzinfo=timezone.utc),
                )

    def test_start_marks_device_shared_and_persists_server_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            home = root / "home"
            database = home / ".cc-switch" / "cc-switch.db"
            runtime.mkdir(parents=True)
            database.parent.mkdir(parents=True)
            (runtime / "device-credentials.json").write_text(
                '{"api_endpoint":"https://smartbrain.example",'
                '"token":"device-token","device_id":"device-1"}',
                encoding="utf-8",
            )
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE proxy_request_logs (request_id TEXT PRIMARY KEY)"
            )
            connection.commit()
            connection.close()

            with patch(
                "employee_telemetry.shared_cc_switch_session._post_json",
                return_value={
                    "status": "active",
                    "started_at": "2026-08-13T06:00:00+00:00",
                    "scheduled_stop_at": "2026-08-13T11:00:00+00:00",
                },
            ):
                result = start_session(
                    runtime_dir=runtime,
                    session_id="11111111-1111-1111-1111-111111111111",
                    activation_token="x" * 43,
                    home_dir=home,
                    now=datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc),
                )

            shared = (runtime / "shared-device.json").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "active")
        self.assertIn('"device_id": "device-1"', shared)

    def test_poll_keeps_pending_sync_when_finalize_is_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            home = root / "home"
            database = home / ".cc-switch" / "cc-switch.db"
            runtime.mkdir(parents=True)
            database.parent.mkdir(parents=True)
            (runtime / "device-credentials.json").write_text(
                '{"api_endpoint":"https://smartbrain.example",'
                '"token":"device-token","device_id":"device-1"}',
                encoding="utf-8",
            )
            (runtime / "shared-cc-switch-session.json").write_text(
                """
                {
                  "session_id": "11111111-1111-1111-1111-111111111111",
                  "activation_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                  "device_id": "device-1",
                  "started_at": "2026-08-13T06:00:00+00:00",
                  "scheduled_stop_at": "2026-08-13T07:00:00+00:00",
                  "status": "active"
                }
                """,
                encoding="utf-8",
            )
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE proxy_request_logs (
                    request_id TEXT PRIMARY KEY, provider_id TEXT, app_type TEXT,
                    model TEXT, request_model TEXT, input_tokens INTEGER,
                    output_tokens INTEGER, cache_read_tokens INTEGER,
                    cache_creation_tokens INTEGER, total_cost_usd TEXT,
                    status_code INTEGER, created_at INTEGER, pricing_model TEXT,
                    input_token_semantics INTEGER
                )
                """
            )
            connection.commit()
            connection.close()
            calls = 0

            def respond(_url, _token, _payload):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return {
                        "action": "stop",
                        "scheduled_stop_at": "2026-08-13T07:00:00+00:00",
                        "stop_at": "2026-08-13T07:00:00+00:00",
                        "stop_reason": "scheduled",
                    }
                raise RuntimeError("offline")

            with patch(
                "employee_telemetry.shared_cc_switch_session._post_json",
                side_effect=respond,
            ):
                result = poll_session(
                    runtime_dir=runtime,
                    home_dir=home,
                    now=datetime(2026, 8, 13, 7, 1, tzinfo=timezone.utc),
                )

        self.assertEqual(result["status"], "pending_sync")

    def test_pending_sync_retries_finalize_without_reopening_time_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            home = root / "home"
            database = home / ".cc-switch" / "cc-switch.db"
            runtime.mkdir(parents=True)
            database.parent.mkdir(parents=True)
            (runtime / "device-credentials.json").write_text(
                '{"api_endpoint":"https://smartbrain.example",'
                '"token":"device-token","device_id":"device-1"}', encoding="utf-8",
            )
            (runtime / "shared-cc-switch-session.json").write_text(
                """
                {
                  "session_id": "11111111-1111-1111-1111-111111111111",
                  "activation_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                  "device_id": "device-1",
                  "started_at": "2026-08-13T06:00:00+00:00",
                  "scheduled_stop_at": "2026-08-13T07:00:00+00:00",
                  "stopped_at": "2026-08-13T07:00:00+00:00",
                  "stop_reason": "scheduled",
                  "status": "pending_sync"
                }
                """, encoding="utf-8",
            )
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE proxy_request_logs (
                    request_id TEXT PRIMARY KEY, provider_id TEXT, app_type TEXT,
                    model TEXT, request_model TEXT, input_tokens INTEGER,
                    output_tokens INTEGER, cache_read_tokens INTEGER,
                    cache_creation_tokens INTEGER, total_cost_usd TEXT,
                    status_code INTEGER, created_at INTEGER, pricing_model TEXT,
                    input_token_semantics INTEGER
                )
                """
            )
            connection.commit()
            connection.close()
            urls = []

            def respond(url, _token, _payload):
                urls.append(url)
                return {"status": "finalized", "request_count": 0, "total_tokens": 0}

            with patch(
                "employee_telemetry.shared_cc_switch_session._post_json",
                side_effect=respond,
            ):
                result = poll_session(runtime_dir=runtime, home_dir=home)

        self.assertEqual(result["status"], "finalized")
        self.assertEqual(len(urls), 1)
        self.assertTrue(urls[0].endswith("/device-finalize"))


if __name__ == "__main__":
    unittest.main()
