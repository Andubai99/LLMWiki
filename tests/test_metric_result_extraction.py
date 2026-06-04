from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from llmwiki.cli import main
from llmwiki.llm_ingest import create_llm_ingest_proposal
from llmwiki.source_chunks import load_chunks_jsonl
from llmwiki.sources import import_source
from tests.helpers import make_workspace


def source_row(root: Path, source_id: str) -> dict[str, str]:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select * from sources where source_id = ?", (source_id,)).fetchone()
        return dict(row)


class MetricResultProvider:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(messages)
        user = messages[-1]["content"]
        if "PDF consolidation" in user:
            payload = {
                "claims": [
                    {
                        "claim_text": "This consolidation result must be ignored.",
                        "citation_locator": "block:not_real",
                        "confidence_status": "cited",
                    }
                ],
                "metric_result_candidates": [
                    {
                        "claim_text": "This consolidation metric result must be ignored.",
                        "citation_locator": "block:not_real",
                        "confidence_status": "cited",
                        "metric_name": "accuracy",
                        "metric_raw_value": "100%",
                    }
                ],
                "concept": {"title": "Metric Paper", "aliases": []},
                "entity": None,
                "duplicate_candidates": [],
                "conflict_candidates": [],
                "source_summary": "Metric paper summary.",
                "concept_definition": "Metric paper concept.",
            }
        else:
            block_ids = re.findall(r"block:([A-Za-z0-9_.-]+)", user)
            block_id = block_ids[-1]
            claim_text = "MethodA reports 92.3% accuracy on BenchmarkX."
            payload = {
                "claims": [
                    {
                        "claim_text": claim_text,
                        "citation_locator": f"block:{block_id}",
                        "confidence_status": "cited",
                    }
                ],
                "metric_result_candidates": [
                    {
                        "claim_text": claim_text,
                        "citation_locator": f"block:{block_id}",
                        "confidence_status": "cited",
                        "extraction_origin": "table",
                        "method": "MethodA",
                        "dataset": "BenchmarkX",
                        "task": "desktop task",
                        "metric_name": "accuracy",
                        "metric_raw_value": "92.3%",
                        "metric_direction": "higher_is_better",
                        "baseline": "",
                        "comparison_value": "",
                        "setting": "main split",
                        "is_main_result": True,
                        "warnings": [],
                    }
                ],
                "chunk_summary": "Metric result chunk.",
            }
        return {"provider": "fake", "model": "fake-pdf", "content": json.dumps(payload), "usage": {}}


def test_pdf_chunked_ingest_extracts_metric_result_candidates(monkeypatch, capsys) -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    monkeypatch.setattr(
        "llmwiki.pdf_blocks.read_pdf_pages",
        lambda content: (
            {"title": "Metric Paper"},
            [
                "Metric Paper\n\n"
                "Abstract\n"
                "MethodA reports 92.3% accuracy on BenchmarkX.\n\n"
                "2 Results\n"
                "Table 1: MethodA reports 92.3% accuracy on BenchmarkX.\n",
            ],
        ),
    )
    pdf = root / "metric-paper.pdf"
    pdf.write_bytes(b"%PDF fake")
    imported = import_source(root, str(pdf))
    chunks = load_chunks_jsonl(root / "sources" / "chunks" / f"{imported.source_id}.jsonl")
    assert chunks

    provider = MetricResultProvider()
    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: provider)
    normalized_text = (root / imported.normalized_path).read_text(encoding="utf-8")

    proposal = create_llm_ingest_proposal(root, source_row(root, imported.source_id), normalized_text)

    assert proposal is not None
    assert proposal.metric_results
    assert all(result["schema_version"] == "metric_result_claim.v4.3" for result in proposal.metric_results)
    assert all(result["claim_id"].startswith(f"clm_{imported.source_id}_llm_") for result in proposal.metric_results)
    assert all("page:" in result["citation_locator"] and "block:" in result["citation_locator"] for result in proposal.metric_results)
    assert all(result["metric_name"] == "accuracy" for result in proposal.metric_results)
    assert all(result["metric_value"] == "92.3" for result in proposal.metric_results)
    assert not any("consolidation" in result["claim_text"].casefold() for result in proposal.metric_results)

    prompts = "\n".join(call[-1]["content"] for call in provider.calls[:-1])
    assert "metric_result_candidates" in prompts
    assert "abstract" in prompts.casefold()
    assert "tables" in prompts.casefold()
    assert "captions" in prompts.casefold()
    assert "conclusion" in prompts.casefold()
