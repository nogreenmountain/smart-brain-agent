from __future__ import annotations

import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


RAG_RETRIEVAL_VERSION = os.getenv("RAG_RETRIEVAL_VERSION", "v1")

RAG_V2_EMBEDDING_MODEL = os.getenv("RAG_V2_EMBEDDING_MODEL", "BAAI/bge-m3")
RAG_V2_EMBEDDING_VERSION = os.getenv("RAG_V2_EMBEDDING_VERSION", "2026-07-21-bge-m3")
RAG_V2_EMBEDDING_DIM = int(os.getenv("RAG_V2_EMBEDDING_DIM", "1024"))

RAG_EMBEDDING_SERVICE_URL = os.getenv(
    "RAG_EMBEDDING_SERVICE_URL",
    "http://rag-embedding-service:8080",
).rstrip("/")
RAG_RERANKER_SERVICE_URL = os.getenv(
    "RAG_RERANKER_SERVICE_URL",
    "http://rag-reranker-service:8080",
).rstrip("/")

RAG_VECTOR_TOP_K = int(os.getenv("RAG_VECTOR_TOP_K", "20"))
RAG_KEYWORD_TOP_K = int(os.getenv("RAG_KEYWORD_TOP_K", "20"))
RAG_RRF_TOP_K = int(os.getenv("RAG_RRF_TOP_K", "30"))
RAG_RRF_K = int(os.getenv("RAG_RRF_K", "60"))
RAG_RERANK_TOP_K = int(os.getenv("RAG_RERANK_TOP_K", "8"))

RAG_V2_EMBED_ON_UPLOAD = env_bool("RAG_V2_EMBED_ON_UPLOAD", False)
RAG_V2_INGEST_STRICT = env_bool("RAG_V2_INGEST_STRICT", False)
RAG_V2_FALLBACK_TO_V1 = env_bool("RAG_V2_FALLBACK_TO_V1", True)
