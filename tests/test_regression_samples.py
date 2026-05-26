from __future__ import annotations

import sqlite3
from pathlib import Path

from llmwiki.cli import main
from tests.helpers import disable_llm, make_workspace
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

    openai_aliases = scalar(root, "select count(*) from aliases where normalized_alias = 'openai'")
    assert openai_aliases == 1

    contradictions = scalar(
        root,
        "select count(*) from relationships where relationship_type = 'contradicts'",
    )
    assert contradictions >= 1

    assert main(["lint", "--root", str(root)]) == 0
    lint = capsys.readouterr().out
    assert "recorded contradicts relationships:" in lint
    assert "duplicate alias:" in lint
    assert "unresolved potential contradictions:" in lint
    assert "unresolved potential contradictions: 0" in lint


def test_identity_resolution_detects_alias_punctuation_and_entity_candidates(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    disable_llm(root)
    add_ingest_apply(root, fixture("minimal_source.md"))
    add_ingest_apply(root, fixture("regression_entity.md"))
    capsys.readouterr()

    alias_source = root / "rag-punctuation.md"
    alias_source.write_text(
        "# Retrieval-Augmented_Generation Notes\n\n"
        "Retrieval-augmented_generation should preserve citation anchors for audit review.\n",
        encoding="utf-8",
    )
    assert main(["add", str(alias_source), "--root", str(root)]) == 0
    source_id = scalar(
        root,
        "select source_id from sources where title = 'Retrieval-Augmented_Generation Notes'",
    )
    assert main(["ingest", source_id, "--root", str(root)]) == 0
    alias_run = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()
    assert main(["review", alias_run, "--root", str(root)]) == 0
    alias_review = capsys.readouterr().out
    assert "Duplicate candidates:" in alias_review
    assert "wiki/concepts/retrieval-augmented-generation.md" in alias_review
    assert "change" in alias_review and "update" in alias_review
    assert "wiki/concepts/retrieval-augmented-generation-notes.md" not in alias_review

    entity_source = root / "open-ai-variant.md"
    entity_source.write_text(
        "# Open-AI Entity Variant\n\n"
        "Open-AI develops language models for applied research systems.\n",
        encoding="utf-8",
    )
    assert main(["add", str(entity_source), "--root", str(root)]) == 0
    source_id = scalar(root, "select source_id from sources where title = 'Open-AI Entity Variant'")
    assert main(["ingest", source_id, "--root", str(root)]) == 0
    entity_run = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()
    triage = (root / "staging" / entity_run / "triage.md").read_text(encoding="utf-8")
    assert "wiki/entities/openai.md has matching alias OpenAI" in triage


def test_lint_distinguishes_recorded_and_unresolved_contradictions(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into claims (claim_id, source_id, claim_text, citation_locator, confidence_status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("clm_a", "src_a", "RAG systems require citation anchors.", "line:1", "cited", "2026-05-25T00:00:00+00:00"),
        )
        conn.execute(
            """
            insert into claims (claim_id, source_id, claim_text, citation_locator, confidence_status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "clm_b",
                "src_b",
                "RAG systems do not require citation anchors.",
                "line:1",
                "cited",
                "2026-05-25T00:00:00+00:00",
            ),
        )

    assert main(["lint", "--root", str(root)]) == 1
    lint = capsys.readouterr().out
    assert "recorded contradicts relationships: 0" in lint
    assert "unresolved potential contradictions: 1" in lint

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into relationships (
                subject_id, object_id, relationship_type, evidence_claim_id, source_id
            )
            values (?, ?, ?, ?, ?)
            """,
            ("clm_a", "clm_b", "contradicts", "clm_b", "src_b"),
        )

    assert main(["lint", "--root", str(root)]) == 0
    lint = capsys.readouterr().out
    assert "recorded contradicts relationships: 1" in lint
    assert "unresolved potential contradictions: 0" in lint


def test_chinese_regression_sources_cover_alias_entity_conflict_and_support(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    disable_llm(root)

    source_ids = [
        add_ingest_apply(root, fixture("zh_alias_entity.md")),
        add_ingest_apply(root, fixture("zh_conflict.md")),
        add_ingest_apply(root, fixture("zh_supports.md")),
    ]
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

    contradictions = scalar(
        root,
        "select count(*) from relationships where relationship_type = 'contradicts'",
    )
    supports = scalar(
        root,
        "select count(*) from relationships where relationship_type = 'supports'",
    )
    assert contradictions >= 1
    assert supports >= 1

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        claim_rows = conn.execute(
            "select claim_text, citation_locator from claims where source_id in (?, ?, ?)",
            source_ids,
        ).fetchall()
    assert claim_rows
    assert any("检索增强生成" in row[0] for row in claim_rows)
    assert all("line:" in row[1] and "section:" in row[1] and "paragraph:" in row[1] for row in claim_rows)

    assert main(["lint", "--root", str(root)]) == 0
    lint = capsys.readouterr().out
    assert "recorded contradicts relationships:" in lint
    assert "unresolved potential contradictions: 0" in lint


def test_docs_describe_v1_commands_and_constraints():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")

    for command in ("init", "add", "ingest", "review", "apply", "query", "retrieve", "lint", "doctor"):
        assert f"llmwiki {command}" in readme
    assert "--json" in readme
    assert "--format prompt" in readme
    assert "retrieve_context" in readme
    assert "RAG/Agent evidence layer" in readme
    assert "LLM Provider" in readme
    assert "LLM Ingest Proposal" in readme
    assert "llm-proposal.json" in readme
    assert "proposal_engine=llm" in readme
    assert "DEEPSEEK_API_KEY" in readme
    assert "llmwiki llm-test --root ." in readme
    assert "python -m venv .venv" in readme
    assert ".\\.venv\\Scripts\\Activate.ps1" in readme
    assert "python -m pip install -e ." in readme
    assert "Obsidian" in readme
    assert "Git" in readme
    assert "not supported" in readme
    assert "review/apply v2" in readme
    assert "--detail" in readme
    assert "--patches" in readme
    assert "staged" in readme
    assert "reviewed" in readme
    assert "applied" in readme
    assert "weak/uncited" in readme
    assert "backups" in readme

    assert "Do not modify files under `sources/raw/`" in agents
    assert "staging" in agents
    assert "apply" in agents
    assert "citation" in agents
    assert "safety validation" in agents
    assert "must not bypass staging" in agents
    assert "must not overwrite user-authored wiki content without a recoverable backup" in agents
    assert "source locator" in agents
    assert "`llmwiki retrieve` is the standard evidence interface" in agents
    assert "Do not forge claim ids" in agents
    assert "`contradicts` relationships must be exposed" in agents
    assert "API Key" in agents
    assert "DEEPSEEK_API_KEY" in agents
    assert "mock provider" in agents
    assert "llm-proposal.json" in agents
    assert "valid source locators" in agents
    assert "vector" in agents
    assert "Web UI" in agents


def test_gitignore_excludes_virtualenv_and_python_caches():
    root = Path(__file__).resolve().parents[1]
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")

    for pattern in (".venv/", "__pycache__/", ".pytest_cache/", "*.pyc"):
        assert pattern in gitignore
