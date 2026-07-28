from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentops.common.orm import session_scope
from agentops.rag.search import search


@dataclass
class EvalQuestion:
    id: str
    project_id: uuid.UUID
    question: str
    answerable: bool
    relevant_documents: set[str]
    relevant_chunks: set[str]


def _load_questions(path: Path) -> list[EvalQuestion]:
    questions: list[EvalQuestion] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        questions.append(
            EvalQuestion(
                id=str(raw.get("id") or f"line-{line_no}"),
                project_id=uuid.UUID(raw["project_id"]),
                question=raw["question"],
                answerable=bool(raw.get("answerable", True)),
                relevant_documents=set(raw.get("relevant_documents") or []),
                relevant_chunks={str(value) for value in raw.get("relevant_chunks") or []},
            )
        )
    return questions


def _is_relevant(hit: Any, q: EvalQuestion) -> bool:
    if q.relevant_chunks and str(hit.chunk_id) in q.relevant_chunks:
        return True
    return bool(q.relevant_documents and hit.document_name in q.relevant_documents)


def _dcg(gains: list[int]) -> float:
    return sum(gain / math.log2(idx + 2) for idx, gain in enumerate(gains))


def _metrics_for_hits(hits: list[Any], q: EvalQuestion) -> dict[str, float]:
    relevant_count = max(len(q.relevant_chunks or q.relevant_documents), 1)
    seen_units: set[str] = set()
    gains: list[int] = []
    for hit in hits[:10]:
        if q.relevant_chunks:
            unit = str(hit.chunk_id)
        else:
            unit = hit.document_name
        if unit in seen_units:
            gains.append(0)
            continue
        seen_units.add(unit)
        gains.append(1 if _is_relevant(hit, q) else 0)

    def recall_at(k: int) -> float:
        return min(sum(gains[:k]) / relevant_count, 1.0)

    first_rank = next((idx + 1 for idx, gain in enumerate(gains) if gain), None)
    ideal_gains = [1] * min(relevant_count, 5)
    ndcg5 = (_dcg(gains[:5]) / _dcg(ideal_gains)) if ideal_gains else 0.0
    return {
        "recall_at_5": recall_at(5),
        "recall_at_10": recall_at(10),
        "mrr_at_10": (1.0 / first_rank) if first_rank else 0.0,
        "ndcg_at_5": ndcg5,
    }


def _aggregate(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    keys = rows[0].keys()
    return {key: statistics.fmean(row[key] for row in rows) for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval versions")
    parser.add_argument("--questions", required=True, help="JSONL question set")
    parser.add_argument(
        "--version",
        action="append",
        default=[],
        help="Retrieval version to test; repeatable",
    )
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--output", help="Optional JSON output file")
    args = parser.parse_args()

    versions = args.version or ["v1", "v2-vector", "v2-hybrid", "v2-hybrid-rerank"]
    questions = _load_questions(Path(args.questions))
    results: dict[str, Any] = {}

    for version in versions:
        per_question = []
        metric_rows = []
        latencies = []
        for q in questions:
            start = time.perf_counter()
            with session_scope() as session:
                hits = search(
                    session,
                    query=q.question,
                    project_id=q.project_id,
                    k=args.k,
                    retrieval_version=version,
                )
            latency_ms = (time.perf_counter() - start) * 1000.0
            latencies.append(latency_ms)
            metrics = _metrics_for_hits(hits, q) if q.answerable else {}
            if metrics:
                metric_rows.append(metrics)
            per_question.append(
                {
                    "id": q.id,
                    "answerable": q.answerable,
                    "latency_ms": round(latency_ms, 2),
                    "hits": [
                        {
                            "chunk_id": str(hit.chunk_id),
                            "document_name": hit.document_name,
                            "score": hit.score,
                            "retrieval_mode": hit.retrieval_mode,
                            "relevant": _is_relevant(hit, q),
                        }
                        for hit in hits
                    ],
                    "metrics": metrics,
                }
            )

        aggregate = _aggregate(metric_rows)
        aggregate["p50_latency_ms"] = statistics.median(latencies) if latencies else 0.0
        aggregate["p95_latency_ms"] = (
            statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies, default=0.0)
        )
        results[version] = {"aggregate": aggregate, "questions": per_question}

    output = json.dumps(results, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
