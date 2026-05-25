from __future__ import annotations

import json
from pathlib import Path

from llmwiki.cli import main
from tests.helpers import make_workspace


def add_sample_source(root: Path) -> str:
    assert main(["init", "--root", str(root)]) == 0
    source = root / "minimal.md"
    source.write_text(
        "# Retrieval Notes\n\n"
        "Retrieval augmented generation links answers to source passages.\n"
        "RAG systems should preserve citation anchors.\n"
        "Contradiction markers should be preserved when sources conflict.\n",
        encoding="utf-8",
    )
    assert main(["add", str(source), "--root", str(root)]) == 0
    db_path = root / "state" / "catalog.sqlite"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        return conn.execute("select source_id from sources").fetchone()[0]


def snapshot_tree(path: Path) -> dict[str, str]:
    return {
        item.relative_to(path).as_posix(): item.read_text(encoding="utf-8")
        for item in sorted(path.rglob("*.md"))
    }


def test_ingest_writes_only_staging_and_claim_first_files(capsys):
    root = make_workspace()
    source_id = add_sample_source(root)
    before = snapshot_tree(root / "wiki")

    assert main(["ingest", source_id, "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Created ingest run" in out
    run_id = out.split("run_id=", 1)[1].splitlines()[0].strip()

    after = snapshot_tree(root / "wiki")
    assert after == before

    run_dir = root / "staging" / run_id
    assert (run_dir / "claims.jsonl").exists()
    assert (run_dir / "triage.md").exists()
    assert (run_dir / "patches").is_dir()
    patches = sorted((run_dir / "patches").glob("*.json"))
    assert patches

    claims = [
        json.loads(line)
        for line in (run_dir / "claims.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert claims
    assert all(claim["source_id"] == source_id for claim in claims)
    assert all(claim["citation_locator"].startswith("line:") for claim in claims)
    assert all(claim["confidence_status"] == "cited" for claim in claims)

    triage = (run_dir / "triage.md").read_text(encoding="utf-8")
    assert "Duplicate Candidates" in triage
    assert "Conflict Candidates" in triage
    assert "Citation coverage: 100%" in triage

    patch_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in patches]
    target_paths = {payload["target_path"] for payload in patch_payloads}
    assert any(path.startswith("wiki/sources/") for path in target_paths)
    assert any(path.startswith("wiki/concepts/") for path in target_paths)


def test_review_summarizes_staged_run_without_modifying_wiki(capsys):
    root = make_workspace()
    source_id = add_sample_source(root)
    assert main(["ingest", source_id, "--root", str(root)]) == 0
    run_id = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()
    before = snapshot_tree(root / "wiki")

    assert main(["review", run_id, "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert snapshot_tree(root / "wiki") == before
    assert f"Review run: {run_id}" in out
    assert "Candidate patches:" in out
    assert "Duplicate candidates:" in out
    assert "Conflict candidates:" in out
    assert "Citation coverage:" in out
