from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


PAPER_IDENTITY_SCHEMA_VERSION = "paper_identity.v4.2"

ARXIV_RE = re.compile(r"(?i)(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5}(?:v\d+)?)")
DOI_RE = re.compile(r"(?i)\b(10\.\d{4,9}/[^\s<>'\"]+)")
YEAR_RE = re.compile(r"(?<!\d)((?:19|20|21)\d{2})(?!\d)")


@dataclass
class DuplicateWarning:
    warning_type: str
    source_id: str
    other_source_id: str
    reason: str
    shared_value: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperIdentity:
    source_id: str
    source_type: str
    title: str
    sha256: str
    raw_path: str
    normalized_path: str
    imported_at: str
    paper_id: str = ""
    title_source: str = "catalog"
    title_confidence: str = "medium"
    authors: list[str] = field(default_factory=list)
    authors_source: str = "unknown"
    year: int | None = None
    year_source: str = "unknown"
    venue_or_status: str = ""
    venue_or_status_source: str = "unknown"
    doi: str = ""
    doi_source: str = "unknown"
    arxiv_id: str = ""
    arxiv_id_source: str = "unknown"
    metadata_path: str = ""
    blocks_path: str = ""
    chunks_path: str = ""
    page_id: str = ""
    page_path: str = ""
    applied_run_id: str = ""
    applied_status: str = ""
    parser_backend: str = ""
    parser_backend_fallback_from: str = ""
    parser_quality: dict[str, Any] = field(default_factory=dict)
    identity_status: str = "partial"
    warnings: list[str] = field(default_factory=list)
    duplicate_warnings: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = PAPER_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.paper_id:
            self.paper_id = self.source_id

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Keep schema_version first enough for stable human inspection in JSON dumps.
        return {"schema_version": data.pop("schema_version"), **data}


def first_arxiv_id(*texts: str) -> str:
    for text in texts:
        for match in ARXIV_RE.finditer(text or ""):
            value = match.group(1)
            if value:
                return value
    return ""


def arxiv_year(arxiv_id: str) -> int | None:
    match = re.match(r"^(\d{2})\d{2}\.\d{4,5}(?:v\d+)?$", arxiv_id or "")
    if not match:
        return None
    return 2000 + int(match.group(1))


def first_doi(*texts: str) -> str:
    candidates = doi_candidates(*texts)
    return candidates[0] if candidates else ""


def doi_candidates(*texts: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for text in texts:
        for match in DOI_RE.finditer(text or ""):
            value = normalize_doi(match.group(1))
            if value and value not in seen:
                seen.add(value)
                result.append(value)
    return result


def normalize_doi(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"(?i)^https?://(?:dx\.)?doi\.org/", "", value)
    value = re.sub(r"(?i)^doi:\s*", "", value)
    value = value.rstrip(".,;:)]}")
    return value.casefold()


def infer_year(texts: Iterable[str], arxiv_id: str = "") -> tuple[int | None, str]:
    for text in texts:
        cleaned = strip_identifier_noise(text or "")
        match = YEAR_RE.search(cleaned)
        if match:
            return int(match.group(1)), "metadata"
    year = arxiv_year(arxiv_id)
    if year is not None:
        return year, "arxiv_id"
    return None, "unknown"


def strip_identifier_noise(text: str) -> str:
    text = DOI_RE.sub(" ", text or "")
    text = ARXIV_RE.sub(" ", text)
    return text


def normalize_title_key(title: str) -> str:
    text = (title or "").casefold().replace("_", " ")
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def basename_text(path_value: str) -> str:
    return Path(path_value or "").name


def first_value_with_source(candidates: list[tuple[str, str]], extractor) -> tuple[str, str]:  # noqa: ANN001
    for source, text in candidates:
        value = extractor(text)
        if value:
            return value, source
    return "", "unknown"
