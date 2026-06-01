from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from llmwiki.cli import main
from llmwiki.llm_ingest import create_llm_ingest_proposal
from llmwiki.pdf_blocks import load_blocks_jsonl
from llmwiki.providers.base import LLMProviderError
from llmwiki.source_chunks import load_chunks_jsonl
from llmwiki.sources import import_source
from tests.helpers import make_workspace


class FakeChunkProvider:
    def __init__(self, chunks_by_prompt: dict[str, list[str]]):
        self.calls: list[list[dict[str, str]]] = []
        self.chunks_by_prompt = chunks_by_prompt

    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(messages)
        user = messages[-1]["content"]
        if "PDF consolidation" in user:
            content = {
                "claims": [
                    {
                        "claim_text": "This consolidation claim must be ignored.",
                        "citation_locator": "block:not_real",
                        "confidence_status": "cited",
                    }
                ],
                "concept": {"title": "OSWorld", "aliases": ["OSWorld"]},
                "entity": None,
                "duplicate_candidates": [],
                "conflict_candidates": [],
                "source_summary": "OSWorld is a benchmark for computer-use agents.",
                "concept_definition": "OSWorld is a benchmark for open-ended computer-use agents.",
            }
        else:
            block_ids = re.findall(r"block:([A-Za-z0-9_.-]+)", user)
            claim_block = block_ids[-1]
            content = {
                "claims": [
                    {
                        "claim_text": f"Claim extracted from {claim_block}.",
                        "citation_locator": f"block:{claim_block}",
                        "confidence_status": "cited",
                    }
                ],
                "chunk_summary": f"Summary for {claim_block}",
            }
        return {
            "provider": "fake",
            "model": "fake-pdf",
            "content": json.dumps(content),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }


def source_row(root: Path, source_id: str) -> dict[str, str]:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select * from sources where source_id = ?", (source_id,)).fetchone()
        return dict(row)


def test_pdf_source_uses_chunked_ingest_without_16k_truncation(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    def fake_read_pdf_pages(content: bytes):
        return (
            {"title": "OSWorld: Benchmarking Multimodal Agents"},
            [
                "OSWorld: Benchmarking Multimodal Agents\n"
                "Alice Example\n\n"
                "Abstract\n"
                "OSWorld evaluates computer-use agents.\n\n"
                "1 Introduction\n"
                "The benchmark includes desktop tasks.\n\n"
                "2 Results\n"
                "Agents lag humans on many tasks.\n",
            ],
        )

    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", fake_read_pdf_pages)
    pdf = root / "osworld.pdf"
    pdf.write_bytes(b"%PDF fake")
    result = import_source(root, str(pdf))

    blocks = load_blocks_jsonl(root / "sources" / "blocks" / f"{result.source_id}.jsonl")
    chunks = load_chunks_jsonl(root / "sources" / "chunks" / f"{result.source_id}.jsonl")
    assert len(chunks) >= 2
    fake_provider = FakeChunkProvider({})
    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: fake_provider)

    normalized_text = (root / result.normalized_path).read_text(encoding="utf-8")
    proposal = create_llm_ingest_proposal(root, source_row(root, result.source_id), normalized_text)

    assert proposal is not None
    assert proposal.provider == "fake"
    assert proposal.model == "fake-pdf"
    assert proposal.concept_title == "OSWorld"
    assert proposal.source_summary == "OSWorld is a benchmark for computer-use agents."
    assert all(claim["confidence_status"] == "cited" for claim in proposal.claims)
    assert all("block:" in claim["citation_locator"] and "page:" in claim["citation_locator"] for claim in proposal.claims)
    assert not any("consolidation claim" in claim["claim_text"].casefold() for claim in proposal.claims)
    assert proposal.usage["total_tokens"] == 15 * (len(chunks) + 1)

    chunk_calls = fake_provider.calls[:-1]
    assert len(chunk_calls) == len(chunks)
    for call, chunk in zip(chunk_calls, chunks, strict=True):
        prompt = call[-1]["content"]
        allowed = set(chunk.block_ids) | set(chunk.context_block_ids)
        prompt_block_ids = set(re.findall(r"block:([A-Za-z0-9_.-]+)", prompt))
        assert prompt_block_ids <= allowed
        assert prompt_block_ids


def test_pdf_chunk_prompts_exclude_ignored_blocks(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    monkeypatch.setattr(
        "llmwiki.pdf_blocks.read_pdf_pages",
        lambda content: (
            {"title": "Clean Paper"},
            [
                "Clean Paper\n\n"
                "Repeated Header\n\n"
                "1\n\n"
                "Abstract\n"
                "Useful first-page evidence.\n",
                "Repeated Header\n\n"
                "2\n\n"
                "2 Method\n"
                "Useful second-page evidence.\n",
            ],
        ),
    )
    pdf = root / "clean.pdf"
    pdf.write_bytes(b"%PDF fake")
    result = import_source(root, str(pdf))
    ignored_blocks = [
        block
        for block in load_blocks_jsonl(root / "sources" / "blocks" / f"{result.source_id}.jsonl")
        if block.content_role == "ignored"
    ]
    assert ignored_blocks

    fake_provider = FakeChunkProvider({})
    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: fake_provider)
    normalized_text = (root / result.normalized_path).read_text(encoding="utf-8")
    create_llm_ingest_proposal(root, source_row(root, result.source_id), normalized_text)

    ignored_ids = {block.block_id for block in ignored_blocks}
    prompts = "\n".join(call[-1]["content"] for call in fake_provider.calls[:-1])
    assert not any(block_id in prompts for block_id in ignored_ids)
    assert "Repeated Header" not in prompts
    assert "Useful first-page evidence." in prompts


def test_pdf_chunked_ingest_rejects_unknown_block_claims(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    monkeypatch.setattr(
        "llmwiki.pdf_blocks.read_pdf_pages",
        lambda content: (
            {"title": "Small PDF"},
            ["Small PDF\n\nAbstract\nKnown block text.\n"],
        ),
    )
    pdf = root / "small.pdf"
    pdf.write_bytes(b"%PDF fake")
    result = import_source(root, str(pdf))

    class UnknownBlockProvider:
        def complete(self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
            if "PDF consolidation" in messages[-1]["content"]:
                payload = {
                    "claims": [],
                    "concept": {"title": "Small PDF", "aliases": []},
                    "entity": None,
                    "duplicate_candidates": [],
                    "conflict_candidates": [],
                    "source_summary": "Small PDF summary.",
                    "concept_definition": "Small PDF concept.",
                }
            else:
                payload = {
                    "claims": [
                        {
                            "claim_text": "Unknown block claim.",
                            "citation_locator": "block:not_a_real_block",
                            "confidence_status": "cited",
                        }
                    ],
                    "chunk_summary": "Unknown block.",
                }
            return {"provider": "fake", "model": "fake-pdf", "content": json.dumps(payload), "usage": {}}

    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: UnknownBlockProvider())
    normalized_text = (root / result.normalized_path).read_text(encoding="utf-8")

    with pytest.raises(LLMProviderError, match="valid source locators"):
        create_llm_ingest_proposal(root, source_row(root, result.source_id), normalized_text)


def test_pdf_chunked_ingest_drops_uncited_chunk_claims_when_cited_claims_exist(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    monkeypatch.setattr(
        "llmwiki.pdf_blocks.read_pdf_pages",
        lambda content: (
            {"title": "Mixed Locator PDF"},
            ["Mixed Locator PDF\n\nAbstract\nKnown block text.\n"],
        ),
    )
    pdf = root / "mixed.pdf"
    pdf.write_bytes(b"%PDF fake")
    result = import_source(root, str(pdf))
    known_block_id = load_blocks_jsonl(root / "sources" / "blocks" / f"{result.source_id}.jsonl")[-1].block_id

    class MixedLocatorProvider:
        def complete(self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
            if "PDF consolidation" in messages[-1]["content"]:
                payload = {
                    "claims": [],
                    "concept": {"title": "Mixed Locator PDF", "aliases": []},
                    "entity": None,
                    "duplicate_candidates": [],
                    "conflict_candidates": [],
                    "source_summary": "Mixed locator summary.",
                    "concept_definition": "Mixed locator concept.",
                }
            else:
                payload = {
                    "claims": [
                        {
                            "claim_text": "Known block claim.",
                            "citation_locator": f"block:{known_block_id}",
                            "confidence_status": "cited",
                        },
                        {
                            "claim_text": "Unknown block claim should stay out of catalog.",
                            "citation_locator": "block:not_a_real_block",
                            "confidence_status": "cited",
                        },
                    ],
                    "chunk_summary": "Mixed locator.",
                }
            return {"provider": "fake", "model": "fake-pdf", "content": json.dumps(payload), "usage": {}}

    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: MixedLocatorProvider())
    normalized_text = (root / result.normalized_path).read_text(encoding="utf-8")

    proposal = create_llm_ingest_proposal(root, source_row(root, result.source_id), normalized_text)

    assert [claim["claim_text"] for claim in proposal.claims] == ["Known block claim."]
    assert proposal.claims[0]["confidence_status"] == "cited"


def test_pdf_add_exposes_parse_diagnostics_in_staging_and_source_page(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    monkeypatch.setattr(
        "llmwiki.pdf_blocks.read_pdf_pages",
        lambda content: (
            {"title": "OSWorld: Benchmarking Multimodal Agents"},
            [
                "OSWorld: Benchmarking Multimodal Agents\n"
                "Alice Example\n\n"
                "Abstract\n"
                "OSWorld evaluates computer-use agents.\n\n"
                "1 Introduction\n"
                "The benchmark includes desktop tasks.\n\n"
                "2 Results\n"
                "Agents lag humans on many tasks.\n",
            ],
        ),
    )
    fake_provider = FakeChunkProvider({})
    monkeypatch.setattr("llmwiki.llm_ingest.create_provider", lambda config, root=None: fake_provider)

    pdf = root / "osworld.pdf"
    pdf.write_bytes(b"%PDF fake")

    assert main(["add", str(pdf), "--root", str(root)]) == 0
    capsys.readouterr()

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        source = conn.execute("select * from sources where source_type = 'pdf'").fetchone()
        source_id = source["source_id"]
        run = conn.execute("select run_id from ingest_runs where source_id = ?", (source_id,)).fetchone()
        assert conn.execute("select count(*) from pages where page_type = 'paper'").fetchone()[0] == 0
    run_dir = root / "staging" / run["run_id"]
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["source_parse_schema"] == "source_block.v2.9.2"
    assert manifest["source_chunk_schema"] == "source_chunk.v2.9.2"
    assert manifest["title_quality"]["selected_source"] in {"metadata", "block"}
    assert manifest["parser_quality"]["page_count"] == 1
    assert manifest["page_count"] == 1
    assert manifest["block_count"] >= 5
    assert manifest["chunk_count"] >= 2

    triage = (run_dir / "triage.md").read_text(encoding="utf-8")
    assert "## PDF Parse Diagnostics" in triage
    assert "## Paper Metadata" in triage
    assert "## Parser Quality" in triage
    assert "title_candidates" in triage
    assert "- page_count: 1" in triage
    assert "- metadata_path: `sources/metadata/" in triage
    assert "- chunks_path: `sources/chunks/" in triage

    proposal = json.loads((run_dir / "llm-proposal.json").read_text(encoding="utf-8"))
    raw_content = json.loads(proposal["content"])
    assert raw_content["mode"] == "chunked_pdf"
    assert raw_content["chunk_count"] == manifest["chunk_count"]

    source_page = (root / "wiki" / "sources" / f"{source_id}.md").read_text(encoding="utf-8")
    assert "## Source Metadata" in source_page
    assert "## Paper Metadata" in source_page
    assert "## Parser Quality" in source_page
    assert "- page_count: `1`" in source_page
    assert f"- metadata_path: `sources/metadata/{source_id}.json`" in source_page
    assert f"- blocks_path: `sources/blocks/{source_id}.jsonl`" in source_page
    assert f"- chunks_path: `sources/chunks/{source_id}.jsonl`" in source_page
    assert "page:1;block:" in source_page
