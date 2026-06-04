from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import re

from ..llm import create_provider, load_llm_config
from ..pdf.blocks import SourceBlock, block_comment, block_evidence_text, load_blocks_jsonl, load_metadata_json
from ..providers.base import LLMProviderError
from ..pdf.chunks import SourceChunk, load_chunks_jsonl
from .metric_results import (
    MetricResultValidationError,
    assign_metric_result_ids,
    dedupe_metric_results,
    metric_result_from_candidate,
    validate_pdf_result_locator,
)


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
    repair_events: list[LLMJsonRepairEvent] = field(default_factory=list)
    metric_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class LLMJsonRepairEvent:
    response_kind: str
    chunk_id: str | None
    status: str
    error: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "response_kind": self.response_kind,
            "chunk_id": self.chunk_id,
            "status": self.status,
            "error": self.error,
        }


def create_llm_ingest_proposal(
    root: Path,
    source: dict[str, str],
    normalized_text: str,
) -> LLMIngestProposal | None:
    config = load_llm_config(root)
    if not config.enabled:
        return None
    provider = create_provider(config, root=root)
    if is_chunked_pdf_source(root, source):
        return create_chunked_pdf_ingest_proposal(root, source, normalized_text, provider, config)
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


def is_chunked_pdf_source(root: Path, source: dict[str, str]) -> bool:
    source_id = source["source_id"]
    return (
        str(source.get("source_type") or "") == "pdf"
        and (root / "sources" / "blocks" / f"{source_id}.jsonl").exists()
        and (root / "sources" / "chunks" / f"{source_id}.jsonl").exists()
    )


def create_chunked_pdf_ingest_proposal(
    root: Path,
    source: dict[str, str],
    normalized_text: str,
    provider: Any,
    config: Any,
) -> LLMIngestProposal:
    source_id = source["source_id"]
    blocks_path = root / "sources" / "blocks" / f"{source_id}.jsonl"
    chunks_path = root / "sources" / "chunks" / f"{source_id}.jsonl"
    metadata_path = root / "sources" / "metadata" / f"{source_id}.json"
    blocks = load_blocks_jsonl(blocks_path)
    chunks = load_chunks_jsonl(chunks_path)
    metadata = load_metadata_json(metadata_path) if metadata_path.exists() else None
    blocks_by_id = {block.block_id: block for block in blocks}
    if not chunks:
        raise LLMProviderError("PDF source has no chunks for LLM ingest")

    all_claims: list[dict[str, str]] = []
    metric_candidate_records: list[dict[str, Any]] = []
    chunk_records: list[dict[str, Any]] = []
    repair_events: list[LLMJsonRepairEvent] = []
    usage = empty_usage()
    response_provider = "openai"
    response_model = str(getattr(config, "model", "") or "")

    for chunk in chunks:
        chunk_text = render_chunk_evidence(chunk, blocks_by_id)
        response = provider.complete(build_chunk_ingest_messages(source, chunk, chunk_text), schema=chunk_proposal_schema())
        response_provider = str(response.get("provider") or response_provider)
        response_model = str(response.get("model") or response_model)
        content = str(response.get("content") or "")
        payload, content, events, repair_usage = parse_llm_json_with_repair(
            content=content,
            provider=provider,
            schema=chunk_proposal_schema(),
            response_kind="chunk",
            chunk_id=chunk.chunk_id,
        )
        repair_events.extend(events)
        chunk_proposal = normalize_payload({"claims": payload.get("claims") or []}, source_id, chunk_text)
        chunk_claims = cited_claims_only(chunk_proposal.claims)
        all_claims.extend(chunk_claims)
        allowed_block_ids = set(chunk.block_ids) | set(chunk.context_block_ids)
        for raw_candidate in payload.get("metric_result_candidates") or []:
            if not isinstance(raw_candidate, dict):
                continue
            try:
                validation = validate_pdf_result_locator(
                    str(raw_candidate.get("citation_locator") or ""),
                    source_id=source_id,
                    blocks_by_id=blocks_by_id,
                    allowed_block_ids=allowed_block_ids,
                )
            except MetricResultValidationError:
                continue
            claim_text = clean_optional_string(raw_candidate.get("claim_text")) or ""
            metric_name = clean_optional_string(raw_candidate.get("metric_name")) or ""
            if not claim_text or not metric_name:
                continue
            metric_candidate_records.append(
                {
                    "raw": raw_candidate,
                    "claim_text": claim_text,
                    "citation_locator": validation.normalized_locator,
                    "confidence_status": str(raw_candidate.get("confidence_status") or "cited"),
                    "locator_validation": validation,
                }
            )
        add_usage(usage, dict(response.get("usage") or {}))
        add_usage(usage, repair_usage)
        chunk_records.append(
            {
                "chunk_id": chunk.chunk_id,
                "chunk_type": chunk.chunk_type,
                "block_ids": chunk.block_ids,
                "chunk_summary": clean_optional_string(payload.get("chunk_summary")) or "",
                "metric_result_candidate_count": len(payload.get("metric_result_candidates") or []),
                "raw_content": content,
            }
        )

    consolidation_response = provider.complete(
        build_pdf_consolidation_messages(source, metadata, chunk_records),
        schema=proposal_schema(),
    )
    response_provider = str(consolidation_response.get("provider") or response_provider)
    response_model = str(consolidation_response.get("model") or response_model)
    consolidation_content = str(consolidation_response.get("content") or "")
    consolidation_payload, consolidation_content, events, repair_usage = parse_llm_json_with_repair(
        content=consolidation_content,
        provider=provider,
        schema=proposal_schema(),
        response_kind="consolidation",
    )
    repair_events.extend(events)
    consolidation = normalize_payload({**consolidation_payload, "claims": []}, source_id, normalized_text)
    add_usage(usage, dict(consolidation_response.get("usage") or {}))
    add_usage(usage, repair_usage)

    claims = dedupe_exact_claims(all_claims, source_id)
    metric_results = metric_results_for_claims(
        metric_candidate_records,
        claims=claims,
        source_id=source_id,
        paper_id=source_id,
    )
    if not any(claim["confidence_status"] == "cited" for claim in claims):
        raise LLMProviderError("LLM ingest proposal did not include any cited claims with valid source locators")

    raw_content = json.dumps(
        {
            "mode": "chunked_pdf",
            "chunk_count": len(chunks),
            "block_count": len(blocks),
            "chunk_responses": chunk_records,
            "consolidation": consolidation_content,
            "llm_json_repair_events": [event.to_dict() for event in repair_events],
        },
        ensure_ascii=False,
    )
    return LLMIngestProposal(
        claims=claims,
        concept_title=consolidation.concept_title,
        aliases=consolidation.aliases,
        entity_title=consolidation.entity_title,
        entity_aliases=consolidation.entity_aliases,
        duplicate_candidates=consolidation.duplicate_candidates,
        conflict_candidates=consolidation.conflict_candidates,
        source_summary=consolidation.source_summary,
        concept_definition=consolidation.concept_definition,
        provider=response_provider,
        model=response_model,
        raw_content=raw_content,
        usage=usage,
        repair_events=repair_events,
        metric_results=[result.to_dict() for result in metric_results],
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


def build_chunk_ingest_messages(source: dict[str, str], chunk: SourceChunk, chunk_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You maintain a local Markdown research wiki through staged proposals only. "
                "Extract citation-backed claims from one PDF chunk. "
                "Use only block locators present in this chunk. "
                "Return strict JSON only, with no markdown fences or commentary."
            ),
        },
        {
            "role": "user",
            "content": (
                "PDF chunk claim extraction\n"
                f"source_id: {source['source_id']}\n"
                f"title: {source['title']}\n"
                f"chunk_id: {chunk.chunk_id}\n"
                f"chunk_type: {chunk.chunk_type}\n"
                f"section_path: {' > '.join(chunk.section_path) if chunk.section_path else '(none)'}\n\n"
                "Return this JSON object:\n"
                "{\n"
                '  "claims": [\n'
                '    {"claim_text": "...", "citation_locator": "block:<block_id>", "confidence_status": "cited"}\n'
                "  ],\n"
                '  "metric_result_candidates": [\n'
                '    {\n'
                '      "claim_text": "...",\n'
                '      "citation_locator": "block:<block_id>",\n'
                '      "confidence_status": "cited",\n'
                '      "extraction_origin": "abstract|method|experiment|table|caption|conclusion|other",\n'
                '      "method": "", "dataset": "", "task": "",\n'
                '      "metric_name": "", "metric_raw_value": "", "metric_direction": "unknown",\n'
                '      "baseline": "", "comparison_value": "", "setting": "",\n'
                '      "is_main_result": null, "warnings": []\n'
                "    }\n"
                "  ],\n"
                '  "chunk_summary": "..."\n'
                "}\n\n"
                "Rules:\n"
                "- Every important claim must cite block:<block_id> from the evidence below.\n"
                "- Extract metric_result_candidates only when this chunk explicitly reports a metric/result.\n"
                "- Relevant result regions include abstract headline results, method sections that report results, experiment/results sections, tables, captions, and conclusion or limitation sections.\n"
                "- Do not infer missing baselines, datasets, methods, metric directions, or values.\n"
                "- Do not cite blocks outside this chunk.\n"
                "- Do not invent sources, page paths, or citations.\n\n"
                "Chunk evidence:\n"
                f"{chunk_text}"
            ),
        },
    ]


def build_pdf_consolidation_messages(
    source: dict[str, str],
    metadata: Any,
    chunk_records: list[dict[str, Any]],
) -> list[dict[str, str]]:
    chunk_summaries = "\n".join(
        f"- {record['chunk_id']} ({record['chunk_type']}): {record.get('chunk_summary') or '(no summary)'}"
        for record in chunk_records
    )
    title = getattr(metadata, "title", "") or source.get("title") or ""
    page_count = getattr(metadata, "page_count", None)
    paper_identity = getattr(metadata, "paper_identity", {}) or {}
    parser_quality = getattr(metadata, "parser_quality", {}) or {}
    section_claim_counts = {
        record["chunk_id"]: len(record.get("block_ids") or [])
        for record in chunk_records
    }
    return [
        {
            "role": "system",
            "content": (
                "You consolidate chunk-level PDF extraction into page proposals. "
                "Do not create formal claims in this step. "
                "Return strict JSON only, with no markdown fences or commentary."
            ),
        },
        {
            "role": "user",
            "content": (
                "PDF consolidation\n"
                f"source_id: {source['source_id']}\n"
                f"title: {title}\n"
                f"page_count: {page_count if page_count is not None else 'unknown'}\n"
                f"paper_identity: {json.dumps(paper_identity, ensure_ascii=False)}\n"
                f"parser_quality: {json.dumps(parser_quality, ensure_ascii=False)}\n"
                f"section_claim_context: {json.dumps(section_claim_counts, ensure_ascii=False)}\n\n"
                "Return this JSON object:\n"
                "{\n"
                '  "claims": [],\n'
                '  "concept": {"title": "...", "aliases": ["..."]},\n'
                '  "entity": {"title": "...", "aliases": ["..."]} or null,\n'
                '  "duplicate_candidates": ["..."],\n'
                '  "conflict_candidates": ["..."],\n'
                '  "source_summary": "...",\n'
                '  "concept_definition": "..."\n'
                "}\n\n"
                "Chunk summaries:\n"
                f"{chunk_summaries}"
            ),
        },
    ]


def chunk_proposal_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["claims", "metric_result_candidates", "chunk_summary"],
        "properties": {
            "claims": {"type": "array"},
            "metric_result_candidates": {"type": "array"},
            "chunk_summary": {"type": "string"},
        },
    }


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


def parse_llm_json_with_repair(
    *,
    content: str,
    provider: Any,
    schema: dict[str, Any] | None,
    response_kind: str,
    chunk_id: str | None = None,
) -> tuple[dict[str, Any], str, list[LLMJsonRepairEvent], dict[str, Any]]:
    try:
        return parse_json_object(content), content, [], {}
    except (json.JSONDecodeError, LLMProviderError) as first_error:
        sanitized_error = sanitize_llm_parse_error(str(first_error))

    repair_messages = build_json_repair_messages(
        malformed_content=content,
        parse_error=sanitized_error,
        schema=schema,
        response_kind=response_kind,
        chunk_id=chunk_id,
    )
    repair_response = provider.complete(repair_messages, schema=schema)
    repaired_content = str(repair_response.get("content") or "")
    try:
        payload = parse_json_object(repaired_content)
    except (json.JSONDecodeError, LLMProviderError) as repair_error:
        safe_error = sanitize_llm_parse_error(str(repair_error))
        location = f" chunk {chunk_id}" if chunk_id else ""
        raise LLMProviderError(f"LLM {response_kind}{location} JSON repair failed: {safe_error}") from repair_error

    usage: dict[str, Any] = {}
    add_usage(usage, dict(repair_response.get("usage") or {}))
    event = LLMJsonRepairEvent(
        response_kind=response_kind,
        chunk_id=chunk_id,
        status="repaired",
        error=sanitized_error,
    )
    return payload, repaired_content, [event], usage


def build_json_repair_messages(
    *,
    malformed_content: str,
    parse_error: str,
    schema: dict[str, Any] | None,
    response_kind: str,
    chunk_id: str | None = None,
) -> list[dict[str, str]]:
    location = f"\nchunk_id: {chunk_id}" if chunk_id else ""
    return [
        {
            "role": "system",
            "content": (
                "Repair invalid JSON from a previous LLM response. "
                "Return repaired JSON only, with no markdown fences or commentary. "
                "Do not add facts, claims, sources, citations, block ids, or fields not present in the original response."
            ),
        },
        {
            "role": "user",
            "content": (
                f"response_kind: {response_kind}{location}\n"
                f"parse_error: {sanitize_llm_parse_error(parse_error)}\n"
                f"expected_schema: {json.dumps(schema or {}, ensure_ascii=False)}\n\n"
                "Malformed response:\n"
                f"{sanitize_malformed_llm_content(malformed_content)}"
            ),
        },
    ]


def sanitize_llm_parse_error(text: str) -> str:
    cleaned = sanitize_malformed_llm_content(text)
    cleaned = re.sub(r"\bapi[_-]?key\b", "[redacted-key-field]", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:240] if cleaned else "invalid JSON"


def sanitize_malformed_llm_content(text: str) -> str:
    cleaned = text.replace("config/api-keys.toml", "[redacted-config]")
    cleaned = cleaned.replace("config\\api-keys.toml", "[redacted-config]")
    cleaned = re.sub(r"sk-[A-Za-z0-9._-]+", "[redacted-api-key]", cleaned)
    cleaned = re.sub(
        r'(["\']?\bapi[_-]?key\b["\']?\s*[:=]\s*)(["\'])[^"\']*\2',
        r"\1\2[redacted]\2",
        cleaned,
        flags=re.I,
    )
    return cleaned


def parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = loads_json_object_text(stripped)
    except json.JSONDecodeError as first_error:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1:
            raise LLMProviderError("LLM ingest response did not contain a JSON object")
        if end == -1 or end <= start:
            raise LLMProviderError(f"LLM ingest response JSON parse failed: {first_error}") from first_error
        try:
            parsed = loads_json_object_text(stripped[start : end + 1])
        except json.JSONDecodeError as second_error:
            raise LLMProviderError(f"LLM ingest response JSON parse failed: {second_error}") from second_error
    if not isinstance(parsed, dict):
        raise LLMProviderError("LLM ingest response JSON root must be an object")
    return parsed


def loads_json_object_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as first_error:
        if "Invalid control character" not in str(first_error):
            raise
        return json.loads(text, strict=False)


def render_chunk_evidence(chunk: SourceChunk, blocks_by_id: dict[str, SourceBlock]) -> str:
    lines: list[str] = []
    for label, block_ids in (("Context blocks", chunk.context_block_ids), ("Evidence blocks", chunk.block_ids)):
        if not block_ids:
            continue
        lines.append(f"{label}:")
        for block_id in block_ids:
            block = blocks_by_id.get(block_id)
            if not block:
                continue
            if block.content_role == "ignored":
                continue
            lines.append(block_comment(block))
            lines.append(block_evidence_text(block))
            lines.append("")
    return "\n".join(lines).strip()


def dedupe_exact_claims(claims: list[dict[str, str]], source_id: str) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for claim in claims:
        key = (claim.get("claim_text", "").strip(), claim.get("citation_locator", "").strip())
        if key in seen:
            continue
        seen.add(key)
        updated = dict(claim)
        updated["claim_id"] = f"clm_{source_id}_llm_{len(result) + 1:03d}"
        result.append(updated)
    return result


def cited_claims_only(claims: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        claim
        for claim in claims
        if claim.get("citation_locator") and claim.get("confidence_status") == "cited"
    ]


def empty_usage() -> dict[str, Any]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def add_usage(total: dict[str, Any], usage: dict[str, Any]) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int | float):
            total[key] = total.get(key, 0) + value


def normalize_payload(
    payload: dict[str, Any],
    source_id: str,
    normalized_text: str,
) -> LLMIngestProposal:
    locators = source_locators(normalized_text)
    claims: list[dict[str, str]] = []
    for index, item in enumerate(payload.get("claims") or [], start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("claim_text") or "").strip()
        if not text:
            continue
        locator = canonical_locator(str(item.get("citation_locator") or ""), locators)
        confidence = normalize_claim_confidence(locator, str(item.get("confidence_status") or "cited"))
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
        metric_results=[],
    )


def metric_results_for_claims(
    candidate_records: list[dict[str, Any]],
    *,
    claims: list[dict[str, str]],
    source_id: str,
    paper_id: str,
) -> list[Any]:
    claims_by_key = {
        (claim.get("claim_text", "").strip(), claim.get("citation_locator", "").strip()): claim
        for claim in claims
        if claim.get("confidence_status") == "cited"
    }
    results = []
    for record in candidate_records:
        key = (record["claim_text"].strip(), record["citation_locator"].strip())
        claim = claims_by_key.get(key)
        if not claim:
            continue
        results.append(
            metric_result_from_candidate(
                record["raw"],
                source_id=source_id,
                paper_id=paper_id,
                claim_id=claim["claim_id"],
                claim_text=claim["claim_text"],
                citation_locator=claim["citation_locator"],
                confidence_status=claim["confidence_status"],
                created_at="",
                locator_validation=record["locator_validation"],
            )
        )
    return assign_metric_result_ids(dedupe_metric_results(results))


def line_locators(normalized_text: str) -> dict[str, str]:
    locators = source_locators(normalized_text)
    return {key: value for key, value in locators.items() if key.isdigit()}


def source_locators(normalized_text: str) -> dict[str, str]:
    locators: dict[str, str] = {}
    current_section = ""
    current_paragraph = ""
    for line in normalized_text.splitlines():
        block_locator = block_locator_from_comment(line)
        if block_locator:
            block_id, canonical = block_locator
            locators[block_id] = canonical
            locators[f"block:{block_id}"] = canonical
            continue
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
        canonical = ";".join(parts)
        locators[line_match.group(1)] = canonical
        locators[f"line:{line_match.group(1)}"] = canonical
    return locators


def canonical_locator(value: str, locators: dict[str, str]) -> str:
    block_match = re.search(r"block:([A-Za-z0-9_.-]+)", value)
    if block_match:
        return locators.get(block_match.group(1), "") or locators.get(f"block:{block_match.group(1)}", "")
    match = re.search(r"line:(\d+)", value)
    if not match:
        return ""
    return locators.get(match.group(1), "") or locators.get(f"line:{match.group(1)}", "")


def normalize_claim_confidence(locator: str, confidence_status: str) -> str:
    confidence = str(confidence_status or "cited").casefold()
    if confidence not in {"cited", "weak", "uncited"}:
        confidence = "cited"
    if has_cited_locator(locator):
        return "cited"
    return "weak" if confidence == "cited" else confidence


def has_line_locator(locator: str) -> bool:
    return re.search(r"(?:^|;)line:[1-9]\d*(?:;|$)", str(locator or "")) is not None


def has_block_locator(locator: str) -> bool:
    return re.search(r"(?:^|;)page:[1-9]\d*;block:[A-Za-z0-9_.-]+(?:;|$)", str(locator or "")) is not None


def has_cited_locator(locator: str) -> bool:
    return has_line_locator(locator) or has_block_locator(locator)


def block_locator_from_comment(line: str) -> tuple[str, str] | None:
    comment_match = re.match(r"<!--\s*(.*?)\s*-->", line.strip())
    if not comment_match:
        return None
    attributes: dict[str, str] = {}
    for part in comment_match.group(1).split(";"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        attributes[key.strip()] = value.strip()
    block_id = attributes.get("block")
    page = attributes.get("page")
    if not block_id or not page or not page.isdigit() or int(page) <= 0:
        return None
    parts = [f"page:{int(page)}", f"block:{block_id}"]
    section = attributes.get("section")
    if section:
        parts.append(f"section:{section}")
    return block_id, ";".join(parts)


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
