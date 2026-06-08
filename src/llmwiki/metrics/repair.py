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


METRIC_REPAIR_PLAN_SCHEMA_VERSION = "metric_repair_plan.v4.8"
METRIC_REPAIR_PROPOSAL_SCHEMA_VERSION = "metric_repair_proposal.v4.8"
METRIC_REPAIR_DECISION_SCHEMA_VERSION = "metric_repair_review_decision.v4.8"
METRIC_REPAIR_PROJECTION_SCHEMA_VERSION = "metric_repair_projection.v4.8"
METRIC_REPAIR_WARNING_SCHEMA_VERSION = "metric_repair_warning.v4.8"
METRIC_REPAIR_RUN_SCHEMA_VERSION = "metric_repair_run.v4.8"

DEFAULT_LIMIT = 200
REPAIR_MAX_LIMIT = 1000
SPLIT_WORDS = {"test", "train", "dev", "subset", "sub", "full", "mini", "pro", "version", "v1", "v2", "v3"}
VAGUE_METRIC_KEYS = {"score", "avg", "overall", "performance", "result", "metric", "value"}
DECISION_STATUSES = {"accepted", "rejected", "needs_review", "blocked"}


class MetricRepairFilterError(ValueError):
    """Invalid V4.8 metric repair filter."""


class MetricRepairCatalogError(RuntimeError):
    """Catalog is unavailable or incompatible with V4.8 metric repair review."""


class MetricRepairStagingError(RuntimeError):
    """Metric repair staging run is missing or invalid."""


@dataclass
class MetricRepairPlan:
    root: str
    query: dict[str, Any]
    summary: dict[str, Any]
    proposals: list[dict[str, Any]]
    projections: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    repair_run_id: str = ""
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = METRIC_REPAIR_PLAN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "repair_run_id": self.repair_run_id,
            "query": self.query,
            "summary": self.summary,
            "proposal_count": len(self.proposals),
            "projection_count": len(self.projections),
            "warning_count": len(self.warnings),
            "proposals": self.proposals,
            "projections": self.projections,
            "warnings": self.warnings,
        }
        return payload


def validate_limit_offset(limit: int | None, offset: int | None) -> tuple[int, int, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    resolved_limit = DEFAULT_LIMIT if limit is None else int(limit)
    resolved_offset = 0 if offset is None else int(offset)
    if resolved_limit <= 0:
        raise MetricRepairFilterError("invalid limit: must be positive")
    if resolved_offset < 0:
        raise MetricRepairFilterError("invalid offset: must be >= 0")
    if resolved_limit > REPAIR_MAX_LIMIT:
        warnings.append(warning("limit_clamped", f"Limit clamped from {resolved_limit} to {REPAIR_MAX_LIMIT}."))
        resolved_limit = REPAIR_MAX_LIMIT
    return resolved_limit, resolved_offset, warnings


def build_metric_repair_plan(
    root: Path,
    *,
    metric: str | None = None,
    dataset: str | None = None,
    task: str | None = None,
    proposal_type: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> MetricRepairPlan:
    root = root.resolve()
    resolved_limit, resolved_offset, warnings = validate_limit_offset(limit, offset)
    try:
        canonicalization = build_metric_canonicalization_report(
            root,
            metric=metric,
            dataset=dataset,
            task=task,
            limit=MAX_LIMIT,
            offset=0,
        ).to_dict()
        evidence = build_result_evidence_quality(
            root,
            metric=metric,
            dataset=dataset,
            task=task,
            limit=MAX_LIMIT,
            offset=0,
        ).to_dict()
    except (MetricCanonicalizationCatalogError, MetricCanonicalizationFilterError, ResultEvidenceCatalogError, ResultEvidenceFilterError) as exc:
        raise MetricRepairCatalogError(str(exc)) from exc

    warnings.extend(wrap_external_warnings(canonicalization.get("warnings", [])))
    warnings.extend(wrap_external_warnings(evidence.get("warnings", [])))
    items = list(evidence["items"])
    paper_by_id = paper_identity_by_id(root, warnings)
    repair_by_result_id = {
        str(repair.get("result_id") or ""): repair for repair in canonicalization.get("value_repairs", [])
    }

    proposals: list[dict[str, Any]] = []
    proposals.extend(year_repair_proposals(items, paper_by_id, repair_by_result_id, canonicalization))
    proposals.extend(value_repair_proposals(items, repair_by_result_id, canonicalization))
    proposals.extend(metric_alias_proposals(canonicalization))
    proposals.extend(dataset_alias_proposals(items, repair_by_result_id))
    proposals.extend(task_alias_proposals(items, repair_by_result_id))
    proposals.extend(blocked_vague_label_proposals(canonicalization))
    proposals = dedupe_proposals(proposals)
    proposals.sort(key=proposal_sort_key)
    if proposal_type:
        proposals = [proposal for proposal in proposals if proposal["proposal_type"] == proposal_type]

    projections = build_projections(canonicalization, proposals)
    if not proposals:
        warnings.append(warning("no_repair_proposals", "No metric repair proposals matched the query."))

    summary = build_summary(canonicalization, evidence, proposals, projections, warnings)
    return MetricRepairPlan(
        root=root.as_posix(),
        query={
            "metric": metric or "",
            "dataset": dataset or "",
            "task": task or "",
            "proposal_type": proposal_type or "",
            "limit": resolved_limit,
            "offset": resolved_offset,
        },
        summary=summary,
        proposals=page(proposals, resolved_limit, resolved_offset),
        projections=page(projections, resolved_limit, resolved_offset),
        warnings=dedupe_warnings(warnings),
    )


def stage_metric_repair_plan(root: Path, plan: MetricRepairPlan, *, label: str = "") -> MetricRepairPlan:
    root = root.resolve()
    if int(plan.summary.get("proposal_count_unpaged") or len(plan.proposals)) > len(plan.proposals):
        plan = build_metric_repair_plan(
            root,
            metric=plan.query.get("metric") or None,
            dataset=plan.query.get("dataset") or None,
            task=plan.query.get("task") or None,
            proposal_type=plan.query.get("proposal_type") or None,
            limit=REPAIR_MAX_LIMIT,
            offset=0,
        )
    run_id = create_repair_run_id(plan, label=label)
    run_dir = root / "staging" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    staged = MetricRepairPlan(
        root=plan.root,
        query=dict(plan.query),
        summary=dict(plan.summary),
        proposals=[dict(proposal) for proposal in plan.proposals],
        projections=[dict(projection) for projection in plan.projections],
        warnings=[dict(warning_item) for warning_item in plan.warnings],
        repair_run_id=run_id,
        generated_at=plan.generated_at,
    )
    manifest = {
        "schema_version": METRIC_REPAIR_RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "run_type": "metric_repair_review",
        "status": "staged",
        "label": label or "",
        "created_at": utc_now(),
        "proposal_count": len(staged.proposals),
        "projection_count": len(staged.projections),
    }
    write_json(run_dir / "run.json", manifest)
    write_json(run_dir / "metric-repair-plan.json", staged.to_dict())
    write_jsonl(run_dir / "metric-repair-proposals.jsonl", staged.proposals)
    (run_dir / "metric-repair-decisions.jsonl").write_text("", encoding="utf-8")
    (run_dir / "triage.md").write_text(format_repair_triage(staged), encoding="utf-8")
    return staged


def read_metric_repair_status(root: Path, repair_run_id: str) -> MetricRepairPlan:
    run_dir = repair_run_dir(root, repair_run_id)
    plan_path = run_dir / "metric-repair-plan.json"
    proposals_path = run_dir / "metric-repair-proposals.jsonl"
    if not plan_path.exists() or not proposals_path.exists():
        raise MetricRepairStagingError(f"missing metric repair plan artifacts: {repair_run_id}")
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    proposals = read_jsonl(proposals_path)
    decisions = read_decisions(root, repair_run_id)
    latest = latest_decision_by_proposal(decisions)
    proposals_with_decisions: list[dict[str, Any]] = []
    for proposal in proposals:
        current = latest.get(str(proposal.get("proposal_id") or ""))
        updated = dict(proposal)
        if current:
            updated["current_decision"] = current
            updated["review_status"] = current["status"]
        else:
            updated["current_decision"] = {}
        proposals_with_decisions.append(updated)

    summary = dict(plan_payload.get("summary") or {})
    current_status_counts = Counter(proposal["review_status"] for proposal in proposals_with_decisions)
    summary["decision_count"] = len(decisions)
    summary["accepted_proposal_count"] = current_status_counts.get("accepted", 0)
    summary["rejected_proposal_count"] = current_status_counts.get("rejected", 0)
    summary["needs_review_proposal_count"] = current_status_counts.get("needs_review", 0)
    summary["proposal_counts_by_status"] = dict(sorted(current_status_counts.items()))
    return MetricRepairPlan(
        root=str(plan_payload.get("root") or root.resolve().as_posix()),
        query=dict(plan_payload.get("query") or {}),
        summary=summary,
        proposals=proposals_with_decisions,
        projections=list(plan_payload.get("projections") or []),
        warnings=list(plan_payload.get("warnings") or []),
        repair_run_id=repair_run_id,
        generated_at=str(plan_payload.get("generated_at") or utc_now()),
    )


def append_metric_repair_decision(
    root: Path,
    repair_run_id: str,
    proposal_id: str,
    *,
    status: str,
    reason: str = "",
) -> dict[str, Any]:
    if status not in DECISION_STATUSES:
        raise MetricRepairStagingError(f"invalid repair decision status: {status}")
    run_dir = repair_run_dir(root, repair_run_id)
    proposals = read_jsonl(run_dir / "metric-repair-proposals.jsonl")
    if proposal_id not in {str(proposal.get("proposal_id") or "") for proposal in proposals}:
        raise MetricRepairStagingError(f"unknown metric repair proposal: {proposal_id}")
    decision_body = {
        "proposal_id": proposal_id,
        "status": status,
        "reason": reason or "",
        "decided_at": utc_now(),
    }
    decision = {
        "schema_version": METRIC_REPAIR_DECISION_SCHEMA_VERSION,
        "decision_id": decision_id_for_payload(decision_body),
        **decision_body,
    }
    with (run_dir / "metric-repair-decisions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n")
    return decision


def create_repair_run_id(plan: MetricRepairPlan, *, label: str = "") -> str:
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d%H%M%S")
    digest_payload = {
        "generated_at": plan.generated_at,
        "query": plan.query,
        "proposal_count": len(plan.proposals),
        "label": label or "",
        "timestamp": timestamp,
    }
    digest = hashlib.sha256(json.dumps(digest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    return f"run_metric_repair_{timestamp}_{digest}"


def repair_run_dir(root: Path, repair_run_id: str) -> Path:
    if not repair_run_id.startswith("run_metric_repair_"):
        raise MetricRepairStagingError(f"invalid metric repair run id: {repair_run_id}")
    staging_root = root.resolve() / "staging"
    run_dir = (staging_root / repair_run_id).resolve()
    try:
        run_dir.relative_to(staging_root.resolve())
    except ValueError as exc:
        raise MetricRepairStagingError(f"metric repair run is outside staging: {repair_run_id}") from exc
    if not run_dir.exists():
        raise MetricRepairStagingError(f"missing metric repair run: {repair_run_id}")
    return run_dir


def read_decisions(root: Path, repair_run_id: str) -> list[dict[str, Any]]:
    decisions_path = repair_run_dir(root, repair_run_id) / "metric-repair-decisions.jsonl"
    if not decisions_path.exists():
        return []
    return read_jsonl(decisions_path)


def latest_decision_by_proposal(decisions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        proposal_id = str(decision.get("proposal_id") or "")
        if proposal_id:
            latest[proposal_id] = decision
    return latest


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise MetricRepairStagingError(f"missing metric repair artifact: {path.name}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def format_repair_triage(plan: MetricRepairPlan) -> str:
    summary = plan.summary
    lines = [
        "# Metric Repair Review",
        "",
        f"- run_id: `{plan.repair_run_id}`",
        f"- schema_version: `{METRIC_REPAIR_RUN_SCHEMA_VERSION}`",
        f"- proposal_count: `{summary.get('proposal_count_unpaged', len(plan.proposals))}`",
        f"- year_repair_proposal_count: `{summary.get('year_repair_proposal_count', 0)}`",
        f"- value_repair_proposal_count: `{summary.get('value_repair_proposal_count', 0)}`",
        f"- metric_alias_review_count: `{summary.get('metric_alias_review_count', 0)}`",
        f"- dataset_alias_review_count: `{summary.get('dataset_alias_review_count', 0)}`",
        f"- task_alias_review_count: `{summary.get('task_alias_review_count', 0)}`",
        f"- blocked_vague_label_count: `{summary.get('blocked_vague_label_count', 0)}`",
        "",
        "## Top Proposals",
    ]
    for proposal in plan.proposals[:20]:
        lines.append(
            f"- `{proposal['proposal_id']}` {proposal['proposal_type']} "
            f"risk={proposal['risk_level']} status={proposal['review_status']} - {proposal['title']}"
        )
    return "\n".join(lines) + "\n"


def proposal_id_for_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "mrp_" + hashlib.sha256(encoded).hexdigest()[:12]


def decision_id_for_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "mrd_" + hashlib.sha256(encoded).hexdigest()[:12]


def review_risk_for_alias(left: str, right: str) -> str:
    left_key = normalize_canonical_metric_key(left)
    right_key = normalize_canonical_metric_key(right)
    if left_key == right_key:
        return "low"
    left_tokens = set(left_key.split("_")) - {"unknown"}
    right_tokens = set(right_key.split("_")) - {"unknown"}
    if (left_tokens | right_tokens) & SPLIT_WORDS:
        return "high"
    if left_tokens and right_tokens and (left_tokens <= right_tokens or right_tokens <= left_tokens):
        return "high"
    return "medium"


def paper_identity_by_id(root: Path, warnings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    try:
        inventory = build_inventory(root).to_dict()
    except Exception as exc:
        warnings.append(warning("inventory_unavailable", f"Paper inventory unavailable: {exc}"))
        return {}
    papers: dict[str, dict[str, Any]] = {}
    for paper in inventory.get("papers", []):
        papers[str(paper.get("paper_id") or paper.get("source_id") or "")] = paper
        papers[str(paper.get("source_id") or "")] = paper
    return {key: value for key, value in papers.items() if key}


def year_repair_proposals(
    items: list[dict[str, Any]],
    paper_by_id: dict[str, dict[str, Any]],
    repair_by_result_id: dict[str, dict[str, Any]],
    canonicalization: dict[str, Any],
) -> list[dict[str, Any]]:
    explicit_years_by_paper: dict[str, set[int]] = defaultdict(set)
    for item in items:
        year = item.get("reported_year")
        if year is not None:
            explicit_years_by_paper[str(item.get("paper_id") or item.get("source_id") or "")].add(int(year))

    proposals: list[dict[str, Any]] = []
    for item in items:
        if item.get("reported_year") is not None:
            continue
        paper_id = str(item.get("paper_id") or item.get("source_id") or "")
        paper = paper_by_id.get(paper_id) or paper_by_id.get(str(item.get("source_id") or "")) or {}
        suggested_year = paper.get("year")
        if suggested_year is None:
            continue
        suggested_year = int(suggested_year)
        explicit_years = explicit_years_by_paper.get(paper_id, set())
        if explicit_years and explicit_years != {suggested_year}:
            continue
        if context_has_conflicting_year(str(item.get("context_preview") or ""), suggested_year):
            continue
        repair = repair_by_result_id.get(str(item.get("result_id") or ""))
        group_key = comparability_group_key(item, repair or build_value_repair(item))
        readiness = readiness_by_group(canonicalization).get(group_key, {})
        proposal = proposal_payload(
            proposal_type="reported_year_from_paper_identity",
            review_status="proposed",
            risk_level=year_risk_level(str(paper.get("year_source") or "")),
            title="Fill missing reported_year from paper identity",
            rationale=f"Result row has no reported_year and source inventory year is {suggested_year}.",
            deterministic_rule="paper_identity_year_no_conflict",
            target=result_target(item),
            current={"reported_year": None},
            suggested={"reported_year": suggested_year},
            evidence_refs=[evidence_ref(item)],
            readiness_impact={
                "before_status": str(readiness.get("readiness_status") or ""),
                "after_status_if_accepted": projected_status_after_year(readiness),
                "comparability_group_key": group_key,
            },
        )
        proposals.append(proposal)
    return proposals


def value_repair_proposals(
    items: list[dict[str, Any]],
    repair_by_result_id: dict[str, dict[str, Any]],
    canonicalization: dict[str, Any],
) -> list[dict[str, Any]]:
    item_by_result = {str(item.get("result_id") or ""): item for item in items}
    proposals: list[dict[str, Any]] = []
    for repair in repair_by_result_id.values():
        if repair.get("repair_status") != "suggested":
            continue
        if repair.get("repair_confidence") not in {"high", "medium"}:
            continue
        item = item_by_result.get(str(repair.get("result_id") or ""))
        if not item:
            continue
        group_key = comparability_group_key(item, repair)
        readiness = readiness_by_group(canonicalization).get(group_key, {})
        proposal = proposal_payload(
            proposal_type="metric_value_from_v47_suggestion",
            review_status="proposed",
            risk_level="low" if repair.get("repair_confidence") == "high" else "medium",
            title="Fill missing metric_value from V4.7 suggestion",
            rationale="V4.7 found one deterministic numeric value for a row missing normalized metric_value.",
            deterministic_rule=f"v47_value_repair_{repair.get('suggestion_source') or 'unknown'}",
            target=result_target(item),
            current={"metric_value": str(item.get("metric_value") or ""), "metric_unit": str(item.get("metric_unit") or "")},
            suggested={
                "metric_value": str(repair.get("suggested_metric_value") or ""),
                "metric_unit": str(repair.get("suggested_metric_unit") or ""),
                "metric_raw_value": str(repair.get("suggested_metric_raw_value") or ""),
                "value_scale": str(repair.get("value_scale") or ""),
            },
            evidence_refs=[evidence_ref(item)],
            readiness_impact={
                "before_status": str(readiness.get("readiness_status") or ""),
                "after_status_if_accepted": projected_status_after_value(readiness),
                "comparability_group_key": group_key,
            },
            warnings=repair.get("warnings") or [],
        )
        proposals.append(proposal)
    return proposals


def metric_alias_proposals(canonicalization: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = list(canonicalization.get("canonical_metrics") or [])
    proposals: list[dict[str, Any]] = []
    for metric in metrics:
        variants = [variant for variant in metric.get("variants", []) if variant]
        if len(variants) > 1 and not is_vague_key(str(metric.get("canonical_metric_key") or "")):
            proposals.append(
                group_proposal(
                    proposal_type="metric_alias_review",
                    risk_level="medium",
                    title="Review metric variants",
                    rationale=f"Metric variants share canonical key {metric.get('canonical_metric_key')}.",
                    deterministic_rule="same_canonical_metric_key_variants",
                    target={"canonical_metric_key": metric.get("canonical_metric_key"), "variants": variants},
                    current={"variants": variants},
                    suggested={"canonical_metric_key": metric.get("canonical_metric_key"), "display_name": metric.get("display_name")},
                )
            )
    for left_index, left in enumerate(metrics):
        for right in metrics[left_index + 1 :]:
            if not likely_metric_alias(str(left.get("canonical_metric_key") or ""), str(right.get("canonical_metric_key") or "")):
                continue
            variants = sorted(set(left.get("variants") or []) | set(right.get("variants") or []), key=str.casefold)
            proposals.append(
                group_proposal(
                    proposal_type="metric_alias_review",
                    risk_level=review_risk_for_alias(str(left.get("display_name") or ""), str(right.get("display_name") or "")),
                    title="Review possible metric alias",
                    rationale="Metric labels are lexically close but not safe to merge automatically.",
                    deterministic_rule="near_metric_key_overlap",
                    target={
                        "left_canonical_metric_key": left.get("canonical_metric_key"),
                        "right_canonical_metric_key": right.get("canonical_metric_key"),
                        "variants": variants,
                    },
                    current={"canonical_metric_keys": [left.get("canonical_metric_key"), right.get("canonical_metric_key")]},
                    suggested={"review_alias": variants},
                )
            )
    return proposals


def dataset_alias_proposals(items: list[dict[str, Any]], repair_by_result_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in items:
        metric_key = normalize_canonical_metric_key(str(item.get("metric_name") or ""))
        task_key = normalize_canonical_metric_key(str(item.get("task") or ""))
        dataset = str(item.get("dataset") or "").strip()
        if metric_key and task_key and dataset:
            grouped[(metric_key, task_key)].add(dataset)
    proposals: list[dict[str, Any]] = []
    for (metric_key, task_key), labels in grouped.items():
        proposals.extend(alias_review_proposals("dataset_alias_review", metric_key, task_key, sorted(labels, key=str.casefold)))
    return proposals


def task_alias_proposals(items: list[dict[str, Any]], repair_by_result_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in items:
        metric_key = normalize_canonical_metric_key(str(item.get("metric_name") or ""))
        dataset_key = normalize_canonical_metric_key(str(item.get("dataset") or ""))
        task = str(item.get("task") or "").strip()
        if metric_key and dataset_key and task:
            grouped[(metric_key, dataset_key)].add(task)
    proposals: list[dict[str, Any]] = []
    for (metric_key, dataset_key), labels in grouped.items():
        proposals.extend(alias_review_proposals("task_alias_review", metric_key, dataset_key, sorted(labels, key=str.casefold)))
    return proposals


def alias_review_proposals(proposal_type: str, left_context: str, right_context: str, labels: list[str]) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for left_index, left in enumerate(labels):
        for right in labels[left_index + 1 :]:
            left_key = normalize_canonical_metric_key(left)
            right_key = normalize_canonical_metric_key(right)
            if left_key == right_key or left_key in right_key or right_key in left_key:
                risk = review_risk_for_alias(left, right)
                proposals.append(
                    group_proposal(
                        proposal_type=proposal_type,
                        risk_level=risk,
                        title=f"Review {proposal_type.replace('_', ' ')}",
                        rationale="Labels are lexically close but may represent different evaluation settings.",
                        deterministic_rule="lexical_label_overlap",
                        target={"context": [left_context, right_context], "labels": [left, right]},
                        current={"labels": [left, right]},
                        suggested={"review_alias": [left, right]},
                    )
                )
    return proposals


def blocked_vague_label_proposals(canonicalization: dict[str, Any]) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for metric in canonicalization.get("canonical_metrics", []):
        key = str(metric.get("canonical_metric_key") or "")
        if not is_vague_key(key):
            continue
        proposals.append(
            group_proposal(
                proposal_type="blocked_vague_label",
                review_status="blocked",
                risk_level="high",
                title="Blocked vague metric label",
                rationale=f"Metric label {metric.get('display_name')} is too vague for automatic repair.",
                deterministic_rule="vague_metric_label",
                target={"canonical_metric_key": key, "variants": list(metric.get("variants") or [])},
                current={"canonical_metric_key": key, "variants": list(metric.get("variants") or [])},
                suggested={"review_required": True},
            )
        )
    return proposals


def build_projections(canonicalization: dict[str, Any], proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for proposal in proposals:
        group_key = str((proposal.get("readiness_impact") or {}).get("comparability_group_key") or "")
        if group_key:
            by_group[group_key].append(proposal)

    projections: list[dict[str, Any]] = []
    for readiness in canonicalization.get("timeline_readiness", []):
        group_key = str(readiness.get("comparability_group_key") or "")
        if not group_key:
            continue
        group_proposals = by_group.get(group_key, [])
        if not group_proposals:
            continue
        proposal_ids = [proposal["proposal_id"] for proposal in group_proposals]
        projected = projected_status(readiness, group_proposals)
        projections.append(
            {
                "schema_version": METRIC_REPAIR_PROJECTION_SCHEMA_VERSION,
                "comparability_group_key": group_key,
                "canonical_metric_key": str(readiness.get("canonical_metric_key") or ""),
                "current_readiness_status": str(readiness.get("readiness_status") or ""),
                "projected_readiness_status": projected,
                "required_proposal_ids": proposal_ids,
                "blocked_proposal_ids": [
                    proposal["proposal_id"] for proposal in group_proposals if proposal.get("review_status") == "blocked"
                ],
                "remaining_blockers": [] if projected in {"strict_ready", "ready_after_value_repair"} else list(readiness.get("blocking_reasons") or []),
            }
        )
    return sorted(projections, key=lambda projection: (projection["projected_readiness_status"], projection["comparability_group_key"]))


def projected_status(readiness: dict[str, Any], proposals: list[dict[str, Any]]) -> str:
    current = str(readiness.get("readiness_status") or "")
    types = {proposal["proposal_type"] for proposal in proposals}
    if current == "needs_year_repair" and "reported_year_from_paper_identity" in types:
        missing_value_count = int(readiness.get("missing_value_count") or 0)
        return "ready_after_value_repair" if missing_value_count else "strict_ready"
    if current == "needs_value_repair" and "metric_value_from_v47_suggestion" in types:
        return "ready_after_value_repair"
    return current


def projected_status_after_year(readiness: dict[str, Any]) -> str:
    if not readiness:
        return ""
    if int(readiness.get("missing_value_count") or 0):
        return "ready_after_value_repair"
    return "strict_ready"


def projected_status_after_value(readiness: dict[str, Any]) -> str:
    if not readiness:
        return ""
    if str(readiness.get("readiness_status") or "") == "needs_value_repair":
        return "ready_after_value_repair"
    return str(readiness.get("readiness_status") or "")


def build_summary(
    canonicalization: dict[str, Any],
    evidence: dict[str, Any],
    proposals: list[dict[str, Any]],
    projections: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    type_counts = Counter(proposal["proposal_type"] for proposal in proposals)
    status_counts = Counter(proposal["review_status"] for proposal in proposals)
    risk_counts = Counter(proposal["risk_level"] for proposal in proposals)
    projected_counts = Counter(projection["projected_readiness_status"] for projection in projections)
    return {
        "metric_result_count": int(evidence.get("summary", {}).get("metric_result_count") or 0),
        "canonical_metric_count": int(canonicalization.get("summary", {}).get("canonical_metric_count_unpaged") or 0),
        "comparability_group_count": int(canonicalization.get("summary", {}).get("comparability_group_count_unpaged") or 0),
        "proposal_count": len(proposals),
        "proposal_count_unpaged": len(proposals),
        "proposal_counts_by_type": dict(sorted(type_counts.items())),
        "proposal_counts_by_status": dict(sorted(status_counts.items())),
        "proposal_counts_by_risk": dict(sorted(risk_counts.items())),
        "year_repair_proposal_count": type_counts.get("reported_year_from_paper_identity", 0),
        "value_repair_proposal_count": type_counts.get("metric_value_from_v47_suggestion", 0),
        "metric_alias_review_count": type_counts.get("metric_alias_review", 0),
        "dataset_alias_review_count": type_counts.get("dataset_alias_review", 0),
        "task_alias_review_count": type_counts.get("task_alias_review", 0),
        "blocked_vague_label_count": type_counts.get("blocked_vague_label", 0),
        "projected_strict_ready_count": projected_counts.get("strict_ready", 0),
        "projected_ready_after_value_repair_count": projected_counts.get("ready_after_value_repair", 0),
        "projected_discoverable_not_comparable_count": projected_counts.get("discoverable_not_comparable", 0),
        "accepted_proposal_count": status_counts.get("accepted", 0),
        "rejected_proposal_count": status_counts.get("rejected", 0),
        "needs_review_proposal_count": status_counts.get("needs_review", 0),
        "decision_count": 0,
        "warning_count": len(dedupe_warnings(warnings)),
    }


def proposal_payload(
    *,
    proposal_type: str,
    review_status: str,
    risk_level: str,
    title: str,
    rationale: str,
    deterministic_rule: str,
    target: dict[str, Any],
    current: dict[str, Any],
    suggested: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
    readiness_impact: dict[str, Any],
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    identity = {
        "proposal_type": proposal_type,
        "target": target,
        "current": current,
        "suggested": suggested,
    }
    payload = {
        "schema_version": METRIC_REPAIR_PROPOSAL_SCHEMA_VERSION,
        "proposal_id": proposal_id_for_payload(identity),
        "proposal_type": proposal_type,
        "review_status": review_status,
        "risk_level": risk_level,
        "title": title,
        "rationale": rationale,
        "deterministic_rule": deterministic_rule,
        "target": target,
        "current": current,
        "suggested": suggested,
        "evidence_refs": evidence_refs,
        "readiness_impact": readiness_impact,
        "warnings": warnings or [],
    }
    return payload


def group_proposal(
    *,
    proposal_type: str,
    risk_level: str,
    title: str,
    rationale: str,
    deterministic_rule: str,
    target: dict[str, Any],
    current: dict[str, Any],
    suggested: dict[str, Any],
    review_status: str = "proposed",
) -> dict[str, Any]:
    return proposal_payload(
        proposal_type=proposal_type,
        review_status=review_status,
        risk_level=risk_level,
        title=title,
        rationale=rationale,
        deterministic_rule=deterministic_rule,
        target=target,
        current=current,
        suggested=suggested,
        evidence_refs=[],
        readiness_impact={},
    )


def result_target(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": str(item.get("result_id") or ""),
        "claim_id": str(item.get("claim_id") or ""),
        "source_id": str(item.get("source_id") or ""),
        "paper_id": str(item.get("paper_id") or ""),
        "citation_locator": str(item.get("citation_locator") or ""),
    }


def evidence_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": str(item.get("result_id") or ""),
        "claim_id": str(item.get("claim_id") or ""),
        "source_id": str(item.get("source_id") or ""),
        "citation_locator": str(item.get("citation_locator") or ""),
        "context_preview": clip(str(item.get("context_preview") or ""), 240),
    }


def readiness_by_group(canonicalization: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("comparability_group_key") or ""): item
        for item in canonicalization.get("timeline_readiness", [])
        if item.get("comparability_group_key")
    }


def year_risk_level(year_source: str) -> str:
    if year_source in {"metadata", "arxiv_id", "pdf_metadata"}:
        return "low"
    if year_source in {"filename", "source_title", "normalized_source"}:
        return "medium"
    return "high"


def context_has_conflicting_year(context: str, suggested_year: int) -> bool:
    years = {int(value) for value in re.findall(r"\b(19\d{2}|20\d{2})\b", context or "")}
    return bool(years and years != {suggested_year})


def likely_metric_alias(left_key: str, right_key: str) -> bool:
    if not left_key or not right_key or left_key == right_key:
        return False
    left_tokens = set(left_key.split("_"))
    right_tokens = set(right_key.split("_"))
    if is_vague_key(left_key) or is_vague_key(right_key):
        return False
    if {"success", "successful"} & left_tokens and {"success", "successful"} & right_tokens and "rate" in (left_tokens | right_tokens):
        return True
    if left_tokens & right_tokens and (left_tokens <= right_tokens or right_tokens <= left_tokens):
        return True
    return False


def is_vague_key(key: str) -> bool:
    tokens = set(str(key or "").split("_"))
    return bool(tokens) and tokens <= VAGUE_METRIC_KEYS


def dedupe_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for proposal in proposals:
        proposal_id = str(proposal["proposal_id"])
        if proposal_id in seen:
            continue
        seen.add(proposal_id)
        deduped.append(proposal)
    return deduped


def proposal_sort_key(proposal: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(proposal.get("proposal_type") or ""),
        str(proposal.get("risk_level") or ""),
        str(proposal.get("proposal_id") or ""),
    )


def wrap_external_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wrapped: list[dict[str, Any]] = []
    for item in warnings:
        code = str(item.get("code") or "")
        message = str(item.get("message") or code)
        if code and message:
            wrapped.append(warning(code, message, severity=str(item.get("severity") or "warning")))
    return wrapped


def warning(code: str, message: str, *, severity: str = "warning") -> dict[str, Any]:
    return {
        "schema_version": METRIC_REPAIR_WARNING_SCHEMA_VERSION,
        "code": code,
        "severity": severity,
        "message": message,
    }


def dedupe_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in warnings:
        key = (str(item.get("code") or ""), str(item.get("message") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def page(items: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
    return items[offset : offset + limit]


def clip(value: str, max_chars: int) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
