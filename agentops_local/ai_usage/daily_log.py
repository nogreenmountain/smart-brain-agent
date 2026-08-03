from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable


@dataclass(frozen=True)
class WorklogMessage:
    role: str
    content: str


@dataclass(frozen=True)
class WorklogConversation:
    session_id: str
    title: str
    source: str
    messages: tuple[WorklogMessage, ...]


@dataclass(frozen=True)
class WorklogItem:
    title: str
    problem: str
    actions: tuple[str, ...]
    result: str
    artifacts: tuple[str, ...]
    validation: tuple[str, ...]
    source_session_ids: tuple[str, ...]


@dataclass(frozen=True)
class DailyWorklogGeneration:
    work_items: tuple[WorklogItem, ...]
    report_markdown: str
    source_session_ids: tuple[str, ...]


_EXECUTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:created|modified|updated|added|deleted|removed|fixed|implemented|deployed|rebuilt|generated|installed|configured|committed|pushed|executed|completed)\b",
        r"\b(?:ran|run)\s+(?:the\s+)?(?:tests?|build|lint|typecheck|command|script|migration)",
        r"\b\d+\s+(?:tests?\s+)?passed\b",
        r"\b(?:exit|status)\s+code\s*[:=]?\s*0\b",
        r"(?:已修改|已创建|已更新|已新增|已删除|已修复|已完成|已实现|已部署|已重建|已生成|已安装|已配置|已提交|已推送)",
        r"(?:测试|构建|编译|类型检查|部署|迁移)(?:已)?通过",
        r"(?:运行|执行)(?:了|完成|成功)",
    )
)


def _message_has_execution_signal(message: WorklogMessage) -> bool:
    role = message.role.strip().lower()
    if role in {"tool", "function"}:
        return True
    if role != "assistant":
        return False
    content = _compact(message.content, limit=12_000)
    return any(pattern.search(content) for pattern in _EXECUTION_PATTERNS)


def has_execution_signal(conversation: WorklogConversation) -> bool:
    """Return whether a conversation contains evidence of completed Agent work."""
    return any(_message_has_execution_signal(message) for message in conversation.messages)


def _compact(value: Any, *, limit: int = 4000) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _string_list(value: Any, *, limit: int = 12) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items = []
    for raw in value[:limit]:
        item = _compact(raw, limit=800)
        if item and item not in items:
            items.append(item)
    return tuple(items)


def _conversation_block(
    conversation: WorklogConversation,
    *,
    budget: int,
) -> str:
    messages = list(conversation.messages[:80])
    selected_indexes: list[int] = []

    first_user = next(
        (index for index, message in enumerate(messages) if message.role.lower() == "user"),
        None,
    )
    if first_user is not None:
        selected_indexes.append(first_user)

    execution_indexes = [
        index
        for index, message in enumerate(messages)
        if _message_has_execution_signal(message)
    ]
    selected_indexes.extend(execution_indexes[-4:])

    last_assistant = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if messages[index].role.lower() == "assistant"
        ),
        None,
    )
    if last_assistant is not None:
        selected_indexes.append(last_assistant)
    if messages:
        selected_indexes.append(len(messages) - 1)

    selected_indexes = sorted(set(selected_indexes))[:6]
    header = "\n".join([
        f'<conversation id="{conversation.session_id}" source="{conversation.source}">',
        f"title: {_compact(conversation.title, limit=300)}",
    ])
    footer = "</conversation>"
    fixed_size = len(header) + len(footer) + 2
    available = max(budget - fixed_size, 200)
    per_message = max(120, min(1200, available // max(len(selected_indexes), 1) - 16))
    lines = []
    for index in selected_indexes:
        message = messages[index]
        content = _compact(message.content, limit=per_message)
        if content:
            lines.append(f"{message.role}: {content}")
    return "\n".join([header, *lines, footer])


def build_daily_worklog_prompt(
    *,
    employee_name: str,
    work_date: date,
    conversations: Iterable[WorklogConversation],
) -> str:
    blocks = []
    context_chars = 0
    context_limit = 4_500
    for conversation in conversations:
        remaining = context_limit - context_chars
        if remaining <= 0:
            break
        block = _conversation_block(conversation, budget=remaining)
        blocks.append(block)
        context_chars += len(block) + 1
        if context_chars >= context_limit:
            break

    return f"""你是企业 AI 工作日志整理员。请分析 {employee_name} 在 {work_date.isoformat()} 的 AI 会话。

目标：只提取 Agent 实际执行并产生工作结果的事项。

必须纳入：构建或修改代码、创建或修改文档/文件、调试故障、运行测试、部署配置、执行数据处理、完成多步骤工具操作。
必须排除：普通问答、纯教程解释、询问“文件在哪里”、询问“某某操作如何实现”但 AI 只给说明、闲聊、观点讨论、未实际执行的建议。
混合会话只提取其中有实际执行证据的部分。实际执行证据包括工具调用、文件或代码变更、命令执行、测试结果、部署结果、明确产出的文档或制品。
证据不足时宁可排除，不要根据用户意图推断已经完成。

仅输出 JSON：
{{
  "work_items": [
    {{
      "title": "简洁任务标题",
      "problem": "要解决的问题",
      "actions": ["实际执行动作"],
      "result": "完成结果",
      "artifacts": ["实际修改或创建的文件、代码、配置或文档"],
      "validation": ["测试、构建、部署或其他验证结果"],
      "source_session_ids": ["只能填写下方真实 conversation id"]
    }}
  ]
}}

<conversations>
{chr(10).join(blocks)}
</conversations>
"""


def _json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("daily worklog model response is not JSON")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("daily worklog model response must be an object")
    return value


def _render_markdown(items: Iterable[WorklogItem]) -> str:
    sections = []
    for item in items:
        lines = [f"## {item.title}", "", "**解决问题**", item.problem or "未单独说明"]
        if item.actions:
            lines.extend(["", "**执行过程**", *[f"- {value}" for value in item.actions]])
        lines.extend(["", "**完成结果**", item.result or "已完成执行"])
        if item.artifacts:
            lines.extend(["", "**产出内容**", *[f"- {value}" for value in item.artifacts]])
        if item.validation:
            lines.extend(["", "**验证结果**", *[f"- {value}" for value in item.validation]])
        sections.append("\n".join(lines))
    return "\n\n".join(sections).strip()


def merge_daily_worklog_generations(
    generations: Iterable[DailyWorklogGeneration],
) -> DailyWorklogGeneration:
    merged_items: list[WorklogItem] = []
    item_indexes: dict[tuple[Any, ...], int] = {}
    source_session_ids: list[str] = []

    for generation in generations:
        for source_id in generation.source_session_ids:
            if source_id not in source_session_ids:
                source_session_ids.append(source_id)
        for item in generation.work_items:
            key = (
                item.title.casefold(),
                item.problem.casefold(),
                tuple(value.casefold() for value in item.actions),
                item.result.casefold(),
                tuple(value.casefold() for value in item.artifacts),
                tuple(value.casefold() for value in item.validation),
            )
            existing_index = item_indexes.get(key)
            if existing_index is None:
                item_indexes[key] = len(merged_items)
                merged_items.append(item)
                continue
            existing = merged_items[existing_index]
            merged_sources = list(existing.source_session_ids)
            for source_id in item.source_session_ids:
                if source_id not in merged_sources:
                    merged_sources.append(source_id)
            merged_items[existing_index] = WorklogItem(
                title=existing.title,
                problem=existing.problem,
                actions=existing.actions,
                result=existing.result,
                artifacts=existing.artifacts,
                validation=existing.validation,
                source_session_ids=tuple(merged_sources),
            )

    work_items = tuple(merged_items)
    return DailyWorklogGeneration(
        work_items=work_items,
        report_markdown=_render_markdown(work_items),
        source_session_ids=tuple(source_session_ids),
    )


def parse_daily_worklog_response(
    raw: str,
    *,
    allowed_session_ids: set[str],
) -> DailyWorklogGeneration:
    payload = _json_object(raw)
    raw_items = payload.get("work_items")
    if not isinstance(raw_items, list):
        raw_items = []

    items = []
    used_session_ids = []
    for raw_item in raw_items[:30]:
        if not isinstance(raw_item, dict):
            continue
        source_ids = tuple(
            value
            for value in _string_list(raw_item.get("source_session_ids"), limit=20)
            if value in allowed_session_ids
        )
        title = _compact(raw_item.get("title"), limit=200)
        actions = _string_list(raw_item.get("actions"))
        result = _compact(raw_item.get("result"), limit=1600)
        if not source_ids or not title or (not actions and not result):
            continue
        item = WorklogItem(
            title=title,
            problem=_compact(raw_item.get("problem"), limit=1200),
            actions=actions,
            result=result,
            artifacts=_string_list(raw_item.get("artifacts")),
            validation=_string_list(raw_item.get("validation")),
            source_session_ids=source_ids,
        )
        items.append(item)
        for source_id in source_ids:
            if source_id not in used_session_ids:
                used_session_ids.append(source_id)

    work_items = tuple(items)
    return DailyWorklogGeneration(
        work_items=work_items,
        report_markdown=_render_markdown(work_items),
        source_session_ids=tuple(used_session_ids),
    )
