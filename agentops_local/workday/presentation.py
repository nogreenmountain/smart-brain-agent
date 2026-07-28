from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

from .domain import WorkdayAggregation


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def build_response_payload(
    aggregation: WorkdayAggregation,
    *,
    include_traces: bool,
    include_replay_refs: bool,
    include_raw_metrics: bool,
) -> dict[str, Any]:
    """Shape the stable public response while applying privacy include flags."""
    important_traces: list[dict[str, Any]] = []
    if include_traces:
        for trace in aggregation.important_traces:
            item = _json_value(trace)
            item["replay_url"] = (
                f"/traces?trace_id={trace.trace_id}"
                if include_replay_refs
                else None
            )
            important_traces.append(item)

    return {
        "status": aggregation.status,
        "project_id": aggregation.project_id,
        "employee": {
            "id": aggregation.employee_id,
            "name": aggregation.employee_name or aggregation.employee_id,
        },
        "date": aggregation.date.isoformat(),
        "timezone": "Asia/Shanghai",
        "overview": _json_value(aggregation.overview),
        "narrative_summary": aggregation.narrative_summary,
        "tasks": _json_value(aggregation.tasks),
        "findings": _json_value(aggregation.findings),
        "important_traces": important_traces,
        "distillation_candidates": _json_value(
            aggregation.distillation_candidates
        ),
        "raw_metrics": (
            _json_value(aggregation.raw_metrics)
            if include_raw_metrics
            else None
        ),
        "warnings": list(aggregation.warnings),
    }
