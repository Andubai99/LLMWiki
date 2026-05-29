from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.ingest import Claim, find_conflict_candidates
from llmwiki.llm_ingest import LLMIngestProposal
from llmwiki.sources import import_source
from tests.helpers import make_workspace


def claim(text: str, claim_id: str = "clm_src_neg_001") -> Claim:
    return Claim(
        claim_id=claim_id,
        source_id="src_neg",
        claim_text=text,
        citation_locator="line:3;paragraph:1",
        confidence_status="cited",
        created_at="2026-05-29T00:00:00+00:00",
    )


def test_negative_and_caution_claims_are_not_conflict_candidates():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    claims = [
        claim("草莓不耐储存。", "clm_src_neg_001"),
        claim("香蕉不建议需要控制血糖的人多吃。", "clm_src_neg_002"),
        claim("食用前不需要提前清洗。", "clm_src_neg_003"),
        claim("This workflow does not require citation anchors.", "clm_src_neg_004"),
    ]

    assert find_conflict_candidates(root, claims) == []


def test_llm_conflict_notes_do_not_create_formal_contradicts(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source = root / "conflict-note.md"
    source.write_text(
        "# Conflict Note\n\n"
        "RAG systems should preserve citation anchors for audit review.\n",
        encoding="utf-8",
    )
    source_id = import_source(root, str(source)).source_id

    def fake_create(root: Path, source: dict[str, str], normalized_text: str) -> LLMIngestProposal:
        return LLMIngestProposal(
            claims=[
                {
                    "claim_id": f"clm_{source['source_id']}_llm_001",
                    "source_id": source["source_id"],
                    "claim_text": "RAG systems should preserve citation anchors for audit review.",
                    "citation_locator": "line:3;paragraph:1",
                    "confidence_status": "cited",
                }
            ],
            concept_title="Retrieval Augmented Generation",
            aliases=["RAG"],
            entity_title=None,
            entity_aliases=[],
            duplicate_candidates=[],
            conflict_candidates=["Potential conflict requires review, but no opposing claim id was provided."],
            source_summary="RAG evidence should stay auditable.",
            concept_definition="Retrieval augmented generation links answers to source-backed evidence.",
            provider="openai",
            model="test",
            raw_content="{}",
            usage={},
        )

    monkeypatch.setattr("llmwiki.ingest.create_llm_ingest_proposal", fake_create)

    assert main(["ingest", source_id, "--root", str(root)]) == 0
    run_id = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()
    run_dir = root / "staging" / run_id

    triage = (run_dir / "triage.md").read_text(encoding="utf-8")
    assert "Potential conflict requires review" in triage

    patches = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((run_dir / "patches").glob("*.json"))]
    relationships = [relationship for patch in patches for relationship in patch.get("relationships", [])]
    assert relationships
    assert all(relationship["relationship_type"] != "contradicts" for relationship in relationships)


def test_lint_does_not_infer_unresolved_contradiction_from_negation(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.executemany(
            """
            insert into claims (claim_id, source_id, claim_text, citation_locator, confidence_status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "clm_a",
                    "src_a",
                    "RAG systems require citation anchors.",
                    "line:1",
                    "cited",
                    "2026-05-29T00:00:00+00:00",
                ),
                (
                    "clm_b",
                    "src_b",
                    "RAG systems do not require citation anchors.",
                    "line:1",
                    "cited",
                    "2026-05-29T00:00:00+00:00",
                ),
            ],
        )

    assert main(["lint", "--root", str(root)]) == 0
    lint = capsys.readouterr().out
    assert "recorded contradicts relationships: 0" in lint
    assert "unresolved potential contradictions: 0" in lint
