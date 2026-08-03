from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

try:
    from agentops.project_wiki.domain import KnowledgeCandidate
except ModuleNotFoundError:
    domain_path = Path(__file__).parents[1] / "project_wiki" / "domain.py"
    spec = importlib.util.spec_from_file_location("project_wiki_domain_for_memory_publish", domain_path)
    if spec is None or spec.loader is None:
        raise
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    KnowledgeCandidate = module.KnowledgeCandidate


def build_skill_candidates(
    payload: list[dict[str, Any]],
    *,
    source_document_ids: list[str],
) -> list[KnowledgeCandidate]:
    source_ids = [f"document:{document_id}" for document_id in source_document_ids]
    if not source_ids:
        return []
    candidates: list[KnowledgeCandidate] = []
    for item in payload:
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        markdown = str(item.get("markdown_content") or "").strip()
        if not title or not summary or not markdown:
            continue
        candidates.append(
            KnowledgeCandidate(
                title=title,
                page_type="procedure",
                summary=summary,
                markdown_content=markdown,
                usefulness=1.0,
                confidence=1.0,
                source_ids=source_ids,
                link_titles=[],
                contradiction=False,
                sensitive=False,
                ephemeral=False,
            )
        )
    return candidates
