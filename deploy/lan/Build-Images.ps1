#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipAgentOpsDashboard,
    [switch]$SkipRagServices
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

function Invoke-Step([string]$Name, [scriptblock]$Block) {
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Block
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name"
    }
}

Invoke-Step "Build AgentOps API base image" {
    docker build -f api/Dockerfile -t agentops-api-local:patched-2026-07-17-dashboard .
}

Invoke-Step "Build SmartBrain patched API image" {
    docker build -f Dockerfile.api-workday -t agentops-api-local:patched-2026-08-06-global-read .
}

Invoke-Step "Build SmartBrain Wiki MCP image" {
    docker build -f Dockerfile.wiki-mcp -t smartbrain-wiki-mcp-local:latest .
}

if (-not $SkipAgentOpsDashboard) {
    Invoke-Step "Build AgentOps Trace Dashboard image" {
        docker build -t agentops-dashboard-local:latest dashboard
    }
}

Invoke-Step "Build SmartBrain Dashboard image" {
    docker build -t smartbrain-dashboard-local:latest smartbrain-dashboard
}

Invoke-Step "Build OTLP Collector image" {
    docker build -t agentops-otel-local:workday-ccswitch-2026-07-20 opentelemetry-collector
}

if (-not $SkipRagServices) {
    Invoke-Step "Build RAG embedding service image" {
        docker build -f rag_services/embedding_service/Dockerfile -t rag-embedding-service-local:latest .
    }
    Invoke-Step "Build RAG reranker service image" {
        docker build -f rag_services/reranker_service/Dockerfile -t rag-reranker-service-local:latest .
    }
}

Write-Host ""
Write-Host "Images built successfully." -ForegroundColor Green
