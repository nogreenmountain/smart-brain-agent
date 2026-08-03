from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

_LOCAL_ROOT = Path(__file__).parents[1]
_APP_ROOT = _LOCAL_ROOT.parent
_API_AGENTOPS = _APP_ROOT / "api" / "agentops"

try:
    import agentops.rag.hybrid  # noqa: F401
except Exception:
    for name in list(sys.modules):
        if name == "agentops" or name.startswith("agentops."):
            sys.modules.pop(name, None)
    agentops_pkg = types.ModuleType("agentops")
    agentops_pkg.__path__ = [str(_LOCAL_ROOT), str(_API_AGENTOPS)]  # type: ignore[attr-defined]
    sys.modules["agentops"] = agentops_pkg

from agentops.rag.chunker import chunk_markdown_structure
from agentops.rag.hybrid import (
    preprocess_fts_text,
    reciprocal_rank_fusion,
    rerank_or_keep,
)
from agentops.rag.model_clients import EmbeddingServiceClient
from agentops.rag.search import SearchHit


def _hit(label: str, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"chunk-{label}"),
        document_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"document-{label}"),
        document_name=f"{label}.md",
        content=f"content {label}",
        source_page=None,
        source_line=None,
        chunk_index=0,
        score=score,
    )


class RagV2RetrievalTests(unittest.TestCase):
    def test_embedding_client_batches_requests_to_service_limit(self) -> None:
        batch_sizes: list[int] = []

        class FakeResponse:
            def __init__(self, size: int):
                self.size = size

            def raise_for_status(self) -> None:
                return None

            def json(self):
                return {"vectors": [[float(index)] for index in range(self.size)]}

        class FakeHttpClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def post(self, url: str, json: dict):
                size = len(json["texts"])
                if size > 64:
                    raise AssertionError(f"embedding batch exceeds service limit: {size}")
                batch_sizes.append(size)
                return FakeResponse(size)

        client = EmbeddingServiceClient(expected_dim=1)
        with patch("agentops.rag.model_clients.httpx.Client", FakeHttpClient):
            vectors = client.embed_documents([f"chunk-{index}" for index in range(130)])

        self.assertEqual(batch_sizes, [64, 64, 2])
        self.assertEqual(len(vectors), 130)

    def test_preprocess_fts_text_keeps_codes_and_adds_cjk_tokens(self) -> None:
        text = "产品 X1000 v2.3 的退款条件是什么"

        processed = preprocess_fts_text(text)

        self.assertIn("X1000", processed)
        self.assertIn("v2.3", processed)
        self.assertIn("退 款 条 件", processed)

    def test_rrf_promotes_chunks_that_appear_in_both_rankings(self) -> None:
        vector_hits = [_hit("A", 0.91), _hit("B", 0.85), _hit("C", 0.80)]
        keyword_hits = [_hit("B", 3.2), _hit("D", 2.7), _hit("A", 1.1)]

        fused = reciprocal_rank_fusion(vector_hits, keyword_hits, limit=4)

        self.assertEqual(fused[0].document_name, "B.md")
        self.assertEqual(fused[0].vector_rank, 2)
        self.assertEqual(fused[0].keyword_rank, 1)
        self.assertEqual({hit.document_name for hit in fused}, {"A.md", "B.md", "C.md", "D.md"})

    def test_reranker_failure_keeps_rrf_order(self) -> None:
        class FailingReranker:
            def rerank(self, query: str, passages: list[str]) -> list[float]:
                raise RuntimeError("reranker down")

        candidates = [_hit("A", 0.5), _hit("B", 0.4)]

        reranked = rerank_or_keep("question", candidates, FailingReranker())

        self.assertEqual([hit.document_name for hit in reranked], ["A.md", "B.md"])
        self.assertTrue(all(hit.rerank_score is None for hit in reranked))

    def test_markdown_chunking_preserves_heading_path(self) -> None:
        chunks = chunk_markdown_structure(
            "# 产品售后政策\n\n## 一、退款条件\n\n### 1. 普通订单\n\n购买后7天内可申请退款。"
        )

        self.assertTrue(chunks)
        self.assertEqual(
            chunks[0].heading_path,
            "产品售后政策 > 一、退款条件 > 1. 普通订单",
        )
        self.assertIn("产品售后政策 > 一、退款条件 > 1. 普通订单", chunks[0].content)


def _load_knowledge_module():
    route_path = Path(
        os.environ.get(
            "KNOWLEDGE_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "knowledge.py",
        )
    )
    spec = importlib.util.spec_from_file_location("knowledge_route_under_test", route_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load route module from {route_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class KnowledgeApiCompatibilityTests(unittest.TestCase):
    def test_search_hit_schema_exposes_optional_v2_debug_fields(self) -> None:
        route = _load_knowledge_module()

        schema = route.SearchHitSchema(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            document_name="refund.md",
            content="refund policy",
            source_page=None,
            source_line=None,
            chunk_index=3,
            score=0.9,
            heading_path="产品售后政策 > 退款条件",
            vector_rank=2,
            keyword_rank=1,
            rerank_score=0.82,
            retrieval_mode="v2-hybrid-rerank",
        )

        self.assertEqual(schema.heading_path, "产品售后政策 > 退款条件")
        self.assertEqual(schema.vector_rank, 2)
        self.assertEqual(schema.keyword_rank, 1)
        self.assertEqual(schema.rerank_score, 0.82)
        self.assertEqual(schema.retrieval_mode, "v2-hybrid-rerank")


if __name__ == "__main__":
    unittest.main()
