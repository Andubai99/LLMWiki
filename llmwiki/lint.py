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
        page_paths = {row["path"] for row in pages}

        broken_links = [
            row
            for row in conn.execute("select from_page, to_page, link_type from links").fetchall()
            if row["to_page"] not in page_paths and not (root / row["to_page"]).exists()
        ]
        lines.append(f"- broken links: {len(broken_links)}")
        issue_count += len(broken_links)

        linked_pages = {
            row["from_page"] for row in conn.execute("select from_page from links").fetchall()
        } | {row["to_page"] for row in conn.execute("select to_page from links").fetchall()}
        orphan_pages = [
            row["path"]
            for row in pages
            if row["path"] not in linked_pages and row["page_type"] != "index"
        ]
        lines.append(f"- orphan pages: {len(orphan_pages)}")
        issue_count += len(orphan_pages)

        duplicate_aliases = conn.execute(
            """
            select normalized_alias, count(*) as n
            from aliases
            group by normalized_alias
            having count(*) > 1
            """
        ).fetchall()
        lines.append(f"- duplicate alias: {len(duplicate_aliases)}")
        issue_count += len(duplicate_aliases)

        uncited_claims = conn.execute(
            """
            select claim_id
            from claims
            where citation_locator is null
               or citation_locator = ''
               or confidence_status in ('weak', 'uncited')
            """
        ).fetchall()
        lines.append(f"- uncited claims: {len(uncited_claims)}")
        issue_count += len(uncited_claims)

        drift_count = source_hash_drift(root, conn)
        lines.append(f"- source hash drift: {drift_count}")
        issue_count += drift_count

        contradicts = conn.execute(
            "select count(*) from relationships where relationship_type = 'contradicts'"
        ).fetchone()[0]
        lines.append(f"- contradicts relationships: {contradicts}")
        issue_count += contradicts

        potential = potential_contradictions(conn)
        lines.append(f"- potential contradictions: {potential}")
        issue_count += potential

    if issue_count == 0:
        lines.append("Lint OK")
    else:
        lines.append(f"Lint found {issue_count} issue(s)")
    return LintReport(issue_count, lines)


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


def potential_contradictions(conn) -> int:
    rows = conn.execute("select claim_text from claims").fetchall()
    texts = [row["claim_text"].casefold() for row in rows]
    count = 0
    for index, left in enumerate(texts):
        for right in texts[index + 1 :]:
            shared = set(left.split()) & set(right.split())
            if len(shared) >= 3 and (" not " in f" {left} ") != (" not " in f" {right} "):
                count += 1
    return count
