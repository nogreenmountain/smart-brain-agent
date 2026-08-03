from __future__ import annotations

from typing import Iterable, Protocol, TypeVar


MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_BATCH_BYTES = 50 * 1024 * 1024
HARD_BLOCKED_RECOMMENDATIONS = {"duplicate", "sensitive", "low_value"}


class _ConfirmableFile(Protocol):
    id: object
    recommendation: str
    included: bool


class _Skill(Protocol):
    title: str
    markdown_content: str


TFile = TypeVar("TFile", bound=_ConfirmableFile)


def validate_batch_limits(files: Iterable[tuple[str, int]]) -> None:
    rows = list(files)
    if not rows:
        raise ValueError("at least one file is required")
    for filename, size_bytes in rows:
        if size_bytes <= 0:
            raise ValueError(f"file is empty: {filename}")
        if size_bytes > MAX_FILE_BYTES:
            raise ValueError(f"single file exceeds 20 MB: {filename}")
    if sum(size for _, size in rows) > MAX_BATCH_BYTES:
        raise ValueError("batch exceeds 50 MB")


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


def build_review_markdown(
    *,
    project_name: str,
    curated_markdown: str,
    skills: Iterable[_Skill],
) -> str:
    skill_blocks = []
    for index, skill in enumerate(skills, start=1):
        skill_blocks.append(
            f"### {index}. {skill.title}\n\n{skill.markdown_content.strip()}"
        )
    rendered_skills = "\n\n".join(skill_blocks) or "本批资料没有形成可复用 Skill。"
    return f"""# {project_name} 资料整理与长期记忆候选

## 整理后的项目资料

{curated_markdown.strip()}

## 可复用 Skill

{rendered_skills}
""".strip() + "\n"
