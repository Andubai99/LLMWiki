from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any

from .db import catalog_path, connect
from .retrieval import retrieve_context


EVAL_SCHEMA_VERSION = "eval.retrieval.v2.3"


@dataclass(frozen=True)
class RetrievalEvalCase:
    id: str
    question: str
    expected_status: str = "has_evidence"
    language: str = ""
    query_type: str = ""
    expected_claim_ids: list[str] = field(default_factory=list)
    expected_source_ids: list[str] = field(default_factory=list)
    expected_page_ids: list[str] = field(default_factory=list)
    expected_terms: list[str] = field(default_factory=list)
    must_expose_relationship_types: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, line_number: int, path: Path) -> "RetrievalEvalCase":
        case_id = str(payload.get("id") or "").strip()
        question = str(payload.get("question") or "").strip()
        if not case_id:
            raise ValueError(f"{path.name} line {line_number}: missing id")
        if not question:
            raise ValueError(f"{path.name} line {line_number}: missing question")
        expected_status = str(payload.get("expected_status") or "has_evidence")
        if expected_status not in {"has_evidence", "no_evidence"}:
            raise ValueError(f"{path.name} line {line_number}: invalid expected_status {expected_status}")
        return cls(
            id=case_id,
            question=question,
            expected_status=expected_status,
            language=str(payload.get("language") or ""),
            query_type=str(payload.get("query_type") or ""),
            expected_claim_ids=string_list(payload.get("expected_claim_ids")),
            expected_source_ids=string_list(payload.get("expected_source_ids")),
            expected_page_ids=string_list(payload.get("expected_page_ids")),
            expected_terms=string_list(payload.get("expected_terms")),
            must_expose_relationship_types=string_list(payload.get("must_expose_relationship_types")),
            notes=str(payload.get("notes") or ""),
        )


@dataclass(frozen=True)
class RetrievalEvalResult:
    id: str
    question: str
    passed: bool
    failure_stage: str | None
    expected_status: str
    returned_count: int
    relevant_count: int
    expected_count: int
    hit_at_k: float
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float = 0.0
    map_at_k: float = 0.0
    context_precision_at_k: float = 0.0
    context_recall_at_k: float = 0.0
    coverage_at_k: float = 0.0
    source_diversity_at_k: float = 0.0
    redundancy_rate_at_k: float = 0.0
    selected_conflict_exposure: float = 1.0
    weak_evidence_visibility: float = 1.0
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "passed": self.passed,
            "failure_stage": self.failure_stage,
            "expected_status": self.expected_status,
            "returned_count": self.returned_count,
            "relevant_count": self.relevant_count,
            "expected_count": self.expected_count,
            "hit_at_k": self.hit_at_k,
            "recall_at_k": self.recall_at_k,
            "precision_at_k": self.precision_at_k,
            "mrr": self.mrr,
            "ndcg_at_k": self.ndcg_at_k,
            "map_at_k": self.map_at_k,
            "context_precision_at_k": self.context_precision_at_k,
            "context_recall_at_k": self.context_recall_at_k,
            "coverage_at_k": self.coverage_at_k,
            "source_diversity_at_k": self.source_diversity_at_k,
            "redundancy_rate_at_k": self.redundancy_rate_at_k,
            "selected_conflict_exposure": self.selected_conflict_exposure,
            "weak_evidence_visibility": self.weak_evidence_visibility,
            "warnings": self.warnings,
            "diagnostics": self.diagnostics,
        }


@dataclass(frozen=True)
class RetrievalEvalSummary:
    dataset: str
    cases: list[RetrievalEvalResult]
    evidence_contract: dict[str, float]
    latency_ms_p50: float
    latency_ms_p95: float
    llm_calls: int = 0
    estimated_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        case_count = len(self.cases)
        passed = sum(1 for case in self.cases if case.passed)
        failed = case_count - passed
        return {
            "schema_version": EVAL_SCHEMA_VERSION,
            "dataset": self.dataset,
            "case_count": case_count,
            "summary": {
                "passed": passed,
                "failed": failed,
                "hit_at_5": average(case.hit_at_k for case in self.cases),
                "recall_at_5": average(case.recall_at_k for case in self.cases),
                "precision_at_5": average(case.precision_at_k for case in self.cases),
                "mrr": average(case.mrr for case in self.cases),
                "ndcg_at_5": average(case.ndcg_at_k for case in self.cases),
                "map_at_5": average(case.map_at_k for case in self.cases),
                "context_precision_at_5": average(case.context_precision_at_k for case in self.cases),
                "context_recall_at_5": average(case.context_recall_at_k for case in self.cases),
                "coverage_at_5": average(case.coverage_at_k for case in self.cases),
                "source_diversity_at_5": average(case.source_diversity_at_k for case in self.cases),
                "redundancy_rate_at_5": average(case.redundancy_rate_at_k for case in self.cases),
                "selected_conflict_exposure_rate": average(
                    case.selected_conflict_exposure for case in self.cases
                ),
                "weak_evidence_visibility_rate": average(case.weak_evidence_visibility for case in self.cases),
            },
            "evidence_contract": self.evidence_contract,
            "operational": {
                "latency_ms_p50": self.latency_ms_p50,
                "latency_ms_p95": self.latency_ms_p95,
                "llm_calls": self.llm_calls,
                "estimated_cost": self.estimated_cost,
                "error_count": sum(1 for case in self.cases if case.failure_stage == "runtime_error"),
            },
            "cases": [case.to_dict() for case in self.cases],
        }


def load_eval_cases(path: Path) -> list[RetrievalEvalCase]:
    cases: list[RetrievalEvalCase] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Could not read eval dataset {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} line {line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name} line {line_number}: expected JSON object")
        cases.append(RetrievalEvalCase.from_dict(payload, line_number=line_number, path=path))
    if not cases:
        raise ValueError(f"{path.name}: no eval cases found")
    return cases


def evaluate_retrieval(root: Path, dataset: Path, *, limit: int = 5) -> RetrievalEvalSummary:
    root = root.resolve()
    dataset = dataset.resolve()
    cases = load_eval_cases(dataset)
    with connect(catalog_path(root)) as conn:
        catalog = load_catalog_snapshot(conn)
    results: list[RetrievalEvalResult] = []
    latencies: list[float] = []
    contract_accumulator = ContractAccumulator()
    for case in cases:
        started = time.perf_counter()
        try:
            retrieval = retrieve_context(root, case.question, limit=limit)
            latency_ms = (time.perf_counter() - started) * 1000
            latencies.append(latency_ms)
            contract_accumulator.add(retrieval, catalog, case)
            results.append(evaluate_case(case, retrieval, catalog, limit))
        except Exception as exc:  # pragma: no cover - defensive path surfaced in CLI
            latency_ms = (time.perf_counter() - started) * 1000
            latencies.append(latency_ms)
            results.append(
                RetrievalEvalResult(
                    id=case.id,
                    question=case.question,
                    passed=False,
                    failure_stage="runtime_error",
                    expected_status=case.expected_status,
                    returned_count=0,
                    relevant_count=0,
                    expected_count=expected_count(case),
                    hit_at_k=0.0,
                    recall_at_k=0.0,
                    precision_at_k=0.0,
                    mrr=0.0,
                    ndcg_at_k=0.0,
                    map_at_k=0.0,
                    context_precision_at_k=0.0,
                    context_recall_at_k=0.0,
                    coverage_at_k=0.0,
                    source_diversity_at_k=0.0,
                    redundancy_rate_at_k=0.0,
                    selected_conflict_exposure=0.0,
                    weak_evidence_visibility=1.0,
                    warnings=[sanitize_error(exc)],
                    diagnostics={},
                )
            )
    return RetrievalEvalSummary(
        dataset=str(dataset),
        cases=results,
        evidence_contract=contract_accumulator.metrics(),
        latency_ms_p50=percentile(latencies, 50),
        latency_ms_p95=percentile(latencies, 95),
    )


def evaluate_case(
    case: RetrievalEvalCase,
    retrieval: dict[str, Any],
    catalog: dict[str, set[str]],
    limit: int,
) -> RetrievalEvalResult:
    contexts = list(retrieval.get("contexts", []))[:limit]
    relationships = list(retrieval.get("relationships", []))
    warnings = [str(warning) for warning in retrieval.get("warnings", [])]
    diagnostics = dict(retrieval.get("diagnostics", {}))
    relevant_indices = [
        index for index, context in enumerate(contexts, start=1) if is_relevant_context(case, context, catalog)
    ]
    matched_expectations = count_matched_expectations(case, contexts, catalog)
    total_expectations = expected_count(case)

    if case.expected_status == "no_evidence":
        passed = not contexts
        failure_stage = None if passed else "unexpected_evidence"
        return result_from_metrics(
            case,
            passed=passed,
            failure_stage=failure_stage,
            returned_count=len(contexts),
            relevant_indices=[],
            matched_expectations=0,
            total_expectations=max(total_expectations, 1),
            warnings=warnings,
            diagnostics=diagnostics,
            contexts=contexts,
            relationships=relationships,
            catalog=catalog,
        )

    relationship_missing = missing_required_relationship(case, relationships, warnings)
    contract_violations = context_contract_violations(contexts, relationships, catalog)
    passed = bool(relevant_indices) and not relationship_missing and not contract_violations
    if passed:
        failure_stage = None
    elif contract_violations:
        failure_stage = "contract_violation"
    elif relationship_missing:
        failure_stage = "relationship_miss"
    elif not contexts:
        failure_stage = str(diagnostics.get("failure_stage") or "candidate_miss")
    else:
        failure_stage = "ranking_miss"

    return result_from_metrics(
        case,
        passed=passed,
        failure_stage=failure_stage,
        returned_count=len(contexts),
        relevant_indices=relevant_indices,
        matched_expectations=matched_expectations,
        total_expectations=max(total_expectations, 1),
        warnings=warnings,
        diagnostics=diagnostics,
        contexts=contexts,
        relationships=relationships,
        catalog=catalog,
    )


def result_from_metrics(
    case: RetrievalEvalCase,
    *,
    passed: bool,
    failure_stage: str | None,
    returned_count: int,
    relevant_indices: list[int],
    matched_expectations: int,
    total_expectations: int,
    warnings: list[str],
    diagnostics: dict[str, Any],
    contexts: list[dict[str, Any]] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    catalog: dict[str, set[str]] | None = None,
) -> RetrievalEvalResult:
    contexts = contexts or []
    relationships = relationships or []
    catalog = catalog or {"page_id_by_path": {}}
    divisor = min(5, returned_count) if returned_count else 0
    precision = round(len(relevant_indices) / divisor, 4) if divisor else 0.0
    recall = round(min(1.0, matched_expectations / total_expectations), 4)
    return RetrievalEvalResult(
        id=case.id,
        question=case.question,
        passed=passed,
        failure_stage=failure_stage,
        expected_status=case.expected_status,
        returned_count=returned_count,
        relevant_count=len(relevant_indices),
        expected_count=total_expectations,
        hit_at_k=1.0 if relevant_indices else 0.0,
        recall_at_k=recall,
        precision_at_k=precision,
        mrr=round(1 / relevant_indices[0], 4) if relevant_indices else 0.0,
        ndcg_at_k=ndcg_at_k(relevant_indices, total_expectations, k=5),
        map_at_k=map_at_k(relevant_indices, total_expectations, k=5),
        context_precision_at_k=precision,
        context_recall_at_k=recall,
        coverage_at_k=coverage_at_k(case, contexts, catalog),
        source_diversity_at_k=source_diversity_at_k(contexts),
        redundancy_rate_at_k=redundancy_rate_at_k(contexts),
        selected_conflict_exposure=selected_conflict_exposure(case, relationships, warnings),
        weak_evidence_visibility=weak_evidence_visibility(contexts, warnings),
        warnings=warnings,
        diagnostics=diagnostics,
    )


def ndcg_at_k(relevant_indices: list[int], total_expectations: int, *, k: int) -> float:
    relevant = [rank for rank in relevant_indices if rank <= k]
    if not relevant:
        return 0.0
    dcg = sum(1.0 / log2(rank + 1) for rank in relevant)
    ideal_relevant = min(total_expectations, k)
    idcg = sum(1.0 / log2(rank + 1) for rank in range(1, ideal_relevant + 1))
    if idcg == 0:
        return 0.0
    return round(dcg / idcg, 4)


def map_at_k(relevant_indices: list[int], total_expectations: int, *, k: int) -> float:
    relevant = [rank for rank in relevant_indices if rank <= k]
    if not relevant:
        return 0.0
    precision_sum = 0.0
    for hit_number, rank in enumerate(relevant, start=1):
        precision_sum += hit_number / rank
    denominator = min(total_expectations, k)
    return round(precision_sum / denominator, 4) if denominator else 0.0


def log2(value: int) -> float:
    import math

    return math.log2(value)


def coverage_at_k(
    case: RetrievalEvalCase,
    contexts: list[dict[str, Any]],
    catalog: dict[str, set[str]],
) -> float:
    expected_sources = set(case.expected_source_ids)
    if expected_sources:
        returned_sources = {str(context.get("source_id") or "") for context in contexts}
        return round(len(expected_sources & returned_sources) / len(expected_sources), 4)

    expected_pages = set(case.expected_page_ids)
    if expected_pages:
        page_by_path = catalog.get("page_id_by_path", {})
        returned_pages = {
            page_by_path.get(str(context.get("page_path") or ""))
            for context in contexts
        }
        return round(len(expected_pages & returned_pages) / len(expected_pages), 4)

    expected_claims = set(case.expected_claim_ids)
    if expected_claims:
        returned_claims = {str(context.get("claim_id") or "") for context in contexts}
        return round(len(expected_claims & returned_claims) / len(expected_claims), 4)

    return 1.0 if contexts else 0.0


def source_diversity_at_k(contexts: list[dict[str, Any]]) -> float:
    if not contexts:
        return 0.0
    sources = {str(context.get("source_id") or "") for context in contexts}
    return round(len(sources) / len(contexts), 4)


def redundancy_rate_at_k(contexts: list[dict[str, Any]]) -> float:
    if not contexts:
        return 0.0
    groups = {
        str(context.get("redundancy_group") or normalize_context_text(context))
        for context in contexts
    }
    return round(1.0 - (len(groups) / len(contexts)), 4)


def selected_conflict_exposure(
    case: RetrievalEvalCase,
    relationships: list[dict[str, Any]],
    warnings: list[str],
) -> float:
    if "contradicts" not in case.must_expose_relationship_types:
        return 1.0
    return 1.0 if relationship_type_present("contradicts", relationships, warnings) else 0.0


def weak_evidence_visibility(contexts: list[dict[str, Any]], warnings: list[str]) -> float:
    has_weak = any(str(context.get("confidence_status") or "") in {"weak", "uncited"} for context in contexts)
    if not has_weak:
        return 1.0
    return 1.0 if any("weak/uncited" in warning.casefold() for warning in warnings) else 0.0


def normalize_context_text(context: dict[str, Any]) -> str:
    return str(context.get("claim_text") or "").casefold().strip()


class ContractAccumulator:
    def __init__(self) -> None:
        self.claim_valid = RatioCounter()
        self.source_valid = RatioCounter()
        self.locator_present = RatioCounter()
        self.page_valid = RatioCounter()
        self.relationship_valid = RatioCounter()
        self.contradiction_exposed = RatioCounter()

    def add(self, retrieval: dict[str, Any], catalog: dict[str, set[str]], case: RetrievalEvalCase) -> None:
        for context in retrieval.get("contexts", []):
            claim_id = str(context.get("claim_id") or "")
            source_id = str(context.get("source_id") or "")
            citation_locator = str(context.get("citation_locator") or "")
            page_path = str(context.get("page_path") or "")
            self.claim_valid.add(claim_id in catalog["claim_ids"])
            self.source_valid.add(source_id in catalog["source_ids"] or source_id.startswith("synthesis:"))
            self.locator_present.add(bool(citation_locator.strip()))
            self.page_valid.add(page_path in catalog["page_paths"])

        for relationship in retrieval.get("relationships", []):
            self.relationship_valid.add(valid_relationship(relationship, catalog))

        if "contradicts" in case.must_expose_relationship_types:
            relationships = list(retrieval.get("relationships", []))
            warnings = [str(warning) for warning in retrieval.get("warnings", [])]
            self.contradiction_exposed.add(relationship_type_present("contradicts", relationships, warnings))

    def metrics(self) -> dict[str, float]:
        return {
            "claim_id_validity": self.claim_valid.value(),
            "source_id_validity": self.source_valid.value(),
            "citation_locator_presence": self.locator_present.value(),
            "page_path_validity": self.page_valid.value(),
            "relationship_validity": self.relationship_valid.value(),
            "contradiction_exposure_rate": self.contradiction_exposed.value(),
        }


class RatioCounter:
    def __init__(self) -> None:
        self.good = 0
        self.total = 0

    def add(self, ok: bool) -> None:
        self.total += 1
        if ok:
            self.good += 1

    def value(self) -> float:
        if self.total == 0:
            return 1.0
        return round(self.good / self.total, 4)


def load_catalog_snapshot(conn) -> dict[str, set[str]]:
    return {
        "claim_ids": {str(row["claim_id"]) for row in conn.execute("select claim_id from claims")},
        "source_ids": {str(row["source_id"]) for row in conn.execute("select source_id from sources")},
        "page_ids": {str(row["page_id"]) for row in conn.execute("select page_id from pages")},
        "page_paths": {str(row["path"]) for row in conn.execute("select path from pages")},
        "page_id_by_path": {
            str(row["path"]): str(row["page_id"])
            for row in conn.execute("select page_id, path from pages")
        },
    }


def is_relevant_context(
    case: RetrievalEvalCase,
    context: dict[str, Any],
    catalog: dict[str, set[str]],
) -> bool:
    claim_id = str(context.get("claim_id") or "")
    source_id = str(context.get("source_id") or "")
    page_path = str(context.get("page_path") or "")
    page_id = catalog["page_id_by_path"].get(page_path)
    text = f"{context.get('claim_text') or ''} {page_path}".casefold()
    return (
        claim_id in case.expected_claim_ids
        or source_id in case.expected_source_ids
        or (page_id is not None and page_id in case.expected_page_ids)
        or any(term.casefold() in text for term in case.expected_terms)
    )


def count_matched_expectations(
    case: RetrievalEvalCase,
    contexts: list[dict[str, Any]],
    catalog: dict[str, set[str]],
) -> int:
    matched = 0
    context_claims = {str(context.get("claim_id") or "") for context in contexts}
    context_sources = {str(context.get("source_id") or "") for context in contexts}
    context_page_ids = {
        catalog["page_id_by_path"].get(str(context.get("page_path") or ""))
        for context in contexts
    }
    context_text = "\n".join(
        f"{context.get('claim_text') or ''} {context.get('page_path') or ''}" for context in contexts
    ).casefold()
    matched += sum(1 for claim_id in case.expected_claim_ids if claim_id in context_claims)
    matched += sum(1 for source_id in case.expected_source_ids if source_id in context_sources)
    matched += sum(1 for page_id in case.expected_page_ids if page_id in context_page_ids)
    matched += sum(1 for term in case.expected_terms if term.casefold() in context_text)
    return matched


def expected_count(case: RetrievalEvalCase) -> int:
    count = (
        len(case.expected_claim_ids)
        + len(case.expected_source_ids)
        + len(case.expected_page_ids)
        + len(case.expected_terms)
    )
    return max(count, 1)


def missing_required_relationship(
    case: RetrievalEvalCase,
    relationships: list[dict[str, Any]],
    warnings: list[str],
) -> bool:
    for relationship_type in case.must_expose_relationship_types:
        if relationship_type_present(relationship_type, relationships, warnings):
            continue
        return True
    return False


def relationship_type_present(
    relationship_type: str,
    relationships: list[dict[str, Any]],
    warnings: list[str],
) -> bool:
    if any(str(row.get("relationship_type") or "") == relationship_type for row in relationships):
        return True
    if relationship_type == "contradicts":
        return any("contradict" in warning.casefold() for warning in warnings)
    return False


def context_contract_violations(
    contexts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    catalog: dict[str, set[str]],
) -> list[str]:
    problems: list[str] = []
    for context in contexts:
        if str(context.get("claim_id") or "") not in catalog["claim_ids"]:
            problems.append("invalid_claim_id")
        source_id = str(context.get("source_id") or "")
        if source_id not in catalog["source_ids"] and not source_id.startswith("synthesis:"):
            problems.append("invalid_source_id")
        if str(context.get("page_path") or "") not in catalog["page_paths"]:
            problems.append("invalid_page_path")
    for relationship in relationships:
        if not valid_relationship(relationship, catalog):
            problems.append("invalid_relationship")
    return problems


def valid_relationship(relationship: dict[str, Any], catalog: dict[str, set[str]]) -> bool:
    subject_id = str(relationship.get("subject_id") or "")
    object_id = str(relationship.get("object_id") or "")
    evidence_claim_id = str(relationship.get("evidence_claim_id") or "")
    source_id = str(relationship.get("source_id") or "")
    known_node_ids = catalog["page_ids"] | catalog["source_ids"]
    return (
        subject_id in known_node_ids
        and object_id in known_node_ids
        and evidence_claim_id in catalog["claim_ids"]
        and (source_id in catalog["source_ids"] or source_id.startswith("synthesis:"))
    )


def format_eval_report(summary: RetrievalEvalSummary) -> str:
    data = summary.to_dict()
    summary_data = data["summary"]
    contract = data["evidence_contract"]
    lines = [
        f"Retrieval eval: {data['dataset']}",
        "",
        f"Cases: {data['case_count']}",
        f"Passed: {summary_data['passed']}",
        f"Failed: {summary_data['failed']}",
        "",
        "Core metrics:",
        f"- hit@5: {summary_data['hit_at_5']:.2f}",
        f"- recall@5: {summary_data['recall_at_5']:.2f}",
        f"- precision@5: {summary_data['precision_at_5']:.2f}",
        f"- mrr: {summary_data['mrr']:.2f}",
        f"- ndcg@5: {summary_data['ndcg_at_5']:.2f}",
        f"- map@5: {summary_data['map_at_5']:.2f}",
        f"- context_precision@5: {summary_data['context_precision_at_5']:.2f}",
        f"- context_recall@5: {summary_data['context_recall_at_5']:.2f}",
        f"- coverage@5: {summary_data['coverage_at_5']:.2f}",
        f"- source_diversity@5: {summary_data['source_diversity_at_5']:.2f}",
        f"- redundancy_rate@5: {summary_data['redundancy_rate_at_5']:.2f}",
        f"- selected_conflict_exposure_rate: {summary_data['selected_conflict_exposure_rate']:.2f}",
        f"- weak_evidence_visibility_rate: {summary_data['weak_evidence_visibility_rate']:.2f}",
        "",
        "Evidence contract:",
        f"- claim_id_validity: {contract['claim_id_validity']:.2f}",
        f"- source_id_validity: {contract['source_id_validity']:.2f}",
        f"- citation_locator_presence: {contract['citation_locator_presence']:.2f}",
        f"- page_path_validity: {contract['page_path_validity']:.2f}",
        f"- relationship_validity: {contract['relationship_validity']:.2f}",
        f"- contradiction_exposure_rate: {contract['contradiction_exposure_rate']:.2f}",
        "",
        "Failures:",
    ]
    failures = [case for case in summary.cases if not case.passed]
    if failures:
        lines.extend(f"- {case.id}: {case.failure_stage}" for case in failures)
    else:
        lines.append("- None")
    return "\n".join(lines)


def string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [str(value)]
    return [str(item) for item in value if str(item).strip()]


def average(values: Any) -> float:
    items = [float(value) for value in values]
    if not items:
        return 0.0
    return round(sum(items) / len(items), 4)


def percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * (percent / 100))
    return round(ordered[index], 4)


def sanitize_error(exc: BaseException) -> str:
    text = str(exc).replace("config/api-keys.toml", "[api-key-file]")
    return text or exc.__class__.__name__
