from __future__ import annotations

import sqlite3
from pathlib import Path

from llmwiki.cli import main
from tests.helpers import make_workspace
from tests.test_query_lint_doctor import add_ingest_apply, fixture


def scalar(root: Path, sql: str):
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        return conn.execute(sql).fetchone()[0]


def test_regression_samples_preserve_alias_entity_and_conflict(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    for name in (
        "minimal_source.md",
        "regression_alias.md",
        "regression_entity.md",
        "regression_conflict.md",
    ):
        add_ingest_apply(root, fixture(name))
    capsys.readouterr()

    rag_pages = scalar(
        root,
        "select count(*) from pages where page_type = 'concept' and title = 'Retrieval Augmented Generation'",
    )
    assert rag_pages == 1

    openai_entities = scalar(
        root,
        "select count(*) from pages where page_type = 'entity' and title = 'OpenAI'",
    )
    assert openai_entities == 1

    openai_aliases = scalar(
        root,
        "select count(*) from aliases where normalized_alias in ('openai', 'open ai')",
    )
    assert openai_aliases >= 2

    contradictions = scalar(
        root,
        "select count(*) from relationships where relationship_type = 'contradicts'",
    )
    assert contradictions >= 1

    assert main(["lint", "--root", str(root)]) == 1
    lint = capsys.readouterr().out
    assert "contradicts relationships:" in lint
    assert "duplicate alias:" in lint
    assert "potential contradictions:" in lint


def test_docs_describe_v1_commands_and_constraints():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")

    for command in ("init", "add", "ingest", "review", "apply", "query", "lint", "doctor"):
        assert f"llmwiki {command}" in readme
    assert "Obsidian" in readme
    assert "Git" in readme
    assert "not supported" in readme

    assert "Do not modify files under `sources/raw/`" in agents
    assert "staging" in agents
    assert "apply" in agents
    assert "citation" in agents
    assert "vector" in agents
    assert "Web UI" in agents
