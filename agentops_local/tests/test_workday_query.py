from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from workday.query import build_span_query, fetch_span_records, parse_span_rows


class WorkdayQueryTests(unittest.TestCase):
    def test_query_selects_only_whitelisted_structural_attributes(self) -> None:
        sql, params = build_span_query(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
        )

        self.assertNotIn("ResourceAttributes AS", sql)
        self.assertNotIn("SpanAttributes AS", sql)
        self.assertNotIn("SpanAttributes['gen_ai.prompt']", sql)
        self.assertNotIn("SpanAttributes['gen_ai.completion']", sql)
        self.assertNotIn("SpanAttributes['tool.parameters']", sql)
        self.assertNotIn("SpanAttributes['tool.result']", sql)
        self.assertNotIn("SpanName AS", sql)
        self.assertNotIn("StatusMessage", sql)
        self.assertIn("SpanAttributes['agentops.employee.id']", sql)
        self.assertIn("SpanAttributes['agentops.task.id']", sql)
        self.assertEqual(params["project_id"], "project-1")
        self.assertEqual(params["employee_id"], "emp-1")
        self.assertEqual(params["start_utc"].isoformat(), "2026-07-19T16:00:00+00:00")
        self.assertEqual(params["end_utc"].isoformat(), "2026-07-20T16:00:00+00:00")

    def test_query_supports_legacy_agentops_model_and_reported_cost(self) -> None:
        sql, _ = build_span_query(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
        )

        self.assertIn("SpanAttributes['llm.model']", sql)
        self.assertIn("SpanAttributes['llm.cost']", sql)

    def test_query_supports_native_claude_and_current_genai_attributes(self) -> None:
        sql, _ = build_span_query(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
        )

        self.assertIn("SpanAttributes['model']", sql)
        self.assertIn("SpanAttributes['input_tokens']", sql)
        self.assertIn("SpanAttributes['output_tokens']", sql)
        self.assertIn("SpanAttributes['cache_read_tokens']", sql)
        self.assertIn("SpanAttributes['tool_name']", sql)
        self.assertIn("SpanAttributes['span.type']", sql)
        self.assertIn("SpanAttributes['gen_ai.usage.input_tokens']", sql)
        self.assertIn("SpanAttributes['gen_ai.usage.output_tokens']", sql)
        self.assertIn("SpanAttributes['gen_ai.usage.reasoning.output_tokens']", sql)
        self.assertIn("SpanAttributes['gen_ai.usage.cache_read.input_tokens']", sql)

    def test_malformed_rows_are_skipped_without_dropping_the_whole_day(self) -> None:
        rows = [
            {
                "timestamp": datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc),
                "duration_ns": 1_000_000,
                "trace_id": "trace-1",
                "span_id": "span-1",
                "employee_id": "emp-1",
                "task_id": "task-1",
                "status_code": "OK",
            },
            {
                "timestamp": "not-a-datetime",
                "duration_ns": 1,
                "trace_id": "trace-bad",
                "span_id": "span-bad",
                "employee_id": "emp-1",
            },
        ]

        spans, warnings = parse_span_rows(rows)

        self.assertEqual([span.trace_id for span in spans], ["trace-1"])
        self.assertEqual(
            warnings,
            ("1 个 ClickHouse Span 字段异常，已跳过，不影响其余日报数据",),
        )

    def test_fetch_executes_parameterized_query_and_returns_named_rows(self) -> None:
        class Result:
            def named_results(self):
                return []

        class Client:
            def __init__(self) -> None:
                self.sql = ""
                self.parameters = {}

            def query(self, sql, *, parameters):
                self.sql = sql
                self.parameters = parameters
                return Result()

        client = Client()
        spans, warnings = fetch_span_records(
            client,
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
        )

        self.assertEqual(spans, [])
        self.assertEqual(warnings, ())
        self.assertIn("project_id = %(project_id)s", client.sql)
        self.assertEqual(client.parameters["employee_id"], "emp-1")


if __name__ == "__main__":
    unittest.main()
