from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class CCSwitchUsageRow:
    usage_date: date
    app_type: str
    provider_id: str
    model: str
    request_model: str
    pricing_model: str
    request_count: int
    success_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    total_cost_usd: float
    input_token_semantics: int

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
        )


@dataclass(frozen=True)
class CCSwitchUsageCollection:
    rows: tuple[CCSwitchUsageRow, ...]
    source_table: str

    @property
    def total_tokens(self) -> int:
        return sum(row.total_tokens for row in self.rows)

    @property
    def request_count(self) -> int:
        return sum(row.request_count for row in self.rows)

    @property
    def success_count(self) -> int:
        return sum(row.success_count for row in self.rows)


def _nonnegative(value: object) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def collect_cc_switch_usage(
    database: Path,
    *,
    start_date: date,
    end_date: date,
) -> CCSwitchUsageCollection:
    if end_date < start_date:
        raise ValueError("end_date must not be earlier than start_date")
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
            "WHERE type = 'table' AND name = 'usage_daily_rollups'"
        ).fetchone()
        if table is not None:
            records = connection.execute(
                """
                SELECT
                    date, app_type, provider_id, model,
                    request_model, pricing_model,
                    request_count, success_count,
                    input_tokens, output_tokens,
                    cache_read_tokens, cache_creation_tokens,
                    total_cost_usd, input_token_semantics
                FROM usage_daily_rollups
                WHERE date >= ? AND date <= ?
                ORDER BY date, app_type, provider_id, model,
                         request_model, pricing_model
                """,
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        else:
            records = []
        source_table = "usage_daily_rollups"
        if not records:
            log_table = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'proxy_request_logs'"
            ).fetchone()
            if log_table is None:
                raise RuntimeError(
                    "CC Switch usage tables are unavailable"
                )
            records = connection.execute(
                """
                SELECT
                    date(created_at / 1000, 'unixepoch', '+8 hours') AS date,
                    app_type,
                    provider_id,
                    model,
                    COALESCE(request_model, '') AS request_model,
                    COALESCE(pricing_model, '') AS pricing_model,
                    count(*) AS request_count,
                    count(CASE WHEN status_code >= 200 AND status_code < 400
                               THEN 1 END) AS success_count,
                    sum(input_tokens) AS input_tokens,
                    sum(output_tokens) AS output_tokens,
                    sum(cache_read_tokens) AS cache_read_tokens,
                    sum(cache_creation_tokens) AS cache_creation_tokens,
                    sum(CAST(total_cost_usd AS REAL)) AS total_cost_usd,
                    max(input_token_semantics) AS input_token_semantics
                FROM proxy_request_logs
                WHERE date(created_at / 1000, 'unixepoch', '+8 hours') >= ?
                  AND date(created_at / 1000, 'unixepoch', '+8 hours') <= ?
                GROUP BY
                    date, app_type, provider_id, model,
                    request_model, pricing_model
                ORDER BY
                    date, app_type, provider_id, model,
                    request_model, pricing_model
                """,
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
            source_table = "proxy_request_logs"
    finally:
        connection.close()

    rows = tuple(
        CCSwitchUsageRow(
            usage_date=date.fromisoformat(str(record["date"])),
            app_type=str(record["app_type"] or "unknown"),
            provider_id=str(record["provider_id"] or "unknown"),
            model=str(record["model"] or "unknown"),
            request_model=str(record["request_model"] or ""),
            pricing_model=str(record["pricing_model"] or ""),
            request_count=_nonnegative(record["request_count"]),
            success_count=_nonnegative(record["success_count"]),
            input_tokens=_nonnegative(record["input_tokens"]),
            output_tokens=_nonnegative(record["output_tokens"]),
            cache_read_tokens=_nonnegative(record["cache_read_tokens"]),
            cache_creation_tokens=_nonnegative(record["cache_creation_tokens"]),
            total_cost_usd=max(float(record["total_cost_usd"] or 0), 0.0),
            input_token_semantics=_nonnegative(record["input_token_semantics"]),
        )
        for record in records
    )
    return CCSwitchUsageCollection(rows=rows, source_table=source_table)


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
            "User-Agent": "SmartBrain-CCSwitch-Usage-Sync/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"CC Switch usage upload failed: HTTP {error.code} {detail}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"CC Switch usage upload failed: {error.reason}"
        ) from error
    if not raw:
        return {}
    value = json.loads(raw.decode("utf-8"))
    return value if isinstance(value, dict) else {}


def _cc_switch_running() -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cc-switch.exe", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "cc-switch.exe" in result.stdout.casefold()


def _row_payload(row: CCSwitchUsageRow) -> dict[str, Any]:
    return {
        "usage_date": row.usage_date.isoformat(),
        "app_type": row.app_type,
        "provider_id": row.provider_id,
        "model": row.model,
        "request_model": row.request_model,
        "pricing_model": row.pricing_model,
        "request_count": row.request_count,
        "success_count": row.success_count,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cache_read_tokens": row.cache_read_tokens,
        "cache_creation_tokens": row.cache_creation_tokens,
        "total_tokens": row.total_tokens,
        "total_cost_usd": row.total_cost_usd,
        "input_token_semantics": row.input_token_semantics,
    }


def sync_once(
    *,
    runtime_dir: Path,
    home_dir: Path | None = None,
    lookback_days: int = 90,
    now: datetime | None = None,
    trigger: str = "automatic",
    request_id: str | None = None,
) -> dict[str, Any]:
    if trigger not in {"automatic", "manual"}:
        raise ValueError("trigger must be automatic or manual")
    if not 1 <= lookback_days <= 3650:
        raise ValueError("lookback_days must be between 1 and 3650")

    credentials = _load_json(runtime_dir / "device-credentials.json")
    manifest = _load_json(runtime_dir / "manifest.json")
    api_endpoint = str(credentials.get("api_endpoint") or "").rstrip("/")
    project_id = str(credentials.get("project_id") or "")
    token = str(credentials.get("token") or "")
    device_id = str(
        credentials.get("device_id") or manifest.get("device_id") or ""
    )
    if not api_endpoint or not project_id or not token or not device_id:
        raise RuntimeError("device usage sync credentials are incomplete")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_today = current.astimezone(SHANGHAI_TIMEZONE).date()
    start_date = local_today - timedelta(days=lookback_days - 1)
    attempted_at = current.astimezone(timezone.utc).isoformat()
    endpoint = f"{api_endpoint}/v4/ai-usage/cc-switch-sync/device-ingest"
    home = home_dir or Path.home()
    database = home / ".cc-switch" / "cc-switch.db"

    running = _cc_switch_running()
    base_payload: dict[str, Any] = {
        "project_id": project_id,
        "device_id": device_id,
        "trigger": trigger,
        "request_id": request_id,
        "range_start": start_date.isoformat(),
        "range_end": local_today.isoformat(),
        "attempted_at": attempted_at,
        "cc_switch_running": running,
    }
    if not running:
        payload = {
            **base_payload,
            "status": "not_running",
            "source_table": None,
            "rows": [],
            "request_count": 0,
            "success_count": 0,
            "total_tokens": 0,
            "error_message": "CC Switch is not running",
        }
    else:
        try:
            collection = collect_cc_switch_usage(
                database,
                start_date=start_date,
                end_date=local_today,
            )
        except Exception as error:
            payload = {
                **base_payload,
                "status": "error",
                "source_table": None,
                "rows": [],
                "request_count": 0,
                "success_count": 0,
                "total_tokens": 0,
                "error_message": str(error)[:1000],
            }
        else:
            payload = {
                **base_payload,
                "status": "ok",
                "source_table": collection.source_table,
                "rows": [_row_payload(row) for row in collection.rows],
                "request_count": collection.request_count,
                "success_count": collection.success_count,
                "total_tokens": collection.total_tokens,
                "error_message": None,
            }

    response = _post_json(endpoint, token, payload)
    status = {
        "status": str(response.get("status") or payload["status"]),
        "trigger": trigger,
        "request_id": request_id,
        "cc_switch_running": running,
        "range_start": start_date.isoformat(),
        "range_end": local_today.isoformat(),
        "row_count": len(payload["rows"]),
        "request_count": int(response.get("request_count") or payload["request_count"]),
        "total_tokens": int(response.get("total_tokens") or payload["total_tokens"]),
        "attempted_at": attempted_at,
        "synced_at": response.get("synced_at"),
        "error_message": response.get("error_message") or payload["error_message"],
    }
    _atomic_json(runtime_dir / "cc-switch-usage-sync-status.json", status)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync CC Switch token usage")
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path.home()
        / "AppData"
        / "Local"
        / "AIWorkdayTelemetry"
        / "current",
    )
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument(
        "--trigger",
        choices=("automatic", "manual"),
        default="automatic",
    )
    parser.add_argument("--request-id")
    args = parser.parse_args(argv)
    try:
        status = sync_once(
            runtime_dir=args.runtime_dir,
            lookback_days=args.lookback_days,
            trigger=args.trigger,
            request_id=args.request_id,
        )
    except Exception as error:
        print(f"CC Switch usage sync failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
