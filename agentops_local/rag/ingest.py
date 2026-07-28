"""
Document ingestion pipeline.

Pipeline:
  1. Open file, identify format
  2. Create documents row (status=processing)
  3. Parse into text blocks (PDF: per-page, MD/TXT: single block)
  4. Chunk each block into ~512 token pieces
  5. Embed chunks (batched, ~32 per call)
  6. Bulk-insert document_chunks rows
  7. Update documents row (status=ready, chunk_count=N)
  8. On any error: set status=failed, error_message=<trace>

This module is the *library* form. API routes (P4) wrap ingest_file()
to expose it as an HTTP endpoint.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from agentops.common.orm import get_orm_session, session_scope
from agentops.rag import config
from agentops.rag.chunker import chunk_by_paragraphs, chunk_markdown_structure, chunk_text
from agentops.rag.db import Document, DocumentChunk
from agentops.rag.embed import embed_documents
from agentops.rag.ingest_v2 import insert_document_chunks_v2
from agentops.rag.parsers import ParsedBlock, parse
from agentops.project_memory.parsers import SUPPORTED_FORMATS

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32  # fastembed is fast; larger batches save round-trips


@dataclass
class IngestResult:
    document_id: uuid.UUID
    chunk_count: int
    status: str
    error: Optional[str] = None


def _chunk_blocks(blocks: List[ParsedBlock], fmt: str) -> List:
    """Convert parsed blocks into Chunk objects (from chunker module)."""
    from agentops.rag.chunker import Chunk
    out: List[Chunk] = []
    for block in blocks:
        if fmt == "pdf":
            out.extend(chunk_text(block.text, source_page=block.page))
        elif fmt == "md":
            out.extend(chunk_markdown_structure(block.text))
        else:
            out.extend(chunk_by_paragraphs(block.text, source_page=block.page))
    return out


def ingest_file(
    path: str | Path,
    *,
    project_id: uuid.UUID,
    display_name: str,
    created_by_user_id: Optional[uuid.UUID] = None,
) -> IngestResult:
    """
    Ingest a single file. Runs synchronously; API routes should call
    this from a background task in production.
    """
    p = Path(path)
    fmt = p.suffix.lower().lstrip(".")
    fmt = "html" if fmt == "htm" else fmt
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported format: {fmt}")
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(p)

    size_bytes = p.stat().st_size
    filename = display_name

    # 1. Insert documents row (status=processing)
    with session_scope() as session:
        doc = Document(
            project_id=project_id,
            filename=filename,
            display_name=display_name,
            format=fmt,
            size_bytes=size_bytes,
            status="processing",
            created_by_user_id=created_by_user_id,
        )
        session.add(doc)
        session.flush()
        document_id = doc.id

    try:
        # 2. Parse + chunk
        blocks = parse(p, fmt)
        chunks = _chunk_blocks(blocks, fmt)
        if not chunks:
            raise ValueError("no extractable text")

        # 3. Embed in batches
        all_vectors: List[List[float]] = []
        for i in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[i : i + EMBED_BATCH_SIZE]
            vecs = embed_documents([c.content for c in batch])
            all_vectors.extend(vecs)
            logger.info("embedded batch %d/%d", i // EMBED_BATCH_SIZE + 1,
                        (len(chunks) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE)

        # 4. Bulk insert chunks
        with session_scope() as session:
            for idx, (chunk, vec) in enumerate(zip(chunks, all_vectors)):
                row = DocumentChunk(
                    document_id=document_id,
                    project_id=project_id,
                    chunk_index=idx,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    source_page=chunk.source_page,
                    source_line=chunk.source_line,
                    embedding=vec,
                )
                session.add(row)
            # 5. Mark document ready
            doc = session.get(Document, document_id)
            doc.status = "ready"
            doc.chunk_count = len(chunks)

        if config.RAG_V2_EMBED_ON_UPLOAD:
            try:
                with session_scope() as session:
                    insert_document_chunks_v2(
                        session,
                        document_id=document_id,
                        project_id=project_id,
                        chunks=chunks,
                    )
            except Exception:
                logger.exception("RAG v2 chunk insert failed for %s", filename)
                if config.RAG_V2_INGEST_STRICT:
                    raise

        logger.info("ingested %s: %d chunks", filename, len(chunks))
        return IngestResult(document_id=document_id, chunk_count=len(chunks), status="ready")

    except Exception as e:
        logger.exception("ingest failed for %s", filename)
        with session_scope() as session:
            doc = session.get(Document, document_id)
            if doc is not None:
                doc.status = "failed"
                doc.error_message = f"{type(e).__name__}: {e}"[:500]
        return IngestResult(
            document_id=document_id, chunk_count=0, status="failed", error=str(e)
        )
