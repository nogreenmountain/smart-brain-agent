from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return []
    return rows


def _content_text(content: Any, allowed_types: set[str]) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    pieces: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") not in allowed_types:
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            pieces.append(text.strip())
    return "\n".join(pieces)


def _duration_ms(started_at: str | None, ended_at: str | None) -> int | None:
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(int((end - start).total_seconds() * 1000), 0)


def _as_nonnegative_int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _message(
    *,
    role: str,
    content: str,
    message_id: str | None,
    created_at: str | None,
) -> dict[str, Any]:
    return {
        "role": role,
        "content": content,
        "message_id": message_id,
        "created_at": created_at,
        "token_count": None,
        "metadata": {},
    }


def _finalize_codex_turn(
    turn: dict[str, Any] | None,
    *,
    session_id: str,
) -> dict[str, Any] | None:
    if not turn or not turn["messages"]:
        return None
    messages = list(turn["messages"])
    user_messages = [item for item in messages if item["role"] == "user"]
    assistant_messages = [item for item in messages if item["role"] == "assistant"]
    if not user_messages:
        return None
    usage = turn.get("usage") or {}
    prompt_tokens = _as_nonnegative_int(usage.get("input_tokens"))
    completion_tokens = _as_nonnegative_int(usage.get("output_tokens"))
    total_tokens = _as_nonnegative_int(usage.get("total_tokens"))
    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens
    user_messages[-1]["token_count"] = prompt_tokens or None
    if assistant_messages:
        assistant_messages[-1]["token_count"] = completion_tokens or None
    turn_id = str(turn.get("turn_id") or "unknown")
    started_at = turn.get("started_at")
    ended_at = turn.get("ended_at") or turn.get("last_seen_at")
    title = user_messages[-1]["content"].replace("\n", " ")[:120]
    return {
        "source": "cc_switch",
        "conversation_id": f"codex:{session_id}:{turn_id}",
        "title": title or "Codex 对话",
        "task_id": None,
        "task_title": None,
        "model": turn.get("model"),
        "status": "ok" if assistant_messages and turn.get("completed") else "partial",
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": _duration_ms(started_at, ended_at),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost": 0,
        "error_count": 0,
        "trace_id": None,
        "messages": messages,
        "metadata": {"client": "codex", "turn_id": turn_id},
    }


def parse_codex_session(path: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    session_id = path.stem
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        row_type = row.get("type")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        timestamp = row.get("timestamp")
        if row_type == "session_meta":
            session_id = str(payload.get("id") or payload.get("session_id") or session_id)
            continue
        if row_type == "event_msg" and payload.get("type") == "task_started":
            previous = _finalize_codex_turn(current, session_id=session_id)
            if previous:
                turns.append(previous)
            current = {
                "turn_id": payload.get("turn_id"),
                "started_at": timestamp,
                "last_seen_at": timestamp,
                "messages": [],
                "message_indexes": {},
                "usage": {},
                "completed": False,
            }
            continue
        if current is None:
            continue
        current["last_seen_at"] = timestamp or current.get("last_seen_at")
        if row_type == "turn_context":
            current["model"] = payload.get("model") or current.get("model")
            current["turn_id"] = payload.get("turn_id") or current.get("turn_id")
            continue
        if row_type == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            if role not in {"user", "assistant"}:
                continue
            allowed = {"input_text"} if role == "user" else {"output_text"}
            text = _content_text(payload.get("content"), allowed)
            if not text:
                continue
            message_id = str(payload.get("id") or "") or None
            item = _message(
                role=role,
                content=text,
                message_id=message_id,
                created_at=timestamp,
            )
            index = current["message_indexes"].get(message_id) if message_id else None
            if index is None:
                current["messages"].append(item)
                if message_id:
                    current["message_indexes"][message_id] = len(current["messages"]) - 1
            else:
                current["messages"][index] = item
            continue
        if row_type == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info")
            if isinstance(info, dict):
                usage = info.get("last_token_usage")
                if isinstance(usage, dict):
                    current["usage"] = usage
            continue
        if row_type == "event_msg" and payload.get("type") == "task_complete":
            current["completed"] = True
            current["ended_at"] = timestamp

    final = _finalize_codex_turn(current, session_id=session_id)
    if final:
        turns.append(final)
    return turns


def _claude_usage(message: dict[str, Any]) -> tuple[int, int, int]:
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0
    prompt = (
        _as_nonnegative_int(usage.get("input_tokens"))
        + _as_nonnegative_int(usage.get("cache_read_input_tokens"))
        + _as_nonnegative_int(usage.get("cache_creation_input_tokens"))
    )
    completion = _as_nonnegative_int(usage.get("output_tokens"))
    return prompt, completion, prompt + completion


def _finalize_claude_turn(
    turn: dict[str, Any] | None,
    *,
    session_id: str,
) -> dict[str, Any] | None:
    if not turn or not turn["messages"]:
        return None
    assistant_messages = [item for item in turn["messages"] if item["role"] == "assistant"]
    prompt_tokens = sum(item[0] for item in turn["usage_by_id"].values())
    completion_tokens = sum(item[1] for item in turn["usage_by_id"].values())
    total_tokens = sum(item[2] for item in turn["usage_by_id"].values())
    turn["messages"][0]["token_count"] = prompt_tokens or None
    if assistant_messages:
        assistant_messages[-1]["token_count"] = completion_tokens or None
    started_at = turn.get("started_at")
    ended_at = turn.get("last_seen_at")
    user_id = str(turn.get("user_id") or "unknown")
    return {
        "source": "cc_switch",
        "conversation_id": f"claude:{session_id}:{user_id}",
        "title": turn["messages"][0]["content"].replace("\n", " ")[:120],
        "task_id": None,
        "task_title": None,
        "model": turn.get("model"),
        "status": "ok" if assistant_messages else "partial",
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": _duration_ms(started_at, ended_at),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost": 0,
        "error_count": 0,
        "trace_id": None,
        "messages": turn["messages"],
        "metadata": {"client": "claude_code", "turn_id": user_id},
    }


def parse_claude_session(path: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    session_id = path.stem
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        row_type = row.get("type")
        message = row.get("message")
        if not isinstance(message, dict):
            message = {}
        timestamp = row.get("timestamp")
        session_id = str(row.get("sessionId") or session_id)
        if row_type == "user":
            text = _content_text(message.get("content"), {"text"})
            if not text or row.get("isMeta"):
                continue
            previous = _finalize_claude_turn(current, session_id=session_id)
            if previous:
                turns.append(previous)
            current = {
                "user_id": row.get("uuid") or row.get("promptId"),
                "started_at": timestamp,
                "last_seen_at": timestamp,
                "messages": [
                    _message(
                        role="user",
                        content=text,
                        message_id=str(row.get("uuid") or "") or None,
                        created_at=timestamp,
                    )
                ],
                "assistant_indexes": {},
                "usage_by_id": {},
            }
            continue
        if row_type != "assistant" or current is None:
            continue
        current["last_seen_at"] = timestamp or current.get("last_seen_at")
        model = message.get("model")
        if model:
            current["model"] = model
        assistant_id = str(message.get("id") or row.get("uuid") or "")
        usage = _claude_usage(message)
        if assistant_id:
            current["usage_by_id"][assistant_id] = usage
        text = _content_text(message.get("content"), {"text"})
        if not text:
            continue
        item = _message(
            role="assistant",
            content=text,
            message_id=assistant_id or None,
            created_at=timestamp,
        )
        index = current["assistant_indexes"].get(assistant_id) if assistant_id else None
        if index is None:
            current["messages"].append(item)
            if assistant_id:
                current["assistant_indexes"][assistant_id] = len(current["messages"]) - 1
        else:
            current["messages"][index] = item

    final = _finalize_claude_turn(current, session_id=session_id)
    if final:
        turns.append(final)
    return turns


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _post_json(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "SmartBrain-Conversation-Sync/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"conversation upload failed: HTTP {error.code} {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"conversation upload failed: {error.reason}") from error
    if not raw:
        return {}
    value = json.loads(raw.decode("utf-8"))
    return value if isinstance(value, dict) else {}


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _session_files(home_dir: Path, *, cutoff: datetime) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    codex_root = home_dir / ".codex" / "sessions"
    if codex_root.exists():
        candidates.extend(("codex", path) for path in codex_root.rglob("*.jsonl"))
    claude_root = home_dir / ".claude" / "projects"
    if claude_root.exists():
        candidates.extend(
            ("claude", path)
            for path in claude_root.rglob("*.jsonl")
            if "subagents" not in {part.lower() for part in path.parts}
        )
    cutoff_timestamp = cutoff.timestamp()
    return [
        item
        for item in candidates
        if item[1].is_file() and item[1].stat().st_mtime >= cutoff_timestamp
    ]


def sync_once(
    *,
    runtime_dir: Path,
    home_dir: Path | None = None,
    lookback_days: int = 7,
    now: datetime | None = None,
) -> dict[str, Any]:
    if (runtime_dir / "shared-device.json").is_file():
        return {
            "status": "shared_device",
            "uploaded": 0,
            "unchanged_files": 0,
            "errors": 0,
        }
    credentials = _load_json(runtime_dir / "device-credentials.json")
    api_endpoint = str(credentials.get("api_endpoint") or "").rstrip("/")
    project_id = str(credentials.get("project_id") or "")
    token = str(credentials.get("token") or "")
    if not api_endpoint or not project_id or not token:
        raise RuntimeError("device conversation sync credentials are incomplete")
    if not 1 <= lookback_days <= 3650:
        raise ValueError("lookback_days must be between 1 and 3650")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    state_path = runtime_dir / "conversation-sync-state.json"
    state = _load_json(state_path)
    file_fingerprints = dict(state.get("files") or {})
    turn_fingerprints = dict(state.get("turns") or {})
    uploaded = 0
    skipped = 0
    errors: list[str] = []
    home = home_dir or Path.home()
    cutoff = current - timedelta(days=lookback_days)
    endpoint = f"{api_endpoint}/v4/ai-chat/device-ingest"

    for client, path in _session_files(home, cutoff=cutoff):
        try:
            stat = path.stat()
        except OSError:
            continue
        file_key = f"{client}:{path}"
        file_fingerprint = f"{stat.st_mtime_ns}:{stat.st_size}"
        if file_fingerprints.get(file_key) == file_fingerprint:
            skipped += 1
            continue
        parser = parse_codex_session if client == "codex" else parse_claude_session
        file_ok = True
        for payload in parser(path):
            payload["project_id"] = project_id
            conversation_id = str(payload.get("conversation_id") or "")
            fingerprint = _payload_fingerprint(payload)
            if turn_fingerprints.get(conversation_id) == fingerprint:
                continue
            try:
                _post_json(endpoint, token, payload)
            except RuntimeError as error:
                errors.append(str(error))
                file_ok = False
                continue
            turn_fingerprints[conversation_id] = fingerprint
            uploaded += 1
        if file_ok:
            file_fingerprints[file_key] = file_fingerprint

    updated_state = {
        "version": 1,
        "files": file_fingerprints,
        "turns": turn_fingerprints,
        "last_run_at": current.astimezone(timezone.utc).isoformat(),
        "last_error": errors[-1] if errors else None,
    }
    _atomic_json(state_path, updated_state)
    status = {
        "uploaded": uploaded,
        "unchanged_files": skipped,
        "errors": len(errors),
        "last_run_at": updated_state["last_run_at"],
    }
    _atomic_json(runtime_dir / "conversation-sync-status.json", status)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Codex and Claude conversations")
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path.home() / "AppData" / "Local" / "AIWorkdayTelemetry" / "current",
    )
    parser.add_argument("--lookback-days", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        status = sync_once(
            runtime_dir=args.runtime_dir,
            lookback_days=args.lookback_days,
        )
    except Exception as error:
        print(f"AI conversation sync failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(status, ensure_ascii=False))
    return 0 if not status["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
