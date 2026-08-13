from __future__ import annotations

import json
import re
from datetime import date
from typing import Iterable


def normalize_list(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else list(value)
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        for part in re.split(r"[,，;；\n]+", str(item)):
            cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", part).strip()
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key not in seen:
                seen.add(key)
                result.append(cleaned[:300])
    return result


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_meeting_markdown(
    *,
    title: str,
    meeting_date: date,
    participants: list[str],
    tags: list[str],
    summary: str,
    decisions: list[str],
    action_items: list[str],
) -> str:
    cleaned_summary = summary.strip()
    lines = [
        "---",
        f"title: {_yaml_string(title.strip())}",
        f"meeting_date: {meeting_date.isoformat()}",
        f"participants: {json.dumps(participants, ensure_ascii=False)}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        "---",
        "",
        f"# {title.strip()}",
        "",
        "## 会议内容",
        "",
        cleaned_summary,
    ]
    if decisions:
        lines.extend(["", "## 关键决策", ""])
        lines.extend(f"- {item}" for item in decisions)
    if action_items:
        lines.extend(["", "## 行动项", ""])
        lines.extend(f"- [ ] {item}" for item in action_items)
    return "\n".join(lines).strip() + "\n"
