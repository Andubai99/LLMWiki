from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from llmwiki.cli import main
from llmwiki.ingest import Claim, proposal_concept, slugify
from llmwiki.llm_ingest import LLMIngestProposal
from llmwiki.sources import import_source
from tests.helpers import disable_llm, make_workspace


def add_sample_source(root: Path) -> str:
    assert main(["init", "--root", str(root)]) == 0
    disable_llm(root)
    source = root / "minimal.md"
    source.write_text(
        "# Retrieval Notes\n\n"
        "Retrieval augmented generation links answers to source passages.\n"
        "RAG systems should preserve citation anchors.\n"
        "Contradiction markers should be preserved when sources conflict.\n",
        encoding="utf-8",
    )
    return import_source(root, str(source)).source_id


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
    catalog_before = (root / "state" / "catalog.sqlite").read_bytes()

    assert main(["review", run_id, "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert snapshot_tree(root / "wiki") == before
    assert (root / "state" / "catalog.sqlite").read_bytes() == catalog_before
    assert "Run information" in out
    assert f"- run_id: {run_id}" in out
    assert f"- source_id: {source_id}" in out
    assert "- status: staged" in out
    assert "- created_at:" in out
    assert "- claims:" in out
    assert "- patches:" in out
    assert "- citation_coverage:" in out
    assert "Triage summary" in out
    assert "Claims" in out
    assert "claim_id | status | citation | claim_text" in out
    assert "Patches" in out
    assert "target_path | page_type | title | aliases | claim_ids | change" in out
    assert "New pages:" in out
    assert "Updated pages:" in out
    assert "Duplicate candidates:" in out
    assert "Conflict candidates:" in out
    assert "Weak/uncited claims:" in out


def test_review_detail_shows_full_claims_and_triage(capsys):
    root = make_workspace()
    source_id = add_sample_source(root)
    assert main(["ingest", source_id, "--root", str(root)]) == 0
    run_id = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()

    assert main(["review", run_id, "--detail", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "Detailed claims" in out
    assert "Citation coverage detail" in out
    assert "Triage details" in out
    assert "Retrieval augmented generation links answers to source passages." in out
    assert "## Candidate Patches" in out


def test_review_subprocess_stdout_is_utf8_for_unicode_claims(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    disable_llm(root)
    source = root / "banana.md"
    source.write_text(
        "# 香蕉\n\n"
        "香蕉 适合 作为 日常 加餐，也 可以 快速 补充 能量。\n",
        encoding="utf-8",
    )
    source_id = import_source(root, str(source)).source_id
    assert main(["ingest", source_id, "--root", str(root)]) == 0
    run_id = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llmwiki",
            "review",
            run_id,
            "--detail",
            "--root",
            str(root),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    out = result.stdout.decode("utf-8")
    assert "香蕉 适合 作为 日常 加餐" in out
    assert "\ufffd" not in out


def test_review_patches_shows_candidate_markdown_content(capsys):
    root = make_workspace()
    source_id = add_sample_source(root)
    assert main(["ingest", source_id, "--root", str(root)]) == 0
    run_id = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()

    assert main(["review", run_id, "--patches", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "Patch contents" in out
    assert "### patches/" in out
    assert "```markdown" in out
    assert "## Source Metadata" in out
    assert "## Key Claims" in out


def test_ingest_filters_non_claim_lines_and_adds_rich_locators(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    disable_llm(root)
    source = root / "claim-quality.md"
    source.write_text(
        "# Claim Quality Notes\n\n"
        "- Topic: internal regression metadata.\n"
        "- Created for: testing claim filters.\n"
        "- Introduction\n"
        "- Scope\n\n"
        "## Retrieval Practice\n\n"
        "RAG systems should preserve citation anchors during review.\n"
        "Citation-aware review makes later synthesis auditable.\n",
        encoding="utf-8",
    )
    import_source(root, str(source))
    import sqlite3

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        source_id = conn.execute("select source_id from sources").fetchone()[0]
        normalized_path = conn.execute("select normalized_path from sources").fetchone()[0]
    normalized = (root / normalized_path).read_text(encoding="utf-8")
    assert "<!-- section:Retrieval Practice -->" in normalized
    assert "<!-- paragraph:" in normalized

    assert main(["ingest", source_id, "--root", str(root)]) == 0
    run_id = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()
    claims = [
        json.loads(line)
        for line in (root / "staging" / run_id / "claims.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    texts = [claim["claim_text"] for claim in claims]
    assert texts == [
        "RAG systems should preserve citation anchors during review.",
        "Citation-aware review makes later synthesis auditable.",
    ]
    assert all("line:" in claim["citation_locator"] for claim in claims)
    assert all("section:Retrieval Practice" in claim["citation_locator"] for claim in claims)
    assert all("paragraph:" in claim["citation_locator"] for claim in claims)
    assert all(claim["confidence_status"] == "cited" for claim in claims)


def test_slugify_preserves_unicode_title_text():
    assert slugify("草莓：酸甜可口的浆果类水果") == "草莓-酸甜可口的浆果类水果"
    assert slugify("橙子：富含维生素 C 的柑橘类水果") == "橙子-富含维生素-c-的柑橘类水果"


def test_proposal_concept_keeps_source_title_out_of_concept_aliases():
    source = {"title": "苹果：营养均衡的日常水果"}
    claims = [
        Claim(
            claim_id="clm_src_apple_llm_001",
            source_id="src_apple",
            claim_text="苹果 是 一种 常见 日常 水果。",
            citation_locator="line:1",
            confidence_status="cited",
            created_at="2026-05-26T00:00:00+00:00",
        )
    ]
    proposal = LLMIngestProposal(
        claims=[],
        concept_title="苹果：营养均衡的日常水果",
        aliases=["苹果", "苹果：营养均衡的日常水果"],
        entity_title=None,
        entity_aliases=[],
        duplicate_candidates=[],
        conflict_candidates=[],
        source_summary=None,
        concept_definition=None,
        provider="openai",
        model="test",
        raw_content="{}",
        usage={},
    )

    title, aliases = proposal_concept(source, claims, proposal)

    assert title == "苹果"
    assert aliases == ["苹果"]
