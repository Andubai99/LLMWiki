from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any

from .db import catalog_path, connect
from .llm import create_provider, load_llm_config
from .providers.base import LLMProviderError


PLANNER_SCHEMA_VERSION = "query_plan.v2.5"
ALLOWED_INTENTS = {"lookup", "compare", "explain", "summarize", "verify", "unknown"}
ALLOWED_FILTER_KEYS = {"source_id", "page_type", "confidence"}
ALLOWED_CONFIDENCE = {None, "cited", "weak"}
FORBIDDEN_EVIDENCE_FIELDS = {"claim_id", "citation_locator", "page_path", "score"}


@dataclass(frozen=True)
class QuerySubquery:
    query: str
    purpose: str = ""
    filters: dict[str, str | None] = field(default_factory=dict)
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "purpose": self.purpose,
            "filters": self.filters,
            "required": self.required,
        }


@dataclass(frozen=True)
class RequiredEvidence:
    description: str
    coverage: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "description": self.description,
            "coverage": self.coverage,
        }


@dataclass(frozen=True)
class QueryPlan:
    schema_version: str
    intent: str
    question_summary: str
    entities: list[dict[str, Any]]
    concepts: list[dict[str, Any]]
    subqueries: list[QuerySubquery]
    required_evidence: list[RequiredEvidence]
    uncertainties: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intent": self.intent,
            "question_summary": self.question_summary,
            "entities": self.entities,
            "concepts": self.concepts,
            "subqueries": [subquery.to_dict() for subquery in self.subqueries],
            "required_evidence": [item.to_dict() for item in self.required_evidence],
            "uncertainties": self.uncertainties,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class PlanningOptions:
    limit: int = 8
    source_id: str | None = None
    page_type: str | None = None
    confidence: str | None = None
    max_subqueries: int = 8

    def to_filter_dict(self) -> dict[str, str | None]:
        return {
            "source_id": self.source_id,
            "page_type": self.page_type,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class PlanningResult:
    status: str
    plan: QueryPlan | None = None
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        if self.plan is None:
            return {
                "schema_version": PLANNER_SCHEMA_VERSION,
                "status": self.status,
                "intent": "",
                "subquery_count": 0,
                "retrieved_context_count": 0,
                "warnings": self.warnings,
                "error": self.error,
            }
        return {
            "schema_version": self.plan.schema_version,
            "status": self.status,
            "intent": self.plan.intent,
            "subquery_count": len(self.plan.subqueries),
            "retrieved_context_count": 0,
            "warnings": [*self.plan.warnings, *self.warnings],
            "plan": self.plan.to_dict(),
        }


class PlannerValidationError(ValueError):
    """Raised when LLM planner JSON cannot be safely executed."""


@dataclass(frozen=True)
class CatalogOverview:
    source_ids: set[str]
    page_ids: set[str]
    page_types: set[str]
    sources: list[dict[str, str]]
    pages: list[dict[str, str]]
    aliases: list[dict[str, str]]
    relationship_types: list[str]

    @property
    def catalog_refs(self) -> set[str]:
        return self.source_ids | self.page_ids

    def to_prompt_dict(self) -> dict[str, object]:
        return {
            "sources": self.sources,
            "pages": self.pages,
            "aliases": self.aliases,
            "relationship_types": self.relationship_types,
        }


def plan_question(root: Path, question: str, options: PlanningOptions | None = None) -> PlanningResult:
    root = root.resolve()
    options = options or PlanningOptions()
    catalog = load_catalog_overview(root)
    try:
        provider = create_provider(load_llm_config(root), root=root)
        messages = build_planner_prompt(question, options, catalog)
        response = provider.complete(messages, schema=planner_schema())
        plan = parse_and_validate_query_plan(str(response.get("content") or ""), catalog, options)
    except json.JSONDecodeError:
        try:
            repair_messages = build_planner_repair_prompt(question, options, catalog)
            response = provider.complete(repair_messages, schema=planner_schema())  # type: ignore[name-defined]
            plan = parse_and_validate_query_plan(str(response.get("content") or ""), catalog, options)
        except Exception as exc:
            return PlanningResult(status="planning_invalid", error=sanitize_planner_error(exc))
    except PlannerValidationError as exc:
        return PlanningResult(status="planning_invalid", error=sanitize_planner_error(exc))
    except (LLMProviderError, ValueError) as exc:
        return PlanningResult(status="planning_failed", error=sanitize_planner_error(exc))

    return PlanningResult(status="planned", plan=plan)


def build_planner_prompt(
    question: str,
    options: PlanningOptions,
    catalog: CatalogOverview,
) -> list[dict[str, str]]:
    payload = {
        "question": question,
        "filters": options.to_filter_dict(),
        "catalog": catalog.to_prompt_dict(),
        "schema": planner_schema(),
    }
    return [
        {
            "role": "system",
            "content": (
                "You are LLMWiki's query planner. Produce retrieval subqueries only. "
                "Do not answer the question. Do not provide evidence, claim ids, citation locators, "
                "page paths, scores, or fabricated catalog identifiers. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, indent=2),
        },
    ]


def build_planner_repair_prompt(
    question: str,
    options: PlanningOptions,
    catalog: CatalogOverview,
) -> list[dict[str, str]]:
    messages = build_planner_prompt(question, options, catalog)
    messages.append(
        {
            "role": "user",
            "content": "Return valid JSON only. Do not include Markdown fences or prose outside JSON.",
        }
    )
    return messages


def parse_query_plan(content: str) -> dict[str, Any]:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise PlannerValidationError("Planner JSON must be an object.")
    return payload


def parse_and_validate_query_plan(
    content: str,
    catalog: CatalogOverview,
    options: PlanningOptions | None = None,
) -> QueryPlan:
    return validate_query_plan(parse_query_plan(content), catalog, options or PlanningOptions())


def validate_query_plan(
    payload: dict[str, Any],
    catalog: CatalogOverview,
    options: PlanningOptions | None = None,
) -> QueryPlan:
    options = options or PlanningOptions()
    assert_no_forbidden_evidence_fields(payload)

    schema_version = str(payload.get("schema_version") or "")
    if schema_version != PLANNER_SCHEMA_VERSION:
        raise PlannerValidationError(f"Invalid planner schema_version: {schema_version}")

    intent = str(payload.get("intent") or "unknown")
    if intent not in ALLOWED_INTENTS:
        raise PlannerValidationError(f"Invalid planner intent: {intent}")

    raw_subqueries = payload.get("subqueries")
    if not isinstance(raw_subqueries, list) or not raw_subqueries:
        raise PlannerValidationError("Planner subqueries must be a non-empty list.")
    if len(raw_subqueries) > options.max_subqueries:
        raise PlannerValidationError(f"Planner subqueries exceed maximum: {options.max_subqueries}")

    subqueries = [parse_subquery(raw, catalog) for raw in raw_subqueries]
    validate_catalog_refs(payload.get("entities", []), catalog, "entities")
    validate_catalog_refs(payload.get("concepts", []), catalog, "concepts")

    return QueryPlan(
        schema_version=schema_version,
        intent=intent,
        question_summary=str(payload.get("question_summary") or ""),
        entities=list_of_dicts(payload.get("entities", []), "entities"),
        concepts=list_of_dicts(payload.get("concepts", []), "concepts"),
        subqueries=subqueries,
        required_evidence=parse_required_evidence(payload.get("required_evidence", [])),
        uncertainties=list_of_strings(payload.get("uncertainties", []), "uncertainties"),
        warnings=list_of_strings(payload.get("warnings", []), "warnings"),
    )


def parse_subquery(raw: Any, catalog: CatalogOverview) -> QuerySubquery:
    if not isinstance(raw, dict):
        raise PlannerValidationError("Planner subquery must be an object.")
    unknown_keys = set(raw.get("filters", {}).keys()) - ALLOWED_FILTER_KEYS if isinstance(raw.get("filters"), dict) else set()
    if unknown_keys:
        raise PlannerValidationError(f"Unknown planner filter keys: {', '.join(sorted(unknown_keys))}")
    query = str(raw.get("query") or "").strip()
    if not query:
        raise PlannerValidationError("Planner subquery query must not be empty.")
    if len(query) > 240:
        raise PlannerValidationError("Planner subquery query is too long.")
    filters = parse_filters(raw.get("filters", {}), catalog)
    return QuerySubquery(
        query=query,
        purpose=str(raw.get("purpose") or ""),
        filters=filters,
        required=bool(raw.get("required", True)),
    )


def parse_filters(raw: Any, catalog: CatalogOverview) -> dict[str, str | None]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise PlannerValidationError("Planner subquery filters must be an object.")
    source_id = optional_string(raw.get("source_id"))
    page_type = optional_string(raw.get("page_type"))
    confidence = optional_string(raw.get("confidence"))
    if source_id is not None and source_id not in catalog.source_ids:
        raise PlannerValidationError(f"Unknown source_id in planner filters: {source_id}")
    if page_type is not None and page_type not in catalog.page_types:
        raise PlannerValidationError(f"Unknown page_type in planner filters: {page_type}")
    if confidence not in ALLOWED_CONFIDENCE:
        raise PlannerValidationError(f"Invalid confidence in planner filters: {confidence}")
    return {"source_id": source_id, "page_type": page_type, "confidence": confidence}


def parse_required_evidence(raw: Any) -> list[RequiredEvidence]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PlannerValidationError("Planner required_evidence must be a list.")
    result: list[RequiredEvidence] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PlannerValidationError("Planner required_evidence item must be an object.")
        result.append(
            RequiredEvidence(
                description=str(item.get("description") or ""),
                coverage=str(item.get("coverage") or ""),
            )
        )
    return result


def validate_catalog_refs(raw: Any, catalog: CatalogOverview, field_name: str) -> None:
    for item in list_of_dicts(raw, field_name):
        refs = item.get("catalog_refs", [])
        if refs is None:
            continue
        if not isinstance(refs, list):
            raise PlannerValidationError(f"Planner {field_name}.catalog_refs must be a list.")
        for ref in refs:
            value = str(ref)
            if value and value not in catalog.catalog_refs:
                raise PlannerValidationError(f"Unknown catalog_ref in planner {field_name}: {value}")


def assert_no_forbidden_evidence_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if key_text in FORBIDDEN_EVIDENCE_FIELDS:
                raise PlannerValidationError(f"forbidden evidence field in planner output: {key_text}")
            assert_no_forbidden_evidence_fields(item, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_forbidden_evidence_fields(item, f"{path}[{index}]")


def list_of_dicts(raw: Any, field_name: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PlannerValidationError(f"Planner {field_name} must be a list.")
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PlannerValidationError(f"Planner {field_name} items must be objects.")
        result.append(dict(item))
    return result


def list_of_strings(raw: Any, field_name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PlannerValidationError(f"Planner {field_name} must be a list.")
    return [str(item) for item in raw if str(item).strip()]


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def planner_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["schema_version", "intent", "question_summary", "subqueries", "required_evidence"],
        "properties": {
            "schema_version": {"const": PLANNER_SCHEMA_VERSION},
            "intent": {"enum": sorted(ALLOWED_INTENTS)},
            "question_summary": {"type": "string"},
            "entities": {"type": "array"},
            "concepts": {"type": "array"},
            "subqueries": {"type": "array"},
            "required_evidence": {"type": "array"},
            "uncertainties": {"type": "array"},
            "warnings": {"type": "array"},
        },
    }


def load_catalog_overview(root: Path) -> CatalogOverview:
    with connect(catalog_path(root)) as conn:
        sources = [
            {"source_id": str(row["source_id"]), "title": str(row["title"])}
            for row in conn.execute(
                "select source_id, title from sources order by title, source_id limit 80"
            ).fetchall()
        ]
        pages = [
            {
                "page_id": str(row["page_id"]),
                "title": str(row["title"]),
                "page_type": str(row["page_type"]),
            }
            for row in conn.execute(
                "select page_id, title, page_type from pages order by page_type, title, page_id limit 120"
            ).fetchall()
        ]
        aliases = [
            {
                "alias": str(row["alias"]),
                "target_type": str(row["target_type"]),
                "target_id": str(row["target_id"]),
            }
            for row in conn.execute(
                "select alias, target_type, target_id from aliases order by alias, target_id limit 160"
            ).fetchall()
        ]
        relationship_types = [
            str(row["relationship_type"])
            for row in conn.execute(
                "select distinct relationship_type from relationships order by relationship_type"
            ).fetchall()
        ]
    return CatalogOverview(
        source_ids={item["source_id"] for item in sources},
        page_ids={item["page_id"] for item in pages},
        page_types={item["page_type"] for item in pages},
        sources=sources,
        pages=pages,
        aliases=aliases,
        relationship_types=relationship_types,
    )


def sanitize_planner_error(exc: BaseException) -> str:
    text = str(exc)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", text)
    text = text.replace("config/api-keys.toml", "[api-key-file]")
    return text or exc.__class__.__name__
