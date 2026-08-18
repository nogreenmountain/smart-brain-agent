from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


TEXT_CODE_FORMATS = {
    "bat",
    "c",
    "conf",
    "cpp",
    "cs",
    "css",
    "csv",
    "go",
    "h",
    "hpp",
    "java",
    "js",
    "json",
    "jsx",
    "log",
    "ps1",
    "py",
    "rs",
    "scss",
    "sh",
    "sql",
    "ts",
    "tsx",
    "vue",
    "xml",
    "yaml",
    "yml",
}
SUPPORTED_FORMATS = {"pdf", "md", "txt", "html", "htm", "docx", "pptx", "xlsx", *TEXT_CODE_FORMATS}


@dataclass(frozen=True)
class ExtractedText:
    filename: str
    format: str
    text: str


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style"}:
            self._skip_depth += 1
        if tag.lower() in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = data.strip()
        if value:
            self.parts.append(value)


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank:
                compact.append("")
            previous_blank = True
            continue
        compact.append(line)
        previous_blank = False
    return "\n".join(compact).strip()


def _extract_html(path: Path) -> str:
    parser = _TextHTMLParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return _normalize_text("\n".join(parser.parts))


def _extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    texts = [
        node.text or ""
        for node in root.iter()
        if node.tag.endswith("}t") and node.text
    ]
    return _normalize_text("\n".join(texts))


def _extract_pptx(path: Path) -> str:
    texts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            slide_text = [
                node.text or ""
                for node in root.iter()
                if node.tag.endswith("}t") and node.text
            ]
            if slide_text:
                texts.append("\n".join(slide_text))
    return _normalize_text("\n\n".join(texts))


def _extract_xlsx(path: Path) -> str:
    shared_strings: list[str] = []
    sheets: list[str] = []
    with zipfile.ZipFile(path) as archive:
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.iter():
                if not item.tag.endswith("}si"):
                    continue
                shared_strings.append(
                    "".join(
                        node.text or ""
                        for node in item.iter()
                        if node.tag.endswith("}t")
                    )
                )

        sheet_names = sorted(
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        for name in sheet_names:
            root = ElementTree.fromstring(archive.read(name))
            rows: list[str] = []
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                values: list[str] = []
                for cell in row:
                    if not cell.tag.endswith("}c"):
                        continue
                    cell_type = cell.attrib.get("t", "")
                    value_node = next(
                        (node for node in cell if node.tag.endswith("}v")),
                        None,
                    )
                    value = ""
                    if cell_type == "s" and value_node is not None and value_node.text:
                        try:
                            value = shared_strings[int(value_node.text)]
                        except (IndexError, ValueError):
                            value = value_node.text
                    elif cell_type == "inlineStr":
                        value = "".join(
                            node.text or ""
                            for node in cell.iter()
                            if node.tag.endswith("}t")
                        )
                    elif cell_type == "b" and value_node is not None:
                        value = "TRUE" if value_node.text == "1" else "FALSE"
                    elif value_node is not None and value_node.text:
                        value = value_node.text
                    else:
                        formula_node = next(
                            (node for node in cell if node.tag.endswith("}f")),
                            None,
                        )
                        if formula_node is not None and formula_node.text:
                            value = formula_node.text
                    if value:
                        values.append(value)
                if values:
                    rows.append("\t".join(values))
            if rows:
                sheets.append("\n".join(rows))
    return _normalize_text("\n\n".join(sheets))


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return _normalize_text("\n\n".join(pages))


def extract_text(path: Path) -> ExtractedText:
    suffix = path.suffix.lower().lstrip(".")
    fmt = "html" if suffix == "htm" else suffix
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported project memory format: {suffix}")
    if fmt == "pdf":
        text = _extract_pdf(path)
    elif fmt == "html":
        text = _extract_html(path)
    elif fmt == "docx":
        text = _extract_docx(path)
    elif fmt == "pptx":
        text = _extract_pptx(path)
    elif fmt == "xlsx":
        text = _extract_xlsx(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = _normalize_text(text)
    if not text:
        raise ValueError(f"no extractable text: {path.name}")
    return ExtractedText(filename=path.name, format=fmt, text=text)
