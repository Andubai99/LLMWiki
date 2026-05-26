from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import re

from .llm import create_provider, load_llm_config
from .providers.base import LLMProviderError


@dataclass(frozen=True)
class LLMIngestProposal:
    claims: list[dict[str, str]]
    concept_title: str | None
    aliases: list[str]
    entity_title: str | None
    entity_aliases: list[str]
    duplicate_candidates: list[str]
    conflict_candidates: list[str]
    source_summary: str | None
    concept_definition: str | None
    provider: str
    model: str
    raw_content: str
    usage: dict[str, Any]


def create_llm_ingest_proposal(
    root: Path,
    source: dict[str, str],
    normalized_text: str,
) -> LLMIngestProposal | None:
    config = load_llm_config(root)
    if not config.enabled:
        return None
    provider = create_provider(config)
    response = provider.complete(build_ingest_messages(source, normalized_text), schema=proposal_schema())
    content = str(response.get("content") or "")
    payload = parse_json_object(content)
    proposal = normalize_payload(payload, source["source_id"], normalized_text)
    if not any(claim["confidence_status"] == "cited" for claim in proposal.claims):
        raise LLMProviderError("LLM ingest proposal did not include any cited claims with valid source locators")
    return LLMIngestProposal(
        claims=proposal.claims,
        concept_title=proposal.concept_title,
        aliases=proposal.aliases,
        entity_title=proposal.entity_title,
        entity_aliases=proposal.entity_aliases,
        duplicate_candidates=proposal.duplicate_candidates,
        conflict_candidates=proposal.conflict_candidates,
        source_summary=proposal.source_summary,
        concept_definition=proposal.concept_definition,
        provider=str(response.get("provider") or "openai"),
        model=str(response.get("model") or config.model),
        raw_content=content,
        usage=dict(response.get("usage") or {}),
    )


def build_ingest_messages(source: dict[str, str], normalized_text: str) -> list[dict[str, str]]:
    content = normalized_text[:16000]
    return [
        {
            "role": "system",
            "content": (
                "You maintain a local Markdown research wiki through staged proposals only. "
                "Extract claims from the provided normalized source. "
                "Use only line locators present in the source. "
                "Return strict JSON only, with no markdown fences or commentary."
            ),
        },
        {
            "role": "user",
            "content": (
                f"source_id: {source['source_id']}\n"
                f"title: {source['title']}\n\n"
                "Return this JSON object:\n"
                "{\n"
                '  "claims": [\n'
                '    {"claim_text": "...", "citation_locator": "line:N", "confidence_status": "cited"}\n'
                "  ],\n"
                '  "concept": {"title": "...", "aliases": ["..."]},\n'
                '  "entity": {"title": "...", "aliases": ["..."]} or null,\n'
                '  "duplicate_candidates": ["..."],\n'
                '  "conflict_candidates": ["..."],\n'
                '  "source_summary": "...",\n'
                '  "concept_definition": "..."\n'
                "}\n\n"
                "Rules:\n"
                "- Every important claim must include a line:N locator copied from the source.\n"
                "- If a claim lacks a valid locator, mark confidence_status as weak or uncited.\n"
                "- Do not invent sources, page paths, or citations.\n"
                "- Preserve conflicts instead of choosing a winner.\n\n"
                "Normalized source:\n"
                f"{content}"
            ),
        },
    ]


def proposal_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["claims", "concept", "source_summary"],
        "properties": {
            "claims": {"type": "array"},
            "concept": {"type": "object"},
            "entity": {"type": ["object", "null"]},
            "duplicate_candidates": {"type": "array"},
            "conflict_candidates": {"type": "array"},
            "source_summary": {"type": "string"},
            "concept_definition": {"type": "string"},
        },
    }


def parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LLMProviderError("LLM ingest response did not contain a JSON object")
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise LLMProviderError("LLM ingest response JSON root must be an object")
    return parsed


def normalize_payload(
    payload: dict[str, Any],
    source_id: str,
    normalized_text: str,
) -> LLMIngestProposal:
    locators = line_locators(normalized_text)
    claims: list[dict[str, str]] = []
    for index, item in enumerate(payload.get("claims") or [], start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("claim_text") or "").strip()
        if not text:
            continue
        locator = canonical_locator(str(item.get("citation_locator") or ""), locators)
        confidence = str(item.get("confidence_status") or "cited").casefold()
        if confidence not in {"cited", "weak", "uncited"}:
            confidence = "cited"
        if not locator:
            confidence = "weak" if confidence == "cited" else confidence
        claims.append(
            {
                "claim_id": f"clm_{source_id}_llm_{index:03d}",
                "source_id": source_id,
                "claim_text": text,
                "citation_locator": locator,
                "confidence_status": confidence,
            }
        )

    concept = payload.get("concept") if isinstance(payload.get("concept"), dict) else {}
    entity = payload.get("entity") if isinstance(payload.get("entity"), dict) else {}
    return LLMIngestProposal(
        claims=claims,
        concept_title=clean_optional_string(concept.get("title")) if concept else None,
        aliases=clean_string_list(concept.get("aliases") if concept else []),
        entity_title=clean_optional_string(entity.get("title")) if entity else None,
        entity_aliases=clean_string_list(entity.get("aliases") if entity else []),
        duplicate_candidates=clean_string_list(payload.get("duplicate_candidates") or []),
        conflict_candidates=clean_string_list(payload.get("conflict_candidates") or []),
        source_summary=clean_optional_string(payload.get("source_summary")),
        concept_definition=clean_optional_string(payload.get("concept_definition")),
        provider="openai",
        model="",
        raw_content="",
        usage={},
    )


def line_locators(normalized_text: str) -> dict[str, str]:
    locators: dict[str, str] = {}
    current_section = ""
    current_paragraph = ""
    for line in normalized_text.splitlines():
        section_match = re.match(r"<!-- section:(.*?) -->", line)
        if section_match:
            current_section = section_match.group(1).strip()
            current_paragraph = ""
            continue
        paragraph_match = re.match(r"<!-- paragraph:(\d+) -->", line)
        if paragraph_match:
            current_paragraph = paragraph_match.group(1)
            continue
        line_match = re.match(r"\[line:(\d+)\]", line)
        if not line_match:
            continue
        parts = [f"line:{line_match.group(1)}"]
        if current_section:
            parts.append(f"section:{current_section}")
        if current_paragraph:
            parts.append(f"paragraph:{current_paragraph}")
        locators[line_match.group(1)] = ";".join(parts)
    return locators


def canonical_locator(value: str, locators: dict[str, str]) -> str:
    match = re.search(r"line:(\d+)", value)
    if not match:
        return ""
    return locators.get(match.group(1), "")


def clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result
