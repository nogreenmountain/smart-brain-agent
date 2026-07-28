from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from workday.domain import SpanRecord, aggregate_workday
from workday.presentation import build_response_payload


class WorkdayPresentationTests(unittest.TestCase):
    def test_include_flags_control_trace_replay_and_raw_metrics(self) -> None:
        aggregation = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=[
                SpanRecord(
                    timestamp=datetime(
                        2026,
                        7,
                        20,
                        1,
                        0,
                        tzinfo=timezone.utc,
                    ),
                    duration_ns=100_000_000,
                    trace_id="trace-1",
                    span_id="span-1",
                    employee_id="emp-1",
                    task_id="task-1",
                    work_date="2026-07-20",
                    tool_name="search",
                )
            ],
        )

        hidden = build_response_payload(
            aggregation,
            include_traces=False,
            include_replay_refs=False,
            include_raw_metrics=False,
        )
        visible = build_response_payload(
            aggregation,
            include_traces=True,
            include_replay_refs=True,
            include_raw_metrics=True,
        )

        self.assertEqual(hidden["important_traces"], [])
        self.assertIsNone(hidden["raw_metrics"])
        self.assertEqual(
            visible["important_traces"][0]["replay_url"],
            "/traces?trace_id=trace-1",
        )
        self.assertIsNotNone(visible["raw_metrics"])


if __name__ == "__main__":
    unittest.main()
