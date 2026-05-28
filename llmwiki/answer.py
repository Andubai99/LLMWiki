from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any

from .llm import create_provider, load_llm_config
from .planned_retrieval import PlannedRetrievalResult, execute_query_plan
from .planner import PlanningOptions, PlanningResult, plan_question
from .providers.base import LLMProviderError


@dataclass(frozen=True)
class AskOptions:
    limit: int = 8
    source_id: str | None = None
    page_type: str | None = None
    confidence: str | None = None


@dataclass(frozen=True)
class AnswerCitation:
    claim_id: str
    source_id: str
    citation_locator: str
    page_path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "source_id": self.source_id,
            "citation_locator": self.citation_locator,
            "page_path": self.page_path,
        }


@dataclass(frozen=True)
class AskResult:
    question: str
    status: str
    answer: str = ""
    analysis: str = ""
    citations: list[AnswerCitation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    suggested_title: str = ""
    contexts: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    planning: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "question": self.question,
            "answer": self.answer,
            "status": self.status,
            "citations": [citation.to_dict() for citation in self.citations],
            "warnings": self.warnings,
            "writeback": {"status": "skipped", "run_id": None, "pages": []},
        }
        if self.planning is not None:
            data["planning"] = self.planning
        return data


def answer_question(root: Path, question: str, options: AskOptions | None = None) -> AskResult:
    root = root.resolve()
    options = options or AskOptions()
    planning = plan_question(
        root,
        question,
        PlanningOptions(
            limit=options.limit,
            source_id=options.source_id,
            page_type=options.page_type,
            confidence=options.confidence,
        ),
    )
    if planning.status != "planned" or planning.plan is None:
        planning_dict = planning.to_dict()
        return AskResult(
            question=question,
            status=planning.status,
            warnings=[planning.error] if planning.error else planning.warnings,
            planning=planning_dict,
            error=planning.error,
        )

    planned_retrieval = execute_query_plan(root, planning.plan, options)
    retrieval = planned_retrieval.to_retrieval_dict(question)
    planning_dict = planning_output(planning, planned_retrieval)
    contexts = list(planned_retrieval.contexts)
    relationships = list(planned_retrieval.relationships)
    warnings = [str(warning) for warning in planned_retrieval.warnings]
    if not contexts:
        planning_dict["status"] = "planned_insufficient_evidence"
        return AskResult(
            question=question,
            status="planned_insufficient_evidence",
            warnings=warnings or ["No matching claims found."],
            contexts=contexts,
            relationships=relationships,
            planning=planning_dict,
        )

    config = load_llm_config(root)
    try:
        provider = create_provider(config, root=root)
        messages = build_answer_prompt(question, retrieval)
        response = provider.complete(messages, schema=answer_schema())
        payload = parse_llm_answer(str(response.get("content") or ""))
    except json.JSONDecodeError:
        try:
            repair_messages = build_repair_prompt(question, retrieval)
            response = provider.complete(repair_messages, schema=answer_schema())
            payload = parse_llm_answer(str(response.get("content") or ""))
        except Exception as exc:
            return failed_result(question, "llm_failed", exc, warnings, contexts, relationships, planning_dict)
    except (LLMProviderError, ValueError) as exc:
        return failed_result(question, "llm_failed", exc, warnings, contexts, relationships, planning_dict)

    try:
        citations = validate_answer_citations(payload, contexts)
    except ValueError as exc:
        return failed_result(question, "invalid_citations", exc, warnings, contexts, relationships, planning_dict)

    if not citations:
        return failed_result(
            question,
            "invalid_citations",
            ValueError("Answer did not cite any retrieved claim."),
            warnings,
            contexts,
            relationships,
            planning_dict,
        )

    return AskResult(
        question=question,
        status="answered",
        answer=str(payload.get("short_answer") or ""),
        analysis=str(payload.get("analysis") or ""),
        citations=citations,
        warnings=warnings,
        uncertainties=[str(item) for item in payload.get("uncertainties", []) if str(item).strip()],
        conflicts=[str(item) for item in payload.get("conflicts", []) if str(item).strip()],
        suggested_title=str(payload.get("suggested_title") or ""),
        contexts=contexts,
        relationships=relationships,
        planning=planning_dict,
    )


def planning_output(
    planning: PlanningResult,
    planned_retrieval: PlannedRetrievalResult | None = None,
) -> dict[str, Any]:
    data = dict(planning.to_dict())
    if planned_retrieval is not None:
        data["retrieved_context_count"] = len(planned_retrieval.contexts)
        data["warnings"] = [*list(data.get("warnings", [])), *planned_retrieval.warnings]
        data["planned_retrieval"] = planned_retrieval.diagnostics
    return data


def build_answer_prompt(question: str, retrieval: dict[str, Any]) -> list[dict[str, str]]:
    evidence_json = json.dumps(
        {
            "contexts": retrieval.get("contexts", []),
            "relationships": retrieval.get("relationships", []),
            "warnings": retrieval.get("warnings", []),
        },
        ensure_ascii=False,
        indent=2,
    )
    return [
        {
            "role": "system",
            "content": (
                "You answer LLMWiki questions using only retrieved local evidence. "
                "Every factual conclusion must cite retrieved claim_id, source_id, and citation_locator. "
                "Expose weak evidence and contradictions instead of hiding uncertainty. "
                "Return only JSON with keys short_answer, analysis, citations, uncertainties, conflicts, suggested_title."
            ),
        },
        {
            "role": "user",
            "content": f"Question:\n{question}\n\nRetrieved evidence:\n{evidence_json}",
        },
    ]


def build_repair_prompt(question: str, retrieval: dict[str, Any]) -> list[dict[str, str]]:
    messages = build_answer_prompt(question, retrieval)
    messages.append(
        {
            "role": "user",
            "content": "Return valid JSON only. Do not include Markdown fences or prose outside JSON.",
        }
    )
    return messages


def answer_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["short_answer", "analysis", "citations", "uncertainties", "conflicts", "suggested_title"],
    }


def parse_llm_answer(content: str) -> dict[str, Any]:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("LLM answer JSON must be an object.")
    citations = payload.get("citations")
    if not isinstance(citations, list):
        raise ValueError("LLM answer citations must be a list.")
    return payload


def validate_answer_citations(
    payload: dict[str, Any],
    contexts: list[dict[str, Any]],
) -> list[AnswerCitation]:
    contexts_by_claim = {str(context["claim_id"]): context for context in contexts}
    citations: list[AnswerCitation] = []
    for raw_citation in payload.get("citations", []):
        if not isinstance(raw_citation, dict):
            raise ValueError("Answer citation must be an object.")
        claim_id = str(raw_citation.get("claim_id") or "")
        source_id = str(raw_citation.get("source_id") or "")
        citation_locator = str(raw_citation.get("citation_locator") or "")
        context = contexts_by_claim.get(claim_id)
        if context is None:
            raise ValueError(f"Answer cited claim outside retrieved evidence: {claim_id}")
        if source_id != str(context["source_id"]):
            raise ValueError(f"Answer citation source_id mismatch for {claim_id}")
        if citation_locator != str(context["citation_locator"]):
            raise ValueError(f"Answer citation locator mismatch for {claim_id}")
        citations.append(
            AnswerCitation(
                claim_id=claim_id,
                source_id=source_id,
                citation_locator=citation_locator,
                page_path=str(context["page_path"]),
            )
        )
    return citations


def failed_result(
    question: str,
    status: str,
    exc: BaseException,
    warnings: list[str],
    contexts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    planning: dict[str, Any] | None = None,
) -> AskResult:
    return AskResult(
        question=question,
        status=status,
        warnings=[*warnings, sanitize_error(exc)],
        contexts=contexts,
        relationships=relationships,
        planning=planning,
        error=sanitize_error(exc),
    )


def sanitize_error(exc: BaseException) -> str:
    text = str(exc)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", text)
    text = text.replace("config/api-keys.toml", "[api-key-file]")
    return text or exc.__class__.__name__
