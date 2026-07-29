from __future__ import annotations

import importlib.util
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


def _load_route_module():
    route_path = Path(
        os.environ.get(
            "AI_USAGE_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "ai_usage.py",
        )
    )
    spec = importlib.util.spec_from_file_location("ai_usage_route_under_test", route_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load route module from {route_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


route = _load_route_module()


class _EmptyResult:
    def named_results(self):
        return []


class _CapturingClickHouse:
    def __init__(self) -> None:
        self.sql = ""
        self.parameters = {}

    def query(self, sql, parameters=None):
        self.sql = sql
        self.parameters = parameters or {}
        return _EmptyResult()


class AIUsageTraceQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clickhouse = _CapturingClickHouse()
        self.projects = [
            SimpleNamespace(
                id="00000000-0000-0000-0000-000000000001",
                name="Project",
                department_id="research",
            )
        ]

    def _query(self) -> str:
        route._trace_records(
            self.clickhouse,
            projects=self.projects,
            employee_id="employee-001",
            start_utc=datetime(2026, 7, 29, tzinfo=timezone.utc),
            end_utc=datetime(2026, 7, 30, tzinfo=timezone.utc),
            source=None,
        )
        return " ".join(self.clickhouse.sql.split())

    def test_query_filters_internal_diagnostic_traces(self) -> None:
        sql = self._query()

        self.assertIn("HAVING", sql)
        self.assertIn("meaningful_span_count > 0", sql)
        self.assertIn("session_task.turn", sql)

    def test_query_supports_codex_turn_token_attributes(self) -> None:
        sql = self._query()

        self.assertIn("codex.turn.token_usage.input_tokens", sql)
        self.assertIn("codex.turn.token_usage.output_tokens", sql)
        self.assertIn("codex.turn.token_usage.total_tokens", sql)

    def test_synced_conversation_replaces_overlapping_trace_without_double_count(self) -> None:
        started_at = datetime(2026, 7, 29, 3, 36, 21, tzinfo=timezone.utc)
        common = {
            "project_id": "00000000-0000-0000-0000-000000000001",
            "project_name": "Project",
            "employee_id": "employee-001",
            "employee_name": "Employee",
            "source": "cc_switch",
            "task_id": "unassigned",
            "status": "ok",
        }
        chat = route.UsageRecord(
            id="chat-1",
            record_type="chat",
            title="你好",
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=5),
            prompt_tokens=120,
            completion_tokens=18,
            total_tokens=138,
            model="gpt-5.6-luna",
            **common,
        )
        trace = route.UsageRecord(
            id="trace-1",
            record_type="trace",
            title="Codex 对话",
            started_at=started_at + timedelta(seconds=1),
            ended_at=started_at + timedelta(seconds=6),
            prompt_tokens=120,
            completion_tokens=18,
            total_tokens=138,
            model="gpt-5.6-luna",
            trace_id="trace-id-1",
            **common,
        )

        chats, traces = route._merge_synced_conversations([chat], [trace])

        self.assertEqual(len(chats), 1)
        self.assertEqual(traces, [])
        self.assertEqual(chats[0].trace_id, "trace-id-1")
        self.assertEqual(chats[0].total_tokens, 138)


if __name__ == "__main__":
    unittest.main()
