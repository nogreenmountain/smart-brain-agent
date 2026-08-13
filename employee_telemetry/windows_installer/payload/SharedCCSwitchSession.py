from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))
CACHE_INCLUSIVE_APP_TYPES = frozenset({"codex", "gemini"})
STATE_FILE = "shared-cc-switch-session.json"
SHARED_DEVICE_FILE = "shared-device.json"


@dataclass(frozen=True)
class SharedCCSwitchRequest:
    request_id: str
    requested_at: datetime
    app_type: str
    provider_id: str
    model: str
    request_model: str
    pricing_model: str
    status_code: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    total_cost_usd: float
    input_token_semantics: int

    @property
    def fresh_input_tokens(self) -> int:
        if self.input_token_semantics == 2:
            return self.input_tokens
        if self.app_type not in CACHE_INCLUSIVE_APP_TYPES:
            return self.input_tokens
        cached = self.cache_read_tokens
        if self.input_token_semantics == 1:
            cached += self.cache_creation_tokens
        if self.input_tokens >= cached:
            return self.input_tokens - cached
        return self.input_tokens

    @property
    def total_tokens(self) -> int:
        return (
            self.fresh_input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
        )


def _timestamp_seconds(value: object) -> float:
    raw = float(value or 0)
    return raw / 1000 if raw >= 100_000_000_000 else raw


def collect_session_requests(
    database: Path,
    *,
    started_at: datetime,
    stopped_at: datetime,
) -> tuple[SharedCCSwitchRequest, ...]:
    if stopped_at <= started_at:
        raise ValueError("stopped_at must be later than started_at")
    resolved = database.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"CC Switch database was not found: {resolved}")
    connection = sqlite3.connect(
        f"file:{resolved.as_posix()}?mode=ro",
        uri=True,
        timeout=10,
    )
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'proxy_request_logs'"
        ).fetchone()
        if table is None:
            raise RuntimeError(
                "CC Switch proxy_request_logs is required for shared-device attribution"
            )
        rows = connection.execute(
            """
            SELECT request_id, provider_id, app_type, model,
                   COALESCE(request_model, '') AS request_model,
                   COALESCE(pricing_model, '') AS pricing_model,
                   input_tokens, output_tokens,
                   cache_read_tokens, cache_creation_tokens,
                   total_cost_usd, status_code, created_at,
                   input_token_semantics
            FROM proxy_request_logs
            WHERE (CASE WHEN created_at >= 100000000000
                        THEN created_at / 1000.0 ELSE created_at END) >= ?
              AND (CASE WHEN created_at >= 100000000000
                        THEN created_at / 1000.0 ELSE created_at END) <= ?
            ORDER BY created_at, request_id
            """,
            (started_at.timestamp(), stopped_at.timestamp()),
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        SharedCCSwitchRequest(
            request_id=str(row["request_id"]),
            requested_at=datetime.fromtimestamp(
                _timestamp_seconds(row["created_at"]), timezone.utc
            ),
            app_type=str(row["app_type"] or "unknown").lower(),
            provider_id=str(row["provider_id"] or "unknown"),
            model=str(row["model"] or "unknown"),
            request_model=str(row["request_model"] or ""),
            pricing_model=str(row["pricing_model"] or ""),
            status_code=max(int(row["status_code"] or 0), 0),
            input_tokens=max(int(row["input_tokens"] or 0), 0),
            output_tokens=max(int(row["output_tokens"] or 0), 0),
            cache_read_tokens=max(int(row["cache_read_tokens"] or 0), 0),
            cache_creation_tokens=max(int(row["cache_creation_tokens"] or 0), 0),
            total_cost_usd=max(float(row["total_cost_usd"] or 0), 0.0),
            input_token_semantics=max(int(row["input_token_semantics"] or 0), 0),
        )
        for row in rows
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _post_json(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "SmartBrain-Shared-CCSwitch/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"shared session upload failed: HTTP {error.code} {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"shared session upload failed: {error.reason}") from error
    if not raw:
        return {}
    value = json.loads(raw.decode("utf-8"))
    return value if isinstance(value, dict) else {}


def _request_payload(row: SharedCCSwitchRequest) -> dict[str, Any]:
    payload = asdict(row)
    payload["requested_at"] = row.requested_at.isoformat()
    payload["total_tokens"] = row.total_tokens
    return payload


def _credentials(runtime_dir: Path) -> tuple[str, str, str]:
    value = _load_json(runtime_dir / "device-credentials.json")
    manifest = _load_json(runtime_dir / "manifest.json")
    endpoint = str(value.get("api_endpoint") or "").rstrip("/")
    token = str(value.get("token") or "")
    device_id = str(value.get("device_id") or manifest.get("device_id") or "")
    if not endpoint or not token or not device_id:
        raise RuntimeError("shared-device credentials are incomplete")
    return endpoint, token, device_id


def start_session(
    *,
    runtime_dir: Path,
    session_id: str,
    activation_token: str,
    home_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    endpoint, device_token, device_id = _credentials(runtime_dir)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    home = home_dir or Path.home()
    database = home / ".cc-switch" / "cc-switch.db"
    if not database.is_file():
        raise FileNotFoundError(f"CC Switch database was not found: {database}")
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='proxy_request_logs'"
        ).fetchone()
        if table is None:
            raise RuntimeError("CC Switch proxy_request_logs is unavailable")
        watermark_row = connection.execute(
            "SELECT COALESCE(max(rowid), 0) FROM proxy_request_logs"
        ).fetchone()
    finally:
        connection.close()
    response = _post_json(
        f"{endpoint}/v4/ai-usage/shared-sessions/device-activate",
        device_token,
        {
            "session_id": session_id,
            "activation_token": activation_token,
            "device_id": device_id,
            "started_at": current.isoformat(),
            "start_watermark": str(int(watermark_row[0] or 0)),
        },
    )
    state = {
        "session_id": session_id,
        "activation_token": activation_token,
        "device_id": device_id,
        "started_at": response.get("started_at") or current.isoformat(),
        "scheduled_stop_at": response["scheduled_stop_at"],
        "status": response.get("status", "active"),
    }
    _atomic_json(runtime_dir / STATE_FILE, state)
    _atomic_json(
        runtime_dir / SHARED_DEVICE_FILE,
        {"device_id": device_id, "enabled_at": current.isoformat()},
    )
    return state


def poll_session(
    *,
    runtime_dir: Path,
    force_stop: bool = False,
    home_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    state_path = runtime_dir / STATE_FILE
    state = _load_json(state_path)
    if not state or state.get("status") == "finalized":
        return {"status": "idle"}
    endpoint, device_token, device_id = _credentials(runtime_dir)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if state.get("status") == "pending_sync":
        command = {
            "action": "stop",
            "scheduled_stop_at": state["scheduled_stop_at"],
            "stop_at": state["stopped_at"],
            "stop_reason": state.get("stop_reason") or "scheduled",
        }
    else:
        command = _post_json(
            f"{endpoint}/v4/ai-usage/shared-sessions/device-command",
            device_token,
            {
                "session_id": state["session_id"],
                "activation_token": state["activation_token"],
                "device_id": device_id,
                "checked_at": current.isoformat(),
            },
        )
        state["scheduled_stop_at"] = command["scheduled_stop_at"]
        should_stop = force_stop or command.get("action") == "stop"
        if force_stop and command.get("action") != "stop":
            raise RuntimeError("server has not accepted the shared session stop yet")
        if not should_stop:
            _atomic_json(state_path, state)
            return {"status": "active", "scheduled_stop_at": state["scheduled_stop_at"]}
    stopped_at = datetime.fromisoformat(str(command["stop_at"]).replace("Z", "+00:00"))
    started_at = datetime.fromisoformat(str(state["started_at"]).replace("Z", "+00:00"))
    database = (home_dir or Path.home()) / ".cc-switch" / "cc-switch.db"
    rows = collect_session_requests(
        database,
        started_at=started_at,
        stopped_at=stopped_at,
    )
    try:
        response = _post_json(
            f"{endpoint}/v4/ai-usage/shared-sessions/device-finalize",
            device_token,
            {
                "session_id": state["session_id"],
                "activation_token": state["activation_token"],
                "device_id": device_id,
                "stopped_at": stopped_at.isoformat(),
                "stop_reason": command.get("stop_reason") or "scheduled",
                "requests": [_request_payload(row) for row in rows],
            },
        )
    except RuntimeError as error:
        state["status"] = "pending_sync"
        state["stopped_at"] = stopped_at.isoformat()
        state["stop_reason"] = command.get("stop_reason") or "scheduled"
        state["error_message"] = str(error)
        _atomic_json(state_path, state)
        return state
    state.update(response)
    state.pop("activation_token", None)
    _atomic_json(state_path, state)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage a shared CC Switch attribution session")
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path.home() / "AppData" / "Local" / "AIWorkdayTelemetry" / "current",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--session-id", required=True)
    start.add_argument("--activation-token", required=True)
    subparsers.add_parser("poll")
    subparsers.add_parser("stop")
    args = parser.parse_args(argv)
    try:
        if args.action == "start":
            start_session(
                runtime_dir=args.runtime_dir,
                session_id=args.session_id,
                activation_token=args.activation_token,
            )
        else:
            poll_session(runtime_dir=args.runtime_dir, force_stop=args.action == "stop")
    except Exception as error:
        print(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
