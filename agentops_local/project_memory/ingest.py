from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from agentops.rag.ingest import IngestResult, ingest_file


def ingest_markdown_memory(
    *,
    markdown: str,
    project_id: uuid.UUID,
    display_name: str,
    created_by_user_id: uuid.UUID | None,
) -> IngestResult:
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as tmp:
        tmp.write(markdown)
        path = Path(tmp.name)
    try:
        return ingest_file(
            path,
            project_id=project_id,
            display_name=display_name,
            created_by_user_id=created_by_user_id,
        )
    finally:
        path.unlink(missing_ok=True)

