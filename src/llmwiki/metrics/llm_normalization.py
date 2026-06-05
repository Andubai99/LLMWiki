from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..corpus.inventory import build_inventory
from ..evals.result_evidence import (
    ResultEvidenceCatalogError,
    ResultEvidenceFilterError,
    build_result_evidence_quality,
)
from ..llm import create_provider, load_llm_config
from ..providers.base import LLMProviderError
from ..workspace import utc_now
from .canonicalization import (
    MAX_LIMIT,
    MetricCanonicalizationCatalogError,
    MetricCanonicalizationFilterError,
    build_metric_canonicalization_report,
    build_value_repair,
    comparability_group_key,
    normalize_canonical_metric_key,
)
from .llm_normalization_prompt import build_metric_normalization_messages, metric_normalization_schema
from .repair import MetricRepairCatalogError, build_metric_repair_plan


METRIC_NORMALIZATION_RUN_SCHEMA_VERSION = "metric_normalization_run.v4.9"
METRIC_EVIDENCE_BUNDLE_SCHEMA_VERSION = "metric_evidence_bundle.v4.9"
METRIC_NORMALIZATION_DECISION_SCHEMA_VERSION = "metric_normalization_decision.v4.9"
METRIC_TIMELINE_GROUP_SCHEMA_VERSION = "metric_timeline_group.v4.9"
METRIC_TIMELINE_POINT_SCHEMA_VERSION = "metric_timeline_point.v4.9"
METRIC_TIMELINE_SYNTHESIS_SCHEMA_VERSION = "metric_timeline_synthesis.v4.9"
METRIC_NORMALIZATION_WARNING_SCHEMA_VERSION = "metric_normalization_warning.v4.9"

DEFAULT_LIMIT = 200
NORMALIZATION_MAX_LIMIT = 1000
DEFAULT_MAX_RESULTS_PER_GROUP = 40
DECISION_STATUSES = {"auto_accepted", "needs_review", "blocked", "conflict", "insufficient_evidence"}
DECISION_CONFIDENCES = {"high", "medium", "low"}
RESULT_ROLES = {"main_result", "baseline", "prior_work", "ablation", "diagnostic", "dataset_stat", "method_description", "unclear"}
AUTO_TIMELINE_CONFIDENCES = {"high", "medium"}


class MetricNormalizationFilterError(ValueError):
    """Invalid V4.9 metric normalization filter."""


class MetricNormalizationCatalogError(RuntimeError):
    """Catalog is unavailable or incompatible with V4.9 normalization."""


class MetricNormalizationStagingError(RuntimeError):
    """Metric normalization staging run is missing or invalid."""


class MetricNormalizationLLMError(RuntimeError):
    """LLM output is unsafe or incompatible with V4.9 normalization."""


@dataclass
class MetricNormalizationRun:
    root: str
    query: dict[str, Any]
    summary: dict[str, Any]
    evidence_bundles: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    timeline_groups: list[dict[str, Any]]
    timeline_points: list[dict[str, Any]]
    timeline_synthesis: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    normalization_run_id: str = ""
    mode: str = "run"
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = METRIC_NORMALIZATION_RUN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "normalization_run_id": self.normalization_run_id,
            "mode": self.mode,
            "query": self.query,
            "summary": self.summary,
            "evidence_bundle_count": len(self.evidence_bundles),
            "decision_count": len(self.decisions),
            "timeline_group_count": len(self.timeline_groups),
            "timeline_point_count": len(self.timeline_points),
            "warning_count": len(self.warnings),
            "evidence_bundles": self.evidence_bundles,
            "decisions": self.decisions,
            "timeline_groups": self.timeline_groups,
            "timeline_points": self.timeline_points,
            "timeline_synthesis": self.timeline_synthesis,
            "warnings": self.warnings,
        }


@dataclass
class MetricTimelineSynthesisResponse:
    root: str
    normalization_run_id: str
    summary: dict[str, Any]
    timeline_groups: list[dict[str, Any]]
    timeline_points: list[dict[str, Any]]
    synthesis: str
    evidence_refs: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = METRIC_TIMELINE_SYNTHESIS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "normalization_run_id": self.normalization_run_id,
            "summary": self.summary,
            "timeline_group_count": len(self.timeline_groups),
            "timeline_point_count": len(self.timeline_points),
            "warning_count": len(self.warnings),
            "timeline_groups": self.timeline_groups,
            "timeline_points": self.timeline_points,
            "synthesis": self.synthesis,
            "evidence_refs": self.evidence_refs,
            "warnings": self.warnings,
        }


def validate_limit_offset(limit: int | None, offset: int | None) -> tuple[int, int, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    resolved_limit = DEFAULT_LIMIT if limit is None else int(limit)
    resolved_offset = 0 if offset is None else int(offset)
    if resolved_limit <= 0:
        raise MetricNormalizationFilterError("invalid limit: must be positive")
    if resolved_offset < 0:
        raise MetricNormalizationFilterError("invalid offset: must be >= 0")
    if resolved_limit > NORMALIZATION_MAX_LIMIT:
        warnings.append(warning("limit_clamped", f"Limit clamped from {resolved_limit} to {NORMALIZATION_MAX_LIMIT}."))
        resolved_limit = NORMALIZATION_MAX_LIMIT
    return resolved_limit, resolved_offset, warnings


def build_metric_normalization_dry_run(
    root: Path,
    *,
    metric: str | None = None,
    dataset: str | None = None,
    task: str | None = None,
    source_id: str | None = None,
    paper_id: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    max_groups: int | None = None,
    max_results_per_group: int | None = None,
) -> MetricNormalizationRun:
    root = root.resolve()
    resolved_limit, resolved_offset, warnings = validate_limit_offset(limit, offset)
    bundles, build_summary, build_warnings = build_evidence_bundles(
        root,
        metric=metric,
        dataset=dataset,
        task=task,
        source_id=source_id,
        paper_id=paper_id,
        limit=resolved_limit,
        offset=resolved_offset,
        max_groups=max_groups,
        max_results_per_group=max_results_per_group,
    )
    warnings.extend(build_warnings)
    summary = {
        **build_summary,
        "estimated_prompt_tokens": estimate_prompt_tokens(bundles),
        "estimated_completion_tokens": max(0, len(bundles) * 700),
        "provider_call_count": 0,
        "decision_count": 0,
        "auto_accepted_decision_count": 0,
        "timeline_group_count": 0,
        "timeline_point_count": 0,
    }
    return MetricNormalizationRun(
        root=root.as_posix(),
        query=query_payload(metric, dataset, task, source_id, paper_id, resolved_limit, resolved_offset, max_groups, max_results_per_group),
        summary=summary,
        evidence_bundles=bundles,
        decisions=[],
        timeline_groups=[],
        timeline_points=[],
        timeline_synthesis=empty_timeline_synthesis(""),
        warnings=dedupe_warnings(warnings),
        mode="dry_run",
    )


def build_metric_normalization_run(
    root: Path,
    *,
    metric: str | None = None,
    dataset: str | None = None,
    task: str | None = None,
    source_id: str | None = None,
    paper_id: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    max_groups: int | None = None,
    max_results_per_group: int | None = None,
    reuse_run: str | None = None,
) -> MetricNormalizationRun:
    root = root.resolve()
    if reuse_run:
        return build_metric_normalization_status(root, reuse_run)
    dry_run = build_metric_normalization_dry_run(
        root,
        metric=metric,
        dataset=dataset,
        task=task,
        source_id=source_id,
        paper_id=paper_id,
        limit=limit,
        offset=offset,
        max_groups=max_groups,
        max_results_per_group=max_results_per_group,
    )
    config = load_llm_config(root)
    if not config.enabled:
        raise MetricNormalizationLLMError("LLM provider is disabled.")
    provider = create_provider(config, root=root)

    decisions: list[dict[str, Any]] = []
    warnings = list(dry_run.warnings)
    provider_name = config.provider
    model_name = config.model
    total_tokens = 0
    for bundle in dry_run.evidence_bundles:
        try:
            response = provider.complete(build_metric_normalization_messages(bundle), schema=metric_normalization_schema())
        except LLMProviderError as exc:
            raise MetricNormalizationLLMError(str(exc)) from exc
        provider_name = str(response.get("provider") or provider_name)
        model_name = str(response.get("model") or model_name)
        usage = response.get("usage") or {}
        if isinstance(usage, dict):
            total_tokens += int(usage.get("total_tokens") or usage.get("completion_tokens") or 0)
        payload = parse_provider_json(response)
        bundle_decisions, bundle_warnings = normalize_decision_payload(payload, bundle)
        decisions.extend(bundle_decisions)
        warnings.extend(bundle_warnings)

    timeline_groups, timeline_points = build_timeline_preview(decisions, dry_run.evidence_bundles)
    synthesis = build_timeline_synthesis_payload("", timeline_groups, timeline_points, warnings)
    run_id = create_normalization_run_id(dry_run.query, decisions)
    run = MetricNormalizationRun(
        root=root.as_posix(),
        query=dry_run.query,
        summary=build_run_summary(dry_run.summary, decisions, timeline_groups, timeline_points, provider_name, model_name, total_tokens),
        evidence_bundles=dry_run.evidence_bundles,
        decisions=decisions,
        timeline_groups=timeline_groups,
        timeline_points=timeline_points,
        timeline_synthesis=synthesis,
        warnings=dedupe_warnings(warnings),
        normalization_run_id=run_id,
        mode="run",
    )
    stage_metric_normalization_run(root, run, provider_name=provider_name, model_name=model_name)
    return run


def build_evidence_bundles(
    root: Path,
    *,
    metric: str | None,
    dataset: str | None,
    task: str | None,
    source_id: str | None,
    paper_id: str | None,
    limit: int,
    offset: int,
    max_groups: int | None,
    max_results_per_group: int | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    try:
        evidence = build_result_evidence_quality(
            root,
            source_id=source_id,
            paper_id=paper_id,
            metric=metric,
            dataset=dataset,
            task=task,
            limit=MAX_LIMIT,
            offset=0,
        ).to_dict()
        canonicalization = build_metric_canonicalization_report(
            root,
            metric=metric,
            dataset=dataset,
            task=task,
            limit=MAX_LIMIT,
            offset=0,
        ).to_dict()
        repair_plan = build_metric_repair_plan(
            root,
            metric=metric,
            dataset=dataset,
            task=task,
            limit=MAX_LIMIT,
            offset=0,
        ).to_dict()
    except (
        ResultEvidenceCatalogError,
        ResultEvidenceFilterError,
        MetricCanonicalizationCatalogError,
        MetricCanonicalizationFilterError,
        MetricRepairCatalogError,
    ) as exc:
        raise MetricNormalizationCatalogError(str(exc)) from exc
    warnings.extend(wrap_external_warnings(evidence.get("warnings", [])))
    warnings.extend(wrap_external_warnings(canonicalization.get("warnings", [])))
    warnings.extend(wrap_external_warnings(repair_plan.get("warnings", [])))

    paper_by_id = paper_identity_by_id(root, warnings)
    repair_by_result_id = {str(item.get("result_id") or ""): item for item in canonicalization.get("value_repairs", [])}
    proposals_by_result = group_repair_proposals_by_result(repair_plan.get("proposals", []))
    items = list(evidence.get("items") or [])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        repair = repair_by_result_id.get(str(item.get("result_id") or "")) or build_value_repair(item)
        grouped[comparability_group_key(item, repair)].append(item)

    max_results = DEFAULT_MAX_RESULTS_PER_GROUP if max_results_per_group is None else int(max_results_per_group)
    if max_results <= 0:
        raise MetricNormalizationFilterError("invalid max-results-per-group: must be positive")
    group_keys = sorted(grouped)
    unpaged_group_count = len(group_keys)
    group_keys = group_keys[offset : offset + limit]
    if max_groups is not None:
        if int(max_groups) <= 0:
            raise MetricNormalizationFilterError("invalid max-groups: must be positive")
        group_keys = group_keys[: int(max_groups)]

    bundles: list[dict[str, Any]] = []
    for group_key in group_keys:
        rows = grouped[group_key][:max_results]
        bundle = evidence_bundle_payload(
            group_key,
            rows,
            paper_by_id=paper_by_id,
            proposals_by_result=proposals_by_result,
            truncated_count=max(0, len(grouped[group_key]) - len(rows)),
        )
        bundles.append(bundle)
    if not bundles:
        warnings.append(warning("no_metric_results", "No metric result rows matched normalization filters."))

    summary = {
        "result_count": len(items),
        "candidate_group_count_unpaged": unpaged_group_count,
        "evidence_bundle_count": len(bundles),
        "truncated_result_count": sum(int(bundle.get("truncated_result_count") or 0) for bundle in bundles),
        "repair_proposal_count": int(repair_plan.get("summary", {}).get("proposal_count_unpaged") or len(repair_plan.get("proposals", []))),
    }
    return bundles, summary, warnings


def evidence_bundle_payload(
    group_key: str,
    rows: list[dict[str, Any]],
    *,
    paper_by_id: dict[str, dict[str, Any]],
    proposals_by_result: dict[str, list[dict[str, Any]]],
    truncated_count: int,
) -> dict[str, Any]:
    result_rows = [result_row_payload(row) for row in rows]
    context_refs = [context_ref_payload(row) for row in rows if str(row.get("citation_locator") or "")]
    papers: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("paper_id") or row.get("source_id") or "")
        paper = paper_by_id.get(key) or paper_by_id.get(str(row.get("source_id") or ""))
        if paper:
            papers[key] = paper_identity_payload(paper)
    related_proposals = []
    for row in rows:
        related_proposals.extend(proposals_by_result.get(str(row.get("result_id") or ""), []))
    payload = {
        "schema_version": METRIC_EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "bundle_id": bundle_id_for_payload(group_key, result_rows),
        "candidate_group_key": group_key,
        "result_count": len(result_rows),
        "truncated_result_count": truncated_count,
        "paper_identities": sorted(papers.values(), key=lambda item: (str(item.get("year") or ""), item.get("paper_id", ""))),
        "result_rows": result_rows,
        "context_refs": context_refs,
        "repair_proposals": related_proposals,
        "warnings": [],
    }
    return payload


def result_row_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": str(row.get("result_id") or ""),
        "claim_id": str(row.get("claim_id") or ""),
        "source_id": str(row.get("source_id") or ""),
        "paper_id": str(row.get("paper_id") or row.get("source_id") or ""),
        "citation_locator": str(row.get("citation_locator") or ""),
        "claim_text": str(row.get("claim_text") or ""),
        "metric_name": str(row.get("metric_name") or ""),
        "metric_value": str(row.get("metric_value") or ""),
        "metric_unit": str(row.get("metric_unit") or ""),
        "metric_raw_value": str(row.get("metric_raw_value") or ""),
        "metric_direction": str(row.get("metric_direction") or ""),
        "method": str(row.get("method") or ""),
        "dataset": str(row.get("dataset") or ""),
        "task": str(row.get("task") or ""),
        "baseline": str(row.get("baseline") or ""),
        "reported_year": row.get("reported_year"),
        "confidence_status": str(row.get("confidence_status") or ""),
        "context_preview": str(row.get("context_preview") or "")[:500],
        "context_block_role": str(row.get("context_block_role") or ""),
        "evidence_block_ids": list(row.get("evidence_block_ids") or []),
        "evidence_block_roles": list(row.get("evidence_block_roles") or []),
    }


def context_ref_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": str(row.get("result_id") or ""),
        "claim_id": str(row.get("claim_id") or ""),
        "source_id": str(row.get("source_id") or ""),
        "paper_id": str(row.get("paper_id") or row.get("source_id") or ""),
        "citation_locator": str(row.get("citation_locator") or ""),
        "context_preview": str(row.get("context_preview") or "")[:500],
        "context_page": row.get("context_page"),
        "context_block_id": str(row.get("context_block_id") or ""),
        "context_block_role": str(row.get("context_block_role") or ""),
    }


def paper_identity_payload(paper: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": str(paper.get("paper_id") or paper.get("source_id") or ""),
        "source_id": str(paper.get("source_id") or ""),
        "title": str(paper.get("title") or ""),
        "authors": list(paper.get("authors") or []),
        "year": paper.get("year"),
        "doi": str(paper.get("doi") or ""),
        "arxiv_id": str(paper.get("arxiv_id") or ""),
        "identity_status": str(paper.get("identity_status") or ""),
    }


def normalize_decision_payload(payload: dict[str, Any], bundle: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise MetricNormalizationLLMError("LLM response must contain decisions list.")
    allowed_refs = {
        (
            str(row.get("result_id") or ""),
            str(row.get("claim_id") or ""),
            str(row.get("source_id") or ""),
            str(row.get("citation_locator") or ""),
        )
        for row in bundle.get("result_rows", [])
    }
    allowed_result_ids = {ref[0] for ref in allowed_refs}
    warnings: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for raw in raw_decisions:
        if not isinstance(raw, dict):
            warnings.append(warning("invalid_decision_item", "Skipped non-object normalization decision."))
            continue
        evidence_refs = normalize_evidence_refs(raw.get("evidence_refs") or [])
        for ref in evidence_refs:
            key = (
                ref["result_id"],
                ref["claim_id"],
                ref["source_id"],
                ref["citation_locator"],
            )
            if key not in allowed_refs:
                raise MetricNormalizationLLMError(f"LLM decision references evidence outside bundle: {ref['result_id']}")
        result_ids = normalize_list(raw.get("result_ids")) or sorted({ref["result_id"] for ref in evidence_refs})
        if not set(result_ids) <= allowed_result_ids:
            raise MetricNormalizationLLMError("LLM decision references unknown result_id.")
        status = normalize_choice(raw.get("decision_status"), DECISION_STATUSES, fallback="needs_review")
        confidence = normalize_choice(raw.get("confidence"), DECISION_CONFIDENCES, fallback="low")
        role = normalize_choice(raw.get("result_role"), RESULT_ROLES, fallback="unclear")
        if status == "auto_accepted" and confidence == "low":
            status = "needs_review"
            warnings.append(warning("low_confidence_downgraded", "Low-confidence decision downgraded from auto_accepted."))
        comparable = bool(raw.get("comparable", False)) and status == "auto_accepted" and confidence in AUTO_TIMELINE_CONFIDENCES
        canonical_metric_name = str(raw.get("canonical_metric_name") or raw.get("metric_name") or "").strip()
        canonical_dataset_name = str(raw.get("canonical_dataset_name") or "").strip()
        canonical_task_name = str(raw.get("canonical_task_name") or "").strip()
        decision = {
            "schema_version": METRIC_NORMALIZATION_DECISION_SCHEMA_VERSION,
            "decision_id": decision_id_for_payload(raw),
            "bundle_id": str(bundle.get("bundle_id") or ""),
            "result_ids": result_ids,
            "claim_ids": normalize_list(raw.get("claim_ids")) or sorted({ref["claim_id"] for ref in evidence_refs}),
            "source_ids": normalize_list(raw.get("source_ids")) or sorted({ref["source_id"] for ref in evidence_refs}),
            "paper_ids": normalize_list(raw.get("paper_ids")),
            "canonical_metric_id": stable_id("met", canonical_metric_name),
            "canonical_metric_name": canonical_metric_name,
            "canonical_dataset_id": stable_id("dat", canonical_dataset_name),
            "canonical_dataset_name": canonical_dataset_name,
            "canonical_task_id": stable_id("task", canonical_task_name),
            "canonical_task_name": canonical_task_name,
            "result_role": role,
            "paper_year": normalize_int_or_none(raw.get("paper_year")),
            "result_reported_year": normalize_int_or_none(raw.get("result_reported_year")),
            "timeline_year": normalize_int_or_none(raw.get("timeline_year")),
            "timeline_year_basis": str(raw.get("timeline_year_basis") or ""),
            "comparable": comparable,
            "decision_status": status,
            "confidence": confidence,
            "rationale": str(raw.get("rationale") or "")[:500],
            "evidence_refs": evidence_refs,
            "warnings": normalize_warning_list(raw.get("warnings") or []),
        }
        decisions.append(decision)
    return decisions, dedupe_warnings(warnings)


def build_timeline_preview(decisions: list[dict[str, Any]], bundles: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    row_by_result_id = result_rows_by_id(bundles or [])
    points: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in decisions:
        if not decision.get("comparable"):
            continue
        for ref in decision.get("evidence_refs") or []:
            if ref.get("result_id") not in set(decision.get("result_ids") or []):
                continue
            point = timeline_point_payload(decision, ref, row_by_result_id.get(str(ref.get("result_id") or ""), {}))
            points.append(point)
            grouped[str(point["timeline_group_key"])].append(point)
    groups: list[dict[str, Any]] = []
    for group_key, group_points in sorted(grouped.items()):
        years = [point["timeline_year"] for point in group_points if point.get("timeline_year") is not None]
        groups.append(
            {
                "schema_version": METRIC_TIMELINE_GROUP_SCHEMA_VERSION,
                "timeline_group_key": group_key,
                "canonical_metric_id": group_points[0]["canonical_metric_id"],
                "canonical_metric_name": group_points[0]["canonical_metric_name"],
                "canonical_dataset_id": group_points[0]["canonical_dataset_id"],
                "canonical_dataset_name": group_points[0]["canonical_dataset_name"],
                "canonical_task_id": group_points[0]["canonical_task_id"],
                "canonical_task_name": group_points[0]["canonical_task_name"],
                "result_role_filter": group_points[0]["result_role"],
                "point_count": len(group_points),
                "source_count": len({point["source_id"] for point in group_points}),
                "paper_count": len({point["paper_id"] for point in group_points}),
                "year_min": min(years) if years else None,
                "year_max": max(years) if years else None,
                "warnings": [],
            }
        )
    points.sort(key=lambda item: (item.get("timeline_year") is None, item.get("timeline_year") or 999999, item["result_id"]))
    return groups, points


def timeline_point_payload(decision: dict[str, Any], ref: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    group_key = timeline_group_key(decision)
    return {
        "schema_version": METRIC_TIMELINE_POINT_SCHEMA_VERSION,
        "timeline_group_key": group_key,
        "timeline_year": decision.get("timeline_year"),
        "metric_value": str(row.get("metric_value") or ""),
        "metric_raw_value": str(row.get("metric_raw_value") or ""),
        "metric_unit": str(row.get("metric_unit") or ""),
        "method": str(row.get("method") or ""),
        "paper_title": "",
        "source_id": ref["source_id"],
        "paper_id": first_or_empty(decision.get("paper_ids") or [ref["source_id"]]),
        "claim_id": ref["claim_id"],
        "result_id": ref["result_id"],
        "citation_locator": ref["citation_locator"],
        "canonical_metric_id": decision["canonical_metric_id"],
        "canonical_metric_name": decision["canonical_metric_name"],
        "canonical_dataset_id": decision["canonical_dataset_id"],
        "canonical_dataset_name": decision["canonical_dataset_name"],
        "canonical_task_id": decision["canonical_task_id"],
        "canonical_task_name": decision["canonical_task_name"],
        "result_role": decision["result_role"],
        "confidence": decision["confidence"],
        "decision_id": decision["decision_id"],
    }


def result_rows_by_id(bundles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for bundle in bundles:
        for row in bundle.get("result_rows") or []:
            if isinstance(row, dict) and row.get("result_id"):
                rows[str(row["result_id"])] = row
    return rows


def timeline_group_key(decision: dict[str, Any]) -> str:
    return "|".join(
        [
            str(decision.get("canonical_metric_id") or ""),
            str(decision.get("canonical_dataset_id") or ""),
            str(decision.get("canonical_task_id") or ""),
            str(decision.get("result_role") or ""),
        ]
    )


def build_timeline_synthesis_payload(run_id: str, groups: list[dict[str, Any]], points: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    refs = evidence_refs_from_points(points)
    if points:
        first = points[0]
        text = (
            f"已生成 {len(groups)} 条候选时间线和 {len(points)} 个时间线点。"
            f"示例：{first['canonical_metric_name']} / {first['canonical_dataset_name']} / {first['canonical_task_name']} "
            f"在 {first.get('timeline_year') or '未知年份'} 有结果，引用 {first['result_id']} / {first['claim_id']} / {first['source_id']} / {first['citation_locator']}。"
        )
    else:
        text = "暂无可自动接受的时间线点。"
    return {
        "schema_version": METRIC_TIMELINE_SYNTHESIS_SCHEMA_VERSION,
        "normalization_run_id": run_id,
        "synthesis": text,
        "timeline_group_count": len(groups),
        "timeline_point_count": len(points),
        "evidence_refs": refs,
        "warnings": dedupe_warnings(warnings),
    }


def stage_metric_normalization_run(root: Path, run: MetricNormalizationRun, *, provider_name: str, model_name: str) -> None:
    run_dir = root / "staging" / run.normalization_run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": METRIC_NORMALIZATION_RUN_SCHEMA_VERSION,
        "run_id": run.normalization_run_id,
        "run_type": "metric_llm_normalization",
        "status": "staged",
        "created_at": utc_now(),
        "provider": provider_name,
        "model": model_name,
        "query": run.query,
        "summary": run.summary,
    }
    synthesis = dict(run.timeline_synthesis)
    synthesis["normalization_run_id"] = run.normalization_run_id
    run.timeline_synthesis = synthesis
    write_json(run_dir / "run.json", manifest)
    write_jsonl(run_dir / "evidence-bundles.jsonl", run.evidence_bundles)
    write_jsonl(run_dir / "llm-normalization-decisions.jsonl", run.decisions)
    write_jsonl(run_dir / "timeline-groups.jsonl", run.timeline_groups)
    write_jsonl(run_dir / "timeline-points.jsonl", run.timeline_points)
    write_json(run_dir / "timeline-synthesis.json", synthesis)
    write_jsonl(run_dir / "warnings.jsonl", run.warnings)
    (run_dir / "triage.md").write_text(format_normalization_triage(run), encoding="utf-8")


def build_metric_normalization_status(root: Path, normalization_run_id: str) -> MetricNormalizationRun:
    run_dir = normalization_run_dir(root, normalization_run_id)
    manifest_path = run_dir / "run.json"
    if not manifest_path.exists():
        raise MetricNormalizationStagingError(f"missing metric normalization run: {normalization_run_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundles = read_jsonl(run_dir / "evidence-bundles.jsonl")
    decisions = read_jsonl(run_dir / "llm-normalization-decisions.jsonl")
    groups = read_jsonl(run_dir / "timeline-groups.jsonl")
    points = read_jsonl(run_dir / "timeline-points.jsonl")
    warnings = read_jsonl(run_dir / "warnings.jsonl")
    synthesis_path = run_dir / "timeline-synthesis.json"
    synthesis = json.loads(synthesis_path.read_text(encoding="utf-8")) if synthesis_path.exists() else empty_timeline_synthesis(normalization_run_id)
    summary = dict(manifest.get("summary") or {})
    summary.update(decision_summary(decisions, groups, points))
    return MetricNormalizationRun(
        root=root.resolve().as_posix(),
        query=dict(manifest.get("query") or {}),
        summary=summary,
        evidence_bundles=bundles,
        decisions=decisions,
        timeline_groups=groups,
        timeline_points=points,
        timeline_synthesis=synthesis,
        warnings=warnings,
        normalization_run_id=normalization_run_id,
        mode="run",
        generated_at=str(manifest.get("created_at") or utc_now()),
    )


def build_timeline_synthesis_response(root: Path, normalization_run_id: str, *, metric: str | None = None) -> MetricTimelineSynthesisResponse:
    status = build_metric_normalization_status(root, normalization_run_id)
    points = status.timeline_points
    groups = status.timeline_groups
    if metric:
        points = [point for point in points if point.get("canonical_metric_id") == metric or point.get("canonical_metric_name") == metric]
        group_keys = {point["timeline_group_key"] for point in points}
        groups = [group for group in groups if group["timeline_group_key"] in group_keys]
    synthesis_payload = status.timeline_synthesis or empty_timeline_synthesis(normalization_run_id)
    return MetricTimelineSynthesisResponse(
        root=root.resolve().as_posix(),
        normalization_run_id=normalization_run_id,
        summary={
            "timeline_group_count": len(groups),
            "timeline_point_count": len(points),
            "decision_count": len(status.decisions),
        },
        timeline_groups=groups,
        timeline_points=points,
        synthesis=str(synthesis_payload.get("synthesis") or ""),
        evidence_refs=evidence_refs_from_points(points),
        warnings=list(status.warnings),
    )


def parse_provider_json(response: dict[str, Any]) -> dict[str, Any]:
    content = str(response.get("content") or "")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise MetricNormalizationLLMError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MetricNormalizationLLMError("LLM response must be a JSON object.")
    return parsed


def build_run_summary(
    dry_summary: dict[str, Any],
    decisions: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    points: list[dict[str, Any]],
    provider_name: str,
    model_name: str,
    total_tokens: int,
) -> dict[str, Any]:
    return {
        **dry_summary,
        **decision_summary(decisions, groups, points),
        "provider": provider_name,
        "model": model_name,
        "provider_call_count": dry_summary.get("evidence_bundle_count", 0),
        "llm_total_tokens": total_tokens,
    }


def decision_summary(decisions: list[dict[str, Any]], groups: list[dict[str, Any]], points: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(decision.get("decision_status") or "") for decision in decisions)
    confidences = Counter(str(decision.get("confidence") or "") for decision in decisions)
    roles = Counter(str(decision.get("result_role") or "") for decision in decisions)
    return {
        "decision_count": len(decisions),
        "auto_accepted_decision_count": statuses.get("auto_accepted", 0),
        "needs_review_decision_count": statuses.get("needs_review", 0),
        "blocked_decision_count": statuses.get("blocked", 0),
        "conflict_decision_count": statuses.get("conflict", 0),
        "insufficient_evidence_decision_count": statuses.get("insufficient_evidence", 0),
        "decision_counts_by_status": dict(sorted(statuses.items())),
        "decision_counts_by_confidence": dict(sorted(confidences.items())),
        "decision_counts_by_role": dict(sorted(roles.items())),
        "timeline_group_count": len(groups),
        "timeline_point_count": len(points),
    }


def query_payload(
    metric: str | None,
    dataset: str | None,
    task: str | None,
    source_id: str | None,
    paper_id: str | None,
    limit: int,
    offset: int,
    max_groups: int | None,
    max_results_per_group: int | None,
) -> dict[str, Any]:
    return {
        "metric": metric or "",
        "dataset": dataset or "",
        "task": task or "",
        "source_id": source_id or "",
        "paper_id": paper_id or "",
        "limit": limit,
        "offset": offset,
        "max_groups": max_groups,
        "max_results_per_group": max_results_per_group or DEFAULT_MAX_RESULTS_PER_GROUP,
    }


def paper_identity_by_id(root: Path, warnings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    try:
        inventory = build_inventory(root).to_dict()
    except Exception as exc:
        warnings.append(warning("inventory_unavailable", f"Paper inventory unavailable: {exc}"))
        return {}
    result: dict[str, dict[str, Any]] = {}
    for paper in inventory.get("papers", []):
        for key in (paper.get("paper_id"), paper.get("source_id")):
            if key:
                result[str(key)] = paper
    return result


def group_repair_proposals_by_result(proposals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for proposal in proposals:
        target = proposal.get("target") or {}
        result_id = str(target.get("result_id") or "")
        if result_id:
            grouped[result_id].append(
                {
                    "proposal_id": proposal.get("proposal_id"),
                    "proposal_type": proposal.get("proposal_type"),
                    "review_status": proposal.get("review_status"),
                    "risk_level": proposal.get("risk_level"),
                    "suggested": proposal.get("suggested") or {},
                }
            )
    return grouped


def normalize_evidence_refs(value: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if not isinstance(value, list):
        return refs
    for item in value:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "result_id": str(item.get("result_id") or ""),
                "claim_id": str(item.get("claim_id") or ""),
                "source_id": str(item.get("source_id") or ""),
                "citation_locator": str(item.get("citation_locator") or ""),
            }
        )
    return refs


def normalize_warning_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(
                {
                    "schema_version": METRIC_NORMALIZATION_WARNING_SCHEMA_VERSION,
                    "code": str(item.get("code") or "llm_warning"),
                    "severity": str(item.get("severity") or "warning"),
                    "message": str(item.get("message") or item.get("reason") or "")[:500],
                }
            )
        elif item:
            normalized.append(warning("llm_warning", str(item)[:500]))
    return normalized


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value:
        return [str(value)]
    return []


def normalize_choice(value: Any, allowed: set[str], *, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else fallback


def normalize_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def stable_id(prefix: str, value: str) -> str:
    key = normalize_canonical_metric_key(value) or "unknown"
    return f"{prefix}_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}"


def decision_id_for_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "mnd_" + hashlib.sha256(encoded).hexdigest()[:12]


def bundle_id_for_payload(group_key: str, rows: list[dict[str, Any]]) -> str:
    payload = {"group_key": group_key, "result_ids": [row["result_id"] for row in rows]}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "meb_" + hashlib.sha256(encoded).hexdigest()[:12]


def create_normalization_run_id(query: dict[str, Any], decisions: list[dict[str, Any]]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    seed = json.dumps({"query": query, "decision_ids": [decision["decision_id"] for decision in decisions]}, sort_keys=True)
    return f"run_metric_normalize_{now}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:8]}"


def normalization_run_dir(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"run_metric_normalize_\d{14}_[0-9a-f]{8}", run_id):
        raise MetricNormalizationStagingError(f"invalid metric normalization run id: {run_id}")
    run_dir = root.resolve() / "staging" / run_id
    if not run_dir.exists():
        raise MetricNormalizationStagingError(f"missing metric normalization run: {run_id}")
    return run_dir


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def format_normalization_triage(run: MetricNormalizationRun) -> str:
    summary = run.summary
    lines = [
        "# Metric Normalization Triage",
        "",
        f"- run_id: `{run.normalization_run_id}`",
        f"- evidence_bundle_count: `{len(run.evidence_bundles)}`",
        f"- decision_count: `{summary.get('decision_count', 0)}`",
        f"- auto_accepted_decision_count: `{summary.get('auto_accepted_decision_count', 0)}`",
        f"- timeline_group_count: `{len(run.timeline_groups)}`",
        f"- timeline_point_count: `{len(run.timeline_points)}`",
        "",
        "## Timeline Points",
    ]
    for point in run.timeline_points[:50]:
        lines.append(
            f"- `{point['timeline_year']}` {point['canonical_metric_name']} / {point['canonical_dataset_name']} / "
            f"{point['canonical_task_name']} -> `{point['result_id']}` `{point['claim_id']}` `{point['source_id']}` `{point['citation_locator']}`"
        )
    if not run.timeline_points:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def estimate_prompt_tokens(bundles: list[dict[str, Any]]) -> int:
    chars = sum(len(json.dumps(bundle, ensure_ascii=False)) for bundle in bundles)
    return max(0, chars // 4)


def empty_timeline_synthesis(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": METRIC_TIMELINE_SYNTHESIS_SCHEMA_VERSION,
        "normalization_run_id": run_id,
        "synthesis": "暂无可自动接受的时间线点。",
        "timeline_group_count": 0,
        "timeline_point_count": 0,
        "evidence_refs": [],
        "warnings": [],
    }


def evidence_refs_from_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = [
        {
            "result_id": point["result_id"],
            "claim_id": point["claim_id"],
            "source_id": point["source_id"],
            "paper_id": point["paper_id"],
            "citation_locator": point["citation_locator"],
        }
        for point in points
    ]
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for ref in refs:
        unique[(ref["result_id"], ref["claim_id"], ref["source_id"], ref["citation_locator"])] = ref
    return list(unique.values())


def warning(code: str, message: str, *, severity: str = "warning") -> dict[str, Any]:
    return {
        "schema_version": METRIC_NORMALIZATION_WARNING_SCHEMA_VERSION,
        "code": code,
        "severity": severity,
        "message": message,
    }


def wrap_external_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in warnings:
        result.append(
            warning(
                f"upstream_{item.get('code') or 'warning'}",
                str(item.get("message") or item),
                severity=str(item.get("severity") or "warning"),
            )
        )
    return result


def dedupe_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in warnings:
        key = (str(item.get("code") or ""), str(item.get("message") or ""), str(item.get("severity") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def first_or_empty(values: list[Any]) -> str:
    return str(values[0]) if values else ""
