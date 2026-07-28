from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from workday.domain import SpanRecord, aggregate_workday, business_day_utc_bounds


class BusinessDayTests(unittest.TestCase):
    def test_shanghai_business_day_is_converted_to_utc_half_open_range(self) -> None:
        start, end = business_day_utc_bounds(date(2026, 7, 20))

        self.assertEqual(start, datetime(2026, 7, 19, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc))


class CoreAggregationTests(unittest.TestCase):
    def test_no_matching_spans_returns_explicit_no_data_status(self) -> None:
        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-missing",
            work_date=date(2026, 7, 20),
            spans=[],
        )

        self.assertEqual(result.status, "no_data")
        self.assertEqual(result.overview.span_count, 0)
        self.assertEqual(result.overview.trace_count, 0)

    def test_conflicting_work_date_is_skipped_and_missing_task_is_unassigned(self) -> None:
        spans = [
            SpanRecord(
                timestamp=datetime(2026, 7, 20, 2, 0, tzinfo=timezone.utc),
                duration_ns=1_000_000_000,
                trace_id="trace-good",
                span_id="span-good",
                employee_id="emp-1",
                work_date="2026-07-20",
            ),
            SpanRecord(
                timestamp=datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc),
                duration_ns=1_000_000_000,
                trace_id="trace-conflict",
                span_id="span-conflict",
                employee_id="emp-1",
                task_id="wrong-day",
                work_date="2026-07-19",
            ),
        ]

        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=spans,
        )

        self.assertEqual(result.overview.span_count, 1)
        self.assertEqual(result.tasks[0].task_id, "unassigned")
        self.assertEqual(result.tasks[0].title, "未标记任务")
        self.assertIn("1 个 Span 的 agentops.work.date 与请求日期冲突，已跳过", result.warnings)
        self.assertIn("1 个 Span 未标记任务，已归入 unassigned", result.warnings)

    def test_task_duration_merges_overlapping_trace_intervals(self) -> None:
        spans = [
            SpanRecord(
                timestamp=datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc),
                duration_ns=10_000_000_000,
                trace_id="trace-a",
                span_id="span-a",
                employee_id="emp-1",
                task_id="task-1",
                task_title="Parallel work",
                work_date="2026-07-20",
            ),
            SpanRecord(
                timestamp=datetime(2026, 7, 20, 1, 0, 5, tzinfo=timezone.utc),
                duration_ns=10_000_000_000,
                trace_id="trace-b",
                span_id="span-b",
                employee_id="emp-1",
                task_id="task-1",
                task_title="Parallel work",
                work_date="2026-07-20",
            ),
        ]

        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=spans,
        )

        self.assertEqual(result.tasks[0].trace_count, 2)
        self.assertAlmostEqual(result.tasks[0].duration_seconds, 15.0)

    def test_narrative_summary_is_deterministic_and_uses_only_aggregated_facts(self) -> None:
        span = SpanRecord(
            timestamp=datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc),
            duration_ns=2_000_000_000,
            trace_id="trace-1",
            span_id="span-1",
            employee_id="emp-1",
            employee_name="Alice",
            task_id="task-1",
            task_title="日报",
            work_date="2026-07-20",
            model="MiniMax-M3",
            total_tokens=12,
            reported_cost=0.5,
        )

        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=[span],
        )

        self.assertEqual(
            result.narrative_summary,
            "Alice 在 2026-07-20 共完成 1 个任务，产生 1 条 Trace、1 个 Span；"
            "其中 LLM 调用 1 次、工具调用 0 次、错误 0 次，"
            "累计 12 Tokens，估算成本 0.500000。",
        )

    def test_single_task_does_not_create_a_cost_share_hotspot(self) -> None:
        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=[
                SpanRecord(
                    timestamp=datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc),
                    duration_ns=100_000_000,
                    trace_id="trace-1",
                    span_id="span-1",
                    employee_id="emp-1",
                    task_id="task-only",
                    task_title="唯一任务",
                    work_date="2026-07-20",
                    model="MiniMax-M3",
                    reported_cost=1.0,
                )
            ],
        )

        self.assertFalse(
            any(
                finding.finding_type == "cost"
                and "成本占比较高" in finding.title
                for finding in result.findings
            )
        )
        self.assertEqual(result.distillation_candidates, ())

    def test_findings_cover_cost_latency_and_repeated_tool_errors(self) -> None:
        base = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
        spans = [
            SpanRecord(
                timestamp=base,
                duration_ns=100_000_000,
                trace_id="trace-cheap",
                span_id="cheap",
                employee_id="emp-1",
                task_id="task-cheap",
                work_date="2026-07-20",
                model="m",
                reported_cost=1.0,
            ),
            SpanRecord(
                timestamp=base,
                duration_ns=100_000_000,
                trace_id="trace-hot",
                span_id="hot",
                employee_id="emp-1",
                task_id="task-hot",
                work_date="2026-07-20",
                model="m",
                reported_cost=10.0,
            ),
            SpanRecord(
                timestamp=base,
                duration_ns=1_000_000_000,
                trace_id="trace-slow",
                span_id="slow",
                employee_id="emp-1",
                task_id="task-slow",
                work_date="2026-07-20",
                model="m",
                reported_cost=1.0,
            ),
            SpanRecord(
                timestamp=base,
                duration_ns=100_000_000,
                trace_id="trace-error-a",
                span_id="error-a",
                employee_id="emp-1",
                task_id="task-errors",
                work_date="2026-07-20",
                status_code="ERROR",
                tool_name="shell",
            ),
            SpanRecord(
                timestamp=base,
                duration_ns=100_000_000,
                trace_id="trace-error-b",
                span_id="error-b",
                employee_id="emp-1",
                task_id="task-errors",
                work_date="2026-07-20",
                status_code="ERROR",
                tool_name="shell",
            ),
        ]

        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=spans,
        )

        finding_types = {finding.finding_type for finding in result.findings}
        self.assertIn("cost", finding_types)
        self.assertIn("latency", finding_types)
        self.assertIn("error", finding_types)
        repeated_tool = next(
            finding
            for finding in result.findings
            if finding.evidence.get("tool_name") == "shell"
        )
        self.assertEqual(repeated_tool.task_id, "task-errors")
        self.assertEqual(set(repeated_tool.trace_ids), {"trace-error-a", "trace-error-b"})
        self.assertEqual(repeated_tool.threshold, 2.0)
        self.assertEqual(repeated_tool.actual_value, 2.0)
        self.assertTrue(result.distillation_candidates)
        self.assertTrue(
            all(
                candidate.status == "pending"
                for candidate in result.distillation_candidates
            )
        )
        hot_trace = next(
            trace
            for trace in result.important_traces
            if trace.trace_id == "trace-hot"
        )
        self.assertEqual(hot_trace.reasons.count("cost_finding"), 1)

    def test_important_trace_uses_high_tool_fallback_when_day_has_fewer_than_ten_traces(self) -> None:
        base = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
        spans = [
            SpanRecord(
                timestamp=base,
                duration_ns=100_000_000,
                trace_id="trace-a",
                span_id="a-1",
                employee_id="emp-1",
                task_id="task-1",
                work_date="2026-07-20",
                tool_name="search",
            ),
            *[
                SpanRecord(
                    timestamp=base,
                    duration_ns=100_000_000,
                    trace_id="trace-b",
                    span_id=f"b-{index}",
                    employee_id="emp-1",
                    task_id="task-2",
                    work_date="2026-07-20",
                    tool_name="search",
                )
                for index in range(3)
            ],
        ]

        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=spans,
        )

        self.assertEqual([trace.trace_id for trace in result.important_traces], ["trace-b"])
        self.assertEqual(result.important_traces[0].reasons, ("high_tool_usage",))
        self.assertEqual(result.distillation_candidates, ())

    def test_trace_latency_p95_and_top_ten_percent_tool_selection(self) -> None:
        base = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
        spans = []
        for trace_index in range(20):
            spans.append(
                SpanRecord(
                    timestamp=base,
                    duration_ns=(trace_index + 1) * 1_000_000,
                    trace_id=f"trace-{trace_index:02d}",
                    span_id=f"base-{trace_index}",
                    employee_id="emp-1",
                    task_id=f"task-{trace_index}",
                    work_date="2026-07-20",
                )
            )
        spans.extend(
            SpanRecord(
                timestamp=base,
                duration_ns=1_000_000,
                trace_id="trace-18",
                span_id=f"tool-{index}",
                employee_id="emp-1",
                task_id="task-18",
                work_date="2026-07-20",
                tool_name="search",
            )
            for index in range(5)
        )

        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=spans,
        )

        latency_trace_ids = {
            trace_id
            for finding in result.findings
            if finding.finding_type == "latency"
            for trace_id in finding.trace_ids
        }
        self.assertIn("trace-19", latency_trace_ids)
        selected = {
            trace.trace_id: trace.reasons for trace in result.important_traces
        }
        self.assertIn("high_tool_usage", selected["trace-18"])

    def test_raw_metrics_are_structural_and_unknown_model_price_adds_warning(self) -> None:
        spans = [
            SpanRecord(
                timestamp=datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc),
                duration_ns=100_000_000,
                trace_id="trace-1",
                span_id="llm",
                employee_id="emp-1",
                task_id="task-1",
                work_date="2026-07-20",
                model="unknown-model",
                prompt_tokens=10,
                completion_tokens=5,
                reasoning_tokens=2,
                cache_read_input_tokens=3,
                calculated_cost=0.0,
            ),
            SpanRecord(
                timestamp=datetime(2026, 7, 20, 1, 0, 1, tzinfo=timezone.utc),
                duration_ns=100_000_000,
                trace_id="trace-1",
                span_id="tool",
                employee_id="emp-1",
                task_id="task-1",
                work_date="2026-07-20",
                status_code="ERROR",
                tool_name="shell",
            ),
        ]

        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=spans,
        )

        self.assertEqual(result.raw_metrics.prompt_tokens, 10)
        self.assertEqual(result.raw_metrics.completion_tokens, 5)
        self.assertEqual(result.raw_metrics.reasoning_tokens, 2)
        self.assertEqual(result.raw_metrics.cache_read_input_tokens, 3)
        self.assertEqual(result.raw_metrics.model_usage[0].name, "unknown-model")
        self.assertEqual(result.raw_metrics.tool_usage[0].name, "shell")
        self.assertIn(
            "模型 unknown-model 未找到价格，相关成本按 0 计算",
            result.warnings,
        )

    def test_core_metrics_classify_llm_tool_errors_tokens_cost_and_latency(self) -> None:
        spans = [
            SpanRecord(
                timestamp=datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc),
                duration_ns=2_000_000_000,
                trace_id="trace-1",
                span_id="span-llm",
                employee_id="emp-1",
                employee_name="Alice",
                task_id="task-1",
                task_title="Implement monitor",
                work_date="2026-07-20",
                status_code="OK",
                model="MiniMax-M3",
                gen_ai_operation="chat",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                reported_cost=0.02,
            ),
            SpanRecord(
                timestamp=datetime(2026, 7, 20, 1, 0, 1, tzinfo=timezone.utc),
                duration_ns=1_000_000_000,
                trace_id="trace-1",
                span_id="span-tool",
                employee_id="emp-1",
                employee_name="Alice",
                task_id="task-1",
                task_title="Implement monitor",
                work_date="2026-07-20",
                status_code="ERROR",
                tool_name="filesystem",
                tool_status="error",
            ),
        ]

        result = aggregate_workday(
            project_id="project-1",
            employee_id="emp-1",
            work_date=date(2026, 7, 20),
            spans=spans,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.overview.trace_count, 1)
        self.assertEqual(result.overview.span_count, 2)
        self.assertEqual(result.overview.task_count, 1)
        self.assertEqual(result.overview.llm_call_count, 1)
        self.assertEqual(result.overview.tool_call_count, 1)
        self.assertEqual(result.overview.error_count, 1)
        self.assertEqual(result.overview.total_tokens, 15)
        self.assertAlmostEqual(result.overview.total_cost, 0.02)
        self.assertAlmostEqual(result.overview.active_time_range_seconds, 2.0)
        self.assertAlmostEqual(result.overview.avg_llm_latency_ms, 2000.0)
        self.assertAlmostEqual(result.overview.p95_llm_latency_ms, 2000.0)


if __name__ == "__main__":
    unittest.main()
