#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PublicOtlpUrl = "https://39.105.79.0/v1/traces",
    [string]$ProjectId = "dfaefd9a-8e5e-4775-bc18-e3d551c651e4"
)

$ErrorActionPreference = "Stop"

$runId = [guid]::NewGuid().ToString("N")
$employeeId = "public-relay-smoke-$($runId.Substring(0, 12))"
$remoteRoot = "/tmp/smartbrain-public-otlp-$runId"
$remoteScript = "$remoteRoot/emit_workday_sample.py"
$clickhousePassword = ((
    Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\.env") |
        Where-Object { $_ -like "CLICKHOUSE_PASSWORD=*" } |
        Select-Object -First 1
) -split "=", 2)[1]
if (-not $clickhousePassword) { throw "Missing ClickHouse password." }

$token = $null
try {
    $token = docker exec agentops-api-1 /app/.venv/bin/python -c (
        "import os; from employee_telemetry.bundle import mint_telemetry_token; " +
        "print(mint_telemetry_token(secret=os.environ['JWT_SECRET_KEY'], " +
        "project_id='$ProjectId', employee_id='$employeeId', " +
        "employee_name='Public Relay Smoke', expires_in_days=1))"
    )
    if ($LASTEXITCODE -ne 0 -or -not $token) { throw "Could not mint a smoke-test token." }

    docker exec agentops-api-1 mkdir -p $remoteRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare the API smoke-test directory." }
    docker cp (Join-Path $PSScriptRoot "emit_workday_sample.py") "agentops-api-1:$remoteScript" | Out-Null
    $workDate = Get-Date -Format "yyyy-MM-dd"
    $sampleOutput = docker exec `
        -e "AGENTOPS_OTLP_TOKEN=$token" `
        agentops-api-1 `
        /app/.venv/bin/python $remoteScript `
        --project-id $ProjectId `
        --employee-id $employeeId `
        --employee-name "Public Relay Smoke" `
        --work-date $workDate `
        --endpoint $PublicOtlpUrl
    if ($LASTEXITCODE -ne 0) { throw "Public HTTPS OTLP sample was rejected." }

    $count = 0
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        $count = [int](docker exec agentops-clickhouse-1 clickhouse-client `
            --user default `
            --password $clickhousePassword `
            --query "SELECT count() FROM otel_2.otel_traces WHERE SpanAttributes['agentops.employee.id'] = '$employeeId'")
        if ($count -gt 0) { break }
        Start-Sleep -Seconds 1
    }
    if ($count -lt 1) { throw "OTLP request was accepted but no spans reached ClickHouse." }

    [pscustomobject]@{
        accepted = $sampleOutput -like "OTLP sample accepted:*"
        public_otlp_url = $PublicOtlpUrl
        clickhouse_span_count = $count
    }
} finally {
    if ($employeeId -match "^public-relay-smoke-[0-9a-f]{12}$") {
        docker exec agentops-clickhouse-1 clickhouse-client `
            --user default `
            --password $clickhousePassword `
            --query "ALTER TABLE otel_2.otel_traces DELETE WHERE SpanAttributes['agentops.employee.id'] = '$employeeId' SETTINGS mutations_sync = 2" 2>$null | Out-Null
    }
    if ($remoteRoot -match "^/tmp/smartbrain-public-otlp-[0-9a-f]{32}$") {
        docker exec agentops-api-1 rm -rf $remoteRoot 2>$null | Out-Null
    }
    $token = $null
}
