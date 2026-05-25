from __future__ import annotations

import ast
import json
import re
from pathlib import Path, PurePosixPath

from .db import catalog_path, connect
from .ingest import normalize_alias
from .workspace import utc_now


class UnsafePatchError(ValueError):
    pass


ALLOWED_RUN_STATUSES = {"staged", "reviewed"}
ALLOWED_PAGE_TYPES = {"source", "concept", "entity", "synthesis"}
REQUIRED_FRONTMATTER = {"page_type", "title", "aliases", "source_count", "claim_ids", "updated_at"}
REQUIRED_SECTIONS = {
    "source": (
        "Source Metadata",
        "Key Claims",
        "Summary",
        "Important Evidence",
        "Possible Conflicts",
        "Links",
    ),
    "concept": (
        "Definition",
        "Key Claims",
        "Related Concepts",
        "Supporting Sources",
        "Open Questions",
    ),
    "entity": (
        "Overview",
        "Aliases",
        "Key Claims",
        "Relationships",
        "Supporting Sources",
        "Open Questions",
    ),
    "synthesis": (
        "Question/Topic",
        "Short Answer",
        "Evidence",
        "Analysis",
        "Uncertainties",
        "Related Pages",
    ),
}


def apply_run(root: Path, run_id: str) -> dict[str, int | str]:
    root = root.resolve()
    run_dir = root / "staging" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(run_id)

    validate_run_status(run_dir)
    claims = read_claims(run_dir / "claims.jsonl")
    patches = read_patches(run_dir / "patches")
    if not patches:
        raise ValueError(f"run {run_id} has no patches")

    claims_by_id = known_claims(root, claims)
    for patch in patches:
        validate_patch(root, patch, claims_by_id)

    snapshots = snapshot_mutable_files(root, patches)
    catalog_snapshot = catalog_path(root).read_bytes()
    try:
        backup_existing_targets(root, run_dir, patches)
        for patch in patches:
            target = root / Path(*PurePosixPath(str(patch["target_path"])).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(patch["content"]), encoding="utf-8", newline="\n")

        sync_catalog(root, run_id, claims, patches)
        refresh_index(root)
        append_log(root, run_id, claims, patches)
        mark_run_applied(run_dir)
    except Exception as exc:
        restore_mutable_files(snapshots)
        catalog_path(root).write_bytes(catalog_snapshot)
        raise UnsafePatchError(
            "Apply failed after mutation; restored wiki targets, index/log, and catalog. "
            f"Original error: {exc}"
        ) from exc
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


def validate_run_status(run_dir: Path) -> None:
    manifest_path = run_dir / "run.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    status = str(manifest.get("status", "staged"))
    if status not in ALLOWED_RUN_STATUSES:
        raise UnsafePatchError(
            f"Unsafe run status {status}; only staged or reviewed runs can be applied"
        )


def known_claims(root: Path, staging_claims: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    claims = {claim["claim_id"]: claim for claim in staging_claims}
    with connect(catalog_path(root)) as conn:
        for row in conn.execute(
            "select claim_id, source_id, claim_text, citation_locator, confidence_status, created_at from claims"
        ).fetchall():
            claims.setdefault(row["claim_id"], dict(row))
    return claims


def validate_patch(
    root: Path,
    patch: dict[str, object],
    claims_by_id: dict[str, dict[str, str]],
) -> None:
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
    if pure.parts == ("wiki", "log.md"):
        raise UnsafePatchError("Unsafe patch target cannot rewrite wiki/log.md")
    if pure.suffix.lower() != ".md":
        raise UnsafePatchError(f"Unsafe patch target is not Markdown: {target_path}")
    target = (root / Path(*pure.parts)).resolve()
    wiki_root = (root / "wiki").resolve()
    if target != wiki_root and wiki_root not in target.parents:
        raise UnsafePatchError(f"Unsafe patch target outside wiki: {target_path}")
    if "content" not in patch:
        raise UnsafePatchError("Unsafe patch has no content")
    content = str(patch["content"])
    frontmatter = parse_frontmatter(content)
    missing = sorted(REQUIRED_FRONTMATTER - set(frontmatter))
    if missing:
        raise UnsafePatchError(f"Unsafe patch frontmatter missing required field(s): {', '.join(missing)}")
    page_type = frontmatter.get("page_type", "")
    if page_type not in ALLOWED_PAGE_TYPES:
        raise UnsafePatchError(f"Unsafe patch page_type: {page_type}")
    if str(patch.get("page_type")) != page_type:
        raise UnsafePatchError(
            f"Unsafe patch page_type mismatch: patch={patch.get('page_type')} frontmatter={page_type}"
        )
    claim_ids = [str(claim_id) for claim_id in patch.get("claim_ids", [])]
    if not claim_ids:
        raise UnsafePatchError("Unsafe patch has no claim_ids")
    for claim_id in claim_ids:
        if claim_id not in claims_by_id:
            raise UnsafePatchError(f"Unsafe patch references unknown claim_id: {claim_id}")
    cited_claims = [
        claim
        for claim_id in claim_ids
        for claim in [claims_by_id[claim_id]]
        if claim.get("citation_locator")
        and claim.get("confidence_status", "weak") not in {"weak", "uncited"}
    ]
    if not cited_claims:
        raise UnsafePatchError("Unsafe patch has no cited claims")
    for section in REQUIRED_SECTIONS[page_type]:
        if not has_section(content, section):
            raise UnsafePatchError(f"Unsafe patch missing required section: {section}")


def parse_frontmatter(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise UnsafePatchError("Unsafe patch frontmatter is missing")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise UnsafePatchError("Unsafe patch frontmatter is not closed") from exc
    frontmatter: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise UnsafePatchError(f"Unsafe patch frontmatter line is invalid: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in {"aliases", "claim_ids"}:
            parse_list_value(value, key)
        frontmatter[key] = strip_quotes(value)
    return frontmatter


def parse_list_value(value: str, key: str) -> list[str]:
    try:
        parsed = ast.literal_eval(value)
    except Exception as exc:
        raise UnsafePatchError(f"Unsafe patch frontmatter {key} must be a list") from exc
    if not isinstance(parsed, list):
        raise UnsafePatchError(f"Unsafe patch frontmatter {key} must be a list")
    return [str(item) for item in parsed]


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def has_section(content: str, section: str) -> bool:
    pattern = rf"(?m)^##\s+{re.escape(section)}\s*$"
    return re.search(pattern, content) is not None


def snapshot_mutable_files(root: Path, patches: list[dict[str, object]]) -> dict[Path, bytes | None]:
    paths = {
        root / Path(*PurePosixPath(str(patch["target_path"])).parts)
        for patch in patches
    }
    paths.add(root / "wiki" / "index.md")
    paths.add(root / "wiki" / "log.md")
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def restore_mutable_files(snapshots: dict[Path, bytes | None]) -> None:
    for path, content in snapshots.items():
        if content is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def backup_existing_targets(root: Path, run_dir: Path, patches: list[dict[str, object]]) -> None:
    backup_root = run_dir / "backups"
    for patch in patches:
        pure = PurePosixPath(str(patch["target_path"]))
        target = root / Path(*pure.parts)
        if not target.exists():
            continue
        backup_path = backup_root / Path(*pure.parts)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(target.read_bytes())


def mark_run_applied(run_dir: Path) -> None:
    manifest_path = run_dir / "run.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "applied"
    manifest["applied_at"] = utc_now()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


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
