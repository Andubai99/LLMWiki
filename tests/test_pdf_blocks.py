from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.pdf_blocks import (
    BLOCK_SCHEMA_VERSION,
    METADATA_SCHEMA_VERSION,
    load_blocks_jsonl,
    load_metadata_json,
    parse_pdf_source,
    render_normalized_markdown_from_blocks,
)


def test_parse_pdf_uses_metadata_title_and_skips_page_marker(monkeypatch, tmp_path: Path):
    def fake_read_pdf_pages(content: bytes):
        assert content == b"%PDF fake"
        return (
            {"title": "OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks"},
            [
                "<!-- page:1 -->\n"
                "OSW ORLD: Benchmarking Multimodal Agents for Open-Ended Tasks\n"
                "Alice Example, Bob Example\n\n"
                "Abstract\n"
                "This paper studies open-ended computer-use agents and reports a signif-\n"
                "icantly lower success rate than humans.\n\n"
                "1 Introduction\n"
                "OSWorld evaluates agents on real desktop tasks.\n\n"
                "References\n"
                "[1] Related work.\n"
            ],
        )

    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", fake_read_pdf_pages)

    result = parse_pdf_source(
        source_id="src_osworld",
        content=b"%PDF fake",
        filename="osworld.pdf",
        raw_path="sources/raw/src_osworld-osworld.pdf",
        normalized_path="sources/normalized/src_osworld.md",
        metadata_path="sources/metadata/src_osworld.json",
        blocks_path="sources/blocks/src_osworld.jsonl",
        chunks_path="sources/chunks/src_osworld.jsonl",
    )

    assert result.metadata.title == "OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks"
    assert result.metadata.schema_version == "source_metadata.v2.9.2"
    assert result.metadata.title_quality["selected_source"] == "metadata"
    assert result.metadata.title_candidates
    assert result.metadata.paper_identity["title"] == result.metadata.title
    assert result.metadata.parser_quality["page_count"] == 1
    assert result.metadata.title != "<!-- page:1 -->"
    assert result.metadata.page_count == 1
    assert result.metadata.metadata_path == "sources/metadata/src_osworld.json"
    assert result.metadata.blocks_path == "sources/blocks/src_osworld.jsonl"
    assert result.metadata.chunks_path == "sources/chunks/src_osworld.jsonl"

    block_ids = [block.block_id for block in result.blocks]
    assert block_ids[0] == "src_osworld_p001_b0001"
    assert block_ids == sorted(block_ids)

    block_types = {block.block_type for block in result.blocks}
    assert {"title", "authors", "abstract", "section_heading", "paragraph", "reference"} <= block_types
    assert all(block.text_raw for block in result.blocks)
    assert all(block.text_clean for block in result.blocks)
    assert all(block.schema_version == "source_block.v2.9.2" for block in result.blocks)
    assert all(block.content_role for block in result.blocks)
    assert all(isinstance(block.cleaning_operations, list) for block in result.blocks)
    assert all(isinstance(block.quality_flags, list) for block in result.blocks)
    assert not any(block.text_clean.startswith("<!-- page:") for block in result.blocks)
    assert any("significantly lower success rate" in block.text_clean for block in result.blocks)


def test_parse_pdf_falls_back_to_clean_first_page_title_and_records_warnings(monkeypatch):
    def fake_read_pdf_pages(content: bytes):
        return (
            {},
            [
                "<!-- page:1 -->\n"
                "OSW ORLD: Benchmarking Multimodal Agents\n"
                "Alice Example, Bob Example\n\n"
                "Abstract\n"
                "OSW ORLD evaluates computer-use agents.\n"
            ],
        )

    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", fake_read_pdf_pages)

    result = parse_pdf_source(
        source_id="src_osworld",
        content=b"%PDF fake",
        filename="osworld.pdf",
        raw_path="sources/raw/src_osworld-osworld.pdf",
        normalized_path="sources/normalized/src_osworld.md",
        metadata_path="sources/metadata/src_osworld.json",
        blocks_path="sources/blocks/src_osworld.jsonl",
        chunks_path="sources/chunks/src_osworld.jsonl",
    )

    assert result.metadata.title == "OSWorld: Benchmarking Multimodal Agents"
    assert any("OSW ORLD" in warning and "OSWorld" in warning for warning in result.metadata.warnings)


def test_parse_pdf_title_scoring_ignores_noisy_metadata_and_first_page_status(monkeypatch):
    def fake_read_pdf_pages(content: bytes):
        return (
            {"title": "Published as a conference paper at ICLR 2025"},
            [
                "Published as a conference paper at ICLR 2025\n"
                "Alice Example, Bob Example, Carol Example, David Example\n"
                "A Clean Benchmark Title for Computer-Use Agents\n\n"
                "Abstract\n"
                "The paper introduces a benchmark.\n"
            ],
        )

    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", fake_read_pdf_pages)

    result = parse_pdf_source(
        source_id="src_clean",
        content=b"%PDF fake",
        filename="clean.pdf",
        raw_path="sources/raw/src_clean-clean.pdf",
        normalized_path="sources/normalized/src_clean.md",
        metadata_path="sources/metadata/src_clean.json",
        blocks_path="sources/blocks/src_clean.jsonl",
        chunks_path="sources/chunks/src_clean.jsonl",
    )

    assert result.metadata.title == "A Clean Benchmark Title for Computer-Use Agents"
    assert result.metadata.title_quality["selected_source"] == "block"
    assert any("venue_or_status_line" in candidate["reasons"] for candidate in result.metadata.title_candidates)


def test_v2_9_1_sidecars_load_with_v2_9_2_defaults(tmp_path: Path):
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        """{
  "source_id": "src_old",
  "title": "Old PDF",
  "source_type": "pdf",
  "page_count": 1,
  "raw_path": "sources/raw/src_old.pdf",
  "normalized_path": "sources/normalized/src_old.md",
  "metadata_path": "sources/metadata/src_old.json",
  "blocks_path": "sources/blocks/src_old.jsonl",
  "chunks_path": "sources/chunks/src_old.jsonl",
  "filename": "old.pdf",
  "schema_version": "source_metadata.v2.9.1"
}
""",
        encoding="utf-8",
    )
    blocks_path = tmp_path / "blocks.jsonl"
    blocks_path.write_text(
        """{"source_id":"src_old","block_id":"src_old_p001_b0001","block_type":"title","page_start":1,"page_end":1,"order":1,"text_raw":"Old PDF","text_clean":"Old PDF","schema_version":"source_block.v2.9.1"}\n""",
        encoding="utf-8",
    )

    metadata = load_metadata_json(metadata_path)
    blocks = load_blocks_jsonl(blocks_path)

    assert metadata.schema_version == "source_metadata.v2.9.1"
    assert metadata.title_quality["status"] == "legacy"
    assert metadata.title_candidates == []
    assert metadata.paper_identity["title"] == "Old PDF"
    assert metadata.parser_quality["block_count"] == 0
    assert blocks[0].schema_version == "source_block.v2.9.1"
    assert blocks[0].content_role == "content"
    assert blocks[0].cleaning_operations == []
    assert blocks[0].quality_flags == []
    assert METADATA_SCHEMA_VERSION == "source_metadata.v2.9.2"
    assert BLOCK_SCHEMA_VERSION == "source_block.v2.9.2"


def test_render_normalized_markdown_from_blocks_includes_block_anchors(monkeypatch):
    def fake_read_pdf_pages(content: bytes):
        return (
            {"title": "OSWorld: Benchmarking Multimodal Agents"},
            [
                "OSWorld: Benchmarking Multimodal Agents\n"
                "Alice Example\n\n"
                "Abstract\n"
                "OSWorld evaluates agents.\n\n"
                "2 Method\n"
                "The benchmark includes desktop tasks.\n",
            ],
        )

    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", fake_read_pdf_pages)
    result = parse_pdf_source(
        source_id="src_osworld",
        content=b"%PDF fake",
        filename="osworld.pdf",
        raw_path="sources/raw/src_osworld-osworld.pdf",
        normalized_path="sources/normalized/src_osworld.md",
        metadata_path="sources/metadata/src_osworld.json",
        blocks_path="sources/blocks/src_osworld.jsonl",
        chunks_path="sources/chunks/src_osworld.jsonl",
    )

    markdown = render_normalized_markdown_from_blocks(result.metadata, result.blocks)

    assert "page_count: 1" in markdown
    assert "metadata_path: sources/metadata/src_osworld.json" in markdown
    assert "blocks_path: sources/blocks/src_osworld.jsonl" in markdown
    assert "chunks_path: sources/chunks/src_osworld.jsonl" in markdown
    assert markdown.splitlines()[0] == "---"
    assert "# OSWorld: Benchmarking Multimodal Agents" in markdown
    assert "<!-- block:src_osworld_p001_b0001; page:1; type:title -->" in markdown
    assert "<!-- page:1 -->" not in markdown


def test_parse_pdf_requires_at_least_one_page(monkeypatch):
    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", lambda content: ({}, []))

    with pytest.raises(ValueError, match="No text pages"):
        parse_pdf_source(
            source_id="src_empty",
            content=b"%PDF fake",
            filename="empty.pdf",
            raw_path="sources/raw/src_empty-empty.pdf",
            normalized_path="sources/normalized/src_empty.md",
            metadata_path="sources/metadata/src_empty.json",
            blocks_path="sources/blocks/src_empty.jsonl",
            chunks_path="sources/chunks/src_empty.jsonl",
        )
