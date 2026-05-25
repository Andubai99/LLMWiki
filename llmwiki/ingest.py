from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .db import catalog_path, connect
from .workspace import utc_now


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


def ingest_source(root: Path, source_id: str) -> IngestResult:
    root = root.resolve()
    source = load_source(root, source_id)
    normalized_path = root / source["normalized_path"]
    normalized_text = normalized_path.read_text(encoding="utf-8")
    claims = extract_claims(source_id, normalized_text)
    if not claims:
        raise ValueError(f"no claims found for source {source_id}")

    run_id = f"run_{source_id}_{utc_now().replace(':', '').replace('+', 'Z')}"
    run_dir = root / "staging" / run_id
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(parents=True, exist_ok=False)

    concept_title, aliases = infer_concept(source["title"], claims)
    duplicate_candidates = find_duplicate_candidates(root, concept_title, aliases)
    conflict_candidates = find_conflict_candidates(root, claims)
    coverage = citation_coverage(claims)

    write_jsonl(run_dir / "claims.jsonl", [claim.__dict__ for claim in claims])
    patches = build_patches(
        source=source,
        claims=claims,
        concept_title=concept_title,
        aliases=aliases,
        duplicate_candidates=duplicate_candidates,
        conflict_candidates=conflict_candidates,
    )
    for index, patch in enumerate(patches, start=1):
        patch_path = patches_dir / f"{index:03d}-{patch['page_type']}-{patch['page_id']}.json"
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
    )
    return IngestResult(
        run_id=run_id,
        source_id=source_id,
        run_dir=run_dir,
        claim_count=len(claims),
        patch_count=len(patches),
        citation_coverage=coverage,
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


def extract_claims(source_id: str, normalized_text: str) -> list[Claim]:
    created_at = utc_now()
    claims: list[Claim] = []
    for line in normalized_text.splitlines():
        match = re.match(r"\[line:(\d+)\]\s+(.*)", line)
        if not match:
            continue
        line_no, claim_text = match.groups()
        claim_text = claim_text.strip()
        if not is_claim_text(claim_text):
            continue
        locator = f"line:{line_no}"
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


def is_claim_text(text: str) -> bool:
    if not text or text.startswith("#"):
        return False
    if text.startswith("[unsupported-"):
        return False
    return any(ch.isalpha() for ch in text) and len(text.split()) >= 4


def infer_concept(source_title: str, claims: list[Claim]) -> tuple[str, list[str]]:
    combined = " ".join(claim.claim_text for claim in claims)
    if re.search(r"\bRAG\b|retrieval augmented generation", combined, re.I):
        return "Retrieval Augmented Generation", ["RAG", "retrieval augmented generation"]
    if re.search(r"\balias\b", combined, re.I):
        return "Alias Resolution", ["alias", "identity resolution"]
    if re.search(r"\bconflict|contradict", combined, re.I):
        return "Conflict Preservation", ["conflict", "contradiction"]
    title = re.sub(r"\b(notes|source|overview)\b", "", source_title, flags=re.I).strip()
    return title or source_title, [source_title]


def find_duplicate_candidates(root: Path, concept_title: str, aliases: list[str]) -> list[str]:
    normalized = {normalize_alias(concept_title), *(normalize_alias(alias) for alias in aliases)}
    candidates: list[str] = []
    with connect(catalog_path(root)) as conn:
        page_rows = conn.execute("select path, title from pages").fetchall()
        alias_rows = conn.execute("select alias, target_type, target_id from aliases").fetchall()
    for row in page_rows:
        if normalize_alias(row["title"]) in normalized:
            candidates.append(f"{row['path']} has matching title {row['title']}")
    for row in alias_rows:
        if normalize_alias(row["alias"]) in normalized:
            candidates.append(
                f"{row['target_type']}:{row['target_id']} has matching alias {row['alias']}"
            )
    return candidates


def find_conflict_candidates(root: Path, claims: list[Claim]) -> list[str]:
    candidates: list[str] = []
    conflict_terms = ("contradict", "conflict", "disagree", "not ")
    for claim in claims:
        text_lower = claim.claim_text.lower()
        if any(term in text_lower for term in conflict_terms):
            candidates.append(f"{claim.claim_id}: {claim.claim_text}")

    with connect(catalog_path(root)) as conn:
        existing_claims = conn.execute(
            "select claim_id, claim_text from claims order by created_at"
        ).fetchall()
    for claim in claims:
        for existing in existing_claims:
            if possible_conflict(existing["claim_text"], claim.claim_text):
                candidates.append(
                    f"{claim.claim_id} may contradict {existing['claim_id']}: {claim.claim_text}"
                )
    return candidates


def possible_conflict(left: str, right: str) -> bool:
    left_lower = left.lower()
    right_lower = right.lower()
    shared = set(re.findall(r"[a-z0-9]{4,}", left_lower)) & set(
        re.findall(r"[a-z0-9]{4,}", right_lower)
    )
    if len(shared) < 2:
        return False
    return (" not " in left_lower) != (" not " in right_lower)


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
) -> list[dict[str, object]]:
    source_page_id = source["source_id"]
    concept_page_id = slugify(concept_title)
    source_path = f"wiki/sources/{source_page_id}.md"
    concept_path = f"wiki/concepts/{concept_page_id}.md"
    claim_ids = [claim.claim_id for claim in claims]
    now = utc_now()
    return [
        {
            "patch_id": f"patch_{source_page_id}_source",
            "action": "upsert_page",
            "page_id": source_page_id,
            "page_type": "source",
            "target_path": source_path,
            "title": source["title"],
            "aliases": [source["title"], source["source_id"]],
            "claim_ids": claim_ids,
            "source_id": source["source_id"],
            "content": render_source_page(source, claims, conflict_candidates, concept_path, now),
            "links": [
                {"from_page": source_path, "to_page": concept_path, "link_type": "mentions"}
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
                concept_title, aliases, claims, source, duplicate_candidates, conflict_candidates, now
            ),
            "links": [
                {"from_page": concept_path, "to_page": source_path, "link_type": "supports"}
            ],
            "relationships": build_relationships(
                concept_page_id, source_page_id, claims, source["source_id"], conflict_candidates
            ),
        },
    ]


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
    for conflict in conflict_candidates:
        claim_id = conflict.split(":", 1)[0]
        relationships.append(
            {
                "subject_id": concept_page_id,
                "object_id": source_page_id,
                "relationship_type": "contradicts",
                "evidence_claim_id": claim_id,
                "source_id": source_id,
            }
        )
    return relationships


def render_source_page(
    source: dict[str, str],
    claims: list[Claim],
    conflict_candidates: list[str],
    concept_path: str,
    updated_at: str,
) -> str:
    claim_ids = [claim.claim_id for claim in claims]
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
            "",
            "## Key Claims",
            "",
            *[format_claim_bullet(claim) for claim in claims],
            "",
            "## Summary",
            "",
            f"This source contributes {len(claims)} cited claim(s).",
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


def render_concept_page(
    title: str,
    aliases: list[str],
    claims: list[Claim],
    source: dict[str, str],
    duplicate_candidates: list[str],
    conflict_candidates: list[str],
    updated_at: str,
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
            f"Candidate definition derived from `{source['source_id']}` and pending user review.",
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
) -> None:
    lines = [
        f"# Triage: {run_id}",
        "",
        f"- source_id: `{source['source_id']}`",
        f"- title: {source['title']}",
        f"- claims: {len(claims)}",
        f"- Citation coverage: {coverage}%",
        "",
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


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def review_run(root: Path, run_id: str) -> str:
    run_dir = root.resolve() / "staging" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(run_id)
    claims = [
        json.loads(line)
        for line in (run_dir / "claims.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    patches = sorted((run_dir / "patches").glob("*.json"))
    triage = (run_dir / "triage.md").read_text(encoding="utf-8")
    duplicate_count = count_section_items(triage, "Duplicate Candidates")
    conflict_count = count_section_items(triage, "Conflict Candidates")
    coverage = round(
        sum(1 for claim in claims if claim.get("citation_locator")) * 100 / len(claims)
    ) if claims else 0
    lines = [
        f"Review run: {run_id}",
        f"Claims: {len(claims)}",
        f"Citation coverage: {coverage}%",
        f"Candidate patches: {len(patches)}",
        f"Duplicate candidates: {duplicate_count}",
        f"Conflict candidates: {conflict_count}",
        "Patch list:",
        *[f"- {path.relative_to(run_dir).as_posix()}" for path in patches],
    ]
    return "\n".join(lines)


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


def normalize_alias(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().strip())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "untitled"


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
