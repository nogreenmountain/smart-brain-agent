# CC Switch employee telemetry enrollment

CC Switch remains responsible for provider selection, local routing, and
preserving shared client configuration. Claude Code and Codex produce the
OpenTelemetry traces.

The generated universal bundle contains no employee identity or telemetry
credential. At install time it:

1. Logs in through the existing AgentOps username/password endpoint.
2. Verifies that the authenticated user belongs to the target project.
3. Derives the employee ID from that account.
4. Receives a signed, expiring telemetry JWT.
5. Writes the resulting Claude/Codex configuration locally.
6. Deletes the intermediate token-bearing files.

The password is used only for this one login and is never written to disk,
CC Switch, Claude, or Codex.

The server Collector overwrites client-supplied employee identity from those
signed claims. Employee CLI logs are dropped, and sensitive trace attributes
are removed before ClickHouse export. The generated client configuration also
disables prompt, assistant response, tool detail/content, and raw API body
logging.

The Windows installer also appends the Collector host, `127.0.0.1`, and
`localhost` to the user-level `NO_PROXY` value. This is required when a system
proxy would otherwise intercept Codex's OTLP request. The previous value is
backed up, and uninstall removes only entries introduced by the installer.

Generate the one universal bundle from the running API container:

```powershell
cd D:\AgentOpsServer\AgentOps\app
.\scripts\Generate-UniversalEmployeeTelemetryBundle.ps1
```

The generated directory is written outside the application repository:

`D:\AgentOpsServer\AgentOps\employee-deploy\universal\ai-workday-universal`

The same directory can be distributed to every employee. When a token expires,
the employee reruns the same installer and logs in again; the administrator
does not regenerate an employee-specific package.

The deployment images are:

- `agentops-api-local:patched-2026-07-20-workday-ccswitch`
- `agentops-otel-local:workday-ccswitch-2026-07-20`
