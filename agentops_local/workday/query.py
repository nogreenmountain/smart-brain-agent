from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

from .domain import SpanRecord, business_day_utc_bounds


def build_span_query(
    *,
    project_id: str,
    employee_id: str,
    work_date: date,
) -> tuple[str, dict[str, Any]]:
    """Build the privacy-whitelisted ClickHouse query for one employee day."""
    start_utc, end_utc = business_day_utc_bounds(work_date)
    employee_expr = """
        coalesce(
            nullIf(SpanAttributes['agentops.employee.id'], ''),
            nullIf(ResourceAttributes['agentops.employee.id'], '')
        )
    """
    model_expr = """
        coalesce(
            nullIf(SpanAttributes['gen_ai.response.model'], ''),
            nullIf(SpanAttributes['gen_ai.request.model'], ''),
            nullIf(SpanAttributes['llm.response.model'], ''),
            nullIf(SpanAttributes['llm.request.model'], ''),
            nullIf(SpanAttributes['llm.model'], ''),
            nullIf(SpanAttributes['model'], '')
        )
    """
    prompt_tokens_expr = """
        toUInt64OrZero(
            coalesce(
                nullIf(SpanAttributes['gen_ai.usage.prompt_tokens'], ''),
                nullIf(SpanAttributes['gen_ai.usage.input_tokens'], ''),
                nullIf(SpanAttributes['input_tokens'], ''),
                '0'
            )
        )
    """
    completion_tokens_expr = """
        toUInt64OrZero(
            coalesce(
                nullIf(SpanAttributes['gen_ai.usage.completion_tokens'], ''),
                nullIf(SpanAttributes['gen_ai.usage.output_tokens'], ''),
                nullIf(SpanAttributes['output_tokens'], ''),
                '0'
            )
        )
    """
    sql = f"""
        SELECT
            Timestamp AS timestamp,
            Duration AS duration_ns,
            TraceId AS trace_id,
            SpanId AS span_id,
            StatusCode AS status_code,
            {employee_expr} AS employee_id,
            coalesce(
                nullIf(SpanAttributes['agentops.employee.name'], ''),
                nullIf(ResourceAttributes['agentops.employee.name'], ''),
                ''
            ) AS employee_name,
            coalesce(
                nullIf(SpanAttributes['agentops.task.id'], ''),
                nullIf(ResourceAttributes['agentops.task.id'], ''),
                ''
            ) AS task_id,
            coalesce(
                nullIf(SpanAttributes['agentops.task.title'], ''),
                nullIf(ResourceAttributes['agentops.task.title'], ''),
                ''
            ) AS task_title,
            coalesce(
                nullIf(SpanAttributes['agentops.work.date'], ''),
                nullIf(ResourceAttributes['agentops.work.date'], ''),
                ''
            ) AS work_date,
            coalesce(
                nullIf(SpanAttributes['gen_ai.operation.name'], ''),
                nullIf(SpanAttributes['llm.request.type'], ''),
                nullIf(SpanAttributes['ai.system'], ''),
                nullIf(SpanAttributes['ai.llm'], ''),
                nullIf(SpanAttributes['span.type'], ''),
                ''
            ) AS gen_ai_operation,
            coalesce({model_expr}, '') AS model,
            {prompt_tokens_expr} AS prompt_tokens,
            {completion_tokens_expr} AS completion_tokens,
            toUInt64OrZero(coalesce(
                nullIf(SpanAttributes['gen_ai.usage.reasoning_tokens'], ''),
                nullIf(
                    SpanAttributes['gen_ai.usage.reasoning.output_tokens'],
                    ''
                ),
                '0'
            )) AS reasoning_tokens,
            toUInt64OrZero(coalesce(
                nullIf(
                    SpanAttributes['gen_ai.usage.cache_read_input_tokens'],
                    ''
                ),
                nullIf(
                    SpanAttributes['gen_ai.usage.cache_read.input_tokens'],
                    ''
                ),
                nullIf(SpanAttributes['cache_read_tokens'], ''),
                '0'
            )) AS cache_read_input_tokens,
            toUInt64OrZero(
                SpanAttributes['gen_ai.usage.total_tokens']
            ) AS total_tokens,
            if(
                SpanAttributes['gen_ai.usage.total_cost'] != '',
                toFloat64OrZero(SpanAttributes['gen_ai.usage.total_cost']),
                if(
                    SpanAttributes['llm.cost'] != '',
                    toFloat64OrZero(SpanAttributes['llm.cost']),
                    if(
                        SpanAttributes['gen_ai.usage.prompt_cost'] != ''
                        OR SpanAttributes['gen_ai.usage.completion_cost'] != '',
                        toFloat64OrZero(
                            SpanAttributes['gen_ai.usage.prompt_cost']
                        )
                        + toFloat64OrZero(
                            SpanAttributes['gen_ai.usage.completion_cost']
                        ),
                        CAST(NULL, 'Nullable(Float64)')
                    )
                )
            ) AS reported_cost,
            toFloat64(
                calculate_prompt_cost({prompt_tokens_expr}, coalesce({model_expr}, ''))
                + calculate_completion_cost(
                    {completion_tokens_expr},
                    coalesce({model_expr}, '')
                )
            ) AS calculated_cost,
            coalesce(
                nullIf(SpanAttributes['gen_ai.tool.name'], ''),
                nullIf(SpanAttributes['tool.name'], ''),
                nullIf(SpanAttributes['tool_name'], ''),
                ''
            ) AS tool_name,
            coalesce(
                nullIf(SpanAttributes['gen_ai.tool.call.id'], ''),
                ''
            ) AS tool_call_id,
            coalesce(
                nullIf(SpanAttributes['tool.status'], ''),
                if(
                    SpanAttributes['success'] = 'false',
                    'error',
                    CAST(NULL, 'Nullable(String)')
                ),
                ''
            ) AS tool_status,
            coalesce(
                nullIf(SpanAttributes['agentops.span.kind'], ''),
                if(
                    startsWith(
                        SpanAttributes['span.type'],
                        'claude_code.tool'
                    ),
                    'tool',
                    CAST(NULL, 'Nullable(String)')
                ),
                ''
            ) AS agentops_span_kind
        FROM otel_traces
        WHERE project_id = %(project_id)s
          AND Timestamp >= %(start_utc)s
          AND Timestamp < %(end_utc)s
          AND {employee_expr} = %(employee_id)s
        ORDER BY Timestamp ASC, TraceId ASC, SpanId ASC
    """
    return sql, {
        "project_id": project_id,
        "employee_id": employee_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }


def parse_span_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[SpanRecord], tuple[str, ...]]:
    """Parse typed ClickHouse rows, skipping isolated malformed spans."""
    spans: list[SpanRecord] = []
    skipped = 0
    for row in rows:
        try:
            timestamp = row["timestamp"]
            if not isinstance(timestamp, datetime):
                raise TypeError("timestamp must be datetime")
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = timestamp.astimezone(timezone.utc)
            trace_id = str(row["trace_id"])
            span_id = str(row["span_id"])
            employee_id = str(row["employee_id"])
            if not trace_id or not span_id or not employee_id:
                raise ValueError("required structural id is empty")
            reported_cost_value = row.get("reported_cost")
            spans.append(
                SpanRecord(
                    timestamp=timestamp,
                    duration_ns=max(int(row.get("duration_ns") or 0), 0),
                    trace_id=trace_id,
                    span_id=span_id,
                    employee_id=employee_id,
                    employee_name=str(row.get("employee_name") or ""),
                    task_id=str(row.get("task_id") or ""),
                    task_title=str(row.get("task_title") or ""),
                    work_date=str(row.get("work_date") or ""),
                    status_code=str(row.get("status_code") or ""),
                    model=str(row.get("model") or ""),
                    gen_ai_operation=str(row.get("gen_ai_operation") or ""),
                    prompt_tokens=max(int(row.get("prompt_tokens") or 0), 0),
                    completion_tokens=max(
                        int(row.get("completion_tokens") or 0),
                        0,
                    ),
                    reasoning_tokens=max(
                        int(row.get("reasoning_tokens") or 0),
                        0,
                    ),
                    cache_read_input_tokens=max(
                        int(row.get("cache_read_input_tokens") or 0),
                        0,
                    ),
                    total_tokens=max(int(row.get("total_tokens") or 0), 0),
                    reported_cost=(
                        float(reported_cost_value)
                        if reported_cost_value is not None
                        else None
                    ),
                    calculated_cost=max(
                        float(row.get("calculated_cost") or 0),
                        0.0,
                    ),
                    tool_name=str(row.get("tool_name") or ""),
                    tool_call_id=str(row.get("tool_call_id") or ""),
                    tool_status=str(row.get("tool_status") or ""),
                    agentops_span_kind=str(
                        row.get("agentops_span_kind") or ""
                    ),
                )
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            skipped += 1
    warnings = (
        (f"{skipped} 个 ClickHouse Span 字段异常，已跳过，不影响其余日报数据",)
        if skipped
        else ()
    )
    return spans, warnings


def fetch_span_records(
    client: Any,
    *,
    project_id: str,
    employee_id: str,
    work_date: date,
) -> tuple[list[SpanRecord], tuple[str, ...]]:
    sql, parameters = build_span_query(
        project_id=project_id,
        employee_id=employee_id,
        work_date=work_date,
    )
    result = client.query(sql, parameters=parameters)
    return parse_span_rows(result.named_results())
