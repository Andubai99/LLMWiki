from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .db import catalog_path, connect, schema_status
from .pdf.quality import evaluate_pdf_quality


@dataclass(frozen=True)
class LintReport:
    issue_count: int
    lines: list[str]


def lint_workspace(root: Path) -> LintReport:
    root = root.resolve()
    lines: list[str] = ["Lint report"]
    issue_count = 0

    schema_ok, schema_problems = schema_status(catalog_path(root))
    if not schema_ok:
        issue_count += len(schema_problems)
        lines.extend(f"- schema: {problem}" for problem in schema_problems)
        return LintReport(issue_count, lines)

    with connect(catalog_path(root)) as conn:
        pages = conn.execute("select page_id, path, page_type, title from pages").fetchall()
        page_ids = {row["page_id"] for row in pages}
        page_paths = {row["path"]: row["page_id"] for row in pages}
        links = conn.execute("select from_page, to_page, link_type from links").fetchall()

        broken_links = [
            row
            for row in links
            if page_ref_to_id(row["to_page"], page_ids, page_paths) is None
        ]
        lines.append(f"- broken links: {len(broken_links)}")
        issue_count += len(broken_links)

        linked_pages = {
            page_id
            for row in links
            for value in (row["from_page"], row["to_page"])
            for page_id in [page_ref_to_id(value, page_ids, page_paths)]
            if page_id is not None
        }
        orphan_pages = [
            row["path"]
            for row in pages
            if row["page_id"] not in linked_pages and row["page_type"] != "index"
        ]
        lines.append(f"- orphan pages: {len(orphan_pages)}")
        issue_count += len(orphan_pages)

        duplicate_aliases, shared_concept_entity_aliases = classify_duplicate_aliases(conn)
        lines.append(f"- duplicate alias: {len(duplicate_aliases)}")
        issue_count += len(duplicate_aliases)
        lines.append(f"- shared concept/entity alias: {len(shared_concept_entity_aliases)}")

        uncited_without_locator = conn.execute(
            """
            select distinct c.claim_id
            from claims c
            join relationships r on r.evidence_claim_id = c.claim_id
            where c.citation_locator is null
               or c.citation_locator = ''
            """
        ).fetchall()
        uncited_with_locator = conn.execute(
            """
            select claim_id
            from claims
            where citation_locator is not null
              and citation_locator != ''
              and confidence_status in ('weak', 'uncited')
            """
        ).fetchall()
        lines.append(f"- uncited claims: {len(uncited_without_locator)}")
        issue_count += len(uncited_without_locator)
        lines.append(f"- uncited with locator: {len(uncited_with_locator)}")

        drift_count = source_hash_drift(root, conn)
        lines.append(f"- source hash drift: {drift_count}")
        issue_count += drift_count

        pdf_issues = pdf_parser_quality_issues(root, conn)
        pdf_issue_count = (
            pdf_issues["marker_titles"]
            + pdf_issues["missing_sidecars"]
            + pdf_issues["claims_missing_block_locator"]
            + pdf_issues["claims_invalid_block_locator"]
            + pdf_issues["title_quality_issues"]
            + pdf_issues["invalid_sidecar_schema"]
            + pdf_issues["high_parser_warnings"]
            + pdf_issues["low_content_block_ratio"]
            + pdf_issues["parser_created_aliases"]
            + pdf_issues["source_title_alias_collisions"]
            + pdf_issues["unknown_parser_backends"]
            + pdf_issues["missing_parser_artifacts"]
            + pdf_issues["missing_parser_content_lists"]
            + pdf_issues["parser_secret_snippets"]
            + pdf_issues["ignored_blocks_in_chunks"]
            + pdf_issues["auto_fallback_missing_attempt_diagnostics"]
        )
        lines.append(f"- pdf parser issues: {pdf_issue_count}")
        lines.append(f"  - pdf marker titles: {pdf_issues['marker_titles']}")
        lines.append(f"  - pdf missing sidecars: {pdf_issues['missing_sidecars']}")
        lines.append(f"  - pdf claims missing page/block locator: {pdf_issues['claims_missing_block_locator']}")
        lines.append(f"  - pdf claims with invalid block locator: {pdf_issues['claims_invalid_block_locator']}")
        lines.append(f"  - pdf extraction warnings: {pdf_issues['extraction_warnings']}")
        lines.append(f"  - pdf title quality issues: {pdf_issues['title_quality_issues']}")
        lines.append(f"  - pdf invalid sidecar schema: {pdf_issues['invalid_sidecar_schema']}")
        lines.append(f"  - pdf high parser warnings: {pdf_issues['high_parser_warnings']}")
        lines.append(f"  - pdf low content block ratio: {pdf_issues['low_content_block_ratio']}")
        lines.append(f"  - pdf parser-created aliases: {pdf_issues['parser_created_aliases']}")
        lines.append(f"  - pdf source title alias collisions: {pdf_issues['source_title_alias_collisions']}")
        lines.append(f"  - pdf unknown parser backends: {pdf_issues['unknown_parser_backends']}")
        lines.append(f"  - pdf missing parser artifacts: {pdf_issues['missing_parser_artifacts']}")
        lines.append(f"  - pdf missing parser content lists: {pdf_issues['missing_parser_content_lists']}")
        lines.append(f"  - pdf parser secret snippets: {pdf_issues['parser_secret_snippets']}")
        lines.append(f"  - pdf ignored blocks in chunks: {pdf_issues['ignored_blocks_in_chunks']}")
        lines.append(
            f"  - pdf auto fallback missing attempt diagnostics: {pdf_issues['auto_fallback_missing_attempt_diagnostics']}"
        )
        lines.append(f"  - pdf paper identity overlaps: {pdf_issues['paper_identity_overlaps']}")
        lines.append(f"  - pdf llm json repairs observed: {pdf_issues['llm_json_repairs_observed']}")
        issue_count += pdf_issue_count

        recorded_contradicts = conn.execute(
            "select count(*) from relationships where relationship_type = 'contradicts'"
        ).fetchone()[0]
        lines.append(f"- recorded contradicts relationships: {recorded_contradicts}")

        unresolved = unresolved_potential_contradictions(conn)
        lines.append(f"- unresolved potential contradictions: {unresolved}")
        issue_count += unresolved

    if issue_count == 0:
        lines.append("Lint OK")
    else:
        lines.append(f"Lint found {issue_count} issue(s)")
    return LintReport(issue_count, lines)


def page_ref_to_id(value: str, page_ids: set[str], page_paths: dict[str, str]) -> str | None:
    if value in page_ids:
        return value
    return page_paths.get(value)


def classify_duplicate_aliases(conn) -> tuple[list[str], list[str]]:
    rows = conn.execute(
        """
        select normalized_alias, target_type, target_id
        from aliases
        order by normalized_alias, target_type, target_id
        """
    ).fetchall()
    groups: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        groups.setdefault(row["normalized_alias"], []).append(
            (row["target_type"], row["target_id"])
        )

    duplicate_aliases: list[str] = []
    shared_concept_entity_aliases: list[str] = []
    for normalized_alias, targets in groups.items():
        unique_targets = sorted(set(targets))
        if len(unique_targets) <= 1:
            continue
        if is_shared_concept_entity_alias(unique_targets):
            shared_concept_entity_aliases.append(normalized_alias)
            continue
        duplicate_aliases.append(normalized_alias)
    return duplicate_aliases, shared_concept_entity_aliases


def is_shared_concept_entity_alias(targets: list[tuple[str, str]]) -> bool:
    target_types = {target_type for target_type, _ in targets}
    if not target_types <= {"concept", "entity"}:
        return False
    if not {"concept", "entity"} <= target_types:
        return False
    identity_keys = {typed_page_identity(target_id) for _, target_id in targets}
    return len(identity_keys) == 1


def typed_page_identity(target_id: str) -> str:
    if ":" not in target_id:
        return target_id
    return target_id.split(":", 1)[1]


def source_hash_drift(root: Path, conn) -> int:
    drift = 0
    for row in conn.execute("select raw_path, sha256 from sources").fetchall():
        raw_path = root / row["raw_path"]
        if not raw_path.exists():
            drift += 1
            continue
        digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            drift += 1
    return drift


def pdf_parser_quality_issues(root: Path, conn) -> dict[str, int]:
    pdf_sources = conn.execute(
        "select source_id, title from sources where source_type = 'pdf'"
    ).fetchall()
    marker_titles = 0
    missing_sidecars = 0
    extraction_warnings = 0
    unknown_parser_backends = 0
    missing_parser_artifacts = 0
    missing_parser_content_lists = 0
    parser_secret_snippets = 0
    ignored_blocks_in_chunks = 0
    auto_fallback_missing_attempt_diagnostics = 0
    known_blocks_by_source: dict[str, set[str]] = {}

    for source in pdf_sources:
        source_id = source["source_id"]
        if re.fullmatch(r"<!--\s*page:\d+\s*-->", str(source["title"] or "").strip()):
            marker_titles += 1
        metadata_path = root / "sources" / "metadata" / f"{source_id}.json"
        blocks_path = root / "sources" / "blocks" / f"{source_id}.jsonl"
        chunks_path = root / "sources" / "chunks" / f"{source_id}.jsonl"
        if not (metadata_path.exists() and blocks_path.exists() and chunks_path.exists()):
            missing_sidecars += 1
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                backend = str(metadata.get("parser_backend") or metadata.get("extraction_engine") or "pypdf")
                if backend not in {"pypdf", "mineru"}:
                    unknown_parser_backends += 1
                artifact_paths = metadata.get("parser_artifact_paths")
                if isinstance(artifact_paths, list):
                    for artifact_path in artifact_paths:
                        if not parser_artifact_exists(root, str(artifact_path)):
                            missing_parser_artifacts += 1
                content_list_path = str(metadata.get("parser_content_list_path") or "")
                if backend == "mineru" and content_list_path and not parser_artifact_exists(root, content_list_path):
                    missing_parser_content_lists += 1
                snippets = [
                    str(metadata.get("parser_command_stdout_snippet") or ""),
                    str(metadata.get("parser_command_stderr_snippet") or ""),
                ]
                if any(contains_secret_pattern(snippet) for snippet in snippets):
                    parser_secret_snippets += 1
                attempts = metadata.get("parser_backend_attempts")
                if metadata.get("parser_backend_fallback_from") == "mineru":
                    mineru_failed_attempts = []
                    if isinstance(attempts, list):
                        mineru_failed_attempts = [
                            attempt
                            for attempt in attempts
                            if isinstance(attempt, dict)
                            and attempt.get("backend") == "mineru"
                            and attempt.get("status") == "failed"
                        ]
                    if not mineru_failed_attempts:
                        auto_fallback_missing_attempt_diagnostics += 1
                if isinstance(attempts, list):
                    for attempt in attempts:
                        if not isinstance(attempt, dict):
                            continue
                        attempt_snippets = [
                            str(attempt.get("stdout_snippet") or ""),
                            str(attempt.get("stderr_snippet") or ""),
                            str(attempt.get("failure_reason") or ""),
                            " ".join(str(item) for item in attempt.get("warnings") or []),
                        ]
                        if any(contains_secret_pattern(snippet) for snippet in attempt_snippets):
                            parser_secret_snippets += 1
                warnings = metadata.get("warnings") if isinstance(metadata, dict) else []
                extraction_warnings += len(warnings) if isinstance(warnings, list) else 0
            except (OSError, json.JSONDecodeError):
                extraction_warnings += 1
        known_blocks_by_source[source_id] = load_known_block_ids(blocks_path)
        ignored_blocks_in_chunks += count_ignored_blocks_in_chunks(blocks_path, chunks_path)

    claims_missing_block_locator = 0
    claims_invalid_block_locator = 0
    for claim in conn.execute(
        """
        select c.claim_id, c.source_id, c.citation_locator
        from claims c
        join sources s on s.source_id = c.source_id
        where s.source_type = 'pdf'
        """
    ).fetchall():
        locator = str(claim["citation_locator"] or "")
        block_id = block_id_from_locator(locator)
        if not is_pdf_page_block_locator(locator) or not block_id:
            claims_missing_block_locator += 1
            continue
        if block_id not in known_blocks_by_source.get(claim["source_id"], set()):
            claims_invalid_block_locator += 1

    summary = evaluate_pdf_quality(root)

    return {
        "marker_titles": marker_titles,
        "missing_sidecars": missing_sidecars,
        "claims_missing_block_locator": claims_missing_block_locator,
        "claims_invalid_block_locator": claims_invalid_block_locator,
        "extraction_warnings": extraction_warnings,
        "title_quality_issues": summary.title_quality_issue_count,
        "invalid_sidecar_schema": summary.invalid_sidecar_schema_count,
        "high_parser_warnings": summary.high_parser_warning_source_count,
        "low_content_block_ratio": summary.low_content_block_ratio_source_count,
        "parser_created_aliases": summary.parser_created_duplicate_alias_count,
        "source_title_alias_collisions": summary.source_title_alias_collision_count,
        "unknown_parser_backends": unknown_parser_backends,
        "missing_parser_artifacts": missing_parser_artifacts,
        "missing_parser_content_lists": missing_parser_content_lists,
        "parser_secret_snippets": parser_secret_snippets,
        "ignored_blocks_in_chunks": ignored_blocks_in_chunks,
        "auto_fallback_missing_attempt_diagnostics": auto_fallback_missing_attempt_diagnostics,
        "paper_identity_overlaps": summary.paper_identity_overlap_count,
        "llm_json_repairs_observed": summary.llm_json_repair_observed_count,
    }


def load_known_block_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    block_ids: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict) and payload.get("block_id"):
                block_ids.add(str(payload["block_id"]))
    except (OSError, json.JSONDecodeError):
        return set()
    return block_ids


def is_pdf_page_block_locator(locator: str) -> bool:
    return re.search(r"(?:^|;)page:[1-9]\d*;block:[A-Za-z0-9_.-]+(?:;|$)", locator) is not None


def block_id_from_locator(locator: str) -> str | None:
    match = re.search(r"(?:^|;)page:[1-9]\d*;block:([A-Za-z0-9_.-]+)(?:;|$)", locator)
    return match.group(1) if match else None


def parser_artifact_exists(root: Path, artifact_path: str) -> bool:
    path = Path(artifact_path)
    if path.is_absolute():
        return path.exists()
    return (root / path).exists() or path.exists()


def contains_secret_pattern(text: str) -> bool:
    return (
        bool(re.search(r"sk-[A-Za-z0-9_-]{6,}", text))
        or bool(re.search(r"(?i)api[_-]?key=", text))
        or "config/api-keys.toml" in text
        or "config\\api-keys.toml" in text
    )


def count_ignored_blocks_in_chunks(blocks_path: Path, chunks_path: Path) -> int:
    if not blocks_path.exists() or not chunks_path.exists():
        return 0
    ignored: set[str] = set()
    try:
        for line in blocks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            block = json.loads(line)
            if block.get("content_role") == "ignored" and block.get("block_id"):
                ignored.add(str(block["block_id"]))
        count = 0
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            chunk = json.loads(line)
            block_ids = list(chunk.get("block_ids") or []) + list(chunk.get("context_block_ids") or [])
            count += sum(1 for block_id in block_ids if str(block_id) in ignored)
        return count
    except (OSError, json.JSONDecodeError):
        return 0


def unresolved_potential_contradictions(conn) -> int:
    return 0


def recorded_contradict_claim_ids(conn) -> set[str]:
    claim_ids = {
        row["claim_id"]
        for row in conn.execute("select claim_id from claims").fetchall()
    }
    recorded: set[str] = set()
    for row in conn.execute(
        """
        select subject_id, object_id, evidence_claim_id
        from relationships
        where relationship_type = 'contradicts'
        """
    ).fetchall():
        for value in (row["subject_id"], row["object_id"], row["evidence_claim_id"]):
            if value in claim_ids:
                recorded.add(value)
    return recorded
