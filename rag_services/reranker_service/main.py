from __future__ import annotations

import os

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_NAME = os.getenv("RAG_RERANK_MODEL_NAME", "BAAI/bge-reranker-v2-m3")
BATCH_SIZE = int(os.getenv("RAG_RERANK_BATCH_SIZE", "2"))
MAX_LENGTH = int(os.getenv("RAG_RERANK_MAX_LENGTH", "1024"))
USE_FP16 = os.getenv("RAG_RERANK_USE_FP16", "false").lower() in {"1", "true", "yes", "on"}
DEVICE_ENV = os.getenv("RAG_MODEL_DEVICE", "auto")

app = FastAPI(title="RAG Reranker Service")
reranker = None
device = "cpu"


class RerankRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    passages: list[str] = Field(..., min_length=1, max_length=64)


class RerankResponse(BaseModel):
    model: str
    device: str
    scores: list[float]


def _pick_device() -> str:
    if DEVICE_ENV != "auto":
        return DEVICE_ENV
    return "cuda" if torch.cuda.is_available() else "cpu"


@app.on_event("startup")
def load_model() -> None:
    global reranker, device
    from FlagEmbedding import FlagReranker

    device = _pick_device()
    try:
        reranker = FlagReranker(MODEL_NAME, use_fp16=USE_FP16, device=device)
    except TypeError:
        reranker = FlagReranker(MODEL_NAME, use_fp16=USE_FP16)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok" if reranker is not None else "loading",
        "model": MODEL_NAME,
        "device": device,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


@app.post("/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest) -> RerankResponse:
    if reranker is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    pairs = [[req.query, passage] for passage in req.passages]
    try:
        try:
            raw_scores = reranker.compute_score(
                pairs,
                batch_size=BATCH_SIZE,
                max_length=MAX_LENGTH,
                normalize=True,
            )
        except TypeError:
            raw_scores = reranker.compute_score(pairs, batch_size=BATCH_SIZE)
        if not isinstance(raw_scores, list):
            raw_scores = [raw_scores]
        scores = [float(score) for score in raw_scores]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"rerank failed: {type(exc).__name__}") from exc
    return RerankResponse(model=MODEL_NAME, device=device, scores=scores)
