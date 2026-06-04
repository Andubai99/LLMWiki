from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import re
from pathlib import Path
from typing import Any, Iterable

from ..pdf.blocks import SourceBlock, block_evidence_text


METRIC_RESULT_SCHEMA_VERSION = "metric_result_claim.v4.3"
METRIC_DIRECTIONS = {"higher_is_better", "lower_is_better", "neutral", "unknown"}
NORMALIZATION_STATUSES = {"normalized", "raw_only", "ambiguous", "missing"}


class MetricResultValidationError(ValueError):
    pass


@dataclass(frozen=True)
class MetricLocatorValidation:
    valid: bool
    normalized_locator: str
    evidence_block_ids: list[str] = field(default_factory=list)
    evidence_pages: list[int] = field(default_factory=list)
    evidence_section_path: list[str] = field(default_factory=list)
    evidence_block_roles: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MetricResultClaim:
    result_id: str
    claim_id: str
    source_id: str
    paper_id: str
    claim_text: str
    citation_locator: str
    confidence_status: str
    extraction_origin: str
    metric_name: str
    created_at: str
    evidence_block_ids: list[str] = field(default_factory=list)
    evidence_pages: list[int] = field(default_factory=list)
    evidence_section_path: list[str] = field(default_factory=list)
    evidence_block_roles: list[str] = field(default_factory=list)
    method: str = ""
    dataset: str = ""
    task: str = ""
    metric_value: str = ""
    metric_unit: str = ""
    metric_raw_value: str = ""
    metric_direction: str = "unknown"
    baseline: str = ""
    comparison_value: str = ""
    setting: str = ""
    reported_year: int | None = None
    is_main_result: bool | None = None
    value_normalization_status: str = "missing"
    warnings: list[str] = field(default_factory=list)
    schema_version: str = METRIC_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", METRIC_RESULT_SCHEMA_VERSION)
        for field_name in (
            "result_id",
            "claim_id",
            "source_id",
            "paper_id",
            "claim_text",
            "citation_locator",
            "confidence_status",
            "extraction_origin",
            "metric_name",
            "method",
            "dataset",
            "task",
            "metric_value",
            "metric_unit",
            "metric_raw_value",
            "metric_direction",
            "baseline",
            "comparison_value",
            "setting",
            "value_normalization_status",
            "created_at",
        ):
            object.__setattr__(self, field_name, str(getattr(self, field_name) or "").strip())
        if self.metric_direction not in METRIC_DIRECTIONS:
            object.__setattr__(self, "metric_direction", "unknown")
        if self.value_normalization_status not in NORMALIZATION_STATUSES:
            status = "missing" if not self.metric_raw_value else "raw_only"
            object.__setattr__(self, "value_normalization_status", status)
        object.__setattr__(self, "evidence_block_ids", [str(item) for item in self.evidence_block_ids])
        object.__setattr__(self, "evidence_pages", [int(item) for item in self.evidence_pages])
        object.__setattr__(self, "evidence_section_path", [str(item) for item in self.evidence_section_path])
        object.__setattr__(self, "evidence_block_roles", [str(item) for item in self.evidence_block_roles])
        object.__setattr__(self, "warnings", [str(item) for item in self.warnings if str(item).strip()])

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = METRIC_RESULT_SCHEMA_VERSION
        return data


def normalize_metric_value(raw_value: Any) -> dict[str, str]:
    raw = str(raw_value or "").strip()
    if not raw:
        return {
            "metric_value": "",
            "metric_unit": "",
            "metric_raw_value": "",
            "value_normalization_status": "missing",
        }

    normalized = raw.replace("\u2212", "-")
    patterns = (
        (r"^[+]?(-?\d+(?:\.\d+)?)\s*%$", "%"),
        (r"^[+]?(-?\d+(?:\.\d+)?)\s*(ms|milliseconds?)$", "ms"),
        (r"^[+]?(-?\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?)$", "seconds"),
        (r"^[+]?(-?\d+(?:\.\d+)?)\s*x$", "x"),
        (r"^[+]?(-?\d+(?:\.\d+)?)\s*(points?|pts?)$", "points"),
    )
    for pattern, unit in patterns:
        match = re.match(pattern, normalized, flags=re.I)
        if match:
            return {
                "metric_value": match.group(1),
                "metric_unit": unit,
                "metric_raw_value": raw,
                "value_normalization_status": "normalized",
            }

    plain_number = re.match(r"^[+]?(-?\d+(?:\.\d+)?)$", normalized)
    if plain_number:
        return {
            "metric_value": plain_number.group(1),
            "metric_unit": "",
            "metric_raw_value": raw,
            "value_normalization_status": "normalized",
        }

    return {
        "metric_value": "",
        "metric_unit": "",
        "metric_raw_value": raw,
        "value_normalization_status": "raw_only",
    }


def is_placeholder_metric_value(raw_value: Any) -> bool:
    text = clean_string(raw_value).casefold()
    if not text:
        return False
    normalized = re.sub(r"[\s._-]+", " ", text).strip()
    return normalized in {
        "see table",
        "see figure",
        "see caption",
        "not reported",
        "not specified",
        "not available",
        "n/a",
        "na",
        "none",
        "unknown",
    } or bool(re.match(r"^see\s+(table|figure|appendix|supplementary)\s*\d*", normalized))


def validate_pdf_result_locator(
    locator: str,
    *,
    source_id: str,
    blocks_by_id: dict[str, SourceBlock],
    allowed_block_ids: set[str],
    auxiliary_block_ids: Iterable[str] | None = None,
) -> MetricLocatorValidation:
    block_match = re.search(r"(?:^|;)block:([A-Za-z0-9_.-]+)(?:;|$)", str(locator or ""))
    if not block_match:
        raise MetricResultValidationError("metric result locator must include block:<block-id>")
    block_id = block_match.group(1)
    block = blocks_by_id.get(block_id)
    if block is None:
        raise MetricResultValidationError(f"unknown block: {block_id}")
    if block.source_id != source_id:
        raise MetricResultValidationError(f"block source mismatch: {block_id}")
    if block_id not in allowed_block_ids:
        raise MetricResultValidationError(f"block outside allowed chunk: {block_id}")
    if getattr(block, "content_role", "content") == "ignored":
        raise MetricResultValidationError(f"ignored block cannot support metric result: {block_id}")

    page_match = re.search(r"(?:^|;)page:(\d+)(?:;|$)", str(locator or ""))
    if page_match and int(page_match.group(1)) != int(block.page_start):
        raise MetricResultValidationError(f"page mismatch for block: {block_id}")

    section_match = re.search(r"(?:^|;)section:([^;]+)", str(locator or ""))
    section = section_match.group(1).strip() if section_match else " > ".join(block.section_path).strip()
    parts = [f"page:{int(block.page_start)}", f"block:{block_id}"]
    if section:
        parts.append(f"section:{section}")

    evidence_blocks = [block]
    warnings: list[str] = []
    for auxiliary_id in auxiliary_block_ids or []:
        auxiliary_id = clean_string(auxiliary_id)
        if not auxiliary_id or auxiliary_id == block_id or auxiliary_id in {item.block_id for item in evidence_blocks}:
            continue
        auxiliary = blocks_by_id.get(auxiliary_id)
        if auxiliary is None:
            warnings.append(f"invalid_auxiliary_block: unknown block {auxiliary_id}")
            continue
        if auxiliary.source_id != source_id:
            warnings.append(f"invalid_auxiliary_block: source mismatch {auxiliary_id}")
            continue
        if auxiliary_id not in allowed_block_ids:
            warnings.append(f"invalid_auxiliary_block: outside allowed chunk {auxiliary_id}")
            continue
        if getattr(auxiliary, "content_role", "content") == "ignored":
            warnings.append(f"invalid_auxiliary_block: ignored block {auxiliary_id}")
            continue
        evidence_blocks.append(auxiliary)

    pages: list[int] = []
    for evidence_block in evidence_blocks:
        page = int(evidence_block.page_start)
        if page not in pages:
            pages.append(page)

    return MetricLocatorValidation(
        valid=True,
        normalized_locator=";".join(parts),
        evidence_block_ids=[evidence_block.block_id for evidence_block in evidence_blocks],
        evidence_pages=pages,
        evidence_section_path=list(block.section_path),
        evidence_block_roles=[block_role(evidence_block) for evidence_block in evidence_blocks],
        warnings=warnings,
    )


def block_role(block: SourceBlock) -> str:
    block_type = str(getattr(block, "block_type", "") or "").casefold()
    if "table" in block_type or str(getattr(block, "table_markdown", "") or "").strip():
        return "table"
    if "caption" in block_type or "image" in block_type:
        return "caption"
    if "equation" in block_type or str(getattr(block, "latex", "") or "").strip():
        return "equation"
    return str(getattr(block, "block_type", "") or "content")


def metric_result_from_candidate(
    raw: dict[str, Any],
    *,
    source_id: str,
    paper_id: str,
    claim_id: str,
    claim_text: str,
    citation_locator: str,
    confidence_status: str,
    created_at: str,
    locator_validation: MetricLocatorValidation | None = None,
) -> MetricResultClaim:
    raw_metric_value = clean_string(raw.get("metric_raw_value") or raw.get("metric_value"))
    normalized_value = normalize_metric_value(raw_metric_value)
    metric_value = clean_string(raw.get("metric_value")) or normalized_value["metric_value"]
    metric_unit = clean_string(raw.get("metric_unit")) or normalized_value["metric_unit"]
    metric_raw_value = clean_string(raw.get("metric_raw_value")) or normalized_value["metric_raw_value"]
    value_status = clean_string(raw.get("value_normalization_status")) or normalized_value["value_normalization_status"]
    warnings = clean_string_list(raw.get("warnings"))
    if locator_validation:
        warnings = [*warnings, *locator_validation.warnings]
    return MetricResultClaim(
        result_id="",
        claim_id=claim_id,
        source_id=source_id,
        paper_id=paper_id or source_id,
        claim_text=claim_text,
        citation_locator=citation_locator,
        confidence_status=confidence_status,
        evidence_block_ids=locator_validation.evidence_block_ids if locator_validation else clean_string_list(raw.get("evidence_block_ids")),
        evidence_pages=locator_validation.evidence_pages if locator_validation else clean_int_list(raw.get("evidence_pages")),
        evidence_section_path=locator_validation.evidence_section_path if locator_validation else clean_string_list(raw.get("evidence_section_path")),
        evidence_block_roles=locator_validation.evidence_block_roles if locator_validation else clean_string_list(raw.get("evidence_block_roles")),
        extraction_origin=clean_string(raw.get("extraction_origin")) or "unknown",
        method=clean_string(raw.get("method")),
        dataset=clean_string(raw.get("dataset")),
        task=clean_string(raw.get("task")),
        metric_name=clean_string(raw.get("metric_name")),
        metric_value=metric_value,
        metric_unit=metric_unit,
        metric_raw_value=metric_raw_value,
        metric_direction=clean_string(raw.get("metric_direction")) or "unknown",
        baseline=clean_string(raw.get("baseline")),
        comparison_value=clean_string(raw.get("comparison_value")),
        setting=clean_string(raw.get("setting")),
        reported_year=clean_optional_int(raw.get("reported_year")),
        is_main_result=clean_optional_bool(raw.get("is_main_result")),
        value_normalization_status=value_status,
        warnings=warnings,
        created_at=created_at,
    )


def evidence_bundle_has_concrete_metric_value(
    validation: MetricLocatorValidation,
    blocks_by_id: dict[str, SourceBlock],
) -> bool:
    concrete_value = re.compile(
        r"(?<![A-Za-z])[-+]?(?:\d+\.\d+|\d+\s*(?:%|points?|pts?|ms|milliseconds?|seconds?|secs?|s|x))(?![A-Za-z])",
        flags=re.I,
    )
    for block_id in validation.evidence_block_ids:
        block = blocks_by_id.get(block_id)
        if block and concrete_value.search(block_evidence_text(block)):
            return True
    return False


def assign_metric_result_ids(results: Iterable[MetricResultClaim]) -> list[MetricResultClaim]:
    counts: dict[str, int] = {}
    assigned: list[MetricResultClaim] = []
    for result in results:
        counts[result.claim_id] = counts.get(result.claim_id, 0) + 1
        assigned.append(replace(result, result_id=f"res_{result.claim_id}_{counts[result.claim_id]:03d}"))
    return assigned


def dedupe_metric_results(results: Iterable[MetricResultClaim]) -> list[MetricResultClaim]:
    seen: set[tuple[str, str, str, str, str, str, str, str]] = set()
    deduped: list[MetricResultClaim] = []
    for result in results:
        key = (
            result.source_id.casefold(),
            result.claim_id,
            normalize_key(result.metric_name),
            normalize_key(result.method),
            normalize_key(result.dataset),
            normalize_key(result.task),
            result.metric_value or result.metric_raw_value,
            result.citation_locator,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def write_metric_results_jsonl(path: Path, results: Iterable[MetricResultClaim | dict[str, Any]]) -> None:
    rows = [result.to_dict() if isinstance(result, MetricResultClaim) else normalize_metric_result_dict(result) for result in results]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def read_metric_results_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(normalize_metric_result_dict(json.loads(line)))
    return rows


def normalize_metric_result_dict(raw: dict[str, Any]) -> dict[str, Any]:
    row = dict(raw)
    row["schema_version"] = METRIC_RESULT_SCHEMA_VERSION
    for name in (
        "result_id",
        "claim_id",
        "source_id",
        "paper_id",
        "claim_text",
        "citation_locator",
        "confidence_status",
        "extraction_origin",
        "method",
        "dataset",
        "task",
        "metric_name",
        "metric_value",
        "metric_unit",
        "metric_raw_value",
        "metric_direction",
        "baseline",
        "comparison_value",
        "setting",
        "value_normalization_status",
        "created_at",
    ):
        row[name] = clean_string(row.get(name))
    for name in ("evidence_block_ids", "evidence_section_path", "evidence_block_roles", "warnings"):
        row[name] = clean_string_list(row.get(name))
    row["evidence_pages"] = clean_int_list(row.get("evidence_pages"))
    row["reported_year"] = clean_optional_int(row.get("reported_year"))
    row["is_main_result"] = clean_optional_bool(row.get("is_main_result"))
    if row["metric_direction"] not in METRIC_DIRECTIONS:
        row["metric_direction"] = "unknown"
    if row["value_normalization_status"] not in NORMALIZATION_STATUSES:
        row["value_normalization_status"] = "missing" if not row["metric_raw_value"] else "raw_only"
    return row


def metric_result_stats(results: Iterable[MetricResultClaim | dict[str, Any]]) -> dict[str, int | str]:
    rows = [result.to_dict() if isinstance(result, MetricResultClaim) else normalize_metric_result_dict(result) for result in results]
    return {
        "metric_result_schema": METRIC_RESULT_SCHEMA_VERSION,
        "metric_result_count": len(rows),
        "metric_result_cited_count": sum(1 for row in rows if row.get("confidence_status") == "cited"),
        "metric_result_weak_or_unsupported_count": sum(1 for row in rows if row.get("confidence_status") != "cited"),
        "metric_result_invalid_locator_count": sum(
            1
            for row in rows
            if any("invalid" in str(warning).casefold() for warning in row.get("warnings", []))
        ),
        "metric_result_table_or_caption_count": sum(
            1
            for row in rows
            if row.get("extraction_origin") in {"table", "caption"}
            or any(role in {"table", "caption"} for role in row.get("evidence_block_roles", []))
        ),
    }


def clean_string(value: Any) -> str:
    return str(value or "").strip()


def clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = clean_string(item)
        if text:
            result.append(text)
    return result


def clean_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        parsed = clean_optional_int(item)
        if parsed is not None:
            result.append(parsed)
    return result


def clean_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clean_optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())
