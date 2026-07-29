from __future__ import annotations

import json
import re
from typing import Any


MANAGED_CODEX_START = "# BEGIN AI WORKDAY MONITOR - MANAGED"
MANAGED_CODEX_END = "# END AI WORKDAY MONITOR - MANAGED"

CLAUDE_TELEMETRY_ENV_KEYS = (
    "CLAUDE_CODE_ENABLE_TELEMETRY",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA",
    "OTEL_TRACES_EXPORTER",
    "OTEL_LOGS_EXPORTER",
    "OTEL_METRICS_EXPORTER",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_RESOURCE_ATTRIBUTES",
    "OTEL_SERVICE_NAME",
    "OTEL_LOG_USER_PROMPTS",
    "OTEL_LOG_ASSISTANT_RESPONSES",
    "OTEL_LOG_TOOL_DETAILS",
    "OTEL_LOG_TOOL_CONTENT",
    "OTEL_LOG_RAW_API_BODIES",
)


def _no_proxy_entries(value: str | None) -> list[str]:
    return [
        entry.strip()
        for entry in re.split(r"[,;]", value or "")
        if entry.strip()
    ]


def _deduplicate_entries(entries: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = entry.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(entry)
    return result


def merge_no_proxy(
    existing: str | None,
    managed_entries: tuple[str, ...],
) -> str:
    return ",".join(
        _deduplicate_entries(
            _no_proxy_entries(existing) + list(managed_entries)
        )
    )


def remove_managed_no_proxy(
    current: str | None,
    original: str | None,
    managed_entries: tuple[str, ...],
) -> str:
    original_entries = _no_proxy_entries(original)
    original_keys = {entry.casefold() for entry in original_entries}
    managed_keys = {entry.casefold() for entry in managed_entries}
    retained = [
        entry
        for entry in _no_proxy_entries(current)
        if entry.casefold() not in managed_keys
        or entry.casefold() in original_keys
    ]
    return ",".join(_deduplicate_entries(original_entries + retained))


def merge_claude_common_config(
    existing_text: str,
    snippet: dict[str, Any],
) -> str:
    existing = json.loads(existing_text or "{}")
    if not isinstance(existing, dict):
        raise ValueError("Claude Common Config must be a JSON object")
    snippet_env = snippet.get("env")
    if not isinstance(snippet_env, dict):
        raise ValueError("Claude telemetry snippet is missing env")
    existing_env = existing.setdefault("env", {})
    if not isinstance(existing_env, dict):
        raise ValueError("Claude Common Config env must be a JSON object")
    existing_env.update(snippet_env)
    return json.dumps(existing, ensure_ascii=False, indent=2) + "\n"


def remove_claude_telemetry(existing_text: str) -> str:
    existing = json.loads(existing_text or "{}")
    if not isinstance(existing, dict):
        raise ValueError("Claude config must be a JSON object")
    env = existing.get("env")
    if isinstance(env, dict):
        for key in CLAUDE_TELEMETRY_ENV_KEYS:
            env.pop(key, None)
        if not env:
            existing.pop("env", None)
    return json.dumps(existing, ensure_ascii=False, indent=2) + "\n"


def remove_managed_codex_block(existing_text: str) -> str:
    start = existing_text.find(MANAGED_CODEX_START)
    if start < 0:
        return existing_text
    end = existing_text.find(MANAGED_CODEX_END, start)
    if end < 0:
        return existing_text[:start].rstrip() + "\n"
    end += len(MANAGED_CODEX_END)
    if existing_text[end : end + 2] == "\r\n":
        end += 2
    elif existing_text[end : end + 1] == "\n":
        end += 1
    return existing_text[:start] + existing_text[end:]


def merge_codex_common_config(
    existing_text: str,
    managed_snippet: str,
) -> str:
    clean = remove_managed_codex_block(existing_text)
    if re.search(r"(?m)^\s*\[otel(?:\]|\.)", clean):
        raise ValueError(
            "existing unmanaged [otel] configuration must be removed or "
            "merged manually before installation"
        )
    separator = "" if not clean or clean.endswith("\n") else "\n"
    return clean + separator + managed_snippet.rstrip() + "\n"
