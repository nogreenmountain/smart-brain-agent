from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable


try:
    from agentops.project_wiki.domain import sanitize_untrusted_text
except ModuleNotFoundError:  # Standalone tests load this module without agentops installed.
    path = Path(__file__).parents[1] / "project_wiki" / "domain.py"
    spec = importlib.util.spec_from_file_location("member_wiki_project_domain", path)
    if spec is None or spec.loader is None:
        raise
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    sanitize_untrusted_text = module.sanitize_untrusted_text


TASK_TYPES = {
    "development",
    "debugging",
    "deployment",
    "configuration",
    "data_processing",
    "documentation",
    "testing",
    "research",
    "operations",
    "other",
}
OUTCOMES = {"success", "partial", "failure"}
_OUTCOME_RANK = {"failure": 0, "partial": 1, "success": 2}
_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,119}$")


def _compact(value: Any, *, limit: int) -> str:
    text = " ".join(sanitize_untrusted_text(str(value or "")).split()).strip()
    return text[:limit]


def _items(value: Any, *, limit: int = 20, item_limit: int = 800) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[str] = []
    for raw in value[:limit]:
        item = _compact(raw, limit=item_limit)
        if item and item not in result:
            result.append(item)
    return tuple(result)


def _score(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(parsed, 1.0))


def build_experience_key(task_type: str, requested_key: Any, title: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(requested_key or "")).lower()
    normalized = re.sub(r"[^a-z0-9_-]+", "-", normalized).strip("-_")[:120]
    if _KEY_PATTERN.fullmatch(normalized):
        return normalized
    safe_type = task_type if task_type in TASK_TYPES else "other"
    digest = hashlib.sha256(
        unicodedata.normalize("NFKC", title).casefold().encode("utf-8")
    ).hexdigest()[:16]
    return f"{safe_type}-{digest}"


@dataclass
class MemberExperience:
    experience_key: str
    title: str
    task_type: str
    outcome: str
    summary: str = ""
    applicable_scenarios: tuple[str, ...] = ()
    goal: str = ""
    prerequisites: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    command_patterns: tuple[str, ...] = ()
    validation: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    checklist: tuple[str, ...] = ()
    boundaries: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    confidence: float = 0.0
    source_session_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.title = _compact(self.title, limit=200)
        requested_type = _compact(self.task_type, limit=40).lower()
        self.task_type = requested_type if requested_type in TASK_TYPES else "other"
        requested_outcome = _compact(self.outcome, limit=20).lower()
        self.outcome = requested_outcome if requested_outcome in OUTCOMES else "partial"
        self.experience_key = build_experience_key(
            self.task_type,
            self.experience_key,
            self.title,
        )
        self.summary = _compact(self.summary, limit=1200)
        self.goal = _compact(self.goal, limit=1000)
        for field_name in (
            "applicable_scenarios",
            "prerequisites",
            "steps",
            "decisions",
            "command_patterns",
            "validation",
            "failures",
            "checklist",
            "boundaries",
            "tools",
            "tags",
            "source_session_ids",
        ):
            setattr(self, field_name, _items(getattr(self, field_name)))
        self.tags = self.tags[:20]
        self.tools = self.tools[:20]
        self.confidence = _score(self.confidence)


def _json_object(raw: str) -> dict[str, Any]:
    value = str(raw or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        lines = lines[1:] if lines else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("member Wiki model response is not JSON")
    payload = json.loads(value[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("member Wiki model response must be an object")
    return payload


def parse_experience_response(
    raw: str,
    *,
    allowed_session_ids: set[str],
) -> list[MemberExperience]:
    payload = _json_object(raw)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []
    experiences: list[MemberExperience] = []
    for raw_item in raw_items[:8]:
        if not isinstance(raw_item, dict):
            continue
        sources = tuple(
            item
            for item in _items(raw_item.get("source_session_ids"), limit=20, item_limit=100)
            if item in allowed_session_ids
        )
        title = _compact(raw_item.get("title"), limit=200)
        steps = _items(raw_item.get("steps"))
        validation = _items(raw_item.get("validation"))
        if not title or not sources or not steps or not validation:
            continue
        experiences.append(MemberExperience(
            experience_key=str(raw_item.get("experience_key") or ""),
            title=title,
            task_type=str(raw_item.get("task_type") or "other"),
            outcome=str(raw_item.get("outcome") or "partial"),
            summary=str(raw_item.get("summary") or ""),
            applicable_scenarios=_items(raw_item.get("applicable_scenarios")),
            goal=str(raw_item.get("goal") or ""),
            prerequisites=_items(raw_item.get("prerequisites")),
            steps=steps,
            decisions=_items(raw_item.get("decisions")),
            command_patterns=_items(raw_item.get("command_patterns")),
            validation=validation,
            failures=_items(raw_item.get("failures")),
            checklist=_items(raw_item.get("checklist")),
            boundaries=_items(raw_item.get("boundaries")),
            tools=_items(raw_item.get("tools")),
            tags=_items(raw_item.get("tags")),
            confidence=raw_item.get("confidence", 0),
            source_session_ids=sources,
        ))
    return experiences


def _union(*groups: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for group in groups:
        for item in group:
            if item and item not in result:
                result.append(item)
    return tuple(result)


def merge_experience(
    existing: MemberExperience,
    incoming: MemberExperience,
) -> MemberExperience:
    if existing.experience_key != incoming.experience_key:
        raise ValueError("only experiences with the same key can be merged")
    return MemberExperience(
        experience_key=existing.experience_key,
        title=incoming.title or existing.title,
        task_type=incoming.task_type or existing.task_type,
        outcome=max((existing.outcome, incoming.outcome), key=_OUTCOME_RANK.get),
        summary=incoming.summary or existing.summary,
        applicable_scenarios=_union(existing.applicable_scenarios, incoming.applicable_scenarios),
        goal=incoming.goal or existing.goal,
        prerequisites=_union(existing.prerequisites, incoming.prerequisites),
        steps=_union(existing.steps, incoming.steps),
        decisions=_union(existing.decisions, incoming.decisions),
        command_patterns=_union(existing.command_patterns, incoming.command_patterns),
        validation=_union(existing.validation, incoming.validation),
        failures=_union(existing.failures, incoming.failures),
        checklist=_union(existing.checklist, incoming.checklist),
        boundaries=_union(existing.boundaries, incoming.boundaries),
        tools=_union(existing.tools, incoming.tools),
        tags=_union(existing.tags, incoming.tags),
        confidence=max(existing.confidence, incoming.confidence),
        source_session_ids=_union(existing.source_session_ids, incoming.source_session_ids),
    )


def experience_to_dict(experience: MemberExperience) -> dict[str, Any]:
    return {
        "experience_key": experience.experience_key,
        "title": experience.title,
        "task_type": experience.task_type,
        "outcome": experience.outcome,
        "summary": experience.summary,
        "applicable_scenarios": list(experience.applicable_scenarios),
        "goal": experience.goal,
        "prerequisites": list(experience.prerequisites),
        "steps": list(experience.steps),
        "decisions": list(experience.decisions),
        "command_patterns": list(experience.command_patterns),
        "validation": list(experience.validation),
        "failures": list(experience.failures),
        "checklist": list(experience.checklist),
        "boundaries": list(experience.boundaries),
        "tools": list(experience.tools),
        "tags": list(experience.tags),
        "confidence": experience.confidence,
        "source_session_ids": list(experience.source_session_ids),
    }


def experience_from_dict(value: dict[str, Any]) -> MemberExperience:
    return MemberExperience(
        experience_key=value.get("experience_key", ""),
        title=value.get("title", ""),
        task_type=value.get("task_type", "other"),
        outcome=value.get("outcome", "partial"),
        summary=value.get("summary", ""),
        applicable_scenarios=_items(value.get("applicable_scenarios")),
        goal=value.get("goal", ""),
        prerequisites=_items(value.get("prerequisites")),
        steps=_items(value.get("steps")),
        decisions=_items(value.get("decisions")),
        command_patterns=_items(value.get("command_patterns")),
        validation=_items(value.get("validation")),
        failures=_items(value.get("failures")),
        checklist=_items(value.get("checklist")),
        boundaries=_items(value.get("boundaries")),
        tools=_items(value.get("tools")),
        tags=_items(value.get("tags")),
        confidence=value.get("confidence", 0),
        source_session_ids=_items(value.get("source_session_ids"), item_limit=100),
    )


def _yaml(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _section(title: str, values: Iterable[str], *, checklist: bool = False) -> list[str]:
    items = list(values)
    if not items:
        return []
    prefix = "- [ ] " if checklist else "- "
    return [f"## {title}", "", *[f"{prefix}{item}" for item in items], ""]


def render_experience_markdown(
    experience: MemberExperience,
    *,
    employee_id: str,
    employee_name: str,
    first_observed: date,
    last_observed: date,
    observation_count: int,
    source_session_ids: Iterable[str],
    source_trace_ids: Iterable[str],
) -> str:
    session_ids = tuple(dict.fromkeys(str(item) for item in source_session_ids if item))
    trace_ids = tuple(dict.fromkeys(str(item) for item in source_trace_ids if item))
    lines = [
        "---",
        f"employee_id: {_yaml(employee_id)}",
        f"employee_name: {_yaml(employee_name)}",
        f"experience_key: {_yaml(experience.experience_key)}",
        f"task_type: {_yaml(experience.task_type)}",
        f"outcome: {_yaml(experience.outcome)}",
        f"confidence: {experience.confidence:.3f}",
        f"first_observed: {_yaml(first_observed.isoformat())}",
        f"last_observed: {_yaml(last_observed.isoformat())}",
        f"observation_count: {max(int(observation_count), 1)}",
        f"source_session_ids: {_yaml(list(session_ids))}",
        f"source_trace_ids: {_yaml(list(trace_ids))}",
        f"tools: {_yaml(list(experience.tools))}",
        f"tags: {_yaml(list(experience.tags))}",
        "---",
        "",
        f"# {experience.title}",
        "",
    ]
    if experience.summary:
        lines.extend([experience.summary, ""])
    lines.extend(_section("适用场景", experience.applicable_scenarios))
    if experience.goal:
        lines.extend(["## 目标与完成标准", "", experience.goal, ""])
    lines.extend(_section("前置条件", experience.prerequisites))
    if experience.steps:
        lines.extend([
            "## 实际步骤",
            "",
            *[f"{index}. {item}" for index, item in enumerate(experience.steps, 1)],
            "",
        ])
    lines.extend(_section("关键判断", experience.decisions))
    lines.extend(_section("使用的工具与命令模式", experience.command_patterns))
    lines.extend(_section("验证方法", experience.validation))
    lines.extend(_section("失败尝试与修正", experience.failures))
    lines.extend(_section("可复用检查清单", experience.checklist, checklist=True))
    lines.extend(_section("边界与不适用情况", experience.boundaries))
    lines.extend([
        "## 来源",
        "",
        f"- 观察日期：{first_observed.isoformat()} 至 {last_observed.isoformat()}",
        f"- 有效证据次数：{max(int(observation_count), 1)}",
        f"- 来源会话：{', '.join(session_ids) if session_ids else '无'}",
    ])
    if trace_ids:
        lines.append(f"- Trace：{', '.join(trace_ids)}")
    return "\n".join(lines).strip() + "\n"
