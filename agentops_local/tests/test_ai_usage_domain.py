from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


domain_path = Path(__file__).parents[1] / "ai_usage" / "domain.py"
spec = importlib.util.spec_from_file_location("ai_usage_domain_under_test", domain_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load AI usage domain from {domain_path}")
domain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = domain
spec.loader.exec_module(domain)
UsageRecord = domain.UsageRecord
AuthoritativeUsageDaily = domain.AuthoritativeUsageDaily
build_usage_summary = domain.build_usage_summary
build_usage_summary_with_authoritative_source = (
    domain.build_usage_summary_with_authoritative_source
)


class AIUsageDomainTests(unittest.TestCase):
    def test_summary_uses_calendar_days_and_merges_sources(self) -> None:
        records = [
            UsageRecord(
                id="chat-1",
                record_type="chat",
                project_id="project-1",
                project_name="Project One",
                employee_id="test1",
                employee_name="Test 1",
                source="chatgpt_web",
                title="Login debugging",
                started_at=datetime(2026, 7, 27, 1, 15, tzinfo=timezone.utc),
                prompt_tokens=120,
                completion_tokens=80,
                total_tokens=200,
                error_count=1,
            ),
            UsageRecord(
                id="trace-1",
                record_type="trace",
                project_id="project-1",
                project_name="Project One",
                employee_id="test1",
                employee_name="Test 1",
                source="cc_switch",
                title="API implementation",
                started_at=datetime(2026, 7, 29, 1, 45, tzinfo=timezone.utc),
                prompt_tokens=300,
                completion_tokens=100,
                total_tokens=400,
            ),
        ]

        summary = build_usage_summary(
            records,
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 29),
        )

        self.assertEqual(summary.period_days, 3)
        self.assertEqual(summary.active_days, 2)
        self.assertEqual(summary.total_tokens, 600)
        self.assertEqual(summary.average_tokens_per_day, 200)
        self.assertEqual(summary.record_count, 2)
        self.assertEqual(summary.error_count, 1)
        self.assertEqual(summary.daily_usage[0].date, date(2026, 7, 27))
        self.assertEqual(summary.daily_usage[1].total_tokens, 0)
        self.assertEqual(summary.daily_usage[2].total_tokens, 400)
        self.assertEqual(summary.hourly_usage[9].total_tokens, 600)

    def test_empty_period_still_returns_each_calendar_day(self) -> None:
        summary = build_usage_summary(
            [],
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 28),
        )

        self.assertEqual(summary.period_days, 2)
        self.assertEqual(summary.average_tokens_per_day, 0)
        self.assertEqual([item.total_tokens for item in summary.daily_usage], [0, 0])

    def test_cc_switch_snapshot_replaces_trace_tokens_in_summary(self) -> None:
        records = [
            UsageRecord(
                id="trace-1",
                record_type="trace",
                project_id="project-1",
                project_name="Project One",
                employee_id="test1",
                employee_name="Test 1",
                source="cc_switch",
                title="Trace detail",
                started_at=datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc),
                prompt_tokens=80,
                completion_tokens=20,
                total_tokens=100,
            ),
            UsageRecord(
                id="web-1",
                record_type="chat",
                project_id="project-1",
                project_name="Project One",
                employee_id="test1",
                employee_name="Test 1",
                source="chatgpt_web",
                title="Web detail",
                started_at=datetime(2026, 8, 7, 2, 0, tzinfo=timezone.utc),
                prompt_tokens=20,
                completion_tokens=30,
                total_tokens=50,
            ),
        ]
        snapshots = [
            AuthoritativeUsageDaily(
                usage_date=date(2026, 8, 7),
                request_count=4,
                input_tokens=200,
                output_tokens=100,
                cache_read_tokens=650,
                cache_creation_tokens=50,
                total_tokens=1000,
                error_count=1,
                total_cost=0.5,
            )
        ]

        summary = build_usage_summary_with_authoritative_source(
            records,
            authoritative_source="cc_switch",
            authoritative_daily=snapshots,
            start_date=date(2026, 8, 7),
            end_date=date(2026, 8, 7),
        )

        self.assertEqual(summary.total_tokens, 1050)
        self.assertEqual(summary.prompt_tokens, 920)
        self.assertEqual(summary.completion_tokens, 130)
        self.assertEqual(summary.record_count, 5)
        self.assertEqual(summary.error_count, 1)
        self.assertEqual(summary.daily_usage[0].total_tokens, 1050)
        self.assertEqual(
            [(item.source, item.total_tokens) for item in summary.source_usage],
            [("cc_switch", 1000), ("chatgpt_web", 50)],
        )


if __name__ == "__main__":
    unittest.main()
