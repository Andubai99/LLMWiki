from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..db import catalog_path, connect
from .llm_ingest import LLMIngestProposal, create_llm_ingest_proposal, normalize_claim_confidence
from ..pdf.blocks import BLOCK_SCHEMA_VERSION, load_blocks_jsonl, load_metadata_json
from ..pdf.quality import detect_parser_created_alias
from ..pdf.chunks import CHUNK_SCHEMA_VERSION, load_chunks_jsonl
from ..workspace import utc_now


@dataclass(frozen=True)
class Claim:
    claim_id: str
    source_id: str
    claim_text: str
    citation_locator: str
    confidence_status: str
    created_at: str


@dataclass(frozen=True)
class IngestResult:
    run_id: str
    source_id: str
    run_dir: Path
    claim_count: int
    patch_count: int
    citation_coverage: int
    proposal_engine: str


def ingest_source(
    root: Path,
    source_id: str,
    *,
    require_llm: bool = False,
    trigger: str | None = None,
) -> IngestResult:
    root = root.resolve()
    source = load_source(root, source_id)
    normalized_path = root / source["normalized_path"]
    normalized_text = normalized_path.read_text(encoding="utf-8")
    created_at = utc_now()
    llm_proposal = create_llm_ingest_proposal(root, source, normalized_text)
    if llm_proposal:
        claims = claims_from_llm_proposal(llm_proposal, created_at)
        proposal_engine = "llm"
    elif require_llm:
        raise ValueError("LLM ingest is required for add, but no LLM proposal was produced")
    else:
        claims = extract_claims(source_id, normalized_text, created_at=created_at)
        proposal_engine = "heuristic"
    if not claims:
        raise ValueError(f"no claims found for source {source_id}")
    patch_claims = formal_claims(claims)
    if not patch_claims:
        raise ValueError(f"no cited claims found for source {source_id}")
    parse_diagnostics = source_parse_diagnostics(root, source)

    run_id = f"run_{source_id}_{created_at.replace(':', '').replace('+', 'Z')}_{uuid.uuid4().hex[:8]}"
    run_dir = root / "staging" / run_id
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(parents=True, exist_ok=False)

    concept_title, aliases = proposal_concept(source, patch_claims, llm_proposal)
    entity = proposal_entity(patch_claims, llm_proposal, source)
    duplicate_candidates = find_duplicate_candidates(root, concept_title, aliases)
    if entity:
        entity_title, entity_aliases = entity
        duplicate_candidates.extend(find_duplicate_candidates(root, entity_title, entity_aliases))
        duplicate_candidates = list(dict.fromkeys(duplicate_candidates))
    if llm_proposal:
        duplicate_candidates.extend(llm_proposal.duplicate_candidates)
        duplicate_candidates.extend(pdf_identity_warning_candidates(source, llm_proposal))
        duplicate_candidates = list(dict.fromkeys(duplicate_candidates))
    conflict_candidates = find_conflict_candidates(root, patch_claims)
    if llm_proposal:
        conflict_candidates.extend(llm_proposal.conflict_candidates)
        conflict_candidates = list(dict.fromkeys(conflict_candidates))
    coverage = citation_coverage(claims)

    write_jsonl(run_dir / "claims.jsonl", [claim.__dict__ for claim in claims])
    write_run_manifest(
        run_dir / "run.json",
        run_id=run_id,
        source_id=source_id,
        status="staged",
        created_at=created_at,
        extra={
            "proposal_engine": proposal_engine,
            **(
                {
                    "llm_provider": llm_proposal.provider,
                    "llm_model": llm_proposal.model,
                    "llm_json_repair_count": llm_json_repair_count(llm_proposal),
                    "llm_json_repair_failed_count": llm_json_repair_failed_count(llm_proposal),
                    "llm_json_repair_events": llm_json_repair_events(llm_proposal),
                }
                if llm_proposal
                else {}
            ),
            **({"trigger": trigger} if trigger else {}),
            **parse_diagnostics,
        },
    )
    if llm_proposal:
        write_llm_proposal(run_dir / "llm-proposal.json", llm_proposal)
    patches = build_patches(
        source=source,
        claims=patch_claims,
        concept_title=concept_title,
        aliases=aliases,
        duplicate_candidates=duplicate_candidates,
        conflict_candidates=conflict_candidates,
        entity=entity,
        source_summary=llm_proposal.source_summary if llm_proposal else None,
        concept_definition=llm_proposal.concept_definition if llm_proposal else None,
        source_diagnostics=parse_diagnostics,
    )
    for index, patch in enumerate(patches, start=1):
        patch_path = patches_dir / f"{index:03d}-{patch['page_type']}-{safe_patch_file_stem(str(patch['page_id']))}.json"
        patch_path.write_text(
            json.dumps(patch, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
    write_triage(
        run_dir / "triage.md",
        run_id=run_id,
        source=source,
        claims=claims,
        patches=patches,
        duplicate_candidates=duplicate_candidates,
        conflict_candidates=conflict_candidates,
        coverage=coverage,
        llm_proposal=llm_proposal,
        proposal_engine=proposal_engine,
        source_diagnostics=parse_diagnostics,
    )
    return IngestResult(
        run_id=run_id,
        source_id=source_id,
        run_dir=run_dir,
        claim_count=len(claims),
        patch_count=len(patches),
        citation_coverage=coverage,
        proposal_engine=proposal_engine,
    )


def load_source(root: Path, source_id: str) -> dict[str, str]:
    with connect(catalog_path(root)) as conn:
        row = conn.execute(
            "select source_id, title, source_type, raw_path, normalized_path, sha256, url from sources where source_id = ?",
            (source_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"unknown source_id: {source_id}")
    return dict(row)


def source_parse_diagnostics(root: Path, source: dict[str, str]) -> dict[str, object]:
    if source.get("source_type") != "pdf":
        return {}
    source_id = source["source_id"]
    metadata_rel = f"sources/metadata/{source_id}.json"
    blocks_rel = f"sources/blocks/{source_id}.jsonl"
    chunks_rel = f"sources/chunks/{source_id}.jsonl"
    metadata_path = root / metadata_rel
    blocks_path = root / blocks_rel
    chunks_path = root / chunks_rel
    metadata = load_metadata_json(metadata_path) if metadata_path.exists() else None
    blocks = load_blocks_jsonl(blocks_path) if blocks_path.exists() else []
    chunks = load_chunks_jsonl(chunks_path) if chunks_path.exists() else []
    parser_attempts = metadata.parser_backend_attempts if metadata else []
    return {
        "source_parse_schema": BLOCK_SCHEMA_VERSION,
        "source_chunk_schema": CHUNK_SCHEMA_VERSION,
        "page_count": metadata.page_count if metadata else 0,
        "block_count": len(blocks),
        "chunk_count": len(chunks),
        "parser_warning_count": len(metadata.warnings) if metadata else 0,
        "parser_backend": metadata.parser_backend if metadata else "",
        "parser_backend_version": metadata.parser_backend_version if metadata else None,
        "parser_backend_options": metadata.parser_backend_options if metadata else {},
        "parser_artifact_paths": metadata.parser_artifact_paths if metadata else [],
        "parser_artifact_count": len(metadata.parser_artifact_paths) if metadata else 0,
        "parser_backend_warnings": metadata.parser_backend_warnings if metadata else [],
        "parser_backend_fallback_from": metadata.parser_backend_fallback_from if metadata else None,
        "parser_backend_fallback_reason": metadata.parser_backend_fallback_reason if metadata else "",
        "structured_block_counts": metadata.structured_block_counts if metadata else {},
        "parser_command_invoked": metadata.parser_command_invoked if metadata else False,
        "parser_command": metadata.parser_command if metadata else [],
        "parser_command_returncode": metadata.parser_command_returncode if metadata else None,
        "parser_command_duration_seconds": metadata.parser_command_duration_seconds if metadata else None,
        "parser_command_stdout_snippet": metadata.parser_command_stdout_snippet if metadata else "",
        "parser_command_stderr_snippet": metadata.parser_command_stderr_snippet if metadata else "",
        "parser_content_list_path": metadata.parser_content_list_path if metadata else "",
        "parser_content_list_discovery_count": metadata.parser_content_list_discovery_count if metadata else 0,
        "parser_backend_attempts": parser_attempts,
        "parser_backend_attempt_count": len(parser_attempts),
        "title_quality": metadata.title_quality if metadata else {},
        "title_candidates": metadata.title_candidates if metadata else [],
        "paper_identity": metadata.paper_identity if metadata else {},
        "parser_quality": metadata.parser_quality if metadata else {},
        "metadata_path": metadata_rel,
        "blocks_path": blocks_rel,
        "chunks_path": chunks_rel,
    }


def extract_claims(source_id: str, normalized_text: str, created_at: str | None = None) -> list[Claim]:
    created_at = created_at or utc_now()
    claims: list[Claim] = []
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
        match = re.match(r"\[line:(\d+)\]\s+(.*)", line)
        if not match:
            continue
        line_no, claim_text = match.groups()
        claim_text = claim_text.strip()
        if not is_claim_text(claim_text):
            continue
        locator_parts = [f"line:{line_no}"]
        if current_section:
            locator_parts.append(f"section:{current_section}")
        if current_paragraph:
            locator_parts.append(f"paragraph:{current_paragraph}")
        locator = ";".join(locator_parts)
        claims.append(
            Claim(
                claim_id=f"clm_{source_id}_{line_no}",
                source_id=source_id,
                claim_text=claim_text,
                citation_locator=locator,
                confidence_status="cited",
                created_at=created_at,
            )
        )
    return claims


def claims_from_llm_proposal(proposal: LLMIngestProposal, created_at: str) -> list[Claim]:
    return [
        Claim(
            claim_id=claim["claim_id"],
            source_id=claim["source_id"],
            claim_text=claim["claim_text"],
            citation_locator=claim.get("citation_locator", ""),
            confidence_status=normalize_claim_confidence(
                claim.get("citation_locator", ""),
                claim.get("confidence_status", "weak"),
            ),
            created_at=created_at,
        )
        for claim in proposal.claims
    ]


def formal_claims(claims: list[Claim]) -> list[Claim]:
    return [
        claim
        for claim in claims
        if claim.citation_locator and claim.confidence_status not in {"weak", "uncited"}
    ]


def proposal_concept(
    source: dict[str, str],
    claims: list[Claim],
    proposal: LLMIngestProposal | None,
) -> tuple[str, list[str]]:
    fallback_title, fallback_aliases = infer_concept(source["title"], claims)
    if not proposal or not proposal.concept_title:
        return fallback_title, fallback_aliases
    title = concise_concept_title(proposal.concept_title, source["title"])
    aliases = concept_aliases(
        title,
        proposal.aliases or fallback_aliases,
        source["title"],
        pdf=source.get("source_type") == "pdf",
    )
    return title, aliases


def proposal_entity(
    claims: list[Claim],
    proposal: LLMIngestProposal | None,
    source: dict[str, str] | None = None,
) -> tuple[str, list[str]] | None:
    if proposal and proposal.entity_title:
        aliases = proposal.entity_aliases or [proposal.entity_title]
        if source and source.get("source_type") == "pdf":
            aliases = [
                alias
                for alias in aliases
                if not detect_parser_created_alias(alias)
            ] or [proposal.entity_title]
        return proposal.entity_title, aliases
    return infer_entity(claims)


def is_claim_text(text: str) -> bool:
    text = text.strip()
    if not text or text.startswith("#"):
        return False
    if text.startswith("[unsupported-"):
        return False
    text = re.sub(r"^[-*+]\s+", "", text).strip()
    if not text:
        return False
    lowered = text.casefold()
    metadata_prefixes = (
        "topic:",
        "created for:",
        "author:",
        "date:",
        "source:",
        "tags:",
        "status:",
        "title:",
    )
    if lowered.startswith(metadata_prefixes):
        return False
    table_of_contents = {"contents", "table of contents", "introduction", "scope", "overview"}
    if lowered.strip(" .:-") in table_of_contents:
        return False
    if text.endswith(":"):
        return False
    return any(ch.isalpha() for ch in text) and len(text.split()) >= 4


def infer_concept(source_title: str, claims: list[Claim]) -> tuple[str, list[str]]:
    combined = " ".join(claim.claim_text for claim in claims)
    combined_keys = alias_keys(combined)
    if "rag" in combined_keys or "retrievalaugmentedgeneration" in combined_keys:
        return "Retrieval Augmented Generation", ["RAG", "retrieval augmented generation"]
    if re.search(r"\balias\b", combined, re.I):
        return "Alias Resolution", ["alias", "identity resolution"]
    if re.search(r"\bconflict|contradict", combined, re.I):
        return "Conflict Preservation", ["conflict", "contradiction"]
    title = re.sub(r"\b(notes|source|overview)\b", "", source_title, flags=re.I).strip()
    title = concise_concept_title(title or source_title, source_title)
    return title, concept_aliases(title, [title], source_title)


def concise_concept_title(title: str, source_title: str) -> str:
    if normalize_alias(title) != normalize_alias(source_title):
        return title
    for separator in ("：", ":"):
        if separator in source_title:
            prefix = source_title.split(separator, 1)[0].strip()
            if prefix:
                return prefix
    return title


def concept_aliases(title: str, aliases: list[str], source_title: str, *, pdf: bool = False) -> list[str]:
    source_key = normalize_alias(source_title)
    cleaned: list[str] = []
    seen: set[str] = set()
    for alias in [title, *aliases]:
        if pdf and detect_parser_created_alias(alias):
            continue
        key = normalize_alias(alias)
        if not key or key == source_key or key in seen:
            continue
        cleaned.append(alias)
        seen.add(key)
    return cleaned or [title]


def pdf_identity_warning_candidates(source: dict[str, str], proposal: LLMIngestProposal | None) -> list[str]:
    if source.get("source_type") != "pdf" or not proposal:
        return []
    warnings: list[str] = []
    for alias in [proposal.concept_title or "", *(proposal.aliases or []), proposal.entity_title or "", *(proposal.entity_aliases or [])]:
        if alias and detect_parser_created_alias(alias):
            warnings.append(f"parser-created alias ignored: {alias}")
        if alias and normalize_alias(alias) == normalize_alias(source.get("title", "")):
            warnings.append(f"source title alias ignored: {alias}")
    concept_values = [proposal.concept_title or "", *(proposal.aliases or [])]
    entity_values = [proposal.entity_title or "", *(proposal.entity_aliases or [])]
    concept_keys = {normalize_alias(value) for value in concept_values if normalize_alias(value)}
    entity_keys = {normalize_alias(value) for value in entity_values if normalize_alias(value)}
    for key in sorted(concept_keys & entity_keys):
        warnings.append(f"concept/entity identity overlap: {key}")
    return list(dict.fromkeys(warnings))


def infer_entity(claims: list[Claim]) -> tuple[str, list[str]] | None:
    combined = " ".join(claim.claim_text for claim in claims)
    if "openai" in alias_keys(combined):
        return "OpenAI", ["OpenAI", "Open AI", "Open-AI"]
    return None


def find_duplicate_candidates(root: Path, concept_title: str, aliases: list[str]) -> list[str]:
    wanted_keys = set().union(*(alias_keys(value) for value in [concept_title, *aliases]))
    candidates: list[str] = []
    with connect(catalog_path(root)) as conn:
        page_rows = conn.execute("select path, title from pages").fetchall()
        alias_rows = conn.execute(
            """
            select a.alias, a.target_type, a.target_id, p.path
            from aliases a
            left join pages p on p.page_id = a.target_id
            """
        ).fetchall()
    for row in page_rows:
        existing_keys = alias_keys(row["title"])
        if existing_keys & wanted_keys:
            candidates.append(f"{row['path']} has matching title {row['title']}")
        elif similar_title(row["title"], concept_title):
            candidates.append(f"{row['path']} has similar title {row['title']}")
    for row in alias_rows:
        if alias_keys(row["alias"]) & wanted_keys:
            target = row["path"] if row["path"] else f"{row['target_type']}:{row['target_id']}"
            candidates.append(
                f"{target} has matching alias {row['alias']}"
            )
    return list(dict.fromkeys(candidates))


def find_conflict_candidates(root: Path, claims: list[Claim]) -> list[str]:
    return []


def possible_conflict(left: str, right: str) -> bool:
    return False


def citation_coverage(claims: list[Claim]) -> int:
    if not claims:
        return 0
    cited = sum(1 for claim in claims if claim.citation_locator)
    return round(cited * 100 / len(claims))


def build_patches(
    source: dict[str, str],
    claims: list[Claim],
    concept_title: str,
    aliases: list[str],
    duplicate_candidates: list[str],
    conflict_candidates: list[str],
    entity: tuple[str, list[str]] | None,
    source_summary: str | None = None,
    concept_definition: str | None = None,
    source_diagnostics: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    source_page_id = source["source_id"]
    concept_slug = slugify(concept_title)
    concept_page_id = typed_page_id("concept", concept_slug)
    source_path = f"wiki/sources/{source_page_id}.md"
    concept_path = f"wiki/concepts/{concept_slug}.md"
    claim_ids = [claim.claim_id for claim in claims]
    now = utc_now()
    patches: list[dict[str, object]] = [
        {
            "patch_id": f"patch_{source_page_id}_source",
            "action": "upsert_page",
            "page_id": source_page_id,
            "page_type": "source",
            "target_path": source_path,
            "title": source["title"],
            "aliases": source_page_aliases(source),
            "claim_ids": claim_ids,
            "source_id": source["source_id"],
            "content": render_source_page(
                source,
                claims,
                conflict_candidates,
                concept_path,
                now,
                source_summary=source_summary,
                source_diagnostics=source_diagnostics,
            ),
            "links": [
                {"from_page": source_page_id, "to_page": concept_page_id, "link_type": "mentions"}
            ],
            "relationships": [
                {
                    "subject_id": source_page_id,
                    "object_id": concept_page_id,
                    "relationship_type": "contains",
                    "evidence_claim_id": claim_ids[0],
                    "source_id": source["source_id"],
                }
            ],
        },
        {
            "patch_id": f"patch_{concept_page_id}_concept",
            "action": "upsert_page",
            "page_id": concept_page_id,
            "page_type": "concept",
            "target_path": concept_path,
            "title": concept_title,
            "aliases": aliases,
            "claim_ids": claim_ids,
            "source_id": source["source_id"],
            "content": render_concept_page(
                concept_title,
                aliases,
                claims,
                source,
                duplicate_candidates,
                conflict_candidates,
                now,
                concept_definition=concept_definition,
            ),
            "links": [
                {"from_page": concept_page_id, "to_page": source_page_id, "link_type": "supports"}
            ],
            "relationships": build_relationships(
                concept_page_id, source_page_id, claims, source["source_id"], conflict_candidates
            ),
        },
    ]
    if entity:
        entity_title, entity_aliases = entity
        entity_slug = slugify(entity_title)
        entity_page_id = typed_page_id("entity", entity_slug)
        entity_path = f"wiki/entities/{entity_slug}.md"
        patches.append(
            {
                "patch_id": f"patch_{entity_page_id}_entity",
                "action": "upsert_page",
                "page_id": entity_page_id,
                "page_type": "entity",
                "target_path": entity_path,
                "title": entity_title,
                "aliases": entity_aliases,
                "claim_ids": claim_ids,
                "source_id": source["source_id"],
                "content": render_entity_page(
                    entity_title, entity_aliases, claims, source, conflict_candidates, now
                ),
                "links": [
                    {
                        "from_page": entity_page_id,
                        "to_page": source_page_id,
                        "link_type": "supports",
                    }
                ],
                "relationships": [
                    {
                        "subject_id": entity_page_id,
                        "object_id": source["source_id"],
                        "relationship_type": "supports",
                        "evidence_claim_id": claim_ids[0],
                        "source_id": source["source_id"],
                    }
                ],
            }
        )
    return patches


def source_page_aliases(source: dict[str, str]) -> list[str]:
    if source.get("source_type") == "pdf":
        return [source["source_id"]]
    return [source["title"], source["source_id"]]


def typed_page_id(page_type: str, slug: str) -> str:
    return f"{page_type}:{slug}"


def safe_patch_file_stem(page_id: str) -> str:
    return page_id.replace(":", "-")


def build_relationships(
    concept_page_id: str,
    source_page_id: str,
    claims: list[Claim],
    source_id: str,
    conflict_candidates: list[str],
) -> list[dict[str, str]]:
    relationships = [
        {
            "subject_id": concept_page_id,
            "object_id": source_page_id,
            "relationship_type": "supports",
            "evidence_claim_id": claim.claim_id,
            "source_id": source_id,
        }
        for claim in claims
    ]
    return relationships


def render_source_page(
    source: dict[str, str],
    claims: list[Claim],
    conflict_candidates: list[str],
    concept_path: str,
    updated_at: str,
    source_summary: str | None = None,
    source_diagnostics: dict[str, object] | None = None,
) -> str:
    claim_ids = [claim.claim_id for claim in claims]
    pdf_metadata = pdf_source_metadata_lines(source_diagnostics or {})
    paper_metadata = paper_metadata_lines(source_diagnostics or {})
    parser_quality = parser_quality_lines(source_diagnostics or {})
    return "\n".join(
        [
            "---",
            "page_type: source",
            f"title: {yaml_quote(source['title'])}",
            f"aliases: [{yaml_quote(source['source_id'])}]",
            "source_count: 1",
            f"claim_ids: [{', '.join(yaml_quote(claim_id) for claim_id in claim_ids)}]",
            f"updated_at: {yaml_quote(updated_at)}",
            "---",
            "",
            f"# {source['title']}",
            "",
            "## Source Metadata",
            "",
            f"- source_id: `{source['source_id']}`",
            f"- source_type: `{source['source_type']}`",
            f"- raw_path: `{source['raw_path']}`",
            f"- normalized_path: `{source['normalized_path']}`",
            f"- sha256: `{source['sha256']}`",
            *pdf_metadata,
            "",
            "## Paper Metadata",
            "",
            *paper_metadata,
            "",
            "## Parser Quality",
            "",
            *parser_quality,
            "",
            "## Parser Attempts",
            "",
            *parser_attempt_lines(source_diagnostics or {}),
            "",
            "## Key Claims",
            "",
            *[format_claim_bullet(claim) for claim in claims],
            "",
            "## Summary",
            "",
            source_summary or f"This source contributes {len(claims)} cited claim(s).",
            "",
            "## Important Evidence",
            "",
            *[f"- `{claim.citation_locator}` supports `{claim.claim_id}`." for claim in claims],
            "",
            "## Possible Conflicts",
            "",
            *bullet_lines(conflict_candidates, "- None identified during ingest."),
            "",
            "## Links",
            "",
            f"- [[{concept_path}]]",
            "",
        ]
    )


def pdf_source_metadata_lines(source_diagnostics: dict[str, object]) -> list[str]:
    if not source_diagnostics:
        return []
    return [
        f"- parser_backend: `{source_diagnostics.get('parser_backend', '')}`",
        f"- parser_backend_version: `{source_diagnostics.get('parser_backend_version') or ''}`",
        f"- parser_command_invoked: `{bool_value(source_diagnostics.get('parser_command_invoked'))}`",
        f"- parser_command_returncode: `{source_diagnostics.get('parser_command_returncode') if source_diagnostics.get('parser_command_returncode') is not None else ''}`",
        f"- parser_command_duration_seconds: `{source_diagnostics.get('parser_command_duration_seconds') if source_diagnostics.get('parser_command_duration_seconds') is not None else ''}`",
        f"- parser_content_list_path: `{source_diagnostics.get('parser_content_list_path', '')}`",
        f"- parser_content_list_discovery_count: `{source_diagnostics.get('parser_content_list_discovery_count', 0)}`",
        f"- parser_command_stdout_snippet: `{source_diagnostics.get('parser_command_stdout_snippet', '')}`",
        f"- parser_command_stderr_snippet: `{source_diagnostics.get('parser_command_stderr_snippet', '')}`",
        f"- page_count: `{source_diagnostics.get('page_count', 0)}`",
        f"- block_count: `{source_diagnostics.get('block_count', 0)}`",
        f"- chunk_count: `{source_diagnostics.get('chunk_count', 0)}`",
        f"- parser_artifact_count: `{source_diagnostics.get('parser_artifact_count', 0)}`",
        f"- metadata_path: `{source_diagnostics.get('metadata_path', '')}`",
        f"- blocks_path: `{source_diagnostics.get('blocks_path', '')}`",
        f"- chunks_path: `{source_diagnostics.get('chunks_path', '')}`",
    ]


def paper_metadata_lines(source_diagnostics: dict[str, object]) -> list[str]:
    if not source_diagnostics:
        return ["- Not a PDF source."]
    identity = source_diagnostics.get("paper_identity")
    title_quality = source_diagnostics.get("title_quality")
    candidates = source_diagnostics.get("title_candidates")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(title_quality, dict):
        title_quality = {}
    candidate_count = len(candidates) if isinstance(candidates, list) else 0
    authors = identity.get("authors") if isinstance(identity.get("authors"), list) else []
    return [
        f"- title: `{identity.get('title', '')}`",
        f"- authors: `{', '.join(str(author) for author in authors) if authors else ''}`",
        f"- venue_or_status: `{identity.get('venue_or_status', '')}`",
        f"- title_selected_source: `{title_quality.get('selected_source', '')}`",
        f"- title_score: `{title_quality.get('score', '')}`",
        f"- title_candidates: `{candidate_count}`",
    ]


def parser_quality_lines(source_diagnostics: dict[str, object]) -> list[str]:
    parser_quality = source_diagnostics.get("parser_quality") if source_diagnostics else {}
    if not isinstance(parser_quality, dict):
        parser_quality = {}
    return [
        f"- content_block_count: `{parser_quality.get('content_block_count', 0)}`",
        f"- ignored_block_count: `{parser_quality.get('ignored_block_count', 0)}`",
        f"- content_block_ratio: `{parser_quality.get('content_block_ratio', 0)}`",
        f"- repeated_header_footer_count: `{parser_quality.get('repeated_header_footer_count', 0)}`",
        f"- page_number_count: `{parser_quality.get('page_number_count', 0)}`",
    ]


def parser_attempt_lines(source_diagnostics: dict[str, object]) -> list[str]:
    attempts = source_diagnostics.get("parser_backend_attempts") if source_diagnostics else []
    if not isinstance(attempts, list) or not attempts:
        return ["- None recorded."]
    lines: list[str] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        backend = str(attempt.get("backend", ""))
        status = str(attempt.get("status", ""))
        extras: list[str] = []
        command_source = str(attempt.get("command_source", ""))
        if command_source:
            extras.append(f"source={command_source}")
        returncode = attempt.get("returncode")
        if returncode is not None:
            extras.append(f"returncode={returncode}")
        failure_stage = str(attempt.get("failure_stage", ""))
        if failure_stage:
            extras.append(f"failure_stage={failure_stage}")
        failure_reason = str(attempt.get("failure_reason", ""))
        if failure_reason:
            extras.append(f"reason={failure_reason}")
        suffix = f" ({', '.join(extras)})" if extras else ""
        lines.append(f"- {backend}: {status}{suffix}")
    return lines or ["- None recorded."]


def render_concept_page(
    title: str,
    aliases: list[str],
    claims: list[Claim],
    source: dict[str, str],
    duplicate_candidates: list[str],
    conflict_candidates: list[str],
    updated_at: str,
    concept_definition: str | None = None,
) -> str:
    claim_ids = [claim.claim_id for claim in claims]
    return "\n".join(
        [
            "---",
            "page_type: concept",
            f"title: {yaml_quote(title)}",
            f"aliases: [{', '.join(yaml_quote(alias) for alias in aliases)}]",
            "source_count: 1",
            f"claim_ids: [{', '.join(yaml_quote(claim_id) for claim_id in claim_ids)}]",
            f"updated_at: {yaml_quote(updated_at)}",
            "---",
            "",
            f"# {title}",
            "",
            "## Definition",
            "",
            concept_definition
            or f"Candidate definition derived from `{source['source_id']}` and pending user review.",
            "",
            "## Key Claims",
            "",
            *[format_claim_bullet(claim) for claim in claims],
            "",
            "## Related Concepts",
            "",
            *bullet_lines(
                [f"Duplicate candidate: {item}" for item in duplicate_candidates],
                "- None identified during ingest.",
            ),
            "",
            "## Supporting Sources",
            "",
            f"- [[wiki/sources/{source['source_id']}.md]]",
            "",
            "## Open Questions",
            "",
            *bullet_lines(
                [f"Conflict candidate: {item}" for item in conflict_candidates],
                "- None recorded.",
            ),
            "",
        ]
    )


def render_entity_page(
    title: str,
    aliases: list[str],
    claims: list[Claim],
    source: dict[str, str],
    conflict_candidates: list[str],
    updated_at: str,
) -> str:
    claim_ids = [claim.claim_id for claim in claims]
    return "\n".join(
        [
            "---",
            "page_type: entity",
            f"title: {yaml_quote(title)}",
            f"aliases: [{', '.join(yaml_quote(alias) for alias in aliases)}]",
            "source_count: 1",
            f"claim_ids: [{', '.join(yaml_quote(claim_id) for claim_id in claim_ids)}]",
            f"updated_at: {yaml_quote(updated_at)}",
            "---",
            "",
            f"# {title}",
            "",
            "## Overview",
            "",
            f"Candidate entity page derived from `{source['source_id']}` and pending user review.",
            "",
            "## Aliases",
            "",
            *[f"- {alias}" for alias in aliases],
            "",
            "## Key Claims",
            "",
            *[format_claim_bullet(claim) for claim in claims],
            "",
            "## Relationships",
            "",
            f"- Supported by [[wiki/sources/{source['source_id']}.md]].",
            "",
            "## Supporting Sources",
            "",
            f"- [[wiki/sources/{source['source_id']}.md]]",
            "",
            "## Open Questions",
            "",
            *bullet_lines(
                [f"Conflict candidate: {item}" for item in conflict_candidates],
                "- None recorded.",
            ),
            "",
        ]
    )


def format_claim_bullet(claim: Claim) -> str:
    return (
        f"- {claim.claim_text} "
        f"(`{claim.claim_id}`, `{claim.source_id}`, `{claim.citation_locator}`)"
    )


def bullet_lines(items: list[str], empty_line: str) -> list[str]:
    if not items:
        return [empty_line]
    return [f"- {item}" for item in items]


def write_triage(
    path: Path,
    run_id: str,
    source: dict[str, str],
    claims: list[Claim],
    patches: list[dict[str, object]],
    duplicate_candidates: list[str],
    conflict_candidates: list[str],
    coverage: int,
    llm_proposal: LLMIngestProposal | None = None,
    proposal_engine: str = "heuristic",
    source_diagnostics: dict[str, object] | None = None,
) -> None:
    lines = [
        f"# Triage: {run_id}",
        "",
        f"- source_id: `{source['source_id']}`",
        f"- title: {source['title']}",
        f"- proposal_engine: `{proposal_engine}`",
        f"- claims: {len(claims)}",
        f"- Citation coverage: {coverage}%",
        "",
        "## LLM Proposal",
        "",
        *llm_proposal_lines(llm_proposal),
        "",
        *pdf_parse_diagnostics_section(source_diagnostics or {}),
        "## Candidate Patches",
        "",
        *[f"- `{patch['target_path']}` ({patch['page_type']})" for patch in patches],
        "",
        "## Duplicate Candidates",
        "",
        *bullet_lines(duplicate_candidates, "- None identified."),
        "",
        "## Conflict Candidates",
        "",
        *bullet_lines(conflict_candidates, "- None identified."),
        "",
        "## Claims",
        "",
        *[format_claim_bullet(claim) for claim in claims],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def pdf_parse_diagnostics_section(source_diagnostics: dict[str, object]) -> list[str]:
    if not source_diagnostics:
        return []
    title_candidates = source_diagnostics.get("title_candidates")
    candidate_count = len(title_candidates) if isinstance(title_candidates, list) else 0
    return [
        "## PDF Parse Diagnostics",
        "",
        f"- source_parse_schema: `{source_diagnostics.get('source_parse_schema', '')}`",
        f"- source_chunk_schema: `{source_diagnostics.get('source_chunk_schema', '')}`",
        f"- page_count: {source_diagnostics.get('page_count', 0)}",
        f"- block_count: {source_diagnostics.get('block_count', 0)}",
        f"- chunk_count: {source_diagnostics.get('chunk_count', 0)}",
        f"- parser_warning_count: {source_diagnostics.get('parser_warning_count', 0)}",
        f"- parser_backend: `{source_diagnostics.get('parser_backend', '')}`",
        f"- parser_backend_version: `{source_diagnostics.get('parser_backend_version') or ''}`",
        f"- parser_artifact_count: {source_diagnostics.get('parser_artifact_count', 0)}",
        f"- parser_backend_fallback_from: `{source_diagnostics.get('parser_backend_fallback_from') or ''}`",
        f"- parser_backend_fallback_reason: `{source_diagnostics.get('parser_backend_fallback_reason', '')}`",
        f"- parser_command_invoked: `{bool_value(source_diagnostics.get('parser_command_invoked'))}`",
        f"- parser_command_returncode: `{source_diagnostics.get('parser_command_returncode') if source_diagnostics.get('parser_command_returncode') is not None else ''}`",
        f"- parser_command_duration_seconds: `{source_diagnostics.get('parser_command_duration_seconds') if source_diagnostics.get('parser_command_duration_seconds') is not None else ''}`",
        f"- parser_content_list_path: `{source_diagnostics.get('parser_content_list_path', '')}`",
        f"- parser_content_list_discovery_count: `{source_diagnostics.get('parser_content_list_discovery_count', 0)}`",
        f"- parser_command_stdout_snippet: `{source_diagnostics.get('parser_command_stdout_snippet', '')}`",
        f"- parser_command_stderr_snippet: `{source_diagnostics.get('parser_command_stderr_snippet', '')}`",
        f"- parser_backend_attempt_count: {source_diagnostics.get('parser_backend_attempt_count', 0)}",
        *parser_attempt_lines(source_diagnostics),
        f"- metadata_path: `{source_diagnostics.get('metadata_path', '')}`",
        f"- blocks_path: `{source_diagnostics.get('blocks_path', '')}`",
        f"- chunks_path: `{source_diagnostics.get('chunks_path', '')}`",
        "",
        "## Paper Metadata",
        "",
        *paper_metadata_lines(source_diagnostics),
        f"- title_candidates: `{candidate_count}`",
        "",
        "## Parser Quality",
        "",
        *parser_quality_lines(source_diagnostics),
        "",
    ]


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def bool_value(value: object) -> str:
    return "true" if bool(value) else "false"


def llm_proposal_lines(proposal: LLMIngestProposal | None) -> list[str]:
    if not proposal:
        return ["- proposal_engine: `heuristic`", "- LLM provider was not called."]
    lines = [
        "- proposal_engine: `llm`",
        f"- provider: `{proposal.provider}`",
        f"- model: `{proposal.model}`",
        f"- usage: `{json.dumps(proposal.usage, ensure_ascii=False)}`",
        f"- llm_json_repair_count: `{llm_json_repair_count(proposal)}`",
        f"- llm_json_repair_failed_count: `{llm_json_repair_failed_count(proposal)}`",
    ]
    for event in proposal.repair_events:
        details = event.to_dict()
        chunk = f", chunk_id={details['chunk_id']}" if details.get("chunk_id") else ""
        lines.append(
            "- llm_json_repair_event: "
            f"`{details['response_kind']}` status=`{details['status']}`{chunk} error=`{details['error']}`"
        )
    return lines


def llm_json_repair_events(proposal: LLMIngestProposal) -> list[dict[str, str | None]]:
    return [event.to_dict() for event in proposal.repair_events]


def llm_json_repair_count(proposal: LLMIngestProposal) -> int:
    return len(proposal.repair_events)


def llm_json_repair_failed_count(proposal: LLMIngestProposal) -> int:
    return sum(1 for event in proposal.repair_events if event.status != "repaired")


def write_run_manifest(
    path: Path,
    run_id: str,
    source_id: str,
    status: str,
    created_at: str,
    extra: dict[str, str] | None = None,
) -> None:
    payload = {
        "run_id": run_id,
        "source_id": source_id,
        "status": status,
        "created_at": created_at,
    }
    if extra:
        payload.update(extra)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_llm_proposal(path: Path, proposal: LLMIngestProposal) -> None:
    payload = {
        "provider": proposal.provider,
        "model": proposal.model,
        "usage": proposal.usage,
        "llm_json_repair_count": llm_json_repair_count(proposal),
        "llm_json_repair_failed_count": llm_json_repair_failed_count(proposal),
        "llm_json_repair_events": llm_json_repair_events(proposal),
        "content": proposal.raw_content,
        "claims": proposal.claims,
        "concept_title": proposal.concept_title,
        "aliases": proposal.aliases,
        "entity_title": proposal.entity_title,
        "entity_aliases": proposal.entity_aliases,
        "duplicate_candidates": proposal.duplicate_candidates,
        "conflict_candidates": proposal.conflict_candidates,
        "source_summary": proposal.source_summary,
        "concept_definition": proposal.concept_definition,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def review_run(root: Path, run_id: str, detail: bool = False, show_patches: bool = False) -> str:
    run_dir = root.resolve() / "staging" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(run_id)
    claims = [
        json.loads(line)
        for line in (run_dir / "claims.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    patch_paths = sorted((run_dir / "patches").glob("*.json"))
    patches = [json.loads(path.read_text(encoding="utf-8")) for path in patch_paths]
    triage = (run_dir / "triage.md").read_text(encoding="utf-8")
    manifest = read_run_manifest(run_dir, run_id, claims)
    duplicate_count = count_section_items(triage, "Duplicate Candidates")
    conflict_count = count_section_items(triage, "Conflict Candidates")
    coverage = round(
        sum(1 for claim in claims if claim.get("citation_locator")) * 100 / len(claims)
    ) if claims else 0
    weak_claims = [
        claim
        for claim in claims
        if not claim.get("citation_locator")
        or claim.get("confidence_status") in {"weak", "uncited"}
    ]
    patch_rows = summarize_patches(root.resolve(), patches)
    new_pages = [row for row in patch_rows if row["change"] == "new"]
    updated_pages = [row for row in patch_rows if row["change"] == "update"]
    lines = [
        "Run information",
        f"- run_id: {run_id}",
        f"- source_id: {manifest['source_id']}",
        f"- status: {manifest['status']}",
        f"- created_at: {manifest['created_at']}",
        f"- claims: {len(claims)}",
        f"- patches: {len(patches)}",
        f"- citation_coverage: {coverage}%",
        "",
        "Triage summary",
        f"Duplicate candidates: {duplicate_count}",
        f"Conflict candidates: {conflict_count}",
        f"Weak/uncited claims: {len(weak_claims)}",
        "",
        "Claims",
        "claim_id | status | citation | claim_text",
        "--- | --- | --- | ---",
        *[
            (
                f"{claim['claim_id']} | {claim.get('confidence_status', '')} | "
                f"{claim.get('citation_locator') or ''} | {summarize_text(claim['claim_text'], 96)}"
            )
            for claim in claims
        ],
        "",
        "Patches",
        "target_path | page_type | title | aliases | claim_ids | change",
        "--- | --- | --- | --- | --- | ---",
        *[
            (
                f"{row['target_path']} | {row['page_type']} | {row['title']} | "
                f"{row['aliases']} | {row['claim_ids']} | {row['change']}"
            )
            for row in patch_rows
        ],
        "",
        "New pages:",
        *bullet_lines([row["target_path"] for row in new_pages], "- None"),
        "",
        "Updated pages:",
        *bullet_lines([row["target_path"] for row in updated_pages], "- None"),
        "",
        "Duplicate candidates:",
        *section_items(triage, "Duplicate Candidates"),
        "",
        "Conflict candidates:",
        *section_items(triage, "Conflict Candidates"),
        "",
        "Weak/uncited claims:",
        *bullet_lines([claim["claim_id"] for claim in weak_claims], "- None"),
    ]
    if detail:
        lines.extend(
            [
                "",
                "Detailed claims",
                *[
                    (
                        f"- {claim['claim_id']} [{claim.get('confidence_status', '')}] "
                        f"{claim.get('citation_locator') or 'no-citation'}: {claim['claim_text']}"
                    )
                    for claim in claims
                ],
                "",
                "Citation coverage detail",
                f"- cited: {len(claims) - len(weak_claims)}",
                f"- weak_or_uncited: {len(weak_claims)}",
                f"- coverage: {coverage}%",
                "",
                "Triage details",
                triage.rstrip(),
            ]
        )
    if show_patches:
        lines.extend(["", "Patch contents"])
        for path, patch in zip(patch_paths, patches):
            lines.extend(
                [
                    "",
                    f"### {path.relative_to(run_dir).as_posix()}",
                    f"- target_path: {patch.get('target_path')}",
                    f"- page_type: {patch.get('page_type')}",
                    f"- title: {patch.get('title')}",
                    "",
                    "```markdown",
                    str(patch.get("content", "")).rstrip(),
                    "```",
                ]
            )
    return "\n".join(lines)


def read_run_manifest(run_dir: Path, run_id: str, claims: list[dict[str, str]]) -> dict[str, str]:
    manifest_path = run_dir / "run.json"
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        data = {}
    if "run_id" not in data:
        data["run_id"] = run_id
    if "source_id" not in data:
        data["source_id"] = claims[0]["source_id"] if claims else "unknown"
    if "status" not in data:
        data["status"] = "staged"
    if "created_at" not in data:
        data["created_at"] = created_at_from_run_id(run_id)
    return {key: str(value) for key, value in data.items()}


def created_at_from_run_id(run_id: str) -> str:
    parts = run_id.split("_")
    if len(parts) >= 4:
        return parts[-2]
    return "unknown"


def summarize_patches(root: Path, patches: list[dict[str, object]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for patch in patches:
        target_path = str(patch.get("target_path", ""))
        rows.append(
            {
                "target_path": target_path,
                "page_type": str(patch.get("page_type", "")),
                "title": str(patch.get("title", "")),
                "aliases": ", ".join(str(alias) for alias in patch.get("aliases", [])),
                "claim_ids": ", ".join(str(claim_id) for claim_id in patch.get("claim_ids", [])),
                "change": "update" if (root / target_path).exists() else "new",
            }
        )
    return rows


def summarize_text(text: str, max_length: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3].rstrip()}..."


def count_section_items(markdown: str, heading: str) -> int:
    in_section = False
    count = 0
    for line in markdown.splitlines():
        if line == f"## {heading}":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("- ") and "None identified" not in line:
            count += 1
    return count


def section_items(markdown: str, heading: str) -> list[str]:
    items: list[str] = []
    in_section = False
    for line in markdown.splitlines():
        if line == f"## {heading}":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("- "):
            items.append(line)
    return items or ["- None"]


def normalize_alias(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def alias_keys(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    if not words:
        return set()
    spaced = " ".join(words)
    compact = "".join(words)
    keys = {compact}
    if "retrieval augmented generation" in spaced:
        keys.add("retrievalaugmentedgeneration")
        keys.add("rag")
    if re.search(r"\brag\b", spaced):
        keys.add("rag")
        keys.add("retrievalaugmentedgeneration")
    if "open ai" in spaced or "openai" in compact:
        keys.add("openai")
    return keys


def similar_title(left: str, right: str) -> bool:
    left_tokens = {token for token in re.findall(r"[a-z0-9]{3,}", left.casefold())}
    right_tokens = {token for token in re.findall(r"[a-z0-9]{3,}", right.casefold())}
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    return len(overlap) >= 2 and len(overlap) / min(len(left_tokens), len(right_tokens)) >= 0.5


def slugify(value: str) -> str:
    parts: list[str] = []
    previous_separator = False
    for char in value.casefold():
        if char.isalnum():
            parts.append(char)
            previous_separator = False
        elif not previous_separator:
            parts.append("-")
            previous_separator = True
    slug = "".join(parts).strip("-")
    return slug or "untitled"


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
