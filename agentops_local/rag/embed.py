"""
Embedding service for the RAG knowledge base.

Backed by fastembed (CPU-only ONNX runtime, no PyTorch).
Default model: BAAI/bge-small-en (384 dims, ~130MB).
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable, List

from fastembed import TextEmbedding

DEFAULT_MODEL = os.getenv("RAG_EMBED_MODEL_NAME", "BAAI/bge-small-en")
CACHE_DIR = os.getenv("FASTEMBED_CACHE_PATH", "/app/.cache/fastembed")
EMBED_DIM = 384


@lru_cache(maxsize=1)
def get_model() -> TextEmbedding:
    """Lazy singleton. Loading the ONNX model is ~14s; we do it once per process."""
    return TextEmbedding(model_name=DEFAULT_MODEL, cache_dir=CACHE_DIR)


def embed_documents(texts: Iterable[str]) -> List[List[float]]:
    """Embed a batch of document chunks. Passages are prefixed with the BGE instruction prompt."""
    passages = [f"passage: {t}" for t in texts]
    vectors = list(get_model().embed(passages))
    return [v.tolist() for v in vectors]


def embed_query(query: str) -> List[float]:
    """Embed a single search query. Queries use the BGE query prefix."""
    return embed_documents([f"query: {query}"])[0]