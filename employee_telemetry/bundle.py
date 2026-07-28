from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from .client_config import (
    MANAGED_CODEX_END,
    MANAGED_CODEX_START,
    merge_claude_common_config,
    merge_codex_common_config,
    remove_managed_codex_block,
)


EMPLOYEE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class BundleRequest:
    project_id: str
    employee_id: str
    employee_name: str
    collector_endpoint: str
    expires_in_days: int = 30

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.project_id)
        except ValueError as error:
            raise ValueError("project_id must be a UUID") from error
        if not EMPLOYEE_ID_PATTERN.fullmatch(self.employee_id):
            raise ValueError(
                "employee_id must use 1-64 letters, numbers, dots, "
                "underscores, or hyphens"
            )
        if not self.employee_name or len(self.employee_name) > 80:
            raise ValueError("employee_name must use 1-80 characters")
        if any(ord(character) < 32 for character in self.employee_name):
            raise ValueError("employee_name cannot contain control characters")
        normalize_collector_endpoint(self.collector_endpoint)
        if not 1 <= self.expires_in_days <= 90:
            raise ValueError("expires_in_days must be between 1 and 90")


@dataclass(frozen=True)
class UniversalBundleRequest:
    project_id: str
    api_endpoint: str
    collector_endpoint: str
    default_email_domain: str = "local.dev"

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.project_id)
        except ValueError as error:
            raise ValueError("project_id must be a UUID") from error
        normalize_service_endpoint(self.api_endpoint, "api_endpoint")
        normalize_collector_endpoint(self.collector_endpoint)
        domain = self.default_email_domain.strip().lower()
        if (
            not domain
            or len(domain) > 253
            or "@" in domain
            or any(character.isspace() for character in domain)
        ):
            raise ValueError("default_email_domain is invalid")


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _json_segment(value: dict[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _base64url(raw)


def mint_telemetry_token(
    *,
    secret: str,
    project_id: str,
    employee_id: str,
    employee_name: str,
    expires_in_days: int,
    subject_user_id: str | None = None,
    issued_at: datetime | None = None,
) -> str:
    if len(secret) < 32:
        raise ValueError("JWT secret must contain at least 32 characters")
    now = issued_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("issued_at must be timezone-aware")
    now = now.astimezone(timezone.utc)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "aud": "authenticated",
        "project_id": project_id,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "ingest_kind": "workday_cli",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=expires_in_days)).timestamp()),
    }
    if subject_user_id:
        payload["sub"] = subject_user_id
    signing_input = f"{_json_segment(header)}.{_json_segment(payload)}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_base64url(signature)}"


def decode_unverified_token(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    header_segment, payload_segment, _ = token.split(".")

    def decode(segment: str) -> dict[str, Any]:
        padded = segment + "=" * (-len(segment) % 4)
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))

    return decode(header_segment), decode(payload_segment)


def normalize_collector_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("collector_endpoint must be an HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("collector_endpoint cannot contain query or fragment")
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/traces"):
        path = path[: -len("/v1/traces")]
    if path:
        raise ValueError("collector_endpoint must not contain an extra path")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def normalize_service_endpoint(endpoint: str, field_name: str) -> str:
    parsed = urlsplit(endpoint.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field_name} must be an HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} cannot contain query or fragment")
    if parsed.path.rstrip("/"):
        raise ValueError(f"{field_name} must not contain an extra path")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _resource_value(value: str) -> str:
    return quote(value, safe="-._~")


def build_claude_common_config(
    *,
    employee_id: str,
    employee_name: str,
    collector_endpoint: str,
    token: str,
) -> dict[str, dict[str, str]]:
    base = normalize_collector_endpoint(collector_endpoint)
    attributes = ",".join(
        (
            f"agentops.employee.id={_resource_value(employee_id)}",
            f"agentops.employee.name={_resource_value(employee_name)}",
            "source.application=claude_code",
        )
    )
    return {
        "env": {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
            "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_LOGS_EXPORTER": "none",
            "OTEL_METRICS_EXPORTER": "none",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"{base}/v1/traces",
            "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization=Bearer {token}",
            "OTEL_RESOURCE_ATTRIBUTES": attributes,
            "OTEL_SERVICE_NAME": "claude-code-workday",
            "OTEL_LOG_USER_PROMPTS": "0",
            "OTEL_LOG_ASSISTANT_RESPONSES": "0",
            "OTEL_LOG_TOOL_DETAILS": "0",
            "OTEL_LOG_TOOL_CONTENT": "0",
            "OTEL_LOG_RAW_API_BODIES": "0",
        }
    }


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_codex_common_config(
    *,
    employee_id: str,
    employee_name: str,
    collector_endpoint: str,
    token: str,
) -> str:
    endpoint = f"{normalize_collector_endpoint(collector_endpoint)}/v1/traces"
    return "\n".join(
        (
            MANAGED_CODEX_START,
            "[otel]",
            'environment = "workday"',
            "log_user_prompt = false",
            'exporter = "none"',
            'metrics_exporter = "none"',
            (
                "trace_exporter = { otlp-http = { endpoint = "
                f"{_toml_string(endpoint)}, protocol = \"binary\", "
                "headers = { Authorization = "
                f"{_toml_string(f'Bearer {token}')} "
                "} } }"
            ),
            "",
            "[otel.span_attributes]",
            (
                '"agentops.employee.id" = '
                f"{_toml_string(employee_id)}"
            ),
            (
                '"agentops.employee.name" = '
                f"{_toml_string(employee_name)}"
            ),
            '"source.application" = "codex"',
            MANAGED_CODEX_END,
            "",
        )
    )


def _powershell_install_script() -> str:
    return r"""#Requires -Version 5.1
$ErrorActionPreference = "Stop"

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @($py.Source, "-3") }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @($python.Source) }
    throw "未找到 Python 3。请先安装 Python 3，再重新运行本安装器。"
}

if (Get-Process -Name "cc-switch" -ErrorAction SilentlyContinue) {
    throw "请先从系统托盘彻底退出 CC Switch，再重新运行安装器。"
}

$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "manifest.json") -Raw |
    ConvertFrom-Json
$uri = [Uri]$manifest.collector_endpoint
$port = if ($uri.Port -gt 0) { $uri.Port } elseif ($uri.Scheme -eq "https") { 443 } else { 80 }
$probe = Test-NetConnection -ComputerName $uri.Host -Port $port -WarningAction SilentlyContinue
if (-not $probe.TcpTestSucceeded) {
    throw "无法连接遥测服务器 $($uri.Host):$port，请检查局域网、防火墙或 VPN。"
}

$pythonCommand = @(Find-Python)
$helper = Join-Path $PSScriptRoot "Update-CCSwitchCommonConfig.py"
$arguments = @()
if ($pythonCommand.Count -gt 1) { $arguments += $pythonCommand[1] }
$arguments += @(
    $helper,
    "install",
    "--bundle-dir", $PSScriptRoot,
    "--backup-root", (Join-Path $PSScriptRoot "backups")
)
& $pythonCommand[0] @arguments
if ($LASTEXITCODE -ne 0) {
    throw "配置写入失败，原文件备份保留在本部署包的 backups 目录。"
}

Write-Host ""
Write-Host "AI 工作日监控已安装。" -ForegroundColor Green
Write-Host "请重新打开 CC Switch，切换一次 Claude 和 Codex 当前供应商，然后重启 Claude Code/Codex。"
Write-Host "之后正常使用即可，不需要先登录智慧大脑网页。"
"""


def _powershell_uninstall_script() -> str:
    return r"""#Requires -Version 5.1
$ErrorActionPreference = "Stop"

if (Get-Process -Name "cc-switch" -ErrorAction SilentlyContinue) {
    throw "请先从系统托盘彻底退出 CC Switch，再重新运行卸载器。"
}

$py = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    & $py.Source -3 (Join-Path $PSScriptRoot "Update-CCSwitchCommonConfig.py") uninstall `
        --bundle-dir $PSScriptRoot `
        --backup-root (Join-Path $PSScriptRoot "backups")
} elseif ($python) {
    & $python.Source (Join-Path $PSScriptRoot "Update-CCSwitchCommonConfig.py") uninstall `
        --bundle-dir $PSScriptRoot `
        --backup-root (Join-Path $PSScriptRoot "backups")
} else {
    throw "未找到 Python 3，无法自动卸载。"
}
if ($LASTEXITCODE -ne 0) { throw "自动卸载失败。" }

Write-Host "AI 工作日监控配置已移除。请重新打开 CC Switch。" -ForegroundColor Green
"""


def _powershell_universal_install_script() -> str:
    return r"""#Requires -Version 5.1
$ErrorActionPreference = "Stop"

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @($py.Source, "-3") }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @($python.Source) }
    throw "未找到 Python 3。请先安装 Python 3，再重新运行本安装器。"
}

if (Get-Process -Name "cc-switch" -ErrorAction SilentlyContinue) {
    throw "请先从系统托盘彻底退出 CC Switch，再重新运行安装器。"
}

$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "manifest.json") -Raw |
    ConvertFrom-Json
$uri = [Uri]$manifest.collector_endpoint
$port = if ($uri.Port -gt 0) { $uri.Port } elseif ($uri.Scheme -eq "https") { 443 } else { 80 }
$probe = Test-NetConnection -ComputerName $uri.Host -Port $port -WarningAction SilentlyContinue
if (-not $probe.TcpTestSucceeded) {
    throw "无法连接遥测服务器 $($uri.Host):$port，请检查局域网、防火墙或 VPN。"
}

$pythonCommand = @(Find-Python)
$runtimeRoot = Join-Path $env:LOCALAPPDATA "AIWorkdayTelemetry"
$runtimeDir = Join-Path $runtimeRoot "current"
$backupRoot = Join-Path $runtimeRoot "backups"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

function Invoke-PythonHelper {
    param([string]$Script, [string[]]$Arguments)
    $allArguments = @()
    if ($pythonCommand.Count -gt 1) { $allArguments += $pythonCommand[1] }
    $allArguments += $Script
    $allArguments += $Arguments
    & $pythonCommand[0] @allArguments
    if ($LASTEXITCODE -ne 0) {
        throw "员工身份验证或配置写入失败。"
    }
}

$sensitiveFiles = @(
    (Join-Path $runtimeDir "Claude-Common-Config.json"),
    (Join-Path $runtimeDir "Codex-Common-Config.toml")
)
try {
    Invoke-PythonHelper `
        -Script (Join-Path $PSScriptRoot "Enroll-AIWorkday.py") `
        -Arguments @(
            "--bundle-dir", $PSScriptRoot,
            "--runtime-dir", $runtimeDir
        )
    Invoke-PythonHelper `
        -Script (Join-Path $PSScriptRoot "Update-CCSwitchCommonConfig.py") `
        -Arguments @(
            "install",
            "--bundle-dir", $runtimeDir,
            "--backup-root", $backupRoot
        )
} finally {
    foreach ($sensitiveFile in $sensitiveFiles) {
        if (Test-Path -LiteralPath $sensitiveFile) {
            Remove-Item -LiteralPath $sensitiveFile -Force
        }
    }
}

Write-Host ""
Write-Host "AI 工作日监控已安装。" -ForegroundColor Green
Write-Host "请重新打开 CC Switch，分别切换一次 Claude 和 Codex 当前供应商，然后重启 Claude Code/Codex。"
"""


def _powershell_universal_uninstall_script() -> str:
    return r"""#Requires -Version 5.1
$ErrorActionPreference = "Stop"

if (Get-Process -Name "cc-switch" -ErrorAction SilentlyContinue) {
    throw "请先从系统托盘彻底退出 CC Switch，再重新运行卸载器。"
}

$py = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
$runtimeRoot = Join-Path $env:LOCALAPPDATA "AIWorkdayTelemetry"
$runtimeDir = Join-Path $runtimeRoot "current"
$backupRoot = Join-Path $runtimeRoot "backups"
if (-not (Test-Path -LiteralPath (Join-Path $runtimeDir "manifest.json"))) {
    throw "未找到本机 AI Workday 安装记录。"
}

$helper = Join-Path $PSScriptRoot "Update-CCSwitchCommonConfig.py"
if ($py) {
    & $py.Source -3 $helper uninstall `
        --bundle-dir $runtimeDir `
        --backup-root $backupRoot
} elseif ($python) {
    & $python.Source $helper uninstall `
        --bundle-dir $runtimeDir `
        --backup-root $backupRoot
} else {
    throw "未找到 Python 3，无法自动卸载。"
}
if ($LASTEXITCODE -ne 0) { throw "自动卸载失败。" }

Remove-Item -LiteralPath (Join-Path $runtimeDir "manifest.json") -Force
Write-Host "AI 工作日监控配置已移除。请重新打开 CC Switch。" -ForegroundColor Green
"""


def _universal_readme(request: UniversalBundleRequest) -> str:
    api_endpoint = normalize_service_endpoint(
        request.api_endpoint,
        "api_endpoint",
    )
    collector_endpoint = normalize_collector_endpoint(
        request.collector_endpoint
    )
    return rf"""AI 工作日监控通用安装包

本安装包适用于同一项目的所有员工，不区分 test1、test2 或其他账号。
项目编号：{request.project_id}
登录服务：{api_endpoint}
采集服务：{collector_endpoint}

安装步骤

1. 把整个 ai-workday-universal 文件夹复制到员工电脑本地。
2. 从系统托盘彻底退出 CC Switch。
3. 在本目录运行：
   powershell -ExecutionPolicy Bypass -File .\Install-AIWorkdayTelemetry.ps1
4. 按提示输入智慧大脑用户名和密码。短用户名会自动补全
   @{request.default_email_domain}。
5. 安装成功后重新打开 CC Switch，分别切换一次 Claude 和 Codex
   当前供应商，然后重启 Claude Code/Codex。

安全说明

- 密码只用于一次登录，不写入文件、CC Switch 或遥测配置。
- 员工身份由登录账号和项目成员关系决定，不能在安装器中自行指定。
- 通用安装包本身不含员工身份或遥测令牌，可以统一分发。
- 本机遥测令牌会写入 Claude/Codex 配置供原生 OTLP 上报使用。
- 中间配置文件在安装结束后立即删除。
- 默认不采集 Prompt、AI 回答、工具参数、命令内容或文件内容。

卸载

先退出 CC Switch，再运行：
   powershell -ExecutionPolicy Bypass -File .\Uninstall-AIWorkdayTelemetry.ps1

当前使用局域网 HTTP，仅适合受控内网试运行。正式推广前应启用 HTTPS。
"""


def create_universal_bundle(
    *,
    request: UniversalBundleRequest,
    output_root: Path,
) -> Path:
    output = output_root / "ai-workday-universal"
    output.mkdir(parents=True, exist_ok=True)
    (output / "Install-AIWorkdayTelemetry.ps1").write_text(
        _powershell_universal_install_script(),
        encoding="utf-8-sig",
    )
    (output / "Uninstall-AIWorkdayTelemetry.ps1").write_text(
        _powershell_universal_uninstall_script(),
        encoding="utf-8-sig",
    )
    (output / "README.txt").write_text(
        _universal_readme(request),
        encoding="utf-8-sig",
    )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "project_id": request.project_id,
                "api_endpoint": normalize_service_endpoint(
                    request.api_endpoint,
                    "api_endpoint",
                ),
                "collector_endpoint": normalize_collector_endpoint(
                    request.collector_endpoint
                ),
                "default_email_domain": (
                    request.default_email_domain.strip().lower()
                ),
                "minimum_cc_switch_version": "3.12.2",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    package_dir = Path(__file__).resolve().parent
    shutil.copyfile(
        package_dir / "enroll_client.py",
        output / "Enroll-AIWorkday.py",
    )
    shutil.copyfile(
        package_dir / "update_ccswitch_common_config.py",
        output / "Update-CCSwitchCommonConfig.py",
    )
    shutil.copyfile(
        package_dir / "client_config.py",
        output / "AIWorkdayConfig.py",
    )
    return output


def _readme(request: BundleRequest, expires_at: datetime) -> str:
    return f"""AI 工作日监控员工端部署包

员工编号：{request.employee_id}
员工姓名：{request.employee_name}
项目编号：{request.project_id}
采集地址：{normalize_collector_endpoint(request.collector_endpoint)}
令牌到期：{expires_at.astimezone(timezone.utc).isoformat()}

一、安装前

1. 确认电脑已安装 CC Switch 3.12.2 或更高版本、Claude Code 或 Codex、Python 3。
2. 从系统托盘彻底退出 CC Switch。
3. 本部署包只属于 {request.employee_id}，不要发给其他员工。

二、安装

在本目录空白处按住 Shift 点击鼠标右键，打开 PowerShell，然后运行：

powershell -ExecutionPolicy Bypass -File .\\Install-AIWorkdayTelemetry.ps1

安装器会备份 CC Switch 数据库、Claude settings.json 和 Codex config.toml，
把遥测配置写入 CC Switch Common Config，同步写入当前配置文件，并把采集服务器
加入用户级 NO_PROXY，避免系统代理拦截局域网 Trace。

安装完成后：

1. 重新打开 CC Switch。
2. 在 Claude 和 Codex 各切换一次当前供应商，让 Common Config 重新覆盖生效。
3. 关闭所有已运行的 Claude Code/Codex 窗口，然后重新打开。
4. 正常使用 Claude Code 或 Codex。无需先打开智慧大脑网页。

三、能监控什么

只采集结构化 Trace：使用时间、会话/调用数量、模型、Token、工具名称、成功/失败和延迟。
默认不采集 Prompt 原文、AI 回复原文、工具参数、命令内容、文件内容和完整文件路径。
目前没有动态任务标签时，智慧大脑中的任务会显示为“未标记任务”。

四、查看

管理员或项目成员打开：

http://192.168.1.40:3002/workday

员工编号填写：{request.employee_id}

五、卸载

先退出 CC Switch，再运行：

powershell -ExecutionPolicy Bypass -File .\\Uninstall-AIWorkdayTelemetry.ps1

六、注意

本令牌过期后需要管理员重新生成部署包。
卸载器会移除安装器追加的 NO_PROXY 条目，同时保留安装前已有的代理绕过项。
当前采集地址使用局域网 HTTP，仅适合受控内网试运行；正式跨网部署前应启用 HTTPS。
"""


def create_bundle(
    *,
    request: BundleRequest,
    secret: str,
    output_root: Path,
    issued_at: datetime | None = None,
) -> Path:
    now = (issued_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    token = mint_telemetry_token(
        secret=secret,
        project_id=request.project_id,
        employee_id=request.employee_id,
        employee_name=request.employee_name,
        expires_in_days=request.expires_in_days,
        issued_at=now,
    )
    expires_at = now + timedelta(days=request.expires_in_days)
    claude_config = build_claude_common_config(
        employee_id=request.employee_id,
        employee_name=request.employee_name,
        collector_endpoint=request.collector_endpoint,
        token=token,
    )
    codex_config = build_codex_common_config(
        employee_id=request.employee_id,
        employee_name=request.employee_name,
        collector_endpoint=request.collector_endpoint,
        token=token,
    )

    output = output_root / f"ai-workday-{request.employee_id}"
    output.mkdir(parents=True, exist_ok=True)
    (output / "Claude-Common-Config.json").write_text(
        json.dumps(claude_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "Codex-Common-Config.toml").write_text(
        codex_config,
        encoding="utf-8",
    )
    (output / "Install-AIWorkdayTelemetry.ps1").write_text(
        _powershell_install_script(),
        encoding="utf-8-sig",
    )
    (output / "Uninstall-AIWorkdayTelemetry.ps1").write_text(
        _powershell_uninstall_script(),
        encoding="utf-8-sig",
    )
    (output / "README.txt").write_text(
        _readme(request, expires_at),
        encoding="utf-8-sig",
    )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "employee_id": request.employee_id,
                "employee_name": request.employee_name,
                "project_id": request.project_id,
                "collector_endpoint": normalize_collector_endpoint(
                    request.collector_endpoint
                ),
                "issued_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "minimum_cc_switch_version": "3.12.2",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    package_dir = Path(__file__).resolve().parent
    shutil.copyfile(
        package_dir / "update_ccswitch_common_config.py",
        output / "Update-CCSwitchCommonConfig.py",
    )
    shutil.copyfile(
        package_dir / "client_config.py",
        output / "AIWorkdayConfig.py",
    )
    return output


def secret_from_environment() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        raise ValueError("JWT_SECRET_KEY is not set")
    return secret
