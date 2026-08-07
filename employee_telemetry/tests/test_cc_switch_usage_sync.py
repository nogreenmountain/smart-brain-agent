from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from employee_telemetry.cc_switch_usage_sync import (
    collect_cc_switch_usage,
    sync_once,
)


class CCSwitchUsageCollectionTests(unittest.TestCase):
    def test_reads_daily_rollups_with_cc_switch_token_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "cc-switch.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """
                    CREATE TABLE usage_daily_rollups (
                        date TEXT NOT NULL,
                        app_type TEXT NOT NULL,
                        provider_id TEXT NOT NULL,
                        model TEXT NOT NULL,
                        request_model TEXT NOT NULL DEFAULT '',
                        pricing_model TEXT NOT NULL DEFAULT '',
                        request_count INTEGER NOT NULL DEFAULT 0,
                        success_count INTEGER NOT NULL DEFAULT 0,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                        cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
                        total_cost_usd TEXT NOT NULL DEFAULT '0',
                        avg_latency_ms INTEGER NOT NULL DEFAULT 0,
                        input_token_semantics INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (
                            date, app_type, provider_id, model,
                            request_model, pricing_model
                        )
                    )
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO usage_daily_rollups (
                        date, app_type, provider_id, model,
                        request_model, pricing_model,
                        request_count, success_count,
                        input_tokens, output_tokens,
                        cache_read_tokens, cache_creation_tokens,
                        total_cost_usd, avg_latency_ms,
                        input_token_semantics
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "2026-08-06", "codex", "provider-a", "gpt-5",
                            "gpt-5", "gpt-5", 3, 3,
                            100, 20, 400, 50, "0.25", 1200, 1,
                        ),
                        (
                            "2026-08-07", "claude", "provider-b", "m3",
                            "m3", "m3", 2, 1,
                            80, 10, 30, 5, "0.10", 900, 0,
                        ),
                        (
                            "2026-07-01", "codex", "old", "old",
                            "", "", 1, 1, 999, 999, 999, 999, "9", 1, 0,
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            result = collect_cc_switch_usage(
                database,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 7),
            )

        self.assertEqual(result.source_table, "usage_daily_rollups")
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.total_tokens, 695)
        self.assertEqual(result.rows[0].total_tokens, 570)
        self.assertEqual(result.rows[1].total_tokens, 125)
        self.assertEqual(result.request_count, 5)
        self.assertEqual(result.success_count, 4)

    def test_falls_back_to_proxy_request_logs_when_rollups_are_unavailable(self) -> None:
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
                created_at = int(
                    datetime(2026, 8, 7, 2, 0, tzinfo=timezone.utc).timestamp()
                    * 1000
                )
                connection.executemany(
                    """
                    INSERT INTO proxy_request_logs (
                        request_id, provider_id, app_type, model,
                        request_model, input_tokens, output_tokens,
                        cache_read_tokens, cache_creation_tokens,
                        total_cost_usd, status_code, created_at,
                        pricing_model, input_token_semantics
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "request-1", "provider-a", "codex", "gpt-5",
                            "gpt-5", 100, 10, 30, 5,
                            "0.1", 200, created_at, "gpt-5", 1,
                        ),
                        (
                            "request-2", "provider-a", "codex", "gpt-5",
                            "gpt-5", 50, 5, 15, 0,
                            "0.05", 500, created_at + 1000, "gpt-5", 1,
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            result = collect_cc_switch_usage(
                database,
                start_date=date(2026, 8, 7),
                end_date=date(2026, 8, 7),
            )

        self.assertEqual(result.source_table, "proxy_request_logs")
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.total_tokens, 215)
        self.assertEqual(result.request_count, 2)
        self.assertEqual(result.success_count, 1)


class CCSwitchUsageSyncTests(unittest.TestCase):
    def test_collection_error_is_reported_to_server_for_manual_polling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            home = root / "home"
            runtime.mkdir(parents=True)
            (runtime / "device-credentials.json").write_text(
                """
                {
                  "api_endpoint": "https://smartbrain.example",
                  "project_id": "00000000-0000-0000-0000-000000000001",
                  "token": "device-token"
                }
                """,
                encoding="utf-8",
            )
            (runtime / "manifest.json").write_text(
                '{"device_id":"device-123"}',
                encoding="utf-8",
            )
            requests: list[dict[str, object]] = []

            def capture(_url: str, _token: str, payload: dict[str, object]):
                requests.append(payload)
                return {
                    "status": "error",
                    "error_message": payload["error_message"],
                }

            with (
                patch(
                    "employee_telemetry.cc_switch_usage_sync._cc_switch_running",
                    return_value=True,
                ),
                patch(
                    "employee_telemetry.cc_switch_usage_sync._post_json",
                    side_effect=capture,
                ),
            ):
                status = sync_once(
                    runtime_dir=runtime,
                    home_dir=home,
                    lookback_days=7,
                    now=datetime(2026, 8, 7, 8, tzinfo=timezone.utc),
                    trigger="manual",
                    request_id="11111111-1111-1111-1111-111111111111",
                )

        self.assertEqual(status["status"], "error")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["status"], "error")
        self.assertTrue(requests[0]["cc_switch_running"])
        self.assertEqual(requests[0]["rows"], [])
        self.assertIn("database was not found", requests[0]["error_message"])

    def test_manual_sync_posts_authoritative_rows_with_device_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            home = root / "home"
            database = home / ".cc-switch" / "cc-switch.db"
            runtime.mkdir(parents=True)
            database.parent.mkdir(parents=True)
            (runtime / "device-credentials.json").write_text(
                """
                {
                  "api_endpoint": "https://smartbrain.example",
                  "project_id": "00000000-0000-0000-0000-000000000001",
                  "token": "device-token"
                }
                """,
                encoding="utf-8",
            )
            (runtime / "manifest.json").write_text(
                '{"device_id":"device-123"}',
                encoding="utf-8",
            )
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """
                    CREATE TABLE usage_daily_rollups (
                        date TEXT NOT NULL, app_type TEXT NOT NULL,
                        provider_id TEXT NOT NULL, model TEXT NOT NULL,
                        request_model TEXT NOT NULL DEFAULT '',
                        pricing_model TEXT NOT NULL DEFAULT '',
                        request_count INTEGER NOT NULL DEFAULT 0,
                        success_count INTEGER NOT NULL DEFAULT 0,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                        cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
                        total_cost_usd TEXT NOT NULL DEFAULT '0',
                        avg_latency_ms INTEGER NOT NULL DEFAULT 0,
                        input_token_semantics INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (
                            date, app_type, provider_id, model,
                            request_model, pricing_model
                        )
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO usage_daily_rollups (
                        date, app_type, provider_id, model,
                        request_count, success_count,
                        input_tokens, output_tokens,
                        cache_read_tokens, cache_creation_tokens
                    ) VALUES ('2026-08-07', 'codex', 'provider-a', 'gpt-5',
                              4, 4, 100, 20, 300, 10)
                    """
                )
                connection.commit()
            finally:
                connection.close()

            requests: list[tuple[str, str, dict[str, object]]] = []

            def capture(url: str, token: str, payload: dict[str, object]):
                requests.append((url, token, payload))
                return {"status": "ok", "total_tokens": 430}

            with (
                patch(
                    "employee_telemetry.cc_switch_usage_sync._cc_switch_running",
                    return_value=True,
                ),
                patch(
                    "employee_telemetry.cc_switch_usage_sync._post_json",
                    side_effect=capture,
                ),
            ):
                status = sync_once(
                    runtime_dir=runtime,
                    home_dir=home,
                    lookback_days=7,
                    now=datetime(2026, 8, 7, 8, tzinfo=timezone.utc),
                    trigger="manual",
                    request_id="11111111-1111-1111-1111-111111111111",
                )

            saved_status = (runtime / "cc-switch-usage-sync-status.json").read_text(
                encoding="utf-8"
            )

        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["total_tokens"], 430)
        self.assertIn('"status": "ok"', saved_status)
        self.assertEqual(len(requests), 1)
        url, token, payload = requests[0]
        self.assertEqual(
            url,
            "https://smartbrain.example/v4/ai-usage/cc-switch-sync/device-ingest",
        )
        self.assertEqual(token, "device-token")
        self.assertEqual(payload["device_id"], "device-123")
        self.assertEqual(payload["trigger"], "manual")
        self.assertEqual(payload["source_table"], "usage_daily_rollups")
        self.assertEqual(payload["total_tokens"], 430)
        self.assertEqual(len(payload["rows"]), 1)


if __name__ == "__main__":
    unittest.main()
