from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone


def _attribute(key: str, value: str | int) -> dict:
    value_key = "intValue" if isinstance(value, int) else "stringValue"
    return {"key": key, "value": {value_key: str(value)}}


def _span(
    *,
    name: str,
    start_ns: int,
    duration_ms: int,
    employee_id: str,
    employee_name: str,
    work_date: str,
    task_id: str | None = None,
    task_title: str | None = None,
    attributes: dict[str, str | int] | None = None,
    error: bool = False,
) -> dict:
    values: dict[str, str | int] = {
        "agentops.employee.id": employee_id,
        "agentops.employee.name": employee_name,
        "agentops.work.date": work_date,
        **(attributes or {}),
    }
    if task_id:
        values["agentops.task.id"] = task_id
    if task_title:
        values["agentops.task.title"] = task_title
    return {
        "traceId": secrets.token_hex(16),
        "spanId": secrets.token_hex(8),
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + duration_ms * 1_000_000),
        "attributes": [_attribute(key, value) for key, value in values.items()],
        "status": {"code": 2 if error else 1},
    }


def build_payload(
    *,
    project_id: str,
    employee_id: str,
    employee_name: str,
    work_date: date,
) -> dict:
    shanghai_timezone = timezone(timedelta(hours=8))
    local_start = datetime.combine(
        work_date,
        time(hour=9),
        tzinfo=shanghai_timezone,
    )
    start_ns = int(local_start.timestamp()) * 1_000_000_000
    span_specs = [
        _span(
            name="sample.llm.normal",
            start_ns=start_ns,
            duration_ms=900,
            employee_id=employee_id,
            employee_name=employee_name,
            work_date=work_date.isoformat(),
            task_id="task-normal",
            task_title="实现 Workday Monitor",
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "MiniMax-M3",
                "gen_ai.usage.prompt_tokens": 120,
                "gen_ai.usage.completion_tokens": 40,
                "gen_ai.usage.total_tokens": 160,
                "gen_ai.usage.total_cost": "0.0125",
            },
        ),
        _span(
            name="sample.unassigned",
            start_ns=start_ns + 1_000_000_000,
            duration_ms=250,
            employee_id=employee_id,
            employee_name=employee_name,
            work_date=work_date.isoformat(),
        ),
        _span(
            name="sample.tool.failure.1",
            start_ns=start_ns + 2_000_000_000,
            duration_ms=300,
            employee_id=employee_id,
            employee_name=employee_name,
            work_date=work_date.isoformat(),
            task_id="task-tool-errors",
            task_title="排查工具异常",
            attributes={
                "agentops.span.kind": "tool",
                "tool.name": "sample-shell",
                "tool.status": "error",
            },
            error=True,
        ),
        _span(
            name="sample.tool.failure.2",
            start_ns=start_ns + 3_000_000_000,
            duration_ms=320,
            employee_id=employee_id,
            employee_name=employee_name,
            work_date=work_date.isoformat(),
            task_id="task-tool-errors",
            task_title="排查工具异常",
            attributes={
                "agentops.span.kind": "tool",
                "tool.name": "sample-shell",
                "tool.status": "error",
            },
            error=True,
        ),
        _span(
            name="sample.llm.unknown-price",
            start_ns=start_ns + 4_000_000_000,
            duration_ms=600,
            employee_id=employee_id,
            employee_name=employee_name,
            work_date=work_date.isoformat(),
            task_id="task-cost-missing",
            task_title="验证未知模型价格",
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "sample-unknown-model",
                "gen_ai.usage.prompt_tokens": 20,
                "gen_ai.usage.completion_tokens": 10,
            },
        ),
        _span(
            name="sample.date.conflict",
            start_ns=start_ns + 5_000_000_000,
            duration_ms=100,
            employee_id=employee_id,
            employee_name=employee_name,
            work_date=(work_date - timedelta(days=1)).isoformat(),
            task_id="task-date-conflict",
            task_title="该 Span 应被跳过",
        ),
    ]
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _attribute("agentops.project.id", project_id),
                        _attribute("service.name", "workday-sample"),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "agentops.workday.sample"},
                        "spans": span_specs,
                    }
                ],
            }
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit AI Workday OTLP samples")
    parser.add_argument(
        "--project-id",
        default=os.environ.get("AGENTOPS_PROJECT_ID"),
    )
    parser.add_argument("--employee-id", required=True)
    parser.add_argument("--employee-name", default="")
    parser.add_argument("--work-date", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--endpoint",
        default=os.environ.get(
            "AGENTOPS_OTLP_ENDPOINT",
            "http://localhost:4318/v1/traces",
        ),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("AGENTOPS_OTLP_TOKEN"),
    )
    args = parser.parse_args()
    if not args.project_id:
        parser.error("--project-id or AGENTOPS_PROJECT_ID is required")
    if not args.token:
        parser.error("--token or AGENTOPS_OTLP_TOKEN is required")

    payload = build_payload(
        project_id=args.project_id,
        employee_id=args.employee_id,
        employee_name=args.employee_name or args.employee_id,
        work_date=args.work_date,
    )
    request = urllib.request.Request(
        args.endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {args.token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(
                f"OTLP sample accepted: HTTP {response.status}; "
                f"employee={args.employee_id}; date={args.work_date}"
            )
            return 0
    except urllib.error.HTTPError as error:
        print(f"OTLP sample rejected: HTTP {error.code}", file=sys.stderr)
    except urllib.error.URLError as error:
        print(f"OTLP collector unavailable: {error.reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
