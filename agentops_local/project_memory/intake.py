from __future__ import annotations

from typing import Iterable, Protocol, TypeVar


# Meeting uploads intentionally keep their existing 20 MB limit. Project
# original materials have a separate, larger boundary because they can include
# complete source decks and document archives.
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_MATERIAL_FILE_BYTES = 500 * 1024 * 1024
MAX_MATERIAL_BATCH_BYTES = 500 * 1024 * 1024
MAX_BATCH_BYTES = MAX_MATERIAL_BATCH_BYTES
HARD_BLOCKED_RECOMMENDATIONS = {"review", "duplicate", "sensitive", "low_value"}


class _ConfirmableFile(Protocol):
    id: object
    recommendation: str
    included: bool


class _ReviewFile(Protocol):
    filename: str
    format: str
    size_bytes: int
    reason: str


TFile = TypeVar("TFile", bound=_ConfirmableFile)


def validate_batch_limits(files: Iterable[tuple[str, int]]) -> None:
    rows = list(files)
    if not rows:
        raise ValueError("at least one file is required")
    for filename, size_bytes in rows:
        if size_bytes <= 0:
            raise ValueError(f"file is empty: {filename}")
        if size_bytes > MAX_MATERIAL_FILE_BYTES:
            raise ValueError(f"single file exceeds 500 MB: {filename}")
    if sum(size for _, size in rows) > MAX_MATERIAL_BATCH_BYTES:
        raise ValueError("batch exceeds 500 MB")


def select_confirmed_files(
    files: Iterable[TFile],
    *,
    requested_ids: set[str],
) -> list[TFile]:
    selected: list[TFile] = []
    for row in files:
        if str(row.id) not in requested_ids:
            continue
        if row.recommendation in HARD_BLOCKED_RECOMMENDATIONS:
            continue
        if not row.included and row.recommendation != "review":
            continue
        selected.append(row)
    return selected


def build_original_material_review_markdown(
    *,
    project_name: str,
    files: Iterable[_ReviewFile],
) -> str:
    rows = list(files)
    rendered_files = "\n".join(
        f"- {row.filename}（{row.format.upper()}，{row.size_bytes} 字节）：{row.reason}"
        for row in rows
    ) or "- 无可提交文件"
    return f"""# {project_name} 原始项目资料审批

文件已直接上传，未执行 AI 敏感信息识别，也未进行 AI 总结或归纳。

## 待审批原始文件

{rendered_files}

## 审批说明

管理员采用后，以上原始文件才会写入项目知识库；驳回则不会入库。
""".strip() + "\n"
