from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.llm_ingest import LLMIngestProposal
from tests.helpers import disable_llm, make_workspace


def rows(root: Path, sql: str) -> list[sqlite3.Row]:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql).fetchall()


def write_source(root: Path, name: str = "autonomous.md") -> Path:
    source = root / name
    source.write_text(
        "# Autonomous Add\n\n"
        "Autonomous add should preserve citation anchors for later retrieval.\n"
        "LLMWiki writes formal pages only after staged validation succeeds.\n",
        encoding="utf-8",
    )
    return source


def deterministic_proposal(source: dict[str, str], normalized_text: str) -> LLMIngestProposal:
    return LLMIngestProposal(
        claims=[
            {
                "claim_id": f"clm_{source['source_id']}_llm_001",
                "source_id": source["source_id"],
                "claim_text": "Autonomous add preserves citation anchors for later retrieval.",
                "citation_locator": "line:3;paragraph:1",
                "confidence_status": "cited",
            },
            {
                "claim_id": f"clm_{source['source_id']}_llm_002",
                "source_id": source["source_id"],
                "claim_text": "LLMWiki writes formal pages only after staged validation succeeds.",
                "citation_locator": "line:4;paragraph:1",
                "confidence_status": "cited",
            },
        ],
        concept_title="Autonomous Add",
        aliases=["autonomous add"],
        entity_title=None,
        entity_aliases=[],
        duplicate_candidates=[],
        conflict_candidates=[],
        source_summary="Autonomous add compiles one source into the wiki.",
        concept_definition="Autonomous add is the one-command import-to-wiki pipeline.",
        provider="openai",
        model="deepseek-v4-pro",
        raw_content='{"claims":[]}',
        usage={"total_tokens": 42},
    )


def patch_llm_proposal(monkeypatch) -> None:
    def fake_create(root: Path, source: dict[str, str], normalized_text: str) -> LLMIngestProposal:
        return deterministic_proposal(source, normalized_text)

    monkeypatch.setattr("llmwiki.ingest.create_llm_ingest_proposal", fake_create)


def test_add_keeps_same_title_concept_and_entity_with_distinct_page_ids(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source = write_source(root, "orange.md")

    def fake_create(root: Path, source: dict[str, str], normalized_text: str) -> LLMIngestProposal:
        proposal = deterministic_proposal(source, normalized_text)
        return LLMIngestProposal(
            claims=proposal.claims,
            concept_title="Orange",
            aliases=["orange"],
            entity_title="Orange",
            entity_aliases=["orange"],
            duplicate_candidates=[],
            conflict_candidates=[],
            source_summary=proposal.source_summary,
            concept_definition=proposal.concept_definition,
            provider=proposal.provider,
            model=proposal.model,
            raw_content=proposal.raw_content,
            usage=proposal.usage,
        )

    monkeypatch.setattr("llmwiki.ingest.create_llm_ingest_proposal", fake_create)
    capsys.readouterr()

    assert main(["add", str(source), "--root", str(root)]) == 0

    page_rows = rows(
        root,
        "select page_id, path, page_type from pages where title = 'Orange' order by page_type",
    )
    assert [row["page_type"] for row in page_rows] == ["concept", "entity"]
    assert {row["page_id"] for row in page_rows} == {"concept:orange", "entity:orange"}
    assert (root / "wiki" / "concepts" / "orange.md").exists()
    assert (root / "wiki" / "entities" / "orange.md").exists()

    assert main(["lint", "--root", str(root)]) == 0
    lint = capsys.readouterr().out
    assert "duplicate alias: 0" in lint
    assert "shared concept/entity alias: 1" in lint


def test_add_runs_llm_ingest_apply_and_summarizes_result(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source = write_source(root)
    patch_llm_proposal(monkeypatch)
    capsys.readouterr()

    assert main(["add", str(source), "--root", str(root)]) == 0
    out = capsys.readouterr().out

    source_id = rows(root, "select source_id from sources")[0]["source_id"]
    run_rows = rows(root, "select run_id, status, applied_at from ingest_runs")
    assert len(run_rows) == 1
    run_id = run_rows[0]["run_id"]

    assert f"Added source: {source_id}" in out
    assert "Processed with: llm" in out
    assert f"Applied run: {run_id}" in out
    assert "Claims: 2" in out
    assert "Patches: 2" in out
    assert "Pages:" in out
    assert f"wiki/sources/{source_id}.md" in out
    assert "wiki/concepts/autonomous-add.md" in out
    assert "Warnings: none" in out

    run_dir = root / "staging" / run_id
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "applied"
    assert manifest["trigger"] == "add"
    assert manifest["proposal_engine"] == "llm"
    assert run_rows[0]["status"] == "applied"
    assert run_rows[0]["applied_at"]

    assert (root / "wiki" / "sources" / f"{source_id}.md").exists()
    assert (root / "wiki" / "concepts" / "autonomous-add.md").exists()
    assert rows(root, "select claim_id from claims")
    assert rows(root, "select path from pages where page_type = 'source'")
    assert rows(root, "select path from pages where page_type = 'concept'")
    link_rows = rows(root, "select from_page, to_page from links order by from_page, to_page")
    assert link_rows
    assert {tuple(row) for row in link_rows} == {
        (source_id, "concept:autonomous-add"),
        ("concept:autonomous-add", source_id),
    }
    assert all(not row["from_page"].startswith("wiki/") for row in link_rows)
    assert all(not row["to_page"].startswith("wiki/") for row in link_rows)
    assert rows(root, "select relationship_type from relationships")
    assert f"Applied ingest run `{run_id}`" in (root / "wiki" / "log.md").read_text(encoding="utf-8")

    assert main(["review", run_id, "--root", str(root)]) == 0
    review = capsys.readouterr().out
    assert f"- status: applied" in review
    assert "Patches" in review


def test_add_duplicate_already_applied_source_is_noop(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source = write_source(root)
    patch_llm_proposal(monkeypatch)
    capsys.readouterr()

    assert main(["add", str(source), "--root", str(root)]) == 0
    capsys.readouterr()
    first_runs = rows(root, "select run_id from ingest_runs")
    first_pages = rows(root, "select page_id from pages")

    assert main(["add", str(source), "--root", str(root)]) == 0
    out = capsys.readouterr().out

    source_id = rows(root, "select source_id from sources")[0]["source_id"]
    assert f"Source already imported: {source_id}" in out
    assert "Wiki is already up to date for this source." in out
    assert rows(root, "select run_id from ingest_runs") == first_runs
    assert rows(root, "select page_id from pages") == first_pages


def test_add_requires_llm_without_leaking_secrets(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    disable_llm(root)
    source = write_source(root)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-should-not-print-this")
    monkeypatch.setenv("OTHER_SECRET", "sk-other-do-not-print-this")
    before_wiki = {
        path.relative_to(root / "wiki").as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((root / "wiki").rglob("*.md"))
    }
    capsys.readouterr()

    assert main(["add", str(source), "--root", str(root)]) == 1
    out = capsys.readouterr().out

    assert "Add pipeline failed at: ingest" in out
    assert "LLM ingest is required" in out
    assert "sk-env-should-not-print-this" not in out
    assert "sk-other-do-not-print-this" not in out
    assert not rows(root, "select claim_id from claims")
    assert not rows(root, "select run_id from ingest_runs")
    after_wiki = {
        path.relative_to(root / "wiki").as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((root / "wiki").rglob("*.md"))
    }
    assert after_wiki == before_wiki


def test_add_marks_run_failed_when_apply_rejects_patch(monkeypatch, capsys):
    from llmwiki.apply import UnsafePatchError

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source = write_source(root)
    patch_llm_proposal(monkeypatch)

    def reject_patch(*args, **kwargs):
        raise UnsafePatchError("forced unsafe patch for test")

    monkeypatch.setattr("llmwiki.apply.validate_patch", reject_patch)
    before_wiki = {
        path.relative_to(root / "wiki").as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((root / "wiki").rglob("*.md"))
    }
    capsys.readouterr()

    assert main(["add", str(source), "--root", str(root)]) == 1
    out = capsys.readouterr().out

    assert "Add pipeline failed at: apply" in out
    assert "forced unsafe patch for test" in out
    assert "Debug: llmwiki review " in out
    run_dir = next((root / "staging").glob("run_*"))
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["trigger"] == "add"
    assert manifest["failed_stage"] == "apply"
    assert "forced unsafe patch for test" in manifest["failure_reason"]
    assert not rows(root, "select claim_id from claims")
    assert not rows(root, "select run_id from ingest_runs")
    after_wiki = {
        path.relative_to(root / "wiki").as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((root / "wiki").rglob("*.md"))
    }
    assert after_wiki == before_wiki
