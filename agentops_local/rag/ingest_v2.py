from __future__ import annotations

import logging
import uuid
from typing import Iterable, Sequence

from sqlalchemy import delete
from sqlalchemy.orm import Session

from agentops.rag import config
from agentops.rag.chunker import Chunk
from agentops.rag.db import DocumentChunkV2
from agentops.rag.hybrid import preprocess_fts_text
from agentops.rag.model_clients import EmbeddingServiceClient

logger = logging.getLogger(__name__)


def insert_document_chunks_v2(
    session: Session,
    *,
    document_id: uuid.UUID,
    project_id: uuid.UUID,
    chunks: Sequence[Chunk],
    replace_existing: bool = True,
    embedding_model: str = config.RAG_V2_EMBEDDING_MODEL,
    embedding_version: str = config.RAG_V2_EMBEDDING_VERSION,
) -> int:
    if not chunks:
        return 0

    if replace_existing:
        session.execute(
            delete(DocumentChunkV2)
            .where(DocumentChunkV2.document_id == document_id)
            .where(DocumentChunkV2.embedding_version == embedding_version)
        )

    client = EmbeddingServiceClient()
    vectors = client.embed_documents([chunk.content for chunk in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError("embedding service returned the wrong number of vectors")

    for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
        fts_source = " ".join(
            part for part in [chunk.heading_path, chunk.content] if part
        )
        session.add(
            DocumentChunkV2(
                document_id=document_id,
                project_id=project_id,
                chunk_index=idx,
                content=chunk.content,
                token_count=chunk.token_count,
                source_page=chunk.source_page,
                source_line=chunk.source_line,
                heading_path=chunk.heading_path,
                fts_text=preprocess_fts_text(fts_source),
                embedding_model=embedding_model,
                embedding_version=embedding_version,
                embedding=vector,
            )
        )
    logger.info("inserted %d RAG v2 chunks for document %s", len(chunks), document_id)
    return len(chunks)


def chunks_from_existing_rows(rows: Iterable[object]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for row in rows:
        chunks.append(
            Chunk(
                content=row.content,
                token_count=row.token_count,
                source_page=row.source_page,
                source_line=row.source_line,
                heading_path=None,
            )
        )
    return chunks
