from __future__ import annotations

import os
from typing import Literal

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_NAME = os.getenv("RAG_EMBED_MODEL_NAME", "BAAI/bge-m3")
BATCH_SIZE = int(os.getenv("RAG_EMBED_BATCH_SIZE", "4"))
MAX_LENGTH = int(os.getenv("RAG_EMBED_MAX_LENGTH", "8192"))
USE_FP16 = os.getenv("RAG_EMBED_USE_FP16", "false").lower() in {"1", "true", "yes", "on"}
DEVICE_ENV = os.getenv("RAG_MODEL_DEVICE", "auto")

app = FastAPI(title="RAG Embedding Service")
model = None
device = "cpu"


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=64)
    input_type: Literal["query", "passage"] = "passage"


class EmbedResponse(BaseModel):
    model: str
    device: str
    dim: int
    vectors: list[list[float]]


def _pick_device() -> str:
    if DEVICE_ENV != "auto":
        return DEVICE_ENV
    return "cuda" if torch.cuda.is_available() else "cpu"


@app.on_event("startup")
def load_model() -> None:
    global model, device
    from FlagEmbedding import BGEM3FlagModel

    device = _pick_device()
    model = BGEM3FlagModel(MODEL_NAME, use_fp16=USE_FP16, device=device)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok" if model is not None else "loading",
        "model": MODEL_NAME,
        "device": device,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    if model is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    try:
        result = model.encode(
            req.texts,
            batch_size=BATCH_SIZE,
            max_length=MAX_LENGTH,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        vectors = result["dense_vecs"] if isinstance(result, dict) else result
        vectors_list = [vec.tolist() if hasattr(vec, "tolist") else list(vec) for vec in vectors]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"embedding failed: {type(exc).__name__}") from exc

    dim = len(vectors_list[0]) if vectors_list else 0
    return EmbedResponse(model=MODEL_NAME, device=device, dim=dim, vectors=vectors_list)
