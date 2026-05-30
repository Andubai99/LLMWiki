from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .answer import AskResult
from .db import RELATIONSHIP_TYPES, catalog_path, connect
from .llm import create_provider, load_llm_config
from .pipeline import sanitize_error


SYNTHESIS_PLAN_SCHEMA_VERSION = "synthesis_plan.v2.8"
SYNTHESIS_ACTIONS = {"create", "update", "needs_review"}
SYNTHESIS_STATUSES = {"planned", "needs_review"}
EVIDENCE_ROLES = {"supports", "limits", "contradicts", "background", "open_question"}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"config[/\\]api-keys\.toml", re.IGNORECASE),
)


class SynthesisPlanningError(ValueError):
    """Raised when a synthesis plan cannot be safely staged."""


@dataclass(frozen=True)
class SynthesisEvidenceItem:
    role: str
    claim_id: str
    source_id: str
    citation_locator: str
    page_path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "claim_id": self.claim_id,
            "source_id": self.source_id,
            "citation_locator": self.citation_locator,
            "page_path": self.page_path,
        }


@dataclass(frozen=True)
class SynthesisRelationship:
    subject_id: str
    object_id: str
    relationship_type: str
    evidence_claim_id: str = ""
    source_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "subject_id": self.subject_id,
            "object_id": self.object_id,
            "relationship_type": self.relationship_type,
            "evidence_claim_id": self.evidence_claim_id,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class SynthesisCandidate:
    page_id: str
    title: str
    path: str
    aliases: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    updated_at: str = ""
    match_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "path": self.path,
            "aliases": self.aliases,
            "claim_ids": self.claim_ids,
            "updated_at": self.updated_at,
            "match_reasons": self.match_reasons,
        }


@dataclass(frozen=True)
class SynthesisPlanningOptions:
    writeback_mode: str = "auto"


@dataclass(frozen=True)
class SynthesisPlan:
    schema_version: str
    status: str
    action: str
    target_page_id: str
    target_path: str
    title: str
    topic_key: str
    aliases: list[str] = field(default_factory=list)
    evidence: list[SynthesisEvidenceItem] = field(default_factory=list)
    sections: dict[str, Any] = field(default_factory=dict)
    related_pages: list[str] = field(default_factory=list)
    relationships: list[SynthesisRelationship] = field(default_factory=list)
    candidate_pages: list[SynthesisCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def evidence_claim_ids(self) -> list[str]:
        return [item.claim_id for item in self.evidence]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "action": self.action,
            "target_page_id": self.target_page_id,
            "target_path": self.target_path,
            "title": self.title,
            "topic_key": self.topic_key,
            "aliases": self.aliases,
            "evidence": [item.to_dict() for item in self.evidence],
            "evidence_claim_ids": self.evidence_claim_ids,
            "sections": self.sections,
            "related_pages": self.related_pages,
            "relationships": [item.to_dict() for item in self.relationships],
            "candidate_pages": [item.to_dict() for item in self.candidate_pages],
            "warnings": self.warnings,
        }


def plan_synthesis_writeback(
    root: Path,
    ask_result: AskResult,
    options: SynthesisPlanningOptions | None = None,
) -> SynthesisPlan:
    root = root.resolve()
    options = options or SynthesisPlanningOptions()
    candidates = collect_synthesis_candidates(root, ask_result)
    payload = {
        "question": ask_result.question,
        "answer": ask_result.answer,
        "analysis": ask_result.analysis,
        "citations": [citation.to_dict() for citation in ask_result.citations],
        "suggested_title": ask_result.suggested_title,
        "existing_syntheses": [candidate.to_dict() for candidate in candidates],
        "writeback_mode": options.writeback_mode,
        "schema": synthesis_plan_schema(),
    }
    provider = create_provider(load_llm_config(root), root=root)
    response = provider.complete(build_synthesis_planner_prompt(payload), schema=synthesis_plan_schema())
    content = str(response.get("content") or "")
    try:
        plan = parse_synthesis_plan(content, candidates)
        validate_synthesis_plan(root, ask_result, plan, options)
    except (json.JSONDecodeError, SynthesisPlanningError) as exc:
        error = sanitize_synthesis_error(exc)
        try:
            response = provider.complete(
                build_synthesis_planner_repair_prompt(payload, error=error, original_output=content),
                schema=synthesis_plan_schema(),
            )
            repaired_content = str(response.get("content") or "")
            plan = parse_synthesis_plan(repaired_content, candidates)
            validate_synthesis_plan(root, ask_result, plan, options)
        except Exception as repair_exc:
            if isinstance(repair_exc, SynthesisPlanningError):
                raise SynthesisPlanningError(sanitize_synthesis_error(repair_exc)) from repair_exc
            raise SynthesisPlanningError(sanitize_synthesis_error(exc)) from repair_exc
    return plan


def parse_synthesis_plan(content: str, candidates: list[SynthesisCandidate] | None = None) -> SynthesisPlan:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise SynthesisPlanningError("Synthesis plan JSON must be an object.")
    evidence = [
        SynthesisEvidenceItem(
            role=str(item.get("role") or "supports"),
            claim_id=str(item.get("claim_id") or ""),
            source_id=str(item.get("source_id") or ""),
            citation_locator=str(item.get("citation_locator") or ""),
            page_path=str(item.get("page_path") or ""),
        )
        for item in list_value(payload.get("evidence"))
        if isinstance(item, dict)
    ]
    relationships = [
        SynthesisRelationship(
            subject_id=str(item.get("subject_id") or ""),
            object_id=str(item.get("object_id") or ""),
            relationship_type=str(item.get("relationship_type") or ""),
            evidence_claim_id=str(item.get("evidence_claim_id") or ""),
            source_id=str(item.get("source_id") or ""),
        )
        for item in list_value(payload.get("relationships"))
        if isinstance(item, dict)
    ]
    candidate_lookup = {candidate.page_id: candidate for candidate in candidates or []}
    candidate_pages = [
        candidate_lookup.get(str(item.get("page_id") or ""))
        or SynthesisCandidate(
            page_id=str(item.get("page_id") or ""),
            title=str(item.get("title") or ""),
            path=str(item.get("path") or ""),
        )
        for item in list_value(payload.get("candidate_pages"))
        if isinstance(item, dict)
    ]
    return SynthesisPlan(
        schema_version=str(payload.get("schema_version") or ""),
        status=str(payload.get("status") or "planned"),
        action=str(payload.get("action") or ""),
        target_page_id=str(payload.get("target_page_id") or ""),
        target_path=str(payload.get("target_path") or ""),
        title=str(payload.get("title") or ""),
        topic_key=str(payload.get("topic_key") or ""),
        aliases=[str(item) for item in list_value(payload.get("aliases"))],
        evidence=evidence,
        sections=dict_value(payload.get("sections")),
        related_pages=[str(item) for item in list_value(payload.get("related_pages"))],
        relationships=relationships,
        candidate_pages=[candidate for candidate in candidate_pages if candidate is not None],
        warnings=[str(item) for item in list_value(payload.get("warnings"))],
    )


def validate_synthesis_plan(
    root: Path,
    ask_result: AskResult,
    plan: SynthesisPlan,
    options: SynthesisPlanningOptions | None = None,
) -> None:
    options = options or SynthesisPlanningOptions()
    text = json.dumps(plan.to_dict(), ensure_ascii=False)
    if contains_secret(text):
        raise SynthesisPlanningError("Synthesis plan contains a redacted secret reference.")
    if plan.schema_version != SYNTHESIS_PLAN_SCHEMA_VERSION:
        raise SynthesisPlanningError("Invalid synthesis plan schema_version.")
    if plan.status not in SYNTHESIS_STATUSES:
        raise SynthesisPlanningError("Invalid synthesis plan status.")
    if plan.action not in SYNTHESIS_ACTIONS:
        raise SynthesisPlanningError("Invalid synthesis plan action.")
    if plan.action == "needs_review" and plan.status != "needs_review":
        raise SynthesisPlanningError("needs_review action must use needs_review status.")
    if plan.action in {"create", "update"} and plan.status != "planned":
        raise SynthesisPlanningError("create/update synthesis actions must use planned status.")
    if options.writeback_mode in {"create", "update"} and plan.action != options.writeback_mode:
        raise SynthesisPlanningError(f"Synthesis plan action must be {options.writeback_mode}.")
    validate_target_page_id(plan.target_page_id)
    validate_target_path(plan.target_path)

    cited_contexts = {citation.claim_id: citation for citation in ask_result.citations}
    catalog = load_catalog_evidence(root)
    for item in plan.evidence:
        if item.role not in EVIDENCE_ROLES:
            raise SynthesisPlanningError(f"Invalid evidence role: {item.role}")
        catalog_item = catalog["claims"].get(item.claim_id)
        if catalog_item is None:
            raise SynthesisPlanningError(f"unknown claim: {item.claim_id}")
        if item.claim_id not in cited_contexts:
            raise SynthesisPlanningError(f"evidence claim not cited by answer: {item.claim_id}")
        citation = cited_contexts[item.claim_id]
        if item.source_id != citation.source_id or item.source_id != catalog_item["source_id"]:
            raise SynthesisPlanningError(f"source_id mismatch for claim: {item.claim_id}")
        if item.citation_locator != citation.citation_locator or item.citation_locator != catalog_item["citation_locator"]:
            raise SynthesisPlanningError(f"citation_locator mismatch for claim: {item.claim_id}")
        if item.page_path != citation.page_path or item.page_path not in catalog["page_paths"]:
            raise SynthesisPlanningError(f"page_path mismatch for claim: {item.claim_id}")

    for page_path in plan.related_pages:
        if page_path not in catalog["page_paths"]:
            raise SynthesisPlanningError(f"unknown related page: {page_path}")

    for relationship in plan.relationships:
        if relationship.relationship_type not in RELATIONSHIP_TYPES:
            raise SynthesisPlanningError(f"unknown relationship_type: {relationship.relationship_type}")
        valid_subjects = set(catalog["page_ids"]) | set(catalog["source_ids"]) | {plan.target_page_id}
        valid_objects = (
            set(catalog["page_ids"])
            | set(catalog["source_ids"])
            | set(catalog["claims"].keys())
            | {plan.target_page_id}
        )
        if relationship.subject_id not in valid_subjects:
            raise SynthesisPlanningError(f"unknown relationship subject: {relationship.subject_id}")
        if relationship.object_id not in valid_objects:
            raise SynthesisPlanningError(f"unknown relationship object: {relationship.object_id}")
        if relationship.evidence_claim_id and relationship.evidence_claim_id not in catalog["claims"]:
            raise SynthesisPlanningError(f"unknown relationship evidence claim: {relationship.evidence_claim_id}")
        if relationship.source_id and relationship.source_id not in catalog["source_ids"] and not relationship.source_id.startswith("synthesis:"):
            raise SynthesisPlanningError(f"unknown relationship source: {relationship.source_id}")

    with connect(catalog_path(root)) as conn:
        target = conn.execute(
            "select page_type, path from pages where page_id = ?",
            (plan.target_page_id,),
        ).fetchone()
    target_exists = target is not None
    if plan.action == "update":
        if not target_exists:
            raise SynthesisPlanningError("update target synthesis page does not exist")
        if str(target["page_type"]) != "synthesis":
            raise SynthesisPlanningError("update target is not a synthesis page")
        if str(target["path"]) != plan.target_path:
            raise SynthesisPlanningError("update target_path mismatch")
    elif plan.action == "create":
        if target_exists:
            raise SynthesisPlanningError("create target already exists")
    elif plan.action == "needs_review" and not plan.warnings:
        raise SynthesisPlanningError("needs_review plan must include warnings")


def collect_synthesis_candidates(root: Path, ask_result: AskResult) -> list[SynthesisCandidate]:
    claim_ids = {citation.claim_id for citation in ask_result.citations}
    source_ids = {citation.source_id for citation in ask_result.citations}
    title_terms = normalized_terms([ask_result.suggested_title, ask_result.question])
    candidates: list[SynthesisCandidate] = []
    with connect(catalog_path(root)) as conn:
        rows = conn.execute(
            """
            select page_id, path, title, aliases, updated_at
            from pages
            where page_type = 'synthesis'
            order by updated_at desc, title
            """
        ).fetchall()
        for row in rows:
            page_claim_ids = read_claim_ids_from_page(root / str(row["path"]))
            reasons: list[str] = []
            if claim_ids.intersection(page_claim_ids):
                reasons.append("claim_overlap")
            if title_terms.intersection(normalized_terms([str(row["title"])])):
                reasons.append("title_overlap")
            if source_ids and source_ids.intersection(read_source_ids_for_claims(root, page_claim_ids)):
                reasons.append("source_overlap")
            if reasons:
                candidates.append(
                    SynthesisCandidate(
                        page_id=str(row["page_id"]),
                        title=str(row["title"]),
                        path=str(row["path"]),
                        aliases=parse_json_list(str(row["aliases"])),
                        claim_ids=page_claim_ids,
                        updated_at=str(row["updated_at"]),
                        match_reasons=reasons,
                    )
                )
    return candidates


def format_synthesis_preview(plan: SynthesisPlan) -> str:
    lines = [
        "Synthesis proposal:",
        f"- action: {plan.action}",
        f"- page: {plan.target_path}",
        f"- title: {plan.title}",
        f"- evidence claims: {len(plan.evidence)}",
    ]
    if plan.related_pages:
        lines.append("- related pages:")
        lines.extend(f"  - {page}" for page in plan.related_pages)
    if plan.warnings:
        lines.append("- warnings:")
        lines.extend(f"  - {warning}" for warning in plan.warnings)
    return "\n".join(lines)


def build_synthesis_planner_prompt(payload: dict[str, object]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You plan LLMWiki synthesis writeback. Return JSON only. "
                "Choose create, update, or needs_review. Do not invent evidence identifiers; "
                "use only the provided citations and existing synthesis summaries."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def build_synthesis_planner_repair_prompt(
    payload: dict[str, object],
    *,
    error: str,
    original_output: str,
) -> list[dict[str, str]]:
    messages = build_synthesis_planner_prompt(payload)
    messages.append(
        {
            "role": "user",
            "content": (
                "Return valid JSON only. Do not include Markdown fences or prose outside JSON. "
                f"The previous synthesis plan failed validation: {error}. "
                f"schema_version must be exactly {SYNTHESIS_PLAN_SCHEMA_VERSION}. "
                "status must be planned for create/update, or needs_review for needs_review. "
                "action must be create, update, or needs_review. "
                "target_page_id must be a page id, not a filesystem path. "
                "target_path must be under wiki/syntheses/ and end with .md. "
                "sections must be an object with scope, current_answer, analysis, "
                "conflicts_and_limits, and open_questions, not an array. "
                "relationships may be an empty array. If a relationship is present, "
                f"relationship_type must be one of: {', '.join(RELATIONSHIP_TYPES)}. "
                "Do not include relationship objects with blank relationship_type. "
                "subject_id and object_id must be existing catalog identifiers, "
                "or the target_page_id for a newly created synthesis page. "
                "related_pages must be an array of existing page path strings, not objects. "
                "Use only the provided citations for evidence; do not invent claim ids, "
                "source ids, citation locators, or page paths.\n"
                f"Original invalid output:\n{original_output}"
            ),
        }
    )
    return messages


def synthesis_plan_schema() -> dict[str, object]:
    return {
        "type": "object",
        "required": [
            "schema_version",
            "status",
            "action",
            "target_page_id",
            "target_path",
            "title",
            "topic_key",
            "evidence",
            "sections",
            "related_pages",
            "relationships",
            "warnings",
        ],
    }


def load_catalog_evidence(root: Path) -> dict[str, Any]:
    with connect(catalog_path(root)) as conn:
        claims = {
            str(row["claim_id"]): {
                "source_id": str(row["source_id"]),
                "citation_locator": str(row["citation_locator"] or ""),
            }
            for row in conn.execute("select claim_id, source_id, citation_locator from claims").fetchall()
        }
        source_ids = {str(row["source_id"]) for row in conn.execute("select source_id from sources").fetchall()}
        page_rows = conn.execute("select page_id, path from pages").fetchall()
        page_ids = {str(row["page_id"]) for row in page_rows}
        page_paths = {str(row["path"]) for row in page_rows}
    return {"claims": claims, "source_ids": source_ids, "page_ids": page_ids, "page_paths": page_paths}


def validate_target_path(target_path: str) -> None:
    pure = PurePosixPath(target_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise SynthesisPlanningError("unsafe target_path")
    if len(pure.parts) != 3 or pure.parts[0] != "wiki" or pure.parts[1] != "syntheses":
        raise SynthesisPlanningError("target_path must be under wiki/syntheses")
    if pure.suffix.lower() != ".md":
        raise SynthesisPlanningError("target_path must be Markdown")


def validate_target_page_id(target_page_id: str) -> None:
    if not target_page_id.strip():
        raise SynthesisPlanningError("target_page_id must not be empty")
    if "/" in target_page_id or "\\" in target_page_id:
        raise SynthesisPlanningError("target_page_id must be a page id, not a path")


def read_claim_ids_from_page(path: Path) -> list[str]:
    if not path.exists():
        return []
    match = re.search(r"(?m)^claim_ids:\s*(.+)$", path.read_text(encoding="utf-8"))
    if not match:
        return []
    try:
        parsed = json.loads(match.group(1).replace("'", '"'))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def read_source_ids_for_claims(root: Path, claim_ids: list[str]) -> set[str]:
    if not claim_ids:
        return set()
    placeholders = ",".join("?" for _ in claim_ids)
    with connect(catalog_path(root)) as conn:
        rows = conn.execute(
            f"select distinct source_id from claims where claim_id in ({placeholders})",
            tuple(claim_ids),
        ).fetchall()
    return {str(row["source_id"]) for row in rows}


def normalized_terms(values: list[str]) -> set[str]:
    terms: set[str] = set()
    for value in values:
        for token in re.findall(r"[\w\u4e00-\u9fff]+", value.casefold()):
            if len(token) > 2:
                terms.add(token)
    return terms


def parse_json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def sanitize_synthesis_error(exc: BaseException) -> str:
    return sanitize_error(exc)
