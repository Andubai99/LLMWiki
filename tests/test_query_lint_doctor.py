from __future__ import annotations

from pathlib import Path
import sys

from llmwiki.cli import main, virtualenv_status
from llmwiki.sources import import_source
from tests.helpers import disable_llm, make_workspace
from tests.test_hybrid_retrieval import setup_seeded_workspace


def fixture(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def add_ingest_apply(root: Path, source_path: Path) -> str:
    disable_llm(root)
    result = import_source(root, str(source_path))
    # Caller must read capsys after invoking this helper if stdout matters.
    source_id = result.source_id
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
    assert "page=" in out
    assert "relationship=" in out
    assert "Retrieval augmented generation" in out


def test_query_does_not_call_llm_planner_or_provider(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()

    def fail_provider(*args, **kwargs):
        raise AssertionError("query must not call an LLM provider or planner")

    monkeypatch.setattr("llmwiki.llm.create_provider", fail_provider)
    monkeypatch.setattr("llmwiki.planner.create_provider", fail_provider)

    assert main(["query", "retrieval citation anchors", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "Retrieval context" in out
    assert "source_id=" in out


def test_query_reuses_retrieve_for_natural_chinese_question(capsys):
    root = setup_seeded_workspace()
    capsys.readouterr()

    assert main(["query", "草莓应该怎么保存？", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "Retrieval context for: 草莓应该怎么保存？" in out
    assert "clm_strawberry_storage" in out
    assert "source_id=src_99ab0495789d" in out
    assert "wiki/concepts/草莓.md" in out
    assert "草莓适合冷藏保存" in out


def test_lint_and_doctor_report_workspace_health(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()

    assert main(["doctor", "--root", str(root)]) == 0
    doctor = capsys.readouterr().out
    assert "Python OK" in doctor
    assert "dependencies OK" in doctor
    assert "virtual environment OK" in doctor
    assert "Workspace OK" in doctor
    assert "schema OK" in doctor
    assert "index/log OK" in doctor

    assert main(["lint", "--root", str(root)]) == 0
    lint = capsys.readouterr().out
    assert "Lint OK" in lint
    assert "source hash drift: 0" in lint
    assert "uncited claims: 0" in lint


def test_lint_reports_source_hash_drift(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()

    import sqlite3

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        raw_path = conn.execute("select raw_path from sources limit 1").fetchone()[0]
    with (root / raw_path).open("a", encoding="utf-8") as handle:
        handle.write("\nUnauthorized raw mutation.\n")

    assert main(["lint", "--root", str(root)]) == 1
    lint = capsys.readouterr().out
    assert "source hash drift: 1" in lint


def test_virtualenv_status_warns_when_not_running_in_virtualenv(monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(sys, "prefix", sys.base_prefix, raising=False)

    ok, line = virtualenv_status()

    assert not ok
    assert "warning" in line
    assert "virtual environment" in line
