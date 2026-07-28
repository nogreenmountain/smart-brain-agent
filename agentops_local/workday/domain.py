from __future__ import annotations

import math
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class SpanRecord:
    timestamp: datetime
    duration_ns: int
    trace_id: str
    span_id: str
    employee_id: str
    employee_name: str = ""
    task_id: str = ""
    task_title: str = ""
    work_date: str = ""
    status_code: str = ""
    model: str = ""
    gen_ai_operation: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_input_tokens: int = 0
    total_tokens: int = 0
    reported_cost: float | None = None
    calculated_cost: float = 0.0
    tool_name: str = ""
    tool_call_id: str = ""
    tool_status: str = ""
    agentops_span_kind: str = ""

    @property
    def end_time(self) -> datetime:
        return self.timestamp + timedelta(seconds=max(self.duration_ns, 0) / 1_000_000_000)

    @property
    def is_tool(self) -> bool:
        return bool(
            self.tool_name
            or self.tool_call_id
            or self.agentops_span_kind.lower() == "tool"
        )

    @property
    def is_llm(self) -> bool:
        return not self.is_tool and bool(
            self.model
            or self.gen_ai_operation
            or self.prompt_tokens
            or self.completion_tokens
            or self.reasoning_tokens
            or self.cache_read_input_tokens
            or self.total_tokens
        )

    @property
    def is_error(self) -> bool:
        return self.status_code.upper() == "ERROR" or self.tool_status.lower() in {
            "error",
            "failed",
            "failure",
        }

    @property
    def effective_total_tokens(self) -> int:
        if self.total_tokens:
            return self.total_tokens
        return (
            self.prompt_tokens
            + self.completion_tokens
            + self.reasoning_tokens
            + self.cache_read_input_tokens
        )

    @property
    def cost(self) -> float:
        return self.reported_cost if self.reported_cost is not None else self.calculated_cost


@dataclass(frozen=True)
class Overview:
    active_start: datetime | None = None
    active_end: datetime | None = None
    active_time_range_seconds: float = 0.0
    trace_count: int = 0
    span_count: int = 0
    task_count: int = 0
    llm_call_count: int = 0
    tool_call_count: int = 0
    error_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_llm_latency_ms: float = 0.0
    p95_llm_latency_ms: float = 0.0


@dataclass(frozen=True)
class TaskSummary:
    task_id: str
    title: str
    duration_seconds: float
    trace_count: int
    span_count: int
    llm_call_count: int
    tool_call_count: int
    error_count: int
    total_tokens: int
    total_cost: float
    avg_llm_latency_ms: float


@dataclass(frozen=True)
class Finding:
    finding_type: Literal["cost", "latency", "error"]
    severity: Literal["medium", "high"]
    title: str
    description: str
    evidence: dict[str, object]
    trace_ids: tuple[str, ...]
    task_id: str | None
    threshold: float
    actual_value: float


@dataclass(frozen=True)
class ImportantTrace:
    trace_id: str
    task_id: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    span_count: int
    llm_call_count: int
    tool_call_count: int
    error_count: int
    total_tokens: int
    total_cost: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DistillationCandidate:
    candidate_id: str
    status: Literal["pending"]
    title: str
    reason: str
    task_id: str | None
    trace_ids: tuple[str, ...]
    signals: tuple[str, ...]


@dataclass(frozen=True)
class ModelUsage:
    name: str
    call_count: int
    total_tokens: int
    total_cost: float


@dataclass(frozen=True)
class ToolUsage:
    name: str
    call_count: int
    error_count: int


@dataclass(frozen=True)
class RawMetrics:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_input_tokens: int = 0
    total_tokens: int = 0
    model_usage: tuple[ModelUsage, ...] = ()
    tool_usage: tuple[ToolUsage, ...] = ()


@dataclass(frozen=True)
class WorkdayAggregation:
    project_id: str
    employee_id: str
    employee_name: str
    date: date
    status: Literal["ok", "no_data"]
    overview: Overview
    narrative_summary: str = ""
    tasks: tuple[TaskSummary, ...] = ()
    findings: tuple[Finding, ...] = ()
    important_traces: tuple[ImportantTrace, ...] = ()
    distillation_candidates: tuple[DistillationCandidate, ...] = ()
    raw_metrics: RawMetrics = field(default_factory=RawMetrics)
    warnings: tuple[str, ...] = ()


def business_day_utc_bounds(work_date: date) -> tuple[datetime, datetime]:
    """Return the half-open UTC range for one Shanghai business day."""
    local_start = datetime.combine(work_date, time.min, tzinfo=BUSINESS_TIMEZONE)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _merged_duration_seconds(intervals: list[tuple[datetime, datetime]]) -> float:
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    merged: list[tuple[datetime, datetime]] = [ordered[0]]
    for start, end in ordered[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return sum((end - start).total_seconds() for start, end in merged)


def _task_summary(task_id: str, spans: list[SpanRecord]) -> TaskSummary:
    trace_intervals: list[tuple[datetime, datetime]] = []
    for trace_id in {span.trace_id for span in spans}:
        trace_spans = [span for span in spans if span.trace_id == trace_id]
        trace_intervals.append(
            (
                min(span.timestamp for span in trace_spans),
                max(span.end_time for span in trace_spans),
            )
        )
    llm_latencies = [
        span.duration_ns / 1_000_000 for span in spans if span.is_llm
    ]
    title = next((span.task_title for span in spans if span.task_title), "")
    if task_id == "unassigned":
        title = "未标记任务"
    elif not title:
        title = task_id
    return TaskSummary(
        task_id=task_id,
        title=title,
        duration_seconds=_merged_duration_seconds(trace_intervals),
        trace_count=len({span.trace_id for span in spans}),
        span_count=len(spans),
        llm_call_count=sum(span.is_llm for span in spans),
        tool_call_count=sum(span.is_tool for span in spans),
        error_count=sum(span.is_error for span in spans),
        total_tokens=sum(span.effective_total_tokens for span in spans),
        total_cost=round(sum(span.cost for span in spans), 9),
        avg_llm_latency_ms=(
            sum(llm_latencies) / len(llm_latencies) if llm_latencies else 0.0
        ),
    )


def _narrative_summary(
    employee_name: str,
    employee_id: str,
    work_date: date,
    overview: Overview,
) -> str:
    employee_label = employee_name or employee_id
    return (
        f"{employee_label} 在 {work_date.isoformat()} 共完成 {overview.task_count} 个任务，"
        f"产生 {overview.trace_count} 条 Trace、{overview.span_count} 个 Span；"
        f"其中 LLM 调用 {overview.llm_call_count} 次、工具调用 "
        f"{overview.tool_call_count} 次、错误 {overview.error_count} 次，"
        f"累计 {overview.total_tokens} Tokens，估算成本 "
        f"{overview.total_cost:.6f}。"
    )


def _trace_groups(spans: list[SpanRecord]) -> dict[str, list[SpanRecord]]:
    return {
        trace_id: [span for span in spans if span.trace_id == trace_id]
        for trace_id in sorted({span.trace_id for span in spans})
    }


def _build_findings(
    spans: list[SpanRecord],
    tasks: tuple[TaskSummary, ...],
    overview: Overview,
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    trace_groups = _trace_groups(spans)
    task_trace_ids = {
        task.task_id: tuple(
            sorted(
                {
                    span.trace_id
                    for span in spans
                    if (span.task_id or "unassigned") == task.task_id
                }
            )
        )
        for task in tasks
    }

    if overview.total_cost > 0 and len(tasks) > 1:
        for task in tasks:
            cost_share = task.total_cost / overview.total_cost
            if cost_share > 0.30:
                findings.append(
                    Finding(
                        finding_type="cost",
                        severity="medium",
                        title=f"任务成本占比较高：{task.title}",
                        description=(
                            f"该任务成本占当日总成本的 {cost_share:.1%}，"
                            "超过 30% 阈值。"
                        ),
                        evidence={
                            "task_cost": task.total_cost,
                            "day_cost": overview.total_cost,
                            "cost_share": cost_share,
                        },
                        trace_ids=task_trace_ids[task.task_id],
                        task_id=task.task_id,
                        threshold=0.30,
                        actual_value=cost_share,
                    )
                )

        average_trace_cost = overview.total_cost / max(overview.trace_count, 1)
        trace_cost_threshold = average_trace_cost * 3
        for trace_id, trace_spans in trace_groups.items():
            trace_cost = sum(span.cost for span in trace_spans)
            if trace_cost > trace_cost_threshold:
                task_id = next(
                    (
                        span.task_id or "unassigned"
                        for span in trace_spans
                    ),
                    None,
                )
                findings.append(
                    Finding(
                        finding_type="cost",
                        severity="medium",
                        title=f"Trace 成本异常：{trace_id}",
                        description="该 Trace 成本超过当日平均 Trace 成本的 3 倍。",
                        evidence={
                            "trace_cost": trace_cost,
                            "average_trace_cost": average_trace_cost,
                        },
                        trace_ids=(trace_id,),
                        task_id=task_id,
                        threshold=trace_cost_threshold,
                        actual_value=trace_cost,
                    )
                )

    trace_durations_ms: dict[str, float] = {}
    for trace_id, trace_spans in trace_groups.items():
        trace_start = min(span.timestamp for span in trace_spans)
        trace_end = max(span.end_time for span in trace_spans)
        trace_durations_ms[trace_id] = (trace_end - trace_start).total_seconds() * 1000
    trace_duration_p95 = _percentile(list(trace_durations_ms.values()), 0.95)
    for trace_id, duration_ms in trace_durations_ms.items():
        if duration_ms > trace_duration_p95:
            trace_spans = trace_groups[trace_id]
            findings.append(
                Finding(
                    finding_type="latency",
                    severity="medium",
                    title=f"Trace 延迟异常：{trace_id}",
                    description="该 Trace 墙钟时长超过当日 Trace 时长 P95。",
                    evidence={
                        "trace_duration_ms": duration_ms,
                        "day_trace_p95_ms": trace_duration_p95,
                    },
                    trace_ids=(trace_id,),
                    task_id=next(
                        (span.task_id or "unassigned" for span in trace_spans),
                        None,
                    ),
                    threshold=trace_duration_p95,
                    actual_value=duration_ms,
                )
            )

    if overview.avg_llm_latency_ms > 0:
        task_latency_threshold = overview.avg_llm_latency_ms * 2
        for task in tasks:
            if task.avg_llm_latency_ms > task_latency_threshold:
                findings.append(
                    Finding(
                        finding_type="latency",
                        severity="medium",
                        title=f"任务 LLM 延迟较高：{task.title}",
                        description="该任务平均 LLM 延迟超过当日平均值的 2 倍。",
                        evidence={
                            "task_avg_llm_latency_ms": task.avg_llm_latency_ms,
                            "day_avg_llm_latency_ms": overview.avg_llm_latency_ms,
                        },
                        trace_ids=task_trace_ids[task.task_id],
                        task_id=task.task_id,
                        threshold=task_latency_threshold,
                        actual_value=task.avg_llm_latency_ms,
                    )
                )

    for task in tasks:
        if task.error_count >= 2:
            findings.append(
                Finding(
                    finding_type="error",
                    severity="high",
                    title=f"任务重复报错：{task.title}",
                    description="该任务当日错误数达到或超过 2 次。",
                    evidence={"task_error_count": task.error_count},
                    trace_ids=task_trace_ids[task.task_id],
                    task_id=task.task_id,
                    threshold=2.0,
                    actual_value=float(task.error_count),
                )
            )

    tool_failures: dict[tuple[str, str], list[str]] = {}
    for span in spans:
        if span.is_tool and span.is_error and span.tool_name:
            key = (span.task_id or "unassigned", span.tool_name)
            tool_failures.setdefault(key, []).append(span.trace_id)
    for (task_id, tool_name), trace_ids in sorted(tool_failures.items()):
        if len(trace_ids) >= 2:
            findings.append(
                Finding(
                    finding_type="error",
                    severity="high",
                    title=f"工具重复失败：{tool_name}",
                    description="同一工具在该任务中失败达到或超过 2 次。",
                    evidence={
                        "tool_name": tool_name,
                        "failure_count": len(trace_ids),
                    },
                    trace_ids=tuple(sorted(set(trace_ids))),
                    task_id=task_id,
                    threshold=2.0,
                    actual_value=float(len(trace_ids)),
                )
            )
    return tuple(findings)


def _build_important_traces(
    spans: list[SpanRecord],
    findings: tuple[Finding, ...],
) -> tuple[ImportantTrace, ...]:
    trace_groups = _trace_groups(spans)
    reasons_by_trace: dict[str, set[str]] = {}
    for finding in findings:
        reason = f"{finding.finding_type}_finding"
        for trace_id in finding.trace_ids:
            reasons_by_trace.setdefault(trace_id, set()).add(reason)

    tool_counts = {
        trace_id: sum(span.is_tool for span in trace_spans)
        for trace_id, trace_spans in trace_groups.items()
    }
    if len(trace_groups) < 10:
        if tool_counts:
            trace_id, tool_count = max(
                tool_counts.items(),
                key=lambda item: (item[1], item[0]),
            )
            if tool_count > 0:
                reasons_by_trace.setdefault(trace_id, set()).add("high_tool_usage")
    else:
        top_count = max(1, math.ceil(len(trace_groups) * 0.10))
        ranked = sorted(
            tool_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:top_count]
        for trace_id, tool_count in ranked:
            if tool_count > 0:
                reasons_by_trace.setdefault(trace_id, set()).add("high_tool_usage")

    important: list[ImportantTrace] = []
    for trace_id in sorted(reasons_by_trace):
        trace_spans = trace_groups.get(trace_id)
        if not trace_spans:
            continue
        start_time = min(span.timestamp for span in trace_spans)
        end_time = max(span.end_time for span in trace_spans)
        important.append(
            ImportantTrace(
                trace_id=trace_id,
                task_id=next(
                    (span.task_id or "unassigned" for span in trace_spans),
                    "unassigned",
                ),
                start_time=start_time,
                end_time=end_time,
                duration_seconds=(end_time - start_time).total_seconds(),
                span_count=len(trace_spans),
                llm_call_count=sum(span.is_llm for span in trace_spans),
                tool_call_count=sum(span.is_tool for span in trace_spans),
                error_count=sum(span.is_error for span in trace_spans),
                total_tokens=sum(
                    span.effective_total_tokens for span in trace_spans
                ),
                total_cost=round(sum(span.cost for span in trace_spans), 9),
                reasons=tuple(sorted(reasons_by_trace[trace_id])),
            )
        )
    return tuple(important)


def _build_distillation_candidates(
    project_id: str,
    employee_id: str,
    work_date: date,
    findings: tuple[Finding, ...],
) -> tuple[DistillationCandidate, ...]:
    candidates: list[DistillationCandidate] = []
    for finding in findings:
        identity = "|".join(
            (
                project_id,
                employee_id,
                work_date.isoformat(),
                finding.finding_type,
                finding.task_id or "",
                ",".join(finding.trace_ids),
                finding.title,
            )
        )
        candidate_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        candidates.append(
            DistillationCandidate(
                candidate_id=candidate_id,
                status="pending",
                title=f"待复核：{finding.title}",
                reason=finding.description,
                task_id=finding.task_id,
                trace_ids=finding.trace_ids,
                signals=(finding.finding_type, finding.severity),
            )
        )
    return tuple(candidates)


def _build_raw_metrics(
    spans: list[SpanRecord],
) -> tuple[RawMetrics, tuple[str, ...]]:
    model_groups: dict[str, list[SpanRecord]] = {}
    tool_groups: dict[str, list[SpanRecord]] = {}
    warnings: set[str] = set()
    for span in spans:
        if span.is_llm:
            model_name = span.model or "unknown"
            model_groups.setdefault(model_name, []).append(span)
            if (
                span.reported_cost is None
                and span.calculated_cost == 0
                and span.effective_total_tokens > 0
            ):
                if span.model:
                    warnings.add(
                        f"模型 {span.model} 未找到价格，相关成本按 0 计算"
                    )
                else:
                    warnings.add("LLM Span 缺少模型名，相关成本按 0 计算")
        if span.is_tool:
            tool_groups.setdefault(span.tool_name or "unknown", []).append(span)

    model_usage = tuple(
        ModelUsage(
            name=name,
            call_count=len(group),
            total_tokens=sum(span.effective_total_tokens for span in group),
            total_cost=round(sum(span.cost for span in group), 9),
        )
        for name, group in sorted(model_groups.items())
    )
    tool_usage = tuple(
        ToolUsage(
            name=name,
            call_count=len(group),
            error_count=sum(span.is_error for span in group),
        )
        for name, group in sorted(tool_groups.items())
    )
    return (
        RawMetrics(
            prompt_tokens=sum(span.prompt_tokens for span in spans),
            completion_tokens=sum(span.completion_tokens for span in spans),
            reasoning_tokens=sum(span.reasoning_tokens for span in spans),
            cache_read_input_tokens=sum(
                span.cache_read_input_tokens for span in spans
            ),
            total_tokens=sum(span.effective_total_tokens for span in spans),
            model_usage=model_usage,
            tool_usage=tool_usage,
        ),
        tuple(sorted(warnings)),
    )


def aggregate_workday(
    *,
    project_id: str,
    employee_id: str,
    work_date: date,
    spans: list[SpanRecord],
) -> WorkdayAggregation:
    expected_work_date = work_date.isoformat()
    conflicting_count = sum(
        bool(span.work_date and span.work_date != expected_work_date) for span in spans
    )
    included_spans = [
        span
        for span in spans
        if not span.work_date or span.work_date == expected_work_date
    ]
    warnings: list[str] = []
    if conflicting_count:
        warnings.append(
            f"{conflicting_count} 个 Span 的 agentops.work.date 与请求日期冲突，已跳过"
        )
    unassigned_count = sum(not span.task_id for span in included_spans)
    if unassigned_count:
        warnings.append(
            f"{unassigned_count} 个 Span 未标记任务，已归入 unassigned"
        )

    if not included_spans:
        return WorkdayAggregation(
            project_id=project_id,
            employee_id=employee_id,
            employee_name="",
            date=work_date,
            status="no_data",
            overview=Overview(),
            warnings=tuple(warnings),
        )

    active_start = min(span.timestamp for span in included_spans)
    active_end = max(span.end_time for span in included_spans)
    llm_latencies_ms = [
        span.duration_ns / 1_000_000 for span in included_spans if span.is_llm
    ]
    task_ids = {span.task_id or "unassigned" for span in included_spans}
    employee_name = next(
        (span.employee_name for span in included_spans if span.employee_name),
        "",
    )
    overview = Overview(
        active_start=active_start,
        active_end=active_end,
        active_time_range_seconds=(active_end - active_start).total_seconds(),
        trace_count=len({span.trace_id for span in included_spans}),
        span_count=len(included_spans),
        task_count=len(task_ids),
        llm_call_count=sum(span.is_llm for span in included_spans),
        tool_call_count=sum(span.is_tool for span in included_spans),
        error_count=sum(span.is_error for span in included_spans),
        total_tokens=sum(span.effective_total_tokens for span in included_spans),
        total_cost=round(sum(span.cost for span in included_spans), 9),
        avg_llm_latency_ms=(
            sum(llm_latencies_ms) / len(llm_latencies_ms)
            if llm_latencies_ms
            else 0.0
        ),
        p95_llm_latency_ms=_percentile(llm_latencies_ms, 0.95),
    )
    tasks = tuple(
        _task_summary(
            task_id,
            [
                span
                for span in included_spans
                if (span.task_id or "unassigned") == task_id
            ],
        )
        for task_id in sorted(task_ids)
    )
    findings = _build_findings(included_spans, tasks, overview)
    raw_metrics, cost_warnings = _build_raw_metrics(included_spans)
    warnings.extend(cost_warnings)
    return WorkdayAggregation(
        project_id=project_id,
        employee_id=employee_id,
        employee_name=employee_name,
        date=work_date,
        status="ok",
        overview=overview,
        narrative_summary=_narrative_summary(
            employee_name,
            employee_id,
            work_date,
            overview,
        ),
        tasks=tasks,
        findings=findings,
        important_traces=_build_important_traces(included_spans, findings),
        distillation_candidates=_build_distillation_candidates(
            project_id,
            employee_id,
            work_date,
            findings,
        ),
        raw_metrics=raw_metrics,
        warnings=tuple(warnings),
    )
