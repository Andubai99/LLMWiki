from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from tests.helpers import make_workspace
from tests.test_ingest_review import add_sample_source


def rows(root: Path, sql: str) -> list[sqlite3.Row]:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql).fetchall()


def create_staged_sample(root: Path) -> str:
    source_id = add_sample_source(root)
    assert main(["ingest", source_id, "--root", str(root)]) == 0
    run_dirs = sorted((root / "staging").iterdir())
    assert run_dirs
    return run_dirs[-1].name


def write_manual_run(
    root: Path,
    run_id: str,
    patch: dict,
    claims: list[dict] | None = None,
    status: str = "staged",
) -> None:
    run_dir = root / "staging" / run_id
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(parents=True)
    claims = claims or []
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source_id": claims[0]["source_id"] if claims else "src_manual",
                "status": status,
                "created_at": "2026-05-25T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "claims.jsonl").write_text(
        "".join(json.dumps(claim) + "\n" for claim in claims),
        encoding="utf-8",
    )
    (run_dir / "triage.md").write_text("# manual\n", encoding="utf-8")
    (patches_dir / "001-manual.json").write_text(json.dumps(patch), encoding="utf-8")


def valid_claim() -> dict:
    return {
        "claim_id": "clm_manual_1",
        "source_id": "src_manual",
        "claim_text": "Manual claim keeps a source locator for apply validation.",
        "citation_locator": "line:1",
        "confidence_status": "cited",
        "created_at": "2026-05-25T00:00:00+00:00",
    }


def valid_source_patch(**overrides) -> dict:
    patch = {
        "action": "upsert_page",
        "page_id": "src_manual",
        "page_type": "source",
        "target_path": "wiki/sources/src_manual.md",
        "title": "Manual Source",
        "aliases": ["Manual Source"],
        "claim_ids": ["clm_manual_1"],
        "content": "\n".join(
            [
                "---",
                "page_type: source",
                'title: "Manual Source"',
                'aliases: ["Manual Source"]',
                "source_count: 1",
                'claim_ids: ["clm_manual_1"]',
                'updated_at: "2026-05-25T00:00:00+00:00"',
                "---",
                "",
                "# Manual Source",
                "",
                "## Source Metadata",
                "",
                "- source_id: `src_manual`",
                "",
                "## Key Claims",
                "",
                "- Manual claim keeps a source locator. (`clm_manual_1`, `src_manual`, `line:1`)",
                "",
                "## Summary",
                "",
                "This source contributes one cited claim.",
                "",
                "## Important Evidence",
                "",
                "- `line:1` supports `clm_manual_1`.",
                "",
                "## Possible Conflicts",
                "",
                "- None identified during ingest.",
                "",
                "## Links",
                "",
                "- [[wiki/concepts/manual.md]]",
                "",
            ]
        ),
        "links": [],
        "relationships": [],
    }
    patch.update(overrides)
    return patch


def test_apply_updates_wiki_index_log_and_catalog(capsys):
    root = make_workspace()
    run_id = create_staged_sample(root)

    assert main(["apply", run_id, "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert f"Applied ingest run: {run_id}" in out

    source_pages = sorted((root / "wiki" / "sources").glob("*.md"))
    concept_pages = sorted((root / "wiki" / "concepts").glob("*.md"))
    assert source_pages
    assert concept_pages

    source_text = source_pages[0].read_text(encoding="utf-8")
    concept_text = concept_pages[0].read_text(encoding="utf-8")
    assert "page_type: source" in source_text
    assert "## Source Metadata" in source_text
    assert "## Key Claims" in concept_text

    index = (root / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "wiki/sources/" in index
    assert "wiki/concepts/" in index

    log = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    assert f"Applied ingest run `{run_id}`" in log

    assert rows(root, "select claim_text, citation_locator from claims")
    assert rows(root, "select path, page_type, title from pages")
    assert rows(root, "select from_page, to_page, link_type from links")
    assert rows(root, "select relationship_type from relationships")
    run_rows = rows(root, "select run_id, status, applied_at from ingest_runs")
    assert run_rows[0]["run_id"] == run_id
    assert run_rows[0]["status"] == "applied"
    assert run_rows[0]["applied_at"]


def test_apply_rejects_patch_outside_wiki(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    run_id = "run_unsafe"
    run_dir = root / "staging" / run_id
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(parents=True)
    (run_dir / "claims.jsonl").write_text("", encoding="utf-8")
    (run_dir / "triage.md").write_text("# unsafe\n", encoding="utf-8")
    (patches_dir / "001-bad.json").write_text(
        json.dumps(
            {
                "action": "upsert_page",
                "page_id": "bad",
                "page_type": "source",
                "target_path": "sources/raw/bad.md",
                "title": "Bad",
                "aliases": [],
                "claim_ids": [],
                "content": "bad",
            }
        ),
        encoding="utf-8",
    )

    assert main(["apply", run_id, "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "Unsafe patch" in out
    assert not (root / "sources" / "raw" / "bad.md").exists()

    run_id = "run_unsafe_normalized"
    run_dir = root / "staging" / run_id
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(parents=True)
    (run_dir / "claims.jsonl").write_text("", encoding="utf-8")
    (run_dir / "triage.md").write_text("# unsafe\n", encoding="utf-8")
    (patches_dir / "001-bad.json").write_text(
        json.dumps(
            {
                "action": "upsert_page",
                "page_id": "bad",
                "page_type": "source",
                "target_path": "sources/normalized/bad.md",
                "title": "Bad",
                "aliases": [],
                "claim_ids": [],
                "content": "bad",
            }
        ),
        encoding="utf-8",
    )

    assert main(["apply", run_id, "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "Unsafe patch" in out
    assert not (root / "sources" / "normalized" / "bad.md").exists()


def test_ingest_and_apply_leave_raw_and_normalized_sources_unchanged(capsys):
    root = make_workspace()
    run_id = create_staged_sample(root)
    import sqlite3

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        row = conn.execute("select raw_path, normalized_path from sources").fetchone()
    raw_path = root / row[0]
    normalized_path = root / row[1]
    raw_before = raw_path.read_bytes()
    normalized_before = normalized_path.read_bytes()

    assert main(["apply", run_id, "--root", str(root)]) == 0
    capsys.readouterr()

    assert raw_path.read_bytes() == raw_before
    assert normalized_path.read_bytes() == normalized_before


def test_apply_rejects_run_status_that_is_not_staged_or_reviewed(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    run_id = "run_already_applied"
    write_manual_run(root, run_id, valid_source_patch(), [valid_claim()], status="applied")

    assert main(["apply", run_id, "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "Unsafe patch" in out
    assert "status" in out
    assert not (root / "wiki" / "sources" / "src_manual.md").exists()


def test_apply_rejects_invalid_frontmatter_page_type_and_missing_sections(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    claim = valid_claim()

    invalid_frontmatter = valid_source_patch(content="# Missing frontmatter\n")
    write_manual_run(root, "run_bad_frontmatter", invalid_frontmatter, [claim])
    assert main(["apply", "run_bad_frontmatter", "--root", str(root)]) == 1
    assert "frontmatter" in capsys.readouterr().out

    bad_page_type = valid_source_patch(
        page_type="concept",
        content=valid_source_patch()["content"].replace("page_type: source", "page_type: unknown"),
    )
    write_manual_run(root, "run_bad_page_type", bad_page_type, [claim])
    assert main(["apply", "run_bad_page_type", "--root", str(root)]) == 1
    assert "page_type" in capsys.readouterr().out

    missing_section = valid_source_patch(
        content=valid_source_patch()["content"].replace("## Important Evidence", "## Evidence")
    )
    write_manual_run(root, "run_missing_section", missing_section, [claim])
    assert main(["apply", "run_missing_section", "--root", str(root)]) == 1
    assert "missing required section" in capsys.readouterr().out


def test_apply_rejects_unknown_or_uncited_claims(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    unknown_claim_patch = valid_source_patch(claim_ids=["clm_missing"])
    write_manual_run(root, "run_unknown_claim", unknown_claim_patch, [valid_claim()])
    assert main(["apply", "run_unknown_claim", "--root", str(root)]) == 1
    assert "unknown claim_id" in capsys.readouterr().out

    uncited_claim = valid_claim() | {
        "claim_id": "clm_manual_weak",
        "citation_locator": "",
        "confidence_status": "uncited",
    }
    uncited_patch = valid_source_patch(claim_ids=["clm_manual_weak"]).copy()
    uncited_patch["content"] = uncited_patch["content"].replace("clm_manual_1", "clm_manual_weak")
    write_manual_run(root, "run_uncited_claim", uncited_patch, [uncited_claim])
    assert main(["apply", "run_uncited_claim", "--root", str(root)]) == 1
    assert "no cited claims" in capsys.readouterr().out


def test_apply_backs_up_existing_page_before_update(capsys):
    root = make_workspace()
    first_run = create_staged_sample(root)
    assert main(["apply", first_run, "--root", str(root)]) == 0
    capsys.readouterr()

    concept_page = next((root / "wiki" / "concepts").glob("*.md"))
    original = concept_page.read_text(encoding="utf-8")
    concept_page.write_text(original + "\n\nUser note that must be recoverable.\n", encoding="utf-8")

    second_source = root / "second.md"
    second_source.write_text(
        "# RAG Followup\n\n"
        "RAG systems preserve citation anchors for later review.\n"
        "Retrieval augmented generation benefits from duplicate concept checks.\n",
        encoding="utf-8",
    )
    assert main(["add", str(second_source), "--root", str(root)]) == 0
    source_id = rows(root, "select source_id from sources order by imported_at desc limit 1")[0][0]
    assert main(["ingest", source_id, "--root", str(root)]) == 0
    second_run = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()

    assert main(["apply", second_run, "--root", str(root)]) == 0
    backup_dir = root / "staging" / second_run / "backups"
    backups = sorted(backup_dir.rglob("*.md"))
    assert backups
    assert any("User note that must be recoverable." in path.read_text(encoding="utf-8") for path in backups)
