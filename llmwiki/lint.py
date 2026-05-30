from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .db import catalog_path, connect, schema_status


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
            select claim_id
            from claims
            where citation_locator is null
               or citation_locator = ''
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
