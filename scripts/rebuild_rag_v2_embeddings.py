from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from sqlalchemy import select

from agentops.common.orm import session_scope
from agentops.rag.db import Document, DocumentChunk
from agentops.rag.ingest import _chunk_blocks
from agentops.rag.ingest_v2 import chunks_from_existing_rows, insert_document_chunks_v2
from agentops.rag.parsers import parse


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def _find_source_file(doc: Document, source_dirs: list[Path]) -> Path | None:
    candidates = [doc.filename, doc.display_name]
    for root in source_dirs:
        for name in candidates:
            if not name:
                continue
            path = root / Path(name).name
            if path.exists() and path.is_file():
                return path
    return None


def _load_chunks_from_source(doc: Document, source_path: Path):
    blocks = parse(source_path, doc.format)
    return _chunk_blocks(blocks, doc.format)


def _load_chunks_from_v1(session, doc: Document):
    rows = (
        session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
        )
        .scalars()
        .all()
    )
    return chunks_from_existing_rows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild public.document_chunks_v2")
    parser.add_argument("--project-id", help="Only rebuild documents in one project")
    parser.add_argument("--document-id", action="append", default=[], help="Specific document id")
    parser.add_argument("--source-dir", action="append", default=[], help="Directory containing original files")
    parser.add_argument("--no-v1-fallback", action="store_true", help="Skip docs whose source file is missing")
    parser.add_argument("--dry-run", action="store_true", help="Print work without writing v2 rows")
    args = parser.parse_args()

    project_id = _uuid(args.project_id)
    document_ids = {_uuid(value) for value in args.document_id}
    source_dirs = [Path(value) for value in args.source_dir]

    with session_scope() as session:
        stmt = select(Document).where(Document.status == "ready")
        if project_id:
            stmt = stmt.where(Document.project_id == project_id)
        if document_ids:
            stmt = stmt.where(Document.id.in_(document_ids))
        docs = session.execute(stmt.order_by(Document.created_at)).scalars().all()

    rebuilt = 0
    skipped = 0
    for doc in docs:
        source_path = _find_source_file(doc, source_dirs)
        with session_scope() as session:
            doc_for_session = session.get(Document, doc.id)
            if doc_for_session is None:
                skipped += 1
                continue
            if source_path:
                chunks = _load_chunks_from_source(doc_for_session, source_path)
                mode = f"source:{source_path}"
            elif not args.no_v1_fallback:
                chunks = _load_chunks_from_v1(session, doc_for_session)
                mode = "fallback:v1_chunks"
            else:
                print(f"skip {doc.id} {doc.filename}: source file missing")
                skipped += 1
                continue

            if not chunks:
                print(f"skip {doc.id} {doc.filename}: no chunks")
                skipped += 1
                continue

            print(f"rebuild {doc.id} {doc.filename}: {len(chunks)} chunks via {mode}")
            if not args.dry_run:
                insert_document_chunks_v2(
                    session,
                    document_id=doc_for_session.id,
                    project_id=doc_for_session.project_id,
                    chunks=chunks,
                    replace_existing=True,
                )
        rebuilt += 1

    print(f"rebuilt={rebuilt} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
