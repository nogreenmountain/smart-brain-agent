"""
Document parsers. Returns a list of (text, page_or_line) tuples:
  - PDF:  one entry per page (source_page set)
  - MD/TXT: one entry per paragraph (source_line set on first line)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from collections import Counter
import re

from agentops.project_memory.parsers import SUPPORTED_FORMATS as PROJECT_MATERIAL_FORMATS
from agentops.project_memory.parsers import extract_text


@dataclass
class ParsedBlock:
    text: str
    page: Optional[int] = None
    line: Optional[int] = None


def parse_pdf(path: str | Path) -> List[ParsedBlock]:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    raw_pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()
        if text:
            raw_pages.append((i, text))
    return [
        ParsedBlock(text=text, page=page)
        for page, text in _clean_pdf_page_noise(raw_pages)
        if text.strip()
    ]


def _clean_pdf_page_noise(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    if len(pages) < 2:
        return pages

    edge_lines: list[str] = []
    for _, text in pages:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        edge_lines.extend(lines[:2])
        edge_lines.extend(lines[-2:])

    counts = Counter(edge_lines)
    repeated = {
        line
        for line, count in counts.items()
        if count >= 2 and count / max(len(pages), 1) >= 0.5 and len(line) <= 120
    }
    page_number_re = re.compile(r"^(?:page\s*)?\d+\s*(?:/|of)?\s*\d*$", re.IGNORECASE)

    cleaned: list[tuple[int, str]] = []
    for page, text in pages:
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in repeated:
                continue
            if page_number_re.match(stripped):
                continue
            lines.append(stripped)
        cleaned.append((page, "\n".join(lines)))
    return cleaned


def parse_md(path: str | Path) -> List[ParsedBlock]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return []
    return [ParsedBlock(text=text, line=1)]


def parse_txt(path: str | Path) -> List[ParsedBlock]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return []
    return [ParsedBlock(text=text, line=1)]


def parse_project_material(path: str | Path) -> List[ParsedBlock]:
    extracted = extract_text(Path(path))
    if not extracted.text.strip():
        return []
    return [ParsedBlock(text=extracted.text, line=1)]


PARSERS = {
    "pdf": parse_pdf,
    "md": parse_md,
    "txt": parse_txt,
    **{
        fmt: parse_project_material
        for fmt in PROJECT_MATERIAL_FORMATS
        if fmt not in {"pdf", "md", "txt", "htm"}
    },
    "html": parse_project_material,
}


def parse(path: str | Path, fmt: str) -> List[ParsedBlock]:
    if fmt not in PARSERS:
        raise ValueError(f"unsupported format: {fmt}")
    return PARSERS[fmt](path)
