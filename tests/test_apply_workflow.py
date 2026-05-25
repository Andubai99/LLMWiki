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
