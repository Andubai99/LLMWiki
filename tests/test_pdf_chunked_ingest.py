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
