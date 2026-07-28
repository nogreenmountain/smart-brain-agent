"""
Text chunking for the RAG knowledge base.

Strategy:
  - Token-aware sliding window (cl100k_base via tiktoken).
  - chunk_size=512 tokens, overlap=64 tokens (12.5%).
  - For PDFs we split per-page first, then chunk each page independently.
  - For MD/TXT we split by paragraph first to keep semantic boundaries.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

import tiktoken

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
CHUNK_SIZE_V2 = int(os.getenv("RAG_V2_CHUNK_SIZE", "400"))
CHUNK_OVERLAP_V2 = int(os.getenv("RAG_V2_CHUNK_OVERLAP", "64"))
ENCODER = tiktoken.get_encoding("cl100k_base")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class Chunk:
    content: str
    token_count: int
    source_page: Optional[int] = None
    source_line: Optional[int] = None
    heading_path: Optional[str] = None


def _split_by_tokens(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Sliding window over tokens. Returns decoded text chunks."""
    tokens = ENCODER.encode(text)
    if len(tokens) <= chunk_size:
        return [text]
    step = chunk_size - overlap
    pieces = []
    for start in range(0, len(tokens), step):
        end = start + chunk_size
        piece_tokens = tokens[start:end]
        if not piece_tokens:
            break
        pieces.append(ENCODER.decode(piece_tokens))
        if end >= len(tokens):
            break
    return pieces


def chunk_text(
    text: str,
    source_page: Optional[int] = None,
    *,
    source_line: Optional[int] = None,
    heading_path: Optional[str] = None,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[Chunk]:
    """Chunk a flat text string."""
    if not text.strip():
        return []
    raw_chunks = _split_by_tokens(text, chunk_size, overlap)
    return [
        Chunk(
            content=c,
            token_count=len(ENCODER.encode(c)),
            source_page=source_page,
            source_line=source_line,
            heading_path=heading_path,
        )
        for c in raw_chunks
    ]


def chunk_by_paragraphs(
    text: str,
    source_page: Optional[int] = None,
    *,
    heading_path: Optional[str] = None,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[Chunk]:
    """Split on blank lines first (paragraphs), then chunk each paragraph."""
    if not text.strip():
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    out: List[Chunk] = []
    line_cursor = 1
    for para in paragraphs:
        chunks = chunk_text(
            para,
            source_page=source_page,
            source_line=line_cursor,
            heading_path=heading_path,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        for c in chunks:
            c.source_line = line_cursor
        out.extend(chunks)
        line_cursor += para.count("\n") + 1
    return out


def chunk_markdown_structure(text: str) -> List[Chunk]:
    """Chunk Markdown by heading sections while preserving heading_path."""
    if not text.strip():
        return []

    headings: list[tuple[int, str]] = []
    section_lines: list[str] = []
    section_start_line = 1
    out: list[Chunk] = []

    def heading_path() -> str | None:
        if not headings:
            return None
        return " > ".join(title for _, title in headings)

    def flush() -> None:
        nonlocal section_lines, section_start_line
        meaningful_lines = [
            line for line in section_lines if line.strip() and not _HEADING_RE.match(line)
        ]
        if not meaningful_lines:
            section_lines = []
            return
        body = "\n".join(section_lines).strip()
        if not body:
            section_lines = []
            return
        prefixed = body
        path = heading_path()
        if path and not body.startswith(path):
            prefixed = f"{path}\n\n{body}"
        chunks = chunk_by_paragraphs(
            prefixed,
            source_page=None,
            heading_path=path,
            chunk_size=CHUNK_SIZE_V2,
            overlap=CHUNK_OVERLAP_V2,
        )
        for chunk in chunks:
            chunk.source_line = section_start_line
        out.extend(chunks)
        section_lines = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        match = _HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            headings = [(lvl, t) for lvl, t in headings if lvl < level]
            headings.append((level, title))
            section_start_line = line_no
            section_lines = [line]
            continue
        if not section_lines:
            section_start_line = line_no
        section_lines.append(line)
    flush()

    if out:
        return out
    return chunk_by_paragraphs(
        text,
        chunk_size=CHUNK_SIZE_V2,
        overlap=CHUNK_OVERLAP_V2,
    )
