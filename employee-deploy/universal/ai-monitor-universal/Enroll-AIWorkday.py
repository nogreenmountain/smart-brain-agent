from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import platform
import socket
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


USER_AGENT = "AI-Workday-Installer/1.0"


def normalize_login_name(username: str, default_email_domain: str) -> str:
    value = username.strip().lower()
    if not value or any(ord(character) < 33 for character in value):
        raise ValueError("用户名不能为空或包含空白字符")
    if "@" not in value:
        value = f"{value}@{default_email_domain}"
    local, separator, domain = value.partition("@")
    if not separator or not local or not domain or "@" in domain:
        raise ValueError("用户名格式不正确")
    return value


def _normalize_base_url(value: str, field_name: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field_name} 必须是 HTTP(S) 地址")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} 不能包含查询参数或片段")
    path = parsed.path.rstrip("/")
    if path:
        raise ValueError(f"{field_name} 不能包含额外路径")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _post_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            body = json.loads(raw.decode("utf-8"))
            detail = body.get("detail") or body.get("message")
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = None
        if error.code in {400, 401, 403}:
            raise RuntimeError("账号、密码或项目权限验证失败") from error
        raise RuntimeError(
            f"服务器返回错误 HTTP {error.code}"
            + (f": {detail}" if detail else "")
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法连接智慧大脑服务器: {error.reason}") from error
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def get_or_create_device_id(runtime_dir: Path) -> str:
    path = runtime_dir / "device-id.txt"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if 3 <= len(value) <= 200:
            return value
    value = f"win-{uuid.uuid4()}"
    _atomic_write(path, value + "\n")
    return value


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _validate_enrollment(
    payload: dict[str, Any],
    *,
    project_id: str,
    collector_endpoint: str,
) -> None:
    if str(payload.get("project_id")) != project_id:
        raise RuntimeError("服务器返回了错误的项目身份")
    if (
        _normalize_base_url(
            str(payload.get("collector_endpoint") or ""),
            "collector_endpoint",
        )
        != collector_endpoint
    ):
        raise RuntimeError("服务器返回了未授权的采集地址")
    if not str(payload.get("employee_id") or ""):
        raise RuntimeError("服务器未返回员工身份")
    claude = payload.get("claude_common_config")
    codex = payload.get("codex_common_config")
    if not isinstance(claude, dict) or not isinstance(claude.get("env"), dict):
        raise RuntimeError("Claude 遥测配置格式不正确")
    if not isinstance(codex, str) or "[otel]" not in codex:
        raise RuntimeError("Codex 遥测配置格式不正确")
    headers = str(
        claude["env"].get("OTEL_EXPORTER_OTLP_HEADERS") or ""
    )
    if not headers.startswith("Authorization=Bearer "):
        raise RuntimeError("服务器未返回有效的遥测凭据")


def write_runtime_enrollment(
    payload: dict[str, Any],
    *,
    runtime_dir: Path,
    bundle_manifest: dict[str, Any],
    device_id: str,
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        runtime_dir / "Claude-Common-Config.json",
        json.dumps(
            payload["claude_common_config"],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    _atomic_write(
        runtime_dir / "Codex-Common-Config.toml",
        str(payload["codex_common_config"]),
    )
    runtime_manifest = {
        "project_id": payload["project_id"],
        "employee_id": payload["employee_id"],
        "employee_name": payload["employee_name"],
        "device_id": device_id,
        "package_version": str(bundle_manifest.get("package_version") or ""),
        "api_endpoint": str(bundle_manifest.get("api_endpoint") or ""),
        "collector_endpoint": payload["collector_endpoint"],
        "expires_at": payload["expires_at"],
    }
    _atomic_write(
        runtime_dir / "manifest.json",
        json.dumps(runtime_manifest, ensure_ascii=False, indent=2) + "\n",
    )


def register_device(
    opener: urllib.request.OpenerDirector,
    *,
    api_endpoint: str,
    project_id: str,
    device_id: str,
    package_version: str,
) -> None:
    hostname = socket.gethostname() or "Windows PC"
    _post_json(
        opener,
        f"{api_endpoint}/v4/ai-monitor/devices/register",
        {
            "project_id": project_id,
            "device_id": device_id,
            "device_name": hostname,
            "installer_version": package_version or None,
            "os": platform.platform(),
            "components": [
                {
                    "name": "cc_switch",
                    "status": "installed",
                    "version": package_version or None,
                    "details": {"source": "installer_enrollment"},
                },
                {
                    "name": "chatgpt_desktop",
                    "status": "unsupported",
                    "version": None,
                    "details": {
                        "reason": "personal_desktop_account_not_locally_captured"
                    },
                },
            ],
        },
    )


def enroll(
    *,
    bundle_dir: Path,
    runtime_dir: Path,
    username: str,
    password: str,
) -> dict[str, Any]:
    manifest = json.loads(
        (bundle_dir / "manifest.json").read_text(encoding="utf-8-sig")
    )
    project_id = str(uuid.UUID(str(manifest["project_id"])))
    api_endpoint = _normalize_base_url(
        str(manifest["api_endpoint"]),
        "api_endpoint",
    )
    collector_endpoint = _normalize_base_url(
        str(manifest["collector_endpoint"]),
        "collector_endpoint",
    )
    email = normalize_login_name(
        username,
        str(manifest["default_email_domain"]),
    )
    if not password:
        raise ValueError("密码不能为空")

    device_id = get_or_create_device_id(runtime_dir)
    package_version = str(manifest.get("package_version") or "")
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    _post_json(
        opener,
        f"{api_endpoint}/auth/login",
        {"email": email, "password": password},
    )
    password = ""
    try:
        payload = _post_json(
            opener,
            f"{api_endpoint}/v4/workday/enroll",
            {"project_id": project_id},
        )
        _validate_enrollment(
            payload,
            project_id=project_id,
            collector_endpoint=collector_endpoint,
        )
        write_runtime_enrollment(
            payload,
            runtime_dir=runtime_dir,
            bundle_manifest=manifest,
            device_id=device_id,
        )
        register_device(
            opener,
            api_endpoint=api_endpoint,
            project_id=project_id,
            device_id=device_id,
            package_version=package_version,
        )
        return payload
    finally:
        try:
            _post_json(opener, f"{api_endpoint}/auth/logout", {})
        except RuntimeError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Log in once and enroll this PC for AI Workday telemetry"
    )
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--username")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    try:
        username = args.username or input("智慧大脑用户名: ")
        password = (
            sys.stdin.readline().rstrip("\r\n")
            if args.password_stdin
            else getpass.getpass("智慧大脑密码: ")
        )
        payload = enroll(
            bundle_dir=args.bundle_dir,
            runtime_dir=args.runtime_dir,
            username=username,
            password=password,
        )
        print(
            "登录和身份绑定成功: "
            f"{payload['employee_id']}，凭据到期时间 {payload['expires_at']}"
        )
        return 0
    except Exception as error:
        print(f"AI Workday enrollment failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
