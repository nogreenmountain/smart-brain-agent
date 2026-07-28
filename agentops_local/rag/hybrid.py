from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any, Sequence

from agentops.rag import config

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SPACE_RE = re.compile(r"\s+")


def preprocess_fts_text(text: str) -> str:
    """
    Keep the original text for exact-ish tokens such as X1000/v2.3, and append
    spaced CJK characters so PostgreSQL's simple tokenizer can match Chinese.
    """
    normalized = _SPACE_RE.sub(" ", text).strip()
    cjk_chars = _CJK_RE.findall(normalized)
    if not cjk_chars:
        return normalized
    return f"{normalized} {' '.join(cjk_chars)}"


def reciprocal_rank_fusion(
    vector_hits: Sequence[Any],
    keyword_hits: Sequence[Any],
    *,
    limit: int = config.RAG_RRF_TOP_K,
    rrf_k: int = config.RAG_RRF_K,
) -> list[Any]:
    by_chunk: dict[Any, Any] = {}
    scores: dict[Any, float] = {}

    for rank, hit in enumerate(vector_hits, start=1):
        chunk_id = hit.chunk_id
        if chunk_id not in by_chunk:
            by_chunk[chunk_id] = replace(hit)
        candidate = by_chunk[chunk_id]
        candidate.vector_rank = rank
        candidate.vector_score = hit.score
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)

    for rank, hit in enumerate(keyword_hits, start=1):
        chunk_id = hit.chunk_id
        if chunk_id not in by_chunk:
            by_chunk[chunk_id] = replace(hit)
        candidate = by_chunk[chunk_id]
        candidate.keyword_rank = rank
        candidate.keyword_score = hit.keyword_score if hit.keyword_score is not None else hit.score
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)

    fused = []
    for chunk_id, hit in by_chunk.items():
        hit.rrf_score = scores[chunk_id]
        hit.score = scores[chunk_id]
        fused.append(hit)

    fused.sort(
        key=lambda h: (
            h.rrf_score if h.rrf_score is not None else h.score,
            h.vector_score if h.vector_score is not None else -1.0,
            h.keyword_score if h.keyword_score is not None else -1.0,
        ),
        reverse=True,
    )
    return fused[:limit]


def rerank_or_keep(query: str, candidates: Sequence[Any], reranker: Any | None) -> list[Any]:
    if not candidates:
        return []
    if reranker is None:
        return [replace(hit) for hit in candidates]

    out = [replace(hit) for hit in candidates]
    try:
        scores = reranker.rerank(query, [hit.content for hit in out])
    except Exception:
        logger.exception("RAG reranker failed; keeping RRF order")
        return out

    if len(scores) != len(out):
        logger.warning("RAG reranker score count mismatch; keeping RRF order")
        return out

    for hit, score in zip(out, scores):
        hit.rerank_score = float(score)
        hit.score = float(score)
    out.sort(key=lambda h: h.rerank_score if h.rerank_score is not None else -1.0, reverse=True)
    return out
