from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal


Disposition = Literal["auto_apply", "pending_review", "discard"]

MEMORY_KINDS = {
    "workflow_template",
    "failure_case",
    "success_case",
    "strategy",
    "retrospective",
    "decision_record",
    "checklist",
    "background",
    "timeline_event",
    "reference",
}

PAGE_TYPE_DEFAULT_MEMORY_KIND = {
    "procedure": "workflow_template",
    "troubleshooting": "failure_case",
    "lesson": "retrospective",
    "decision": "decision_record",
    "policy": "strategy",
    "architecture": "background",
    "requirement": "reference",
}

AUTO_USEFULNESS_THRESHOLD = 0.88
AUTO_CONFIDENCE_THRESHOLD = 0.88
MIN_USEFULNESS_THRESHOLD = 0.65
MIN_CONFIDENCE_THRESHOLD = 0.65

GOVERNED_PAGE_TYPES = {
    "architecture",
    "decision",
    "policy",
    "requirement",
}

SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:sk|pk)-(?:ant-)?[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"\b(?:password|passwd|secret|api[_-]?key|auth[_-]?token)\s*[:=]", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?:身份证|银行卡|手机号|家庭住址)\s*[:：]", re.IGNORECASE),
)

PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore (?:all |the )?(?:previous|prior) instructions", re.IGNORECASE),
    re.compile(r"忽略(?:之前|以上|前面)的?(?:所有)?指令", re.IGNORECASE),
    re.compile(r"(?:reveal|print|show).{0,20}(?:system prompt|developer message)", re.IGNORECASE),
)

SOURCE_REDACTION_PATTERNS = (
    re.compile(
        r"\b(?:password|passwd|secret|api[_-]?key|auth[_-]?token|access[_-]?token|refresh[_-]?token)\b"
        r"\s*[:=]\s*[^\s,，;；]+",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:sk|pk)-(?:ant-)?[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.IGNORECASE | re.DOTALL,
    ),
)


def _clamp_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _unique_text(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def build_page_key(page_type: str, title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    safe_type = re.sub(r"[^a-z0-9_-]+", "-", page_type.lower()).strip("-") or "note"
    return f"{safe_type}-{digest}"


@dataclass
class KnowledgeCandidate:
    title: str
    page_type: str
    summary: str
    markdown_content: str
    usefulness: float
    confidence: float
    source_ids: list[str]
    link_titles: list[str]
    contradiction: bool
    sensitive: bool
    ephemeral: bool
    memory_kind: str = ""
    tags: list[str] = field(default_factory=list)
    valid_from: str | None = None
    valid_until: str | None = None
    page_key: str = field(init=False)

    def __post_init__(self) -> None:
        self.title = _clean_text(self.title)
        self.page_type = _clean_text(self.page_type).lower() or "note"
        self.summary = _clean_text(self.summary)
        self.markdown_content = _clean_text(self.markdown_content)
        self.usefulness = _clamp_score(self.usefulness)
        self.confidence = _clamp_score(self.confidence)
        self.source_ids = _unique_text(self.source_ids)
        self.link_titles = _unique_text(self.link_titles)
        requested_kind = _clean_text(self.memory_kind).lower()
        self.memory_kind = (
            requested_kind
            if requested_kind in MEMORY_KINDS
            else PAGE_TYPE_DEFAULT_MEMORY_KIND.get(self.page_type, "reference")
        )
        self.tags = _unique_text(self.tags)[:20]
        self.valid_from = _clean_text(self.valid_from) or None
        self.valid_until = _clean_text(self.valid_until) or None
        self.contradiction = bool(self.contradiction)
        self.sensitive = bool(self.sensitive)
        self.ephemeral = bool(self.ephemeral)
        self.page_key = build_page_key(self.page_type, self.title)


@dataclass(frozen=True)
class CandidateDecision:
    disposition: Disposition
    reason_code: str


def contains_sensitive_content(text: str) -> bool:
    return any(pattern.search(text) for pattern in (*SENSITIVE_PATTERNS, *SOURCE_REDACTION_PATTERNS))


def contains_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS)


def sanitize_untrusted_text(text: str) -> str:
    sanitized = str(text or "")
    for pattern in SOURCE_REDACTION_PATTERNS:
        sanitized = pattern.sub("[敏感信息已移除]", sanitized)

    lines: list[str] = []
    for line in sanitized.splitlines():
        if contains_prompt_injection(line):
            lines.append("[提示注入内容已移除]")
        else:
            lines.append(line)
    return "\n".join(lines)


def classify_candidate(candidate: KnowledgeCandidate) -> CandidateDecision:
    combined_text = "\n".join(
        [candidate.title, candidate.summary, candidate.markdown_content]
    )
    if (
        candidate.sensitive
        or contains_sensitive_content(combined_text)
        or contains_prompt_injection(combined_text)
    ):
        return CandidateDecision("discard", "sensitive_content")
    if not candidate.source_ids:
        return CandidateDecision("discard", "missing_source")
    if candidate.ephemeral:
        return CandidateDecision("discard", "ephemeral")
    if candidate.usefulness < MIN_USEFULNESS_THRESHOLD:
        return CandidateDecision("discard", "low_usefulness")
    if candidate.confidence < MIN_CONFIDENCE_THRESHOLD:
        return CandidateDecision("discard", "low_confidence")
    if candidate.contradiction:
        return CandidateDecision("pending_review", "contradiction")
    if candidate.page_type in GOVERNED_PAGE_TYPES:
        return CandidateDecision("pending_review", "governed_page_type")
    if (
        candidate.usefulness < AUTO_USEFULNESS_THRESHOLD
        or candidate.confidence < AUTO_CONFIDENCE_THRESHOLD
    ):
        return CandidateDecision("pending_review", "medium_confidence")
    return CandidateDecision("auto_apply", "high_value_low_risk")


def _strip_json_fence(raw: str) -> str:
    value = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else value


def parse_candidate_response(raw: str) -> list[KnowledgeCandidate]:
    payload = json.loads(_strip_json_fence(raw))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("candidate response must contain an items array")

    candidates: list[KnowledgeCandidate] = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            continue
        candidate = KnowledgeCandidate(
            title=item.get("title", ""),
            page_type=item.get("page_type", "note"),
            summary=item.get("summary", ""),
            markdown_content=item.get("markdown_content", ""),
            usefulness=item.get("usefulness", 0),
            confidence=item.get("confidence", 0),
            source_ids=item.get("source_ids", []),
            link_titles=item.get("link_titles", []),
            contradiction=item.get("contradiction", False),
            sensitive=item.get("sensitive", False),
            ephemeral=item.get("ephemeral", False),
            memory_kind=item.get("memory_kind", ""),
            tags=item.get("tags", []),
            valid_from=item.get("valid_from"),
            valid_until=item.get("valid_until"),
        )
        if candidate.title and candidate.markdown_content:
            candidates.append(candidate)
    return candidates
