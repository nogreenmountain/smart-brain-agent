"""Search for the RAG knowledge base.

v1 is the original 384-dim pgvector search.
v2 adds BGE-M3 embeddings, PostgreSQL FTS, RRF fusion, and optional reranking.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import List

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from agentops.rag import config
from agentops.rag.db import Document, DocumentChunk, DocumentChunkV2
from agentops.rag.embed import embed_query
from agentops.rag.hybrid import (
    preprocess_fts_text,
    reciprocal_rank_fusion,
    rerank_or_keep,
)
from agentops.rag.model_clients import EmbeddingServiceClient, ModelServiceError, RerankerClient

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    content: str
    source_page: int | None
    source_line: int | None
    chunk_index: int
    score: float
    heading_path: str | None = None
    retrieval_mode: str | None = None
    vector_score: float | None = None
    keyword_score: float | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    embedding_model: str | None = None
    embedding_version: str | None = None


def search(
    orm: Session,
    *,
    query: str,
    project_id: uuid.UUID,
    k: int = 5,
    retrieval_version: str | None = None,
) -> List[SearchHit]:
    """Return the top-k chunks restricted to the given project."""
    if not query.strip():
        return []
    version = retrieval_version or config.RAG_RETRIEVAL_VERSION
    if version == "v1":
        return _search_v1(orm, query=query, project_id=project_id, k=k)

    try:
        if version == "v2-vector":
            return _search_v2_vector(orm, query=query, project_id=project_id, k=k)
        if version == "v2-hybrid":
            return _search_v2_hybrid(
                orm,
                query=query,
                project_id=project_id,
                k=k,
                use_reranker=False,
            )
        if version == "v2-hybrid-rerank":
            return _search_v2_hybrid(
                orm,
                query=query,
                project_id=project_id,
                k=k,
                use_reranker=True,
            )
    except ModelServiceError:
        logger.exception("RAG v2 model service failed")
        if config.RAG_V2_FALLBACK_TO_V1:
            hits = _search_v1(orm, query=query, project_id=project_id, k=k)
            for hit in hits:
                hit.retrieval_mode = "v1-fallback"
            return hits
        raise

    logger.warning("Unknown RAG_RETRIEVAL_VERSION=%s; falling back to v1", version)
    return _search_v1(orm, query=query, project_id=project_id, k=k)


def _search_v1(
    orm: Session,
    *,
    query: str,
    project_id: uuid.UUID,
    k: int,
) -> List[SearchHit]:
    qvec = embed_query(query)
    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.content,
            DocumentChunk.source_page,
            DocumentChunk.source_line,
            DocumentChunk.embedding.cosine_distance(qvec).label("distance"),
            Document.filename,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.project_id == project_id)
        .where(Document.status == "ready")
        .order_by("distance")
        .limit(k)
    )
    rows = orm.execute(stmt).all()
    hits = []
    for idx, r in enumerate(rows, start=1):
        score = float(1.0 - r.distance)
        hits.append(SearchHit(
            chunk_id=r.id,
            document_id=r.document_id,
            document_name=r.filename,
            content=r.content,
            source_page=r.source_page,
            source_line=r.source_line,
            chunk_index=r.chunk_index,
            score=score,
            retrieval_mode="v1",
            vector_score=score,
            vector_rank=idx,
        ))
    return hits


def _search_v2_vector(
    orm: Session,
    *,
    query: str,
    project_id: uuid.UUID,
    k: int,
    limit_override: int | None = None,
) -> List[SearchHit]:
    qvec = EmbeddingServiceClient().embed_query(query)
    limit = limit_override or k
    stmt = (
        select(
            DocumentChunkV2.id,
            DocumentChunkV2.document_id,
            DocumentChunkV2.chunk_index,
            DocumentChunkV2.content,
            DocumentChunkV2.source_page,
            DocumentChunkV2.source_line,
            DocumentChunkV2.heading_path,
            DocumentChunkV2.embedding_model,
            DocumentChunkV2.embedding_version,
            DocumentChunkV2.embedding.cosine_distance(qvec).label("distance"),
            Document.filename,
        )
        .join(Document, Document.id == DocumentChunkV2.document_id)
        .where(DocumentChunkV2.project_id == project_id)
        .where(Document.status == "ready")
        .where(DocumentChunkV2.embedding_model == config.RAG_V2_EMBEDDING_MODEL)
        .where(DocumentChunkV2.embedding_version == config.RAG_V2_EMBEDDING_VERSION)
        .order_by("distance")
        .limit(limit)
    )
    rows = orm.execute(stmt).all()
    hits = []
    for idx, r in enumerate(rows, start=1):
        score = float(1.0 - r.distance)
        hits.append(SearchHit(
            chunk_id=r.id,
            document_id=r.document_id,
            document_name=r.filename,
            content=r.content,
            source_page=r.source_page,
            source_line=r.source_line,
            chunk_index=r.chunk_index,
            score=score,
            heading_path=r.heading_path,
            retrieval_mode="v2-vector",
            vector_score=score,
            vector_rank=idx,
            embedding_model=r.embedding_model,
            embedding_version=r.embedding_version,
        ))
    return hits


def _search_v2_keyword(
    orm: Session,
    *,
    query: str,
    project_id: uuid.UUID,
    limit: int,
) -> List[SearchHit]:
    fts_query = preprocess_fts_text(query)
    stmt = text(
        """
        SELECT
            c.id,
            c.document_id,
            c.chunk_index,
            c.content,
            c.source_page,
            c.source_line,
            c.heading_path,
            c.embedding_model,
            c.embedding_version,
            d.filename,
            ts_rank(c.content_tsv, plainto_tsquery('simple', :fts_query)) AS keyword_score
        FROM public.document_chunks_v2 c
        JOIN public.documents d ON d.id = c.document_id
        WHERE c.project_id = :project_id
          AND d.status = 'ready'
          AND c.embedding_model = :embedding_model
          AND c.embedding_version = :embedding_version
          AND c.content_tsv @@ plainto_tsquery('simple', :fts_query)
        ORDER BY keyword_score DESC, c.created_at ASC
        LIMIT :limit
        """
    )
    rows = orm.execute(
        stmt,
        {
            "project_id": str(project_id),
            "fts_query": fts_query,
            "embedding_model": config.RAG_V2_EMBEDDING_MODEL,
            "embedding_version": config.RAG_V2_EMBEDDING_VERSION,
            "limit": limit,
        },
    ).mappings().all()
    hits = []
    for idx, r in enumerate(rows, start=1):
        score = float(r["keyword_score"] or 0.0)
        hits.append(SearchHit(
            chunk_id=r["id"],
            document_id=r["document_id"],
            document_name=r["filename"],
            content=r["content"],
            source_page=r["source_page"],
            source_line=r["source_line"],
            chunk_index=r["chunk_index"],
            score=score,
            heading_path=r["heading_path"],
            retrieval_mode="v2-keyword",
            keyword_score=score,
            keyword_rank=idx,
            embedding_model=r["embedding_model"],
            embedding_version=r["embedding_version"],
        ))
    return hits


def _search_v2_hybrid(
    orm: Session,
    *,
    query: str,
    project_id: uuid.UUID,
    k: int,
    use_reranker: bool,
) -> List[SearchHit]:
    vector_hits = _search_v2_vector(
        orm,
        query=query,
        project_id=project_id,
        k=k,
        limit_override=max(config.RAG_VECTOR_TOP_K, k),
    )
    keyword_hits = _search_v2_keyword(
        orm,
        query=query,
        project_id=project_id,
        limit=max(config.RAG_KEYWORD_TOP_K, k),
    )
    fused = reciprocal_rank_fusion(
        vector_hits,
        keyword_hits,
        limit=max(config.RAG_RRF_TOP_K, k),
    )
    for hit in fused:
        hit.retrieval_mode = "v2-hybrid"

    if not use_reranker:
        return fused[:k]

    rerank_input = fused[: max(config.RAG_RRF_TOP_K, config.RAG_RERANK_TOP_K, k)]
    reranked = rerank_or_keep(query, rerank_input, RerankerClient())
    for hit in reranked:
        hit.retrieval_mode = "v2-hybrid-rerank"
    return reranked[:k]
