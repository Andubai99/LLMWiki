from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from llmwiki.cli import main
from llmwiki.llm_ingest import create_llm_ingest_proposal
from llmwiki.pdf_blocks import SourceBlock, write_blocks_jsonl
from llmwiki.source_chunks import build_source_chunks, write_chunks_jsonl
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


def table_caption_blocks(source_id: str) -> tuple[SourceBlock, SourceBlock, SourceBlock, SourceBlock]:
    heading = SourceBlock(
        source_id=source_id,
        block_id=f"{source_id}_p004_b0010",
        block_type="section_heading",
        page_start=4,
        page_end=4,
        order=10,
        text_raw="Results",
        text_clean="Results",
        section_path=["Results"],
    )
    result_text = SourceBlock(
        source_id=source_id,
        block_id=f"{source_id}_p004_b0011",
        block_type="paragraph",
        page_start=4,
        page_end=4,
        order=11,
        text_raw="Table 1 reports MethodA accuracy on BenchmarkX.",
        text_clean="Table 1 reports MethodA accuracy on BenchmarkX.",
        section_path=["Results"],
    )
    table = SourceBlock(
        source_id=source_id,
        block_id=f"{source_id}_p004_b0012",
        block_type="table",
        page_start=4,
        page_end=4,
        order=12,
        text_raw="Table 1",
        text_clean="Table 1: Main results.",
        section_path=["Results"],
        content_role="table_like",
        table_markdown="| Method | Dataset | Accuracy |\n| MethodA | BenchmarkX | 92.3% |",
    )
    caption = SourceBlock(
        source_id=source_id,
        block_id=f"{source_id}_p004_b0013",
        block_type="caption",
        page_start=4,
        page_end=4,
        order=13,
        text_raw="Table 1: Main result on BenchmarkX.",
        text_clean="Table 1: Main result on BenchmarkX.",
        section_path=["Results"],
        content_role="caption",
    )
    return heading, result_text, table, caption


class TableCaptionMetricProvider:
    def __init__(
        self,
        *,
        table_id: str,
        caption_id: str,
        raw_value: str = "92.3%",
        method: str = "MethodA",
        dataset: str = "BenchmarkX",
        task: str = "desktop task",
    ) -> None:
        self.table_id = table_id
        self.caption_id = caption_id
        self.raw_value = raw_value
        self.method = method
        self.dataset = dataset
        self.task = task

    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
        user = messages[-1]["content"]
        if "PDF consolidation" in user:
            payload = {
                "claims": [],
                "concept": {"title": "Metric Paper", "aliases": []},
                "entity": None,
                "duplicate_candidates": [],
                "conflict_candidates": [],
                "source_summary": "Metric paper summary.",
                "concept_definition": "Metric paper concept.",
            }
        elif self.table_id in user:
            claim_text = "MethodA reports 92.3% accuracy on BenchmarkX."
            payload = {
                "claims": [
                    {
                        "claim_text": claim_text,
                        "citation_locator": f"block:{self.table_id}",
                        "confidence_status": "cited",
                    }
                ],
                "metric_result_candidates": [
                    {
                        "claim_text": claim_text,
                        "citation_locator": f"block:{self.table_id}",
                        "confidence_status": "cited",
                        "evidence_block_ids": [self.table_id, self.caption_id],
                        "extraction_origin": "table",
                        "method": self.method,
                        "dataset": self.dataset,
                        "task": self.task,
                        "metric_name": "accuracy",
                        "metric_raw_value": self.raw_value,
                        "metric_direction": "higher_is_better",
                        "baseline": "",
                        "comparison_value": "",
                        "setting": "main split",
                        "is_main_result": True,
                        "warnings": [],
                    }
                ],
                "chunk_summary": "Table result chunk.",
            }
        else:
            payload = {"claims": [], "metric_result_candidates": [], "chunk_summary": "No table result."}
        return {"provider": "fake", "model": "fake-pdf", "content": json.dumps(payload), "usage": {}}


def test_pdf_chunked_ingest_preserves_auxiliary_table_caption_evidence(monkeypatch, capsys) -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", lambda content: ({"title": "Metric Paper"}, ["Metric Paper"]))
    pdf = root / "metric-paper.pdf"
    pdf.write_bytes(b"%PDF fake")
    imported = import_source(root, str(pdf))
    blocks = list(table_caption_blocks(imported.source_id))
    write_blocks_jsonl(root / "sources" / "blocks" / f"{imported.source_id}.jsonl", blocks)
    write_chunks_jsonl(root / "sources" / "chunks" / f"{imported.source_id}.jsonl", build_source_chunks(imported.source_id, blocks))
    table = blocks[2]
    caption = blocks[3]
    provider = TableCaptionMetricProvider(table_id=table.block_id, caption_id=caption.block_id)
    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: provider)

    proposal = create_llm_ingest_proposal(
        root,
        source_row(root, imported.source_id),
        (root / imported.normalized_path).read_text(encoding="utf-8"),
    )

    assert len(proposal.metric_results) == 1
    result = proposal.metric_results[0]
    assert result["evidence_block_ids"] == [table.block_id, caption.block_id]
    assert result["evidence_block_roles"] == ["table", "caption"]
    assert result["metric_value"] == "92.3"


def test_pdf_chunked_ingest_drops_placeholder_metric_value_when_table_has_concrete_value(monkeypatch, capsys) -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", lambda content: ({"title": "Metric Paper"}, ["Metric Paper"]))
    pdf = root / "metric-paper.pdf"
    pdf.write_bytes(b"%PDF fake")
    imported = import_source(root, str(pdf))
    blocks = list(table_caption_blocks(imported.source_id))
    write_blocks_jsonl(root / "sources" / "blocks" / f"{imported.source_id}.jsonl", blocks)
    write_chunks_jsonl(root / "sources" / "chunks" / f"{imported.source_id}.jsonl", build_source_chunks(imported.source_id, blocks))
    table = blocks[2]
    caption = blocks[3]
    provider = TableCaptionMetricProvider(table_id=table.block_id, caption_id=caption.block_id, raw_value="See Table 1")
    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: provider)

    proposal = create_llm_ingest_proposal(
        root,
        source_row(root, imported.source_id),
        (root / imported.normalized_path).read_text(encoding="utf-8"),
    )

    assert proposal.claims
    assert proposal.metric_results == []


def test_pdf_chunked_ingest_drops_empty_metric_value_candidates(monkeypatch, capsys) -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", lambda content: ({"title": "Metric Paper"}, ["Metric Paper"]))
    pdf = root / "metric-paper.pdf"
    pdf.write_bytes(b"%PDF fake")
    imported = import_source(root, str(pdf))
    blocks = list(table_caption_blocks(imported.source_id))
    write_blocks_jsonl(root / "sources" / "blocks" / f"{imported.source_id}.jsonl", blocks)
    write_chunks_jsonl(root / "sources" / "chunks" / f"{imported.source_id}.jsonl", build_source_chunks(imported.source_id, blocks))
    table = blocks[2]
    caption = blocks[3]
    provider = TableCaptionMetricProvider(table_id=table.block_id, caption_id=caption.block_id, raw_value="")
    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: provider)

    proposal = create_llm_ingest_proposal(
        root,
        source_row(root, imported.source_id),
        (root / imported.normalized_path).read_text(encoding="utf-8"),
    )

    assert proposal.claims
    assert proposal.metric_results == []


def test_pdf_chunked_ingest_drops_candidates_missing_core_result_fields(monkeypatch, capsys) -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", lambda content: ({"title": "Metric Paper"}, ["Metric Paper"]))
    pdf = root / "metric-paper.pdf"
    pdf.write_bytes(b"%PDF fake")
    imported = import_source(root, str(pdf))
    blocks = list(table_caption_blocks(imported.source_id))
    write_blocks_jsonl(root / "sources" / "blocks" / f"{imported.source_id}.jsonl", blocks)
    write_chunks_jsonl(root / "sources" / "chunks" / f"{imported.source_id}.jsonl", build_source_chunks(imported.source_id, blocks))
    table = blocks[2]
    caption = blocks[3]
    provider = TableCaptionMetricProvider(table_id=table.block_id, caption_id=caption.block_id, dataset="")
    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: provider)

    proposal = create_llm_ingest_proposal(
        root,
        source_row(root, imported.source_id),
        (root / imported.normalized_path).read_text(encoding="utf-8"),
    )

    assert proposal.claims
    assert proposal.metric_results == []
