from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable


PARSER_MARKER_RE = re.compile(r"^<!--\s*page:\d+\s*-->$", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?$", re.IGNORECASE)
VENUE_STATUS_RE = re.compile(
    r"\b(?:published|accepted|submitted|under review|preprint|conference|journal|workshop|proceedings)\b",
    re.IGNORECASE,
)
CAPTION_RE = re.compile(r"^(?:fig(?:ure)?\.?|table)\s*\d+[:.\s-]", re.IGNORECASE)
REFERENCE_ITEM_RE = re.compile(r"^(?:\[\d+\]|\d+\.)\s+\S+")
APPENDIX_RE = re.compile(r"^appendix(?:\s+[A-Z0-9])?\b", re.IGNORECASE)
MATH_SYMBOL_RE = re.compile(r"[=≈≤≥∑∫√∞±×÷∂∆∇α-ωΑ-Ω²³₀-₉]")


@dataclass(frozen=True)
class TitleCandidate:
    text: str
    source: str
    score: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PaperIdentity:
    title: str = ""
    authors: list[str] = None  # type: ignore[assignment]
    venue_or_status: str = ""
    canonical_names: list[str] = None  # type: ignore[assignment]
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "authors", self.authors or [])
        object.__setattr__(self, "canonical_names", self.canonical_names or [])
        object.__setattr__(self, "warnings", self.warnings or [])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParserQuality:
    page_count: int = 0
    block_count: int = 0
    content_block_count: int = 0
    ignored_block_count: int = 0
    parser_marker_count: int = 0
    page_number_count: int = 0
    repeated_header_footer_count: int = 0
    warning_count: int = 0
    content_block_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PdfQualitySummary:
    schema_version: str
    pdf_source_count: int
    title_pass_rate: float
    sidecar_completeness: float
    block_locator_validity: float
    content_block_ratio: float
    parser_created_duplicate_alias_count: int
    issues: list[str]
    warnings: list[str]
    title_quality_issue_count: int = 0
    invalid_sidecar_schema_count: int = 0
    high_parser_warning_source_count: int = 0
    low_content_block_ratio_source_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_title_candidates(
    *,
    metadata: dict[str, Any] | None,
    blocks: Iterable[Any],
    filename: str,
) -> list[TitleCandidate]:
    candidates: list[tuple[str, str, int, int]] = []
    metadata_title = _clean(metadata.get("title") if metadata else "")
    if metadata_title:
        candidates.append((metadata_title, "metadata", 0, 0))
    for block in blocks:
        text = _clean(getattr(block, "text_clean", ""))
        if text:
            candidates.append((text, "block", int(getattr(block, "page_start", 1)), int(getattr(block, "order", 0))))
    filename_title = _clean(Path(filename).stem.replace("_", " ").replace("-", " "))
    if filename_title:
        candidates.append((filename_title, "filename", 9999, 9999))

    seen: set[str] = set()
    scored: list[TitleCandidate] = []
    metadata_tokens = _tokens(metadata_title)
    for text, source, page, order in candidates:
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        score, reasons = _score_title(text, source, page, order, metadata_tokens)
        scored.append(TitleCandidate(text=text, source=source, score=score, reasons=reasons))
    return sorted(scored, key=lambda item: (-item.score, item.source != "metadata", item.text.casefold()))


def classify_block_roles(blocks: list[Any], repeated_texts: set[str] | None = None) -> list[Any]:
    repeated_texts = repeated_texts or set()
    classified: list[Any] = []
    for block in blocks:
        text = _clean(getattr(block, "text_clean", ""))
        role = "content"
        flags: list[str] = list(getattr(block, "quality_flags", []) or [])
        block_type = getattr(block, "block_type", "")

        if is_parser_marker(text):
            role = "ignored"
            flags.append("parser_marker")
        elif is_page_number(text):
            role = "ignored"
            flags.append("page_number")
        elif text in repeated_texts:
            role = "ignored"
            flags.append("repeated_header_footer")
        elif is_venue_or_status_line(text):
            role = "metadata"
            flags.append("venue_or_status_line")
        elif is_author_dense(text):
            role = "metadata"
            flags.append("author_dense")
        elif CAPTION_RE.match(text):
            role = "table_like" if text.lower().startswith("table") else "caption"
        elif is_equation_like(text):
            role = "equation_like"
        elif block_type == "reference" or REFERENCE_ITEM_RE.match(text):
            role = "reference"
        elif APPENDIX_RE.match(text):
            role = "appendix"

        classified.append(
            replace(
                block,
                content_role=role,
                quality_flags=_unique(flags),
            )
        )
    return classified


def detect_repeated_headers_footers(blocks: Iterable[Any]) -> set[str]:
    pages_by_text: dict[str, set[int]] = defaultdict(set)
    original_by_key: dict[str, str] = {}
    for block in blocks:
        text = _clean(getattr(block, "text_clean", ""))
        if not text or len(text) > 140:
            continue
        if is_page_number(text) or is_parser_marker(text):
            continue
        key = _repeat_key(text)
        pages_by_text[key].add(int(getattr(block, "page_start", 0)))
        original_by_key.setdefault(key, text)
    return {original_by_key[key] for key, pages in pages_by_text.items() if len(pages) >= 2}


def detect_parser_created_alias(text: str) -> bool:
    cleaned = _clean(text)
    if not cleaned:
        return True
    compact = re.sub(r"[\s_-]+", "", cleaned).casefold()
    if compact in {"page", "page1", "p1"} or re.fullmatch(r"page\d+", compact):
        return True
    return (
        is_parser_marker(cleaned)
        or is_page_number(cleaned)
        or is_venue_or_status_line(cleaned)
        or is_author_dense(cleaned)
    )


def evaluate_pdf_quality(root: Path) -> PdfQualitySummary:
    catalog = root / "state" / "catalog.sqlite"
    if not catalog.exists():
        return PdfQualitySummary(
            schema_version="eval.pdf_quality.v2.9.2",
            pdf_source_count=0,
            title_pass_rate=1.0,
            sidecar_completeness=1.0,
            block_locator_validity=1.0,
            content_block_ratio=1.0,
            parser_created_duplicate_alias_count=0,
            title_quality_issue_count=0,
            invalid_sidecar_schema_count=0,
            high_parser_warning_source_count=0,
            low_content_block_ratio_source_count=0,
            issues=[],
            warnings=["catalog not found"],
        )

    conn = sqlite3.connect(catalog)
    conn.row_factory = sqlite3.Row
    try:
        sources = conn.execute(
            "select source_id, title from sources where source_type = 'pdf'"
        ).fetchall()
        pdf_count = len(sources)
        if pdf_count == 0:
            return PdfQualitySummary(
                schema_version="eval.pdf_quality.v2.9.2",
                pdf_source_count=0,
                title_pass_rate=1.0,
                sidecar_completeness=1.0,
                block_locator_validity=1.0,
                content_block_ratio=1.0,
                parser_created_duplicate_alias_count=0,
                title_quality_issue_count=0,
                invalid_sidecar_schema_count=0,
                high_parser_warning_source_count=0,
                low_content_block_ratio_source_count=0,
                issues=[],
                warnings=[],
            )

        complete = 0
        valid_titles = 0
        title_quality_issues = 0
        invalid_sidecar_schema_count = 0
        high_parser_warning_source_count = 0
        low_content_block_ratio_source_count = 0
        ratios: list[float] = []
        issues: list[str] = []
        warnings: list[str] = []
        parser_alias_count = 0
        for source in sources:
            metadata_rel, blocks_rel, chunks_rel = pdf_sidecar_paths(source["source_id"])
            paths = [metadata_rel, blocks_rel, chunks_rel]
            existing = [bool((root / path).exists()) for path in paths]
            if all(existing):
                complete += 1
            else:
                issues.append(f"{source['source_id']}: missing pdf sidecar")
            title = source["title"] or ""
            if not detect_parser_created_alias(title):
                valid_titles += 1
            else:
                title_quality_issues += 1
                issues.append(f"{source['source_id']}: parser-created title")

            metadata_path = root / metadata_rel
            if metadata_path.exists():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    schema_version = str(metadata.get("schema_version") or "")
                    if schema_version not in {"source_metadata.v2.9.1", "source_metadata.v2.9.2"}:
                        invalid_sidecar_schema_count += 1
                        issues.append(f"{source['source_id']}: invalid metadata schema {schema_version}")
                    warnings_value = metadata.get("warnings")
                    warning_count = len(warnings_value) if isinstance(warnings_value, list) else 0
                    parser_quality = metadata.get("parser_quality") or {}
                    warning_count = max(warning_count, int(parser_quality.get("warning_count") or 0))
                    if warning_count >= 5:
                        high_parser_warning_source_count += 1
                        issues.append(f"{source['source_id']}: high parser warning count {warning_count}")
                    if "content_block_ratio" in parser_quality:
                        ratio = float(parser_quality["content_block_ratio"])
                        ratios.append(ratio)
                        if ratio < 0.2:
                            low_content_block_ratio_source_count += 1
                            issues.append(f"{source['source_id']}: low content block ratio {ratio:.3f}")
                except Exception as exc:  # pragma: no cover - defensive reporting
                    invalid_sidecar_schema_count += 1
                    issues.append(f"{source['source_id']}: invalid metadata sidecar: {exc}")

        aliases = conn.execute("select alias from aliases").fetchall()
        parser_alias_count = sum(1 for row in aliases if detect_parser_created_alias(row["alias"]))
        if parser_alias_count:
            issues.append(f"parser-created aliases: {parser_alias_count}")
        block_locator_validity = _pdf_block_locator_validity(conn, root)
        if block_locator_validity < 1.0:
            issues.append("invalid pdf block locators")
        return PdfQualitySummary(
            schema_version="eval.pdf_quality.v2.9.2",
            pdf_source_count=pdf_count,
            title_pass_rate=valid_titles / pdf_count,
            sidecar_completeness=complete / pdf_count,
            block_locator_validity=block_locator_validity,
            content_block_ratio=sum(ratios) / len(ratios) if ratios else 1.0,
            parser_created_duplicate_alias_count=parser_alias_count,
            title_quality_issue_count=title_quality_issues,
            invalid_sidecar_schema_count=invalid_sidecar_schema_count,
            high_parser_warning_source_count=high_parser_warning_source_count,
            low_content_block_ratio_source_count=low_content_block_ratio_source_count,
            issues=issues,
            warnings=warnings,
        )
    finally:
        conn.close()


def format_pdf_quality_report(summary: PdfQualitySummary) -> str:
    lines = [
        "PDF quality evaluation",
        f"PDF sources: {summary.pdf_source_count}",
        f"Title pass rate: {summary.title_pass_rate:.3f}",
        f"Sidecar completeness: {summary.sidecar_completeness:.3f}",
        f"Block locator validity: {summary.block_locator_validity:.3f}",
        f"Content block ratio: {summary.content_block_ratio:.3f}",
        f"Parser-created aliases: {summary.parser_created_duplicate_alias_count}",
        f"Title quality issues: {summary.title_quality_issue_count}",
        f"Invalid sidecar schema: {summary.invalid_sidecar_schema_count}",
        f"High parser warnings: {summary.high_parser_warning_source_count}",
        f"Low content block ratio: {summary.low_content_block_ratio_source_count}",
    ]
    if summary.issues:
        lines.append("Issues:")
        lines.extend(f"- {issue}" for issue in summary.issues)
    if summary.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in summary.warnings)
    return "\n".join(lines)


def parser_quality_from_blocks(blocks: list[Any], page_count: int, warning_count: int = 0) -> ParserQuality:
    ignored = sum(1 for block in blocks if getattr(block, "content_role", "") == "ignored")
    marker_count = sum(1 for block in blocks if "parser_marker" in (getattr(block, "quality_flags", []) or []))
    page_numbers = sum(1 for block in blocks if "page_number" in (getattr(block, "quality_flags", []) or []))
    repeated = sum(1 for block in blocks if "repeated_header_footer" in (getattr(block, "quality_flags", []) or []))
    content = len(blocks) - ignored
    ratio = content / len(blocks) if blocks else 0.0
    return ParserQuality(
        page_count=page_count,
        block_count=len(blocks),
        content_block_count=content,
        ignored_block_count=ignored,
        parser_marker_count=marker_count,
        page_number_count=page_numbers,
        repeated_header_footer_count=repeated,
        warning_count=warning_count,
        content_block_ratio=ratio,
    )


def is_parser_marker(text: str) -> bool:
    return bool(PARSER_MARKER_RE.match(_clean(text)))


def is_page_number(text: str) -> bool:
    return bool(PAGE_NUMBER_RE.match(_clean(text)))


def is_venue_or_status_line(text: str) -> bool:
    cleaned = _clean(text)
    return len(cleaned) <= 180 and bool(VENUE_STATUS_RE.search(cleaned))


def is_author_dense(text: str) -> bool:
    cleaned = _clean(text)
    if len(cleaned) > 240:
        return False
    comma_count = cleaned.count(",")
    name_matches = re.findall(r"\b[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+\b", cleaned)
    if comma_count >= 2 and len(name_matches) >= 2:
        return True
    if len(name_matches) >= 4 and not re.search(r"[:?.]", cleaned):
        return True
    return False


def is_equation_like(text: str) -> bool:
    cleaned = _clean(text)
    if len(cleaned) > 220:
        return False
    return bool(MATH_SYMBOL_RE.search(cleaned)) and not cleaned.endswith(".")


def _score_title(text: str, source: str, page: int, order: int, metadata_tokens: set[str]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    length = len(text)
    if source == "metadata":
        score += 20
        reasons.append("metadata")
    if page <= 1:
        score += 15
        reasons.append("early_page")
    if order <= 4:
        score += 10
        reasons.append("early_block")
    if 12 <= length <= 180:
        score += 25
        reasons.append("title_length")
    elif length < 5:
        score -= 30
        reasons.append("too_short")
    elif length > 220:
        score -= 25
        reasons.append("too_long")
    if re.search(r"[A-Za-z\u4e00-\u9fff]", text):
        score += 10
        reasons.append("has_letters")
    overlap = _tokens(text) & metadata_tokens
    if overlap:
        score += min(15, 3 * len(overlap))
        reasons.append("metadata_token_overlap")
    if ":" in text and length <= 180:
        score += 5
        reasons.append("title_punctuation")
    if is_parser_marker(text):
        score -= 200
        reasons.append("parser_marker")
    if is_page_number(text):
        score -= 100
        reasons.append("page_number")
    if is_venue_or_status_line(text):
        score -= 70
        reasons.append("venue_or_status_line")
    if is_author_dense(text):
        score -= 80
        reasons.append("author_dense")
    return score, _unique(reasons)


def _pdf_block_locator_validity(conn: sqlite3.Connection, root: Path) -> float:
    rows = conn.execute(
        """
        select c.claim_id, c.source_id, c.citation_locator
        from claims c
        join sources s on s.source_id = c.source_id
        where s.source_type = 'pdf'
        """
    ).fetchall()
    if not rows:
        return 1.0
    blocks_by_source: dict[str, set[str]] = {}
    valid = 0
    for row in rows:
        if row["source_id"] not in blocks_by_source:
            block_ids: set[str] = set()
            _, blocks_rel, _ = pdf_sidecar_paths(row["source_id"])
            blocks_path = root / blocks_rel
            if blocks_path.exists():
                for line in blocks_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        data = json.loads(line)
                        block_ids.add(data.get("block_id", ""))
            blocks_by_source[row["source_id"]] = block_ids
        match = re.search(r"block:([A-Za-z0-9_.:-]+)", row["citation_locator"] or "")
        if match and match.group(1) in blocks_by_source[row["source_id"]]:
            valid += 1
    return valid / len(rows)


def _tokens(text: str) -> set[str]:
    return {part.casefold() for part in re.findall(r"[\w]+", text) if len(part) > 2}


def _repeat_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def pdf_sidecar_paths(source_id: str) -> tuple[str, str, str]:
    return (
        f"sources/metadata/{source_id}.json",
        f"sources/blocks/{source_id}.jsonl",
        f"sources/chunks/{source_id}.jsonl",
    )
