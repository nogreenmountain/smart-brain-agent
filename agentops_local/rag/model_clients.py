from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

import httpx

from agentops.rag import config

EMBEDDING_BATCH_SIZE = 64


class ModelServiceError(RuntimeError):
    pass


@dataclass
class EmbeddingServiceClient:
    base_url: str = config.RAG_EMBEDDING_SERVICE_URL
    timeout_seconds: float = 120.0
    expected_dim: int = config.RAG_V2_EMBEDDING_DIM

    def embed(self, texts: Iterable[str], *, input_type: str) -> List[List[float]]:
        text_list = list(texts)
        if not text_list:
            return []
        vectors: List[List[float]] = []
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                for start in range(0, len(text_list), EMBEDDING_BATCH_SIZE):
                    payload = {
                        "texts": text_list[start:start + EMBEDDING_BATCH_SIZE],
                        "input_type": input_type,
                    }
                    resp = client.post(f"{self.base_url}/embed", json=payload)
                    resp.raise_for_status()

                    body = resp.json()
                    batch_vectors = body.get("vectors")
                    if not isinstance(batch_vectors, list):
                        raise ModelServiceError("embedding service response missing vectors")
                    for vec in batch_vectors:
                        if not isinstance(vec, list) or len(vec) != self.expected_dim:
                            raise ModelServiceError(
                                f"embedding dimension mismatch: expected {self.expected_dim}"
                            )
                    vectors.extend(batch_vectors)
        except Exception as exc:
            if isinstance(exc, ModelServiceError):
                raise
            raise ModelServiceError(f"embedding service unavailable: {exc}") from exc
        return vectors

    def embed_documents(self, texts: Iterable[str]) -> List[List[float]]:
        return self.embed(texts, input_type="passage")

    def embed_query(self, query: str) -> List[float]:
        vectors = self.embed([query], input_type="query")
        if not vectors:
            raise ModelServiceError("embedding service returned no query vector")
        return vectors[0]


@dataclass
class RerankerClient:
    base_url: str = config.RAG_RERANKER_SERVICE_URL
    timeout_seconds: float = 120.0

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(
                    f"{self.base_url}/rerank",
                    json={"query": query, "passages": passages},
                )
                resp.raise_for_status()
        except Exception as exc:
            raise ModelServiceError(f"reranker service unavailable: {exc}") from exc

        body = resp.json()
        scores = body.get("scores")
        if not isinstance(scores, list) or len(scores) != len(passages):
            raise ModelServiceError("reranker response score count mismatch")
        return [float(score) for score in scores]
