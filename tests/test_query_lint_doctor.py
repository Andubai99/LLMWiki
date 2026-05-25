from __future__ import annotations

from pathlib import Path

from llmwiki.cli import main
from tests.helpers import make_workspace


def fixture(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def add_ingest_apply(root: Path, source_path: Path) -> str:
    assert main(["add", str(source_path), "--root", str(root)]) == 0
    # Caller must read capsys after invoking this helper if stdout matters.
    import sqlite3
    import hashlib

    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        source_id = conn.execute(
            "select source_id from sources where sha256 = ?", (digest,)
        ).fetchone()[0]
    before_runs = set(path.name for path in (root / "staging").glob("run_*"))
    assert main(["ingest", source_id, "--root", str(root)]) == 0
    after_runs = set(path.name for path in (root / "staging").glob("run_*"))
    run_id = (after_runs - before_runs).pop()
    assert main(["review", run_id, "--root", str(root)]) == 0
    assert main(["apply", run_id, "--root", str(root)]) == 0
    return source_id


def test_query_returns_retrieval_context_with_citations(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source_id = add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()

    assert main(["query", "retrieval citation anchors", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "Retrieval context" in out
    assert f"source_id={source_id}" in out
    assert "citation=line:" in out
    assert "Retrieval augmented generation" in out


def test_lint_and_doctor_report_workspace_health(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()

    assert main(["doctor", "--root", str(root)]) == 0
    doctor = capsys.readouterr().out
    assert "Python OK" in doctor
    assert "dependencies OK" in doctor
    assert "Workspace OK" in doctor
    assert "schema OK" in doctor
    assert "index/log OK" in doctor

    assert main(["lint", "--root", str(root)]) == 0
    lint = capsys.readouterr().out
    assert "Lint OK" in lint
    assert "source hash drift: 0" in lint
    assert "uncited claims: 0" in lint
