from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EmployeeSchema(BaseModel):
    id: str
    name: str


class OverviewSchema(BaseModel):
    active_start: datetime | None = None
    active_end: datetime | None = None
    active_time_range_seconds: float = 0
    trace_count: int = 0
    span_count: int = 0
    task_count: int = 0
    llm_call_count: int = 0
    tool_call_count: int = 0
    error_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0
    avg_llm_latency_ms: float = 0
    p95_llm_latency_ms: float = 0


class TaskSchema(BaseModel):
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


class FindingSchema(BaseModel):
    finding_type: Literal["cost", "latency", "error"]
    severity: Literal["medium", "high"]
    title: str
    description: str
    evidence: dict[str, Any]
    trace_ids: list[str]
    task_id: str | None = None
    threshold: float
    actual_value: float


class ImportantTraceSchema(BaseModel):
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
    reasons: list[str]
    replay_url: str | None = None


class DistillationCandidateSchema(BaseModel):
    candidate_id: str
    status: Literal["pending"]
    title: str
    reason: str
    task_id: str | None = None
    trace_ids: list[str]
    signals: list[str]


class ModelUsageSchema(BaseModel):
    name: str
    call_count: int
    total_tokens: int
    total_cost: float


class ToolUsageSchema(BaseModel):
    name: str
    call_count: int
    error_count: int


class RawMetricsSchema(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cache_read_input_tokens: int
    total_tokens: int
    model_usage: list[ModelUsageSchema] = Field(default_factory=list)
    tool_usage: list[ToolUsageSchema] = Field(default_factory=list)


class AIWorkdaySummary(BaseModel):
    status: Literal["ok", "no_data"]
    project_id: str
    employee: EmployeeSchema
    date: date
    timezone: Literal["Asia/Shanghai"]
    overview: OverviewSchema
    narrative_summary: str
    tasks: list[TaskSchema] = Field(default_factory=list)
    findings: list[FindingSchema] = Field(default_factory=list)
    important_traces: list[ImportantTraceSchema] = Field(default_factory=list)
    distillation_candidates: list[DistillationCandidateSchema] = Field(
        default_factory=list
    )
    raw_metrics: RawMetricsSchema | None = None
    warnings: list[str] = Field(default_factory=list)

