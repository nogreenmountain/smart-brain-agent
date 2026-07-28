# AI Workday Monitor trace contract

Workday summaries are grouped by:

`agentops.project.id + agentops.employee.id + Asia/Shanghai business date`

Every participating span should carry these OpenTelemetry attributes:

| Attribute | Required | Meaning |
|---|---:|---|
| `agentops.employee.id` | yes | Stable employee aggregation key |
| `agentops.employee.name` | no | Display name; the API falls back to the ID |
| `agentops.task.id` | no | Stable task key; missing values become `unassigned` |
| `agentops.task.title` | no | Human-readable task title |
| `agentops.work.date` | no | `YYYY-MM-DD`; conflicting values are skipped with a warning |

The backend reads span attributes first and resource attributes second. In
practice, configure these attributes on every span so trace and task metrics
remain complete.

The first release reads only existing AgentOps traces. It does not collect
keyboard, mouse, screenshot, clipboard, browser-history, or desktop activity.
The Workday query never selects raw prompt/completion text, tool parameters,
tool results, secrets, full file contents, or full local paths.

## Claude Code, Codex, and CC Switch

CC Switch is the persistent configuration and provider-routing layer. It does
not emit AgentOps telemetry by itself. The generated employee bundle writes
trace-only OpenTelemetry settings into CC Switch Common Config for Claude Code
and Codex.

Each employee bundle uses a separate expiring collector JWT. The signed
`employee_id` and `employee_name` claims are injected by the server Collector,
overwriting client-supplied employee identity. Native Claude Code attributes
such as `input_tokens`, `output_tokens`, `cache_read_tokens`, `tool_name`, and
`span.type` are normalized by the Workday query alongside current
`gen_ai.usage.*` attributes.

Generate the test employee bundles with:

```powershell
.\scripts\Generate-EmployeeTelemetryBundles.ps1
```

Without a dynamic `agentops.task.id`, native CLI traces are grouped under the
`unassigned` task. Employee/day/application monitoring still works.

## Local OTLP sample

The sample uses only the Python standard library and emits:

- one normal LLM task;
- one unassigned task;
- two failures for the same tool;
- one LLM call with an unknown model price;
- one span whose `agentops.work.date` conflicts with the requested day.

First exchange the project API key for a collector bearer token, then run:

```powershell
$env:AGENTOPS_PROJECT_ID = "<project uuid>"
$env:AGENTOPS_OTLP_TOKEN = "<collector bearer token>"
py -3 scripts\emit_workday_sample.py `
  --employee-id emp-001 `
  --employee-name "测试员工" `
  --work-date 2026-07-20
```

The collector endpoint defaults to `http://localhost:4318/v1/traces`. Override
it with `--endpoint` or `AGENTOPS_OTLP_ENDPOINT`.

## Summary API

```http
GET /v4/workday/summary/{project_id}
  ?employee_id=employee-001
  &date=2026-07-20
  &include_traces=true
  &include_replay_refs=true
  &include_raw_metrics=true
```

- `date` is interpreted as an `Asia/Shanghai` business day.
- The caller must have a row in `public.project_members` for the project.
- `include_traces=false` omits important traces.
- `include_replay_refs=false` retains important traces but omits Replay URLs.
- `include_raw_metrics=false` omits token categories and model/tool details.
- Every allowed or forbidden query is audited as `workday_summary`.

Apply
`supabase/migrations/20260720000000_add_workday_audit_action.sql` before
enabling the endpoint against an existing database. It extends the
`audit_logs_action_check` constraint with the new action.

## Build and deploy

```powershell
cd D:\AgentOpsServer\AgentOps\app
docker build -f Dockerfile.api-workday `
  -t agentops-api-local:patched-2026-07-20-workday .
$env:ANTHROPIC_BASE_URL = "http://host.docker.internal:15721"
docker compose -f compose.server.yaml -f compose.server.override.yaml `
  up -d api smartbrain --force-recreate
```

The SmartBrain page is available at
`http://192.168.1.40:3002/workday`. Replay links open the AgentOps Dashboard
on port `3001`.
