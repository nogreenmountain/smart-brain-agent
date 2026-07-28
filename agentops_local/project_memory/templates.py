from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


TEMPLATE_VERSION = "project-memory-v1"


@dataclass(frozen=True)
class SourceText:
    filename: str
    format: str
    text: str


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _clip(text: str, limit: int = 3500) -> str:
    value = text.strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "\n\n（后续内容已截断，完整资料仍保留在草稿来源中。）"


def _candidate_lines(source: SourceText) -> list[str]:
    lines: list[str] = []
    for raw_line in source.text.splitlines():
        line = _clean(raw_line)
        if len(line) < 6:
            continue
        if len(line) > 220:
            line = line[:220].rstrip() + "..."
        lines.append(line)
        if len(lines) >= 120:
            break
    return lines


def _section_summary(
    sources: list[SourceText],
    *,
    keywords: tuple[str, ...],
    fallback: str,
    limit: int = 8,
) -> str:
    bullets: list[str] = []
    seen: set[str] = set()
    lowered_keywords = tuple(keyword.lower() for keyword in keywords)
    for source in sources:
        for line in _candidate_lines(source):
            lowered = line.lower()
            if not any(keyword in lowered for keyword in lowered_keywords):
                continue
            key = f"{source.filename}:{line}"
            if key in seen:
                continue
            seen.add(key)
            bullets.append(f"- （{source.filename}）{line}")
            if len(bullets) >= limit:
                return "\n".join(bullets)
    return fallback


def _source_blocks(sources: list[SourceText]) -> str:
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        blocks.append(
            "\n".join(
                [
                    f"### 资料 {index}：{source.filename}",
                    f"- 格式：{source.format}",
                    "",
                    "```text",
                    _clip(source.text),
                    "```",
                ]
            )
        )
    return "\n\n".join(blocks) if blocks else "暂无上传资料。"


def build_project_memory_markdown(
    *,
    department_id: str,
    department_name: str,
    project_name: str,
    repository: Mapping[str, object] | None,
    sources: list[SourceText],
) -> str:
    """Build the deterministic Markdown document used for review and RAG."""
    repo_url = _clean(str((repository or {}).get("git_url") or "未填写"))
    repo_branch = _clean(str((repository or {}).get("git_branch") or "main"))
    source_index = "\n".join(
        f"- {index}. `{source.filename}`（{source.format}）"
        for index, source in enumerate(sources, start=1)
    ) or "- 暂无"

    source_text = _source_blocks(sources)
    overview = _section_summary(
        sources,
        keywords=("项目", "目标", "背景", "范围", "模块", "系统", "功能", "需求"),
        fallback="- 本批资料未明确写出项目概览，请审批人根据资料补齐项目目标、范围和主要模块。",
    )
    startup = _section_summary(
        sources,
        keywords=("github", "git", "仓库", "branch", "分支", "启动", "install", "npm", "pnpm", "yarn", "docker", "运行"),
        fallback="- 本批资料未明确写出仓库或启动方式，请审批人补齐克隆、安装、启动和环境变量说明。",
    )
    architecture = _section_summary(
        sources,
        keywords=("架构", "服务", "前端", "后端", "接口", "api", "数据库", "模型", "队列", "缓存", "部署", "docker"),
        fallback="- 本批资料未明确写出技术架构，请审批人补齐技术栈、服务边界和部署依赖。",
    )
    workflow = _section_summary(
        sources,
        keywords=("流程", "步骤", "审批", "上传", "生成", "联调", "验收", "测试", "任务", "开发"),
        fallback="- 本批资料未明确写出关键流程，请审批人补齐研发交付、联调和验收步骤。",
    )
    data_api = _section_summary(
        sources,
        keywords=("表", "字段", "数据库", "接口", "endpoint", "route", "api", "schema", "sql", "权限", "鉴权"),
        fallback="- 本批资料未明确写出数据库与接口，请审批人补齐核心表、接口路径和鉴权规则。",
    )
    decisions = _section_summary(
        sources,
        keywords=("决定", "约定", "规范", "必须", "不要", "禁止", "默认", "兼容", "规则", "版本"),
        fallback="- 本批资料未明确写出重要决策，请审批人补齐命名、权限、版本和不可随意改变的规则。",
    )
    troubleshooting = _section_summary(
        sources,
        keywords=("错误", "失败", "异常", "报错", "排查", "修复", "问题", "warning", "error", "failed"),
        fallback="- 本批资料未明确写出常见问题，请审批人补齐构建、启动、接口和数据排查办法。",
    )
    return f"""# 项目长期记忆：{project_name}

- 部门：{department_name}
- 部门编码：{department_id}
- 项目：{project_name}
- 模板版本：{TEMPLATE_VERSION}
- 审批状态：待审批

## 1. 项目概览

{overview}

## 2. 代码仓库与启动方式

- GitHub 仓库：{repo_url}
- 默认分支：{repo_branch}
{startup}

## 3. 技术架构

{architecture}

## 4. 关键业务流程

{workflow}

## 5. 数据库与接口

{data_api}

## 6. 重要决策与约定

{decisions}

## 7. 常见问题与排查

{troubleshooting}

## 8. 新员工交接清单

- 拉取 GitHub 仓库并切到默认分支。
- 阅读本项目长期记忆。
- 确认本地环境、依赖、密钥和启动命令。
- 跑通核心功能和最小测试。
- 找到当前负责人确认最新开发重点。

## 9. 原始资料索引

{source_index}

## 10. 待补充问题

- 哪些内容需要负责人确认？
- 哪些接口、表结构或部署步骤还缺少权威说明？
- 哪些旧资料可能已经过期？

## 附录：上传资料摘录

{source_text}
""".strip() + "\n"
