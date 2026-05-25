from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from .db import catalog_path, connect
from .ingest import normalize_alias
from .workspace import utc_now


class UnsafePatchError(ValueError):
    pass


def apply_run(root: Path, run_id: str) -> dict[str, int | str]:
    root = root.resolve()
    run_dir = root / "staging" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(run_id)

    claims = read_claims(run_dir / "claims.jsonl")
    patches = read_patches(run_dir / "patches")
    if not patches:
        raise ValueError(f"run {run_id} has no patches")

    for patch in patches:
        validate_patch(root, patch)

    for patch in patches:
        target = root / Path(*PurePosixPath(str(patch["target_path"])).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(patch["content"]), encoding="utf-8", newline="\n")

    sync_catalog(root, run_id, claims, patches)
    refresh_index(root)
    append_log(root, run_id, claims, patches)
    return {"run_id": run_id, "claims": len(claims), "patches": len(patches)}


def read_claims(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_patches(patches_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(patches_dir.glob("*.json"))
    ]


def validate_patch(root: Path, patch: dict[str, object]) -> None:
    if patch.get("action") != "upsert_page":
        raise UnsafePatchError("Unsafe patch action; only upsert_page is supported")
    target_path = patch.get("target_path")
    if not isinstance(target_path, str):
        raise UnsafePatchError("Unsafe patch target_path is missing")
    pure = PurePosixPath(target_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise UnsafePatchError(f"Unsafe patch target: {target_path}")
    if len(pure.parts) < 2 or pure.parts[0] != "wiki":
        raise UnsafePatchError(f"Unsafe patch target outside wiki: {target_path}")
    if pure.suffix.lower() != ".md":
        raise UnsafePatchError(f"Unsafe patch target is not Markdown: {target_path}")
    target = (root / Path(*pure.parts)).resolve()
    wiki_root = (root / "wiki").resolve()
    if target != wiki_root and wiki_root not in target.parents:
        raise UnsafePatchError(f"Unsafe patch target outside wiki: {target_path}")
    if "content" not in patch:
        raise UnsafePatchError("Unsafe patch has no content")


def sync_catalog(
    root: Path,
    run_id: str,
    claims: list[dict[str, str]],
    patches: list[dict[str, object]],
) -> None:
    now = utc_now()
    source_id = first_source_id(claims, patches)
    with connect(catalog_path(root)) as conn:
        for claim in claims:
            conn.execute(
                """
                insert or ignore into claims (
                    claim_id, source_id, claim_text, citation_locator,
                    confidence_status, created_at
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim["claim_id"],
                    claim["source_id"],
                    claim["claim_text"],
                    claim.get("citation_locator"),
                    claim.get("confidence_status", "weak"),
                    claim.get("created_at", now),
                ),
            )
            conn.execute(
                """
                insert into claims_fts (claim_id, claim_text, source_id, citation_locator)
                values (?, ?, ?, ?)
                """,
                (
                    claim["claim_id"],
                    claim["claim_text"],
                    claim["source_id"],
                    claim.get("citation_locator"),
                ),
            )

        for patch in patches:
            page_id = str(patch["page_id"])
            aliases = [str(alias) for alias in patch.get("aliases", [])]
            conn.execute(
                """
                insert into pages (page_id, path, page_type, title, aliases, updated_at)
                values (?, ?, ?, ?, ?, ?)
                on conflict(page_id) do update set
                    path = excluded.path,
                    page_type = excluded.page_type,
                    title = excluded.title,
                    aliases = excluded.aliases,
                    updated_at = excluded.updated_at
                """,
                (
                    page_id,
                    str(patch["target_path"]),
                    str(patch["page_type"]),
                    str(patch["title"]),
                    json.dumps(aliases, ensure_ascii=False),
                    now,
                ),
            )
            conn.execute("delete from aliases where target_id = ?", (page_id,))
            seen_aliases: set[str] = set()
            for alias in [str(patch["title"]), *aliases]:
                normalized = normalize_alias(alias)
                if normalized in seen_aliases:
                    continue
                seen_aliases.add(normalized)
                conn.execute(
                    """
                    insert into aliases (alias, target_type, target_id, normalized_alias)
                    values (?, ?, ?, ?)
                    """,
                    (
                        alias,
                        str(patch["page_type"]),
                        page_id,
                        normalized,
                    ),
                )
            for link in patch.get("links", []):
                conn.execute(
                    "insert into links (from_page, to_page, link_type) values (?, ?, ?)",
                    (
                        str(link["from_page"]),
                        str(link["to_page"]),
                        str(link["link_type"]),
                    ),
                )
            for relationship in patch.get("relationships", []):
                conn.execute(
                    """
                    insert into relationships (
                        subject_id, object_id, relationship_type,
                        evidence_claim_id, source_id
                    )
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        str(relationship["subject_id"]),
                        str(relationship["object_id"]),
                        str(relationship["relationship_type"]),
                        str(relationship.get("evidence_claim_id") or ""),
                        str(relationship.get("source_id") or source_id),
                    ),
                )

        conn.execute(
            """
            insert into ingest_runs (run_id, source_id, status, created_at, applied_at)
            values (?, ?, ?, ?, ?)
            on conflict(run_id) do update set
                status = excluded.status,
                applied_at = excluded.applied_at
            """,
            (run_id, source_id, "applied", now, now),
        )


def first_source_id(claims: list[dict[str, str]], patches: list[dict[str, object]]) -> str:
    if claims:
        return claims[0]["source_id"]
    for patch in patches:
        if patch.get("source_id"):
            return str(patch["source_id"])
    return "unknown"


def refresh_index(root: Path) -> None:
    with connect(catalog_path(root)) as conn:
        rows = conn.execute(
            "select path, page_type, title from pages order by page_type, title"
        ).fetchall()
        source_count = conn.execute("select count(*) from sources").fetchone()[0]
    groups = {
        "source": [],
        "concept": [],
        "entity": [],
        "synthesis": [],
    }
    for row in rows:
        groups.setdefault(row["page_type"], []).append((row["path"], row["title"]))

    now = utc_now()
    lines = [
        "---",
        "page_type: index",
        'title: "LLM Wiki Index"',
        "aliases: []",
        f"source_count: {source_count}",
        "claim_ids: []",
        f'updated_at: "{now}"',
        "---",
        "",
        "# LLM Wiki Index",
        "",
    ]
    for page_type, heading in (
        ("source", "Sources"),
        ("concept", "Concepts"),
        ("entity", "Entities"),
        ("synthesis", "Syntheses"),
    ):
        lines.extend([f"## {heading}", ""])
        if groups.get(page_type):
            lines.extend(
                f"- [[{path}|{title}]]" for path, title in groups[page_type]
            )
        else:
            lines.append(f"No {heading.lower()} applied yet.")
        lines.append("")
    (root / "wiki" / "index.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )


def append_log(root: Path, run_id: str, claims: list[dict[str, str]], patches: list[dict[str, object]]) -> None:
    log_path = root / "wiki" / "log.md"
    source_id = first_source_id(claims, patches)
    entry = (
        f"- {utc_now()} Applied ingest run `{run_id}` for source `{source_id}` "
        f"({len(claims)} claims, {len(patches)} patches).\n"
    )
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(entry)
