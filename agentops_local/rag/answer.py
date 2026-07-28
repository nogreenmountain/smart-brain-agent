"""
LLM answer synthesis for the RAG knowledge base.

Reads ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL from the environment.
If ANTHROPIC_AUTH_TOKEN is missing, falls back to a deterministic
template-based synthesis so the endpoint still works in dev / offline.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable, List

from agentops.rag.search import SearchHit

logger = logging.getLogger(__name__)


DEFAULT_MODEL = os.getenv("RAG_LLM_MODEL", "MiniMax-M3")
DEFAULT_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
MAX_TOKENS = int(os.getenv("RAG_LLM_MAX_TOKENS", "1024"))


SYSTEM_PROMPT = (
    "You are a precise Q&A assistant. Answer the user's question using ONLY "
    "the provided document excerpts. Cite the source number in brackets like "
    "[1], [2] inline. If the excerpts do not contain enough information, say "
    "so explicitly. Keep the answer concise and in the same language as the "
    "question."
)


def _format_context(hits: List[SearchHit]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        loc = []
        if h.source_page:
            loc.append(f"p.{h.source_page}")
        if h.source_line:
            loc.append(f"L{h.source_line}")
        loc_str = " ".join(loc) if loc else "—"
        blocks.append(f"[{i}] {h.document_name} ({loc_str}) — score={h.score:.3f}\n{h.content}")
    return "\n\n".join(blocks)


def _stub_synthesize(query: str, hits: List[SearchHit]) -> str:
    """Template-based synthesis used when ANTHROPIC_AUTH_TOKEN is unset."""
    if not hits:
        return "No relevant documents found in this project's knowledge base."
    cited = [
        f"[{i+1}] {h.document_name}" + (f" p.{h.source_page}" if h.source_page else "")
        for i, h in enumerate(hits)
    ]
    return (
        f"Retrieved {len(hits)} relevant chunks for: \"{query}\".\n"
        f"Sources: {'; '.join(cited)}\n\n"
        f"Top match (score={hits[0].score:.3f}): {hits[0].content[:400]}\n\n"
        f"(LLM synthesis disabled: ANTHROPIC_AUTH_TOKEN not set.)"
    )


def _llm_synthesize(query: str, hits: List[SearchHit]) -> str:
    """Call Anthropic-protocol LLM to synthesize an answer."""
    import anthropic

    client = anthropic.Anthropic(
        base_url=DEFAULT_BASE_URL,
        api_key=os.environ["ANTHROPIC_AUTH_TOKEN"],
    )
    context = _format_context(hits)
    user_msg = f"Question: {query}\n\nDocument excerpts:\n{context}"

    resp = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    # Extract text blocks
    parts = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip() or "(empty LLM response)"


def synthesize(query: str, hits: List[SearchHit]) -> tuple[str, str]:
    """
    Return (synthesis_text, source).
    source is "llm" or "stub" so callers can surface provenance.
    """
    if not os.getenv("ANTHROPIC_AUTH_TOKEN"):
        logger.info("RAG synthesize: ANTHROPIC_AUTH_TOKEN missing, using stub")
        return _stub_synthesize(query, hits), "stub"
    try:
        return _llm_synthesize(query, hits), "llm"
    except Exception as e:
        logger.exception("LLM synthesis failed, falling back to stub")
        text = _stub_synthesize(query, hits) + f"\n\n(LLM error: {type(e).__name__}: {str(e)[:120]})"
        return text, "stub"
