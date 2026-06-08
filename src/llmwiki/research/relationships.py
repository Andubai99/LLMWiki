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
from ..metrics.canonicalization import (
    MAX_LIMIT,
    MetricCanonicalizationCatalogError,
    MetricCanonicalizationFilterError,
    build_metric_canonicalization_report,
    normalize_canonical_metric_key,
)
from ..metrics.llm_normalization import (
    MetricNormalizationStagingError,
    build_metric_normalization_status,
)
from ..metrics.repair import MetricRepairCatalogError, build_metric_repair_plan
from ..providers.base import LLMProviderError
from ..workspace import utc_now
from .relationship_prompt import build_research_relationship_messages, research_relationship_schema


RESEARCH_RELATIONSHIP_RUN_SCHEMA_VERSION = "research_relationship_run.v5.0"
RESEARCH_RELATIONSHIP_BUNDLE_SCHEMA_VERSION = "research_relationship_bundle.v5.0"
RESEARCH_RELATIONSHIP_EDGE_SCHEMA_VERSION = "research_relationship_edge.v5.0"
RESEARCH_GRAPH_SCHEMA_VERSION = "research_graph.v5.0"
RESEARCH_SYNTHESIS_SCHEMA_VERSION = "research_synthesis.v5.0"
RESEARCH_RELATIONSHIP_WARNING_SCHEMA_VERSION = "research_relationship_warning.v5.0"

DEFAULT_LIMIT = 200
RESEARCH_MAX_LIMIT = 1000
DEFAULT_MAX_RESULTS_PER_BUNDLE = 40
RELATIONSHIP_TYPES = {
    "same_task",
    "same_benchmark",
    "same_metric",
    "compares_against",
    "improves_over",
    "extends_method",
    "uses_component",
    "addresses_limitation",
    "supports",
    "contradicts_or_tensions",
    "not_comparable",
    "background_related",
}
ENTITY_TYPES = {
    "paper",
    "method",
    "benchmark",
    "dataset",
    "task",
    "metric",
    "result",
    "claim",
    "component",
    "limitation",
    "concept",
}
DECISION_STATUSES = {"auto_accepted", "needs_review", "blocked", "conflict", "insufficient_evidence"}
CONFIDENCES = {"high", "medium", "low"}
COMPARABILITY_STATUSES = {"comparable", "partially_comparable", "not_comparable", "not_applicable", "unknown"}
SYNTHESIS_CONFIDENCES = {"high", "medium"}


class ResearchRelationshipFilterError(ValueError):
    """Invalid V5.0 research relationship filter."""


class ResearchRelationshipCatalogError(RuntimeError):
    """Catalog is unavailable or incompatible with V5.0 research graph."""


class ResearchRelationshipLLMError(RuntimeError):
    """LLM output is unsafe or incompatible with V5.0 research graph."""


class ResearchRelationshipStagingError(RuntimeError):
    """Research relationship staging run is missing or invalid."""


@dataclass
class ResearchRelationshipRun:
    root: str
    query: dict[str, Any]
    summary: dict[str, Any]
    relationship_bundles: list[dict[str, Any]]
    relationship_edges: list[dict[str, Any]]
    research_graph: dict[str, Any]
    research_synthesis: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    relationship_run_id: str = ""
    mode: str = "run"
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = RESEARCH_RELATIONSHIP_RUN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "relationship_run_id": self.relationship_run_id,
            "mode": self.mode,
            "query": self.query,
            "summary": self.summary,
            "relationship_bundle_count": len(self.relationship_bundles),
            "relationship_edge_count": len(self.relationship_edges),
            "warning_count": len(self.warnings),
            "relationship_bundles": self.relationship_bundles,
            "relationship_edges": self.relationship_edges,
            "research_graph": self.research_graph,
            "research_synthesis": self.research_synthesis,
            "warnings": self.warnings,
        }


@dataclass
class ResearchSynthesisResponse:
    root: str
    relationship_run_id: str
    summary: dict[str, Any]
    synthesis: str
    evidence_refs: list[dict[str, Any]]
    relationship_edges: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = RESEARCH_SYNTHESIS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "relationship_run_id": self.relationship_run_id,
            "summary": self.summary,
            "synthesis": self.synthesis,
            "evidence_refs": self.evidence_refs,
            "relationship_edges": self.relationship_edges,
            "warning_count": len(self.warnings),
            "warnings": self.warnings,
        }


def validate_limit_offset(limit: int | None, offset: int | None) -> tuple[int, int, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    resolved_limit = DEFAULT_LIMIT if limit is None else int(limit)
    resolved_offset = 0 if offset is None else int(offset)
    if resolved_limit <= 0:
        raise ResearchRelationshipFilterError("invalid limit: must be positive")
    if resolved_offset < 0:
        raise ResearchRelationshipFilterError("invalid offset: must be >= 0")
    if resolved_limit > RESEARCH_MAX_LIMIT:
        warnings.append(relationship_warning("limit_clamped", f"Limit clamped from {resolved_limit} to {RESEARCH_MAX_LIMIT}."))
        resolved_limit = RESEARCH_MAX_LIMIT
    return resolved_limit, resolved_offset, warnings


def build_research_relationship_dry_run(
    root: Path,
    *,
    topic: str | None = None,
    source_id: str | None = None,
    paper_id: str | None = None,
    relationship_type: str | None = None,
    metric: str | None = None,
    dataset: str | None = None,
    task: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    max_bundles: int | None = None,
    max_results_per_bundle: int | None = None,
    reuse_normalization_run: str | None = None,
) -> ResearchRelationshipRun:
    root = root.resolve()
    resolved_limit, resolved_offset, warnings = validate_limit_offset(limit, offset)
    bundles, build_summary, build_warnings = build_relationship_bundles(
        root,
        topic=topic,
        source_id=source_id,
        paper_id=paper_id,
        relationship_type=relationship_type,
        metric=metric,
        dataset=dataset,
        task=task,
        limit=resolved_limit,
        offset=resolved_offset,
        max_bundles=max_bundles,
        max_results_per_bundle=max_results_per_bundle,
        reuse_normalization_run=reuse_normalization_run,
    )
    warnings.extend(build_warnings)
    summary = {
        **build_summary,
        "estimated_prompt_tokens": estimate_prompt_tokens(bundles),
        "estimated_completion_tokens": max(0, len(bundles) * 600),
        "provider_call_count": 0,
        "edge_count": 0,
        "accepted_edge_count": 0,
        "not_comparable_edge_count": 0,
    }
    return ResearchRelationshipRun(
        root=root.as_posix(),
        query=query_payload(
            topic,
            source_id,
            paper_id,
            relationship_type,
            metric,
            dataset,
            task,
            resolved_limit,
            resolved_offset,
            max_bundles,
            max_results_per_bundle,
            reuse_normalization_run,
        ),
        summary=summary,
        relationship_bundles=bundles,
        relationship_edges=[],
        research_graph=empty_research_graph(),
        research_synthesis=empty_research_synthesis(""),
        warnings=dedupe_warnings(warnings),
        mode="dry_run",
    )


def build_research_graph_run(
    root: Path,
    *,
    topic: str | None = None,
    source_id: str | None = None,
    paper_id: str | None = None,
    relationship_type: str | None = None,
    metric: str | None = None,
    dataset: str | None = None,
    task: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    max_bundles: int | None = None,
    max_results_per_bundle: int | None = None,
    reuse_normalization_run: str | None = None,
) -> ResearchRelationshipRun:
    root = root.resolve()
    dry_run = build_research_relationship_dry_run(
        root,
        topic=topic,
        source_id=source_id,
        paper_id=paper_id,
        relationship_type=relationship_type,
        metric=metric,
        dataset=dataset,
        task=task,
        limit=limit,
        offset=offset,
        max_bundles=max_bundles,
        max_results_per_bundle=max_results_per_bundle,
        reuse_normalization_run=reuse_normalization_run,
    )
    config = load_llm_config(root)
    if not config.enabled:
        raise ResearchRelationshipLLMError("LLM provider is disabled.")
    provider = create_provider(config, root=root)
    provider_name = config.provider
    model_name = config.model
    total_tokens = 0
    edges: list[dict[str, Any]] = []
    warnings = list(dry_run.warnings)
    for bundle in dry_run.relationship_bundles:
        try:
            response = provider.complete(build_research_relationship_messages(bundle), schema=research_relationship_schema())
        except LLMProviderError as exc:
            raise ResearchRelationshipLLMError(str(exc)) from exc
        provider_name = str(response.get("provider") or provider_name)
        model_name = str(response.get("model") or model_name)
        usage = response.get("usage") or {}
        if isinstance(usage, dict):
            total_tokens += int(usage.get("total_tokens") or usage.get("completion_tokens") or 0)
        payload = parse_provider_json(response)
        bundle_edges, bundle_warnings = validate_relationship_edges(bundle, payload)
        edges.extend(bundle_edges)
        warnings.extend(bundle_warnings)

    graph = build_research_graph_payload(edges, warnings)
    synthesis = build_research_synthesis_payload("", edges, warnings)
    run_id = create_relationship_run_id(dry_run.query, edges)
    run = ResearchRelationshipRun(
        root=root.as_posix(),
        query=dry_run.query,
        summary=build_run_summary(dry_run.summary, edges, provider_name, model_name, total_tokens),
        relationship_bundles=dry_run.relationship_bundles,
        relationship_edges=edges,
        research_graph={**graph, "relationship_run_id": run_id},
        research_synthesis={**synthesis, "relationship_run_id": run_id},
        warnings=dedupe_warnings(warnings),
        relationship_run_id=run_id,
        mode="run",
    )
    stage_research_graph_run(root, run, provider_name=provider_name, model_name=model_name)
    return run


def build_relationship_bundles(
    root: Path,
    *,
    topic: str | None,
    source_id: str | None,
    paper_id: str | None,
    relationship_type: str | None,
    metric: str | None,
    dataset: str | None,
    task: str | None,
    limit: int,
    offset: int,
    max_bundles: int | None,
    max_results_per_bundle: int | None,
    reuse_normalization_run: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    if relationship_type and relationship_type not in RELATIONSHIP_TYPES:
        raise ResearchRelationshipFilterError(f"invalid relationship-type: {relationship_type}")
    max_results = DEFAULT_MAX_RESULTS_PER_BUNDLE if max_results_per_bundle is None else int(max_results_per_bundle)
    if max_results <= 0:
        raise ResearchRelationshipFilterError("invalid max-results-per-bundle: must be positive")
    if max_bundles is not None and int(max_bundles) <= 0:
        raise ResearchRelationshipFilterError("invalid max-bundles: must be positive")
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
        raise ResearchRelationshipCatalogError(str(exc)) from exc
    warnings.extend(wrap_external_warnings(evidence.get("warnings", [])))
    warnings.extend(wrap_external_warnings(canonicalization.get("warnings", [])))
    warnings.extend(wrap_external_warnings(repair_plan.get("warnings", [])))
    normalization = load_normalization_run(root, reuse_normalization_run, warnings)
    items = [item for item in list(evidence.get("items") or []) if matches_topic(item, topic)]
    paper_by_id = paper_identity_by_id(root, warnings)
    proposals_by_result = group_repair_proposals_by_result(repair_plan.get("proposals", []))
    normalization_by_result = group_normalization_by_result(normalization)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[bundle_group_key(item)].append(item)
    group_keys = sorted(grouped)
    unpaged_count = len(group_keys)
    group_keys = group_keys[offset : offset + limit]
    if max_bundles is not None:
        group_keys = group_keys[: int(max_bundles)]

    bundles: list[dict[str, Any]] = []
    for group_key in group_keys:
        rows = grouped[group_key][:max_results]
        bundle = relationship_bundle_payload(
            group_key,
            rows,
            topic=topic,
            paper_by_id=paper_by_id,
            proposals_by_result=proposals_by_result,
            normalization_by_result=normalization_by_result,
            truncated_count=max(0, len(grouped[group_key]) - len(rows)),
        )
        if relationship_type and relationship_type not in bundle["candidate_relationship_types"]:
            continue
        bundles.append(bundle)
    if not bundles:
        warnings.append(relationship_warning("no_relationship_bundles", "No relationship bundles matched the query."))
    summary = {
        "metric_result_count": len(items),
        "relationship_bundle_count_unpaged": unpaged_count,
        "relationship_bundle_count": len(bundles),
        "truncated_result_count": sum(int(bundle.get("truncated_result_count") or 0) for bundle in bundles),
        "candidate_edge_estimate": sum(len(bundle.get("candidate_relationship_types") or []) for bundle in bundles),
        "canonical_metric_count": int(canonicalization.get("summary", {}).get("canonical_metric_count_unpaged") or 0),
        "repair_proposal_count": int(repair_plan.get("summary", {}).get("proposal_count_unpaged") or 0),
    }
    return bundles, summary, warnings


def relationship_bundle_payload(
    group_key: str,
    rows: list[dict[str, Any]],
    *,
    topic: str | None,
    paper_by_id: dict[str, dict[str, Any]],
    proposals_by_result: dict[str, list[dict[str, Any]]],
    normalization_by_result: dict[str, list[dict[str, Any]]],
    truncated_count: int,
) -> dict[str, Any]:
    result_rows = [result_row_payload(row) for row in rows]
    candidate_types = candidate_relationship_types(rows)
    papers: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("paper_id") or row.get("source_id") or "")
        paper = paper_by_id.get(key) or paper_by_id.get(str(row.get("source_id") or ""))
        if paper:
            papers[key] = paper_identity_payload(paper)
    repair_proposals: list[dict[str, Any]] = []
    normalization_decisions: list[dict[str, Any]] = []
    for row in rows:
        result_id = str(row.get("result_id") or "")
        repair_proposals.extend(proposals_by_result.get(result_id, []))
        normalization_decisions.extend(normalization_by_result.get(result_id, []))
    payload = {
        "schema_version": RESEARCH_RELATIONSHIP_BUNDLE_SCHEMA_VERSION,
        "bundle_id": relationship_bundle_id(group_key, result_rows),
        "bundle_type": bundle_type_for_candidate_types(candidate_types),
        "candidate_relationship_types": candidate_types,
        "candidate_group_key": group_key,
        "topic": topic or "",
        "result_count": len(result_rows),
        "truncated_result_count": truncated_count,
        "paper_identities": sorted(papers.values(), key=lambda item: (str(item.get("year") or ""), item.get("paper_id", ""))),
        "result_rows": result_rows,
        "context_refs": [context_ref_payload(row) for row in rows if str(row.get("citation_locator") or "")],
        "repair_proposals": repair_proposals,
        "normalization_decisions": normalization_decisions,
        "warnings": [],
    }
    return payload


def validate_relationship_edges(bundle: dict[str, Any], payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_edges = payload.get("edges")
    if not isinstance(raw_edges, list):
        raise ResearchRelationshipLLMError("LLM response must contain edges list.")
    allowed_refs = allowed_evidence_refs(bundle)
    warnings: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    row_by_ref = {evidence_ref_key(row): row for row in bundle.get("result_rows", []) if isinstance(row, dict)}
    for raw in raw_edges:
        if not isinstance(raw, dict):
            warnings.append(relationship_warning("invalid_edge_item", "Skipped non-object relationship edge."))
            continue
        evidence_refs = normalize_evidence_refs(raw.get("evidence_refs") or [])
        if not evidence_refs:
            warnings.append(relationship_warning("missing_evidence_refs", "Skipped edge without evidence refs."))
            continue
        if any(evidence_ref_key(ref) not in allowed_refs for ref in evidence_refs):
            warnings.append(relationship_warning("fabricated_evidence_ref", "Skipped edge with evidence refs outside the bundle."))
            continue
        status = normalize_choice(raw.get("decision_status"), DECISION_STATUSES, fallback="needs_review")
        confidence, confidence_warnings = normalize_confidence(raw.get("confidence"), status)
        warnings.extend(confidence_warnings)
        comparability = normalize_choice(raw.get("comparability_status"), COMPARABILITY_STATUSES, fallback="unknown")
        relationship_type = normalize_choice(raw.get("relationship_type"), RELATIONSHIP_TYPES, fallback="background_related")
        if status == "auto_accepted" and not evidence_refs:
            status = "insufficient_evidence"
        first_row = row_by_ref.get(evidence_ref_key(evidence_refs[0]), {})
        subject, object_ = fallback_subject_object(raw, relationship_type, first_row)
        edge = {
            "schema_version": RESEARCH_RELATIONSHIP_EDGE_SCHEMA_VERSION,
            "relationship_type": relationship_type,
            "subject": subject,
            "object": object_,
            "source_ids": sorted({ref["source_id"] for ref in evidence_refs if ref["source_id"]}),
            "paper_ids": sorted({ref["paper_id"] for ref in evidence_refs if ref["paper_id"]}),
            "claim_ids": sorted({ref["claim_id"] for ref in evidence_refs if ref["claim_id"]}),
            "result_ids": sorted({ref["result_id"] for ref in evidence_refs if ref["result_id"]}),
            "citation_locators": sorted({ref["citation_locator"] for ref in evidence_refs if ref["citation_locator"]}),
            "evidence_refs": evidence_refs,
            "confidence": confidence,
            "decision_status": status,
            "comparability_status": comparability,
            "rationale": str(raw.get("rationale") or default_rationale(relationship_type, first_row))[:500],
            "warnings": normalize_warning_list(raw.get("warnings") or []),
        }
        edge["relationship_id"] = relationship_edge_id(edge)
        edges.append(edge)
    return edges, warnings


def build_research_graph_status(root: Path, relationship_run_id: str) -> ResearchRelationshipRun:
    root = root.resolve()
    run_dir = relationship_run_dir(root, relationship_run_id)
    run_path = run_dir / "run.json"
    bundles_path = run_dir / "relationship-bundles.jsonl"
    edges_path = run_dir / "relationship-edges.jsonl"
    graph_path = run_dir / "research-graph.json"
    synthesis_path = run_dir / "research-synthesis.json"
    if not run_path.exists() or not bundles_path.exists() or not edges_path.exists():
        raise ResearchRelationshipStagingError(f"missing research graph artifacts: {relationship_run_id}")
    run_manifest = json.loads(run_path.read_text(encoding="utf-8"))
    bundles = read_jsonl(bundles_path)
    edges = read_jsonl(edges_path)
    warnings = read_jsonl(run_dir / "warnings.jsonl")
    graph = json.loads(graph_path.read_text(encoding="utf-8")) if graph_path.exists() else build_research_graph_payload(edges, warnings)
    synthesis = json.loads(synthesis_path.read_text(encoding="utf-8")) if synthesis_path.exists() else build_research_synthesis_payload(relationship_run_id, edges, warnings)
    summary = {
        **dict(run_manifest.get("summary") or {}),
        **edge_summary(edges),
    }
    return ResearchRelationshipRun(
        root=root.as_posix(),
        query=dict(run_manifest.get("query") or {}),
        summary=summary,
        relationship_bundles=bundles,
        relationship_edges=edges,
        research_graph=graph,
        research_synthesis=synthesis,
        warnings=warnings,
        relationship_run_id=relationship_run_id,
        mode=str(run_manifest.get("mode") or "run"),
        generated_at=str(run_manifest.get("generated_at") or utc_now()),
    )


def build_research_synthesis_response(root: Path, relationship_run_id: str, *, topic: str | None = None) -> ResearchSynthesisResponse:
    status = build_research_graph_status(root, relationship_run_id)
    edges = filter_edges_by_topic(status.relationship_edges, topic)
    synthesis_payload = build_research_synthesis_payload(relationship_run_id, edges, status.warnings, topic=topic)
    return ResearchSynthesisResponse(
        root=status.root,
        relationship_run_id=relationship_run_id,
        summary=dict(synthesis_payload.get("summary") or {}),
        synthesis=str(synthesis_payload.get("synthesis") or ""),
        evidence_refs=list(synthesis_payload.get("evidence_refs") or []),
        relationship_edges=edges,
        warnings=list(status.warnings),
        generated_at=utc_now(),
    )


def stage_research_graph_run(root: Path, run: ResearchRelationshipRun, *, provider_name: str, model_name: str) -> None:
    run_dir = root / "staging" / run.relationship_run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": RESEARCH_RELATIONSHIP_RUN_SCHEMA_VERSION,
        "run_type": "research_relationship_graph",
        "status": "staged",
        "relationship_run_id": run.relationship_run_id,
        "generated_at": run.generated_at,
        "mode": run.mode,
        "query": run.query,
        "summary": run.summary,
        "provider": provider_name,
        "model": model_name,
    }
    write_json(run_dir / "run.json", manifest)
    write_jsonl(run_dir / "relationship-bundles.jsonl", run.relationship_bundles)
    write_jsonl(run_dir / "relationship-edges.jsonl", run.relationship_edges)
    write_json(run_dir / "research-graph.json", run.research_graph)
    write_json(run_dir / "research-synthesis.json", run.research_synthesis)
    write_jsonl(run_dir / "warnings.jsonl", run.warnings)
    (run_dir / "triage.md").write_text(format_research_triage(run), encoding="utf-8")


def parse_provider_json(response: dict[str, Any]) -> dict[str, Any]:
    content = str(response.get("content") or "")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ResearchRelationshipLLMError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ResearchRelationshipLLMError("LLM response must be a JSON object.")
    return parsed


def build_research_graph_payload(edges: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": RESEARCH_GRAPH_SCHEMA_VERSION,
        "relationship_run_id": "",
        "edge_count": len(edges),
        "edge_counts_by_type": dict(sorted(Counter(edge.get("relationship_type") for edge in edges).items())),
        "edge_counts_by_status": dict(sorted(Counter(edge.get("decision_status") for edge in edges).items())),
        "edges": edges,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def build_research_synthesis_payload(
    relationship_run_id: str,
    edges: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    *,
    topic: str | None = None,
) -> dict[str, Any]:
    selected = [
        edge
        for edge in edges
        if edge.get("decision_status") == "auto_accepted" and edge.get("confidence") in SYNTHESIS_CONFIDENCES and edge.get("evidence_refs")
    ]
    if topic:
        selected = filter_edges_by_topic(selected, topic)
    lines: list[str] = []
    evidence_refs: list[dict[str, Any]] = []
    for edge in selected[:20]:
        ref = edge["evidence_refs"][0]
        evidence_refs.append(ref)
        lines.append(
            f"- {edge['relationship_type']}: {edge['subject']['label']} -> {edge['object']['label']}，"
            f"证据 `{ref.get('result_id') or ref.get('claim_id')}` / `{ref.get('source_id')}` / `{ref.get('citation_locator')}`。"
        )
    not_comparable = [edge for edge in edges if edge.get("relationship_type") == "not_comparable"]
    if not_comparable:
        edge = not_comparable[0]
        ref = edge["evidence_refs"][0] if edge.get("evidence_refs") else {}
        if ref:
            evidence_refs.append(ref)
        lines.append(f"- not_comparable: {edge.get('rationale') or '存在不可直接比较的证据。'}")
    synthesis = "\n".join(lines) if lines else "暂无可综合的 source-backed research relationships。"
    unique_refs = dedupe_refs(evidence_refs)
    return {
        "schema_version": RESEARCH_SYNTHESIS_SCHEMA_VERSION,
        "relationship_run_id": relationship_run_id,
        "summary": {
            "edge_count": len(edges),
            "synthesis_item_count": len(lines),
            "synthesis_evidence_ref_count": len(unique_refs),
            "not_comparable_edge_count": len(not_comparable),
        },
        "synthesis": synthesis,
        "evidence_refs": unique_refs,
        "warnings": warnings,
    }


def build_run_summary(
    dry_summary: dict[str, Any],
    edges: list[dict[str, Any]],
    provider_name: str,
    model_name: str,
    total_tokens: int,
) -> dict[str, Any]:
    return {
        **dry_summary,
        **edge_summary(edges),
        "provider": provider_name,
        "model": model_name,
        "provider_call_count": dry_summary.get("relationship_bundle_count", 0),
        "llm_total_tokens": total_tokens,
    }


def edge_summary(edges: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(edge.get("decision_status") or "") for edge in edges)
    types = Counter(str(edge.get("relationship_type") or "") for edge in edges)
    confidences = Counter(str(edge.get("confidence") or "") for edge in edges)
    fabricated_count = sum(1 for edge in edges for warning in edge.get("warnings", []) if warning.get("code") == "fabricated_evidence_ref")
    unresolved_locator_count = sum(1 for edge in edges for ref in edge.get("evidence_refs", []) if not ref.get("citation_locator"))
    return {
        "edge_count": len(edges),
        "accepted_edge_count": statuses.get("auto_accepted", 0),
        "needs_review_edge_count": statuses.get("needs_review", 0),
        "blocked_edge_count": statuses.get("blocked", 0),
        "conflict_edge_count": statuses.get("conflict", 0),
        "insufficient_evidence_edge_count": statuses.get("insufficient_evidence", 0),
        "not_comparable_edge_count": types.get("not_comparable", 0),
        "edge_counts_by_type": dict(sorted(types.items())),
        "edge_counts_by_status": dict(sorted(statuses.items())),
        "edge_counts_by_confidence": dict(sorted(confidences.items())),
        "edge_evidence_ref_count": sum(len(edge.get("evidence_refs") or []) for edge in edges),
        "fabricated_reference_count": fabricated_count,
        "unresolved_locator_count": unresolved_locator_count,
    }


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
        "method": str(row.get("method") or ""),
        "dataset": str(row.get("dataset") or ""),
        "task": str(row.get("task") or ""),
        "baseline": str(row.get("baseline") or ""),
        "reported_year": row.get("reported_year"),
        "confidence_status": str(row.get("confidence_status") or ""),
        "context_preview": str(row.get("context_preview") or "")[:500],
        "context_block_role": str(row.get("context_block_role") or ""),
    }


def context_ref_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": str(row.get("result_id") or ""),
        "claim_id": str(row.get("claim_id") or ""),
        "source_id": str(row.get("source_id") or ""),
        "paper_id": str(row.get("paper_id") or row.get("source_id") or ""),
        "citation_locator": str(row.get("citation_locator") or ""),
        "page_path": str(row.get("page_path") or ""),
        "context_preview": str(row.get("context_preview") or "")[:500],
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


def candidate_relationship_types(rows: list[dict[str, Any]]) -> list[str]:
    types = {"same_metric", "same_benchmark", "same_task", "not_comparable", "background_related"}
    if any(str(row.get("baseline") or "").strip() for row in rows):
        types.add("compares_against")
    if len({normalize_key(row.get("dataset")) for row in rows}) > 1:
        types.add("not_comparable")
    return sorted(types)


def bundle_type_for_candidate_types(types: list[str]) -> str:
    if "same_benchmark" in types:
        return "same_benchmark_bundle"
    if "same_metric" in types:
        return "same_metric_bundle"
    if "compares_against" in types:
        return "baseline_comparison_bundle"
    if "not_comparable" in types:
        return "not_comparable_bundle"
    return "topic_cluster_bundle"


def bundle_group_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            normalize_key(row.get("metric_name")),
            normalize_key(row.get("dataset")),
            normalize_key(row.get("task")),
        ]
    )


def matches_topic(item: dict[str, Any], topic: str | None) -> bool:
    if not topic:
        return True
    needle = normalize_key(topic)
    haystack = " ".join(str(item.get(key) or "") for key in ("metric_name", "dataset", "task", "method", "claim_text", "context_preview"))
    return needle in normalize_key(haystack)


def normalize_key(value: Any) -> str:
    return normalize_canonical_metric_key(str(value or "")) or "unknown"


def allowed_evidence_refs(bundle: dict[str, Any]) -> set[tuple[str, str, str, str, str]]:
    refs = set()
    for row in bundle.get("result_rows", []):
        if not isinstance(row, dict):
            continue
        ref = {
            "result_id": str(row.get("result_id") or ""),
            "claim_id": str(row.get("claim_id") or ""),
            "source_id": str(row.get("source_id") or ""),
            "paper_id": str(row.get("paper_id") or row.get("source_id") or ""),
            "citation_locator": str(row.get("citation_locator") or ""),
        }
        refs.add(evidence_ref_key(ref))
    for ref in bundle.get("context_refs", []):
        if not isinstance(ref, dict):
            continue
        refs.add(evidence_ref_key(ref))
    return refs


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
                "paper_id": str(item.get("paper_id") or item.get("source_id") or ""),
                "citation_locator": str(item.get("citation_locator") or ""),
            }
        )
    return refs


def evidence_ref_key(ref: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(ref.get("result_id") or ""),
        str(ref.get("claim_id") or ""),
        str(ref.get("source_id") or ""),
        str(ref.get("paper_id") or ref.get("source_id") or ""),
        str(ref.get("citation_locator") or ""),
    )


def normalize_entity(value: dict[str, Any]) -> dict[str, str]:
    entity_type = str(value.get("entity_type") or "concept")
    if entity_type not in ENTITY_TYPES:
        entity_type = "concept"
    entity_id = str(value.get("entity_id") or value.get("label") or entity_type)
    label = str(value.get("label") or entity_id)
    return {"entity_type": entity_type, "entity_id": entity_id[:200], "label": label[:200]}


def fallback_subject_object(raw: dict[str, Any], relationship_type: str, row: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    subject = normalize_entity(raw.get("subject") or {})
    object_ = normalize_entity(raw.get("object") or {})
    if is_empty_entity(subject):
        subject = default_subject(row, relationship_type)
    if is_empty_entity(object_):
        object_ = default_object(row, relationship_type)
    return subject, object_


def is_empty_entity(entity: dict[str, str]) -> bool:
    return entity.get("entity_type") == "concept" and entity.get("entity_id") == "concept" and entity.get("label") == "concept"


def default_subject(row: dict[str, Any], relationship_type: str) -> dict[str, str]:
    if relationship_type in {"same_metric", "same_benchmark", "same_task", "background_related"}:
        paper_id = str(row.get("paper_id") or row.get("source_id") or "paper")
        return {"entity_type": "paper", "entity_id": paper_id, "label": paper_id}
    if relationship_type in {"not_comparable", "compares_against", "improves_over"}:
        result_id = str(row.get("result_id") or "result")
        return {"entity_type": "result", "entity_id": result_id, "label": str(row.get("method") or result_id)}
    method = str(row.get("method") or row.get("paper_id") or row.get("source_id") or "method")
    return {"entity_type": "method", "entity_id": normalize_key(method), "label": method[:200]}


def default_object(row: dict[str, Any], relationship_type: str) -> dict[str, str]:
    if relationship_type == "same_metric":
        label = str(row.get("metric_name") or "metric")
        return {"entity_type": "metric", "entity_id": normalize_key(label), "label": label[:200]}
    if relationship_type == "same_benchmark":
        label = str(row.get("dataset") or "benchmark")
        return {"entity_type": "benchmark", "entity_id": normalize_key(label), "label": label[:200]}
    if relationship_type == "same_task":
        label = str(row.get("task") or "task")
        return {"entity_type": "task", "entity_id": normalize_key(label), "label": label[:200]}
    if relationship_type in {"compares_against", "improves_over"}:
        label = str(row.get("baseline") or "baseline")
        return {"entity_type": "method", "entity_id": normalize_key(label), "label": label[:200]}
    if relationship_type == "not_comparable":
        label = str(row.get("dataset") or row.get("metric_name") or "comparison setting")
        return {"entity_type": "dataset", "entity_id": normalize_key(label), "label": label[:200]}
    label = str(row.get("metric_name") or row.get("dataset") or row.get("task") or "concept")
    return {"entity_type": "concept", "entity_id": normalize_key(label), "label": label[:200]}


def default_rationale(relationship_type: str, row: dict[str, Any]) -> str:
    if not row:
        return "Relationship is based on the cited bundle evidence."
    metric = str(row.get("metric_name") or "")
    dataset = str(row.get("dataset") or "")
    task = str(row.get("task") or "")
    return f"Relationship {relationship_type} is grounded in cited result evidence for {metric} / {dataset} / {task}."


def normalize_warning_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(
                relationship_warning(
                    str(item.get("code") or "llm_warning"),
                    str(item.get("message") or item.get("reason") or "")[:500],
                    severity=str(item.get("severity") or "warning"),
                )
            )
        elif item:
            normalized.append(relationship_warning("llm_warning", str(item)[:500]))
    return normalized


def normalize_choice(value: Any, allowed: set[str], *, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else fallback


def normalize_confidence(value: Any, status: str) -> tuple[str, list[dict[str, Any]]]:
    text = str(value or "").strip()
    if text in CONFIDENCES:
        return text, []
    if status == "auto_accepted":
        return "medium", [relationship_warning("missing_confidence_defaulted", "Auto-accepted edge had missing or invalid confidence; defaulted to medium.")]
    return "low", []


def paper_identity_by_id(root: Path, warnings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    try:
        inventory = build_inventory(root).to_dict()
    except Exception as exc:
        warnings.append(relationship_warning("inventory_unavailable", f"Paper inventory unavailable: {exc}"))
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


def group_normalization_by_result(normalization: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in normalization.get("decisions", []) if normalization else []:
        for result_id in decision.get("result_ids", []):
            grouped[str(result_id)].append(
                {
                    "decision_id": decision.get("decision_id"),
                    "canonical_metric_name": decision.get("canonical_metric_name"),
                    "canonical_dataset_name": decision.get("canonical_dataset_name"),
                    "canonical_task_name": decision.get("canonical_task_name"),
                    "decision_status": decision.get("decision_status"),
                    "confidence": decision.get("confidence"),
                    "timeline_year": decision.get("timeline_year"),
                }
            )
    return grouped


def load_normalization_run(root: Path, run_id: str | None, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    if not run_id:
        return {}
    try:
        return build_metric_normalization_status(root, run_id).to_dict()
    except MetricNormalizationStagingError as exc:
        warnings.append(relationship_warning("normalization_run_unavailable", str(exc)))
        return {}


def wrap_external_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wrapped: list[dict[str, Any]] = []
    for item in warnings:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "upstream_warning")
        message = str(item.get("message") or code)
        severity = str(item.get("severity") or "warning")
        wrapped.append(relationship_warning(f"upstream_{code}", message[:500], severity=severity))
    return wrapped


def relationship_warning(code: str, message: str, *, severity: str = "warning") -> dict[str, Any]:
    return {
        "schema_version": RESEARCH_RELATIONSHIP_WARNING_SCHEMA_VERSION,
        "code": code,
        "message": message,
        "severity": severity,
    }


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


def dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for ref in refs:
        key = evidence_ref_key(ref)
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def filter_edges_by_topic(edges: list[dict[str, Any]], topic: str | None) -> list[dict[str, Any]]:
    if not topic:
        return list(edges)
    needle = normalize_key(topic)
    return [
        edge
        for edge in edges
        if needle
        in normalize_key(
            " ".join(
                [
                    str(edge.get("relationship_type") or ""),
                    str(edge.get("rationale") or ""),
                    str(edge.get("subject", {}).get("label") or ""),
                    str(edge.get("object", {}).get("label") or ""),
                ]
            )
        )
    ]


def relationship_edge_id(edge: dict[str, Any]) -> str:
    payload = {key: value for key, value in edge.items() if key not in {"relationship_id"}}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "rr_edge_" + hashlib.sha256(encoded).hexdigest()[:12]


def relationship_bundle_id(group_key: str, rows: list[dict[str, Any]]) -> str:
    payload = {"group_key": group_key, "result_ids": [row["result_id"] for row in rows]}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "rrb_" + hashlib.sha256(encoded).hexdigest()[:12]


def create_relationship_run_id(query: dict[str, Any], edges: list[dict[str, Any]]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    seed = json.dumps({"query": query, "edge_ids": [edge["relationship_id"] for edge in edges]}, sort_keys=True)
    return f"run_research_graph_{now}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:8]}"


def relationship_run_dir(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"run_research_graph_\d{14}_[0-9a-f]{8}", run_id):
        raise ResearchRelationshipStagingError(f"invalid research graph run id: {run_id}")
    run_dir = root.resolve() / "staging" / run_id
    if not run_dir.exists():
        raise ResearchRelationshipStagingError(f"missing research graph run: {run_id}")
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
        if line.strip():
            rows.append(json.loads(line))
    return rows


def query_payload(
    topic: str | None,
    source_id: str | None,
    paper_id: str | None,
    relationship_type: str | None,
    metric: str | None,
    dataset: str | None,
    task: str | None,
    limit: int,
    offset: int,
    max_bundles: int | None,
    max_results_per_bundle: int | None,
    reuse_normalization_run: str | None,
) -> dict[str, Any]:
    return {
        "topic": topic or "",
        "source_id": source_id or "",
        "paper_id": paper_id or "",
        "relationship_type": relationship_type or "",
        "metric": metric or "",
        "dataset": dataset or "",
        "task": task or "",
        "limit": limit,
        "offset": offset,
        "max_bundles": max_bundles,
        "max_results_per_bundle": max_results_per_bundle or DEFAULT_MAX_RESULTS_PER_BUNDLE,
        "reuse_normalization_run": reuse_normalization_run or "",
    }


def empty_research_graph() -> dict[str, Any]:
    return {
        "schema_version": RESEARCH_GRAPH_SCHEMA_VERSION,
        "relationship_run_id": "",
        "edge_count": 0,
        "edge_counts_by_type": {},
        "edge_counts_by_status": {},
        "edges": [],
        "warning_count": 0,
        "warnings": [],
    }


def empty_research_synthesis(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": RESEARCH_SYNTHESIS_SCHEMA_VERSION,
        "relationship_run_id": run_id,
        "summary": {"edge_count": 0, "synthesis_item_count": 0, "synthesis_evidence_ref_count": 0, "not_comparable_edge_count": 0},
        "synthesis": "暂无可综合的 source-backed research relationships。",
        "evidence_refs": [],
        "warnings": [],
    }


def estimate_prompt_tokens(bundles: list[dict[str, Any]]) -> int:
    chars = sum(len(json.dumps(bundle, ensure_ascii=False)) for bundle in bundles)
    return max(0, chars // 4)


def format_research_triage(run: ResearchRelationshipRun) -> str:
    summary = run.summary
    lines = [
        "# Research Relationship Graph Triage",
        "",
        f"- run_id: `{run.relationship_run_id}`",
        f"- relationship_bundle_count: `{len(run.relationship_bundles)}`",
        f"- edge_count: `{summary.get('edge_count', 0)}`",
        f"- accepted_edge_count: `{summary.get('accepted_edge_count', 0)}`",
        f"- not_comparable_edge_count: `{summary.get('not_comparable_edge_count', 0)}`",
        "",
        "## Edges",
    ]
    for edge in run.relationship_edges[:50]:
        refs = edge.get("evidence_refs") or []
        ref = refs[0] if refs else {}
        lines.append(
            f"- `{edge['relationship_type']}` `{edge['decision_status']}` {edge['subject']['label']} -> {edge['object']['label']} "
            f"`{ref.get('result_id') or ref.get('claim_id')}` `{ref.get('source_id')}` `{ref.get('citation_locator')}`"
        )
    if not run.relationship_edges:
        lines.append("- none")
    return "\n".join(lines) + "\n"
