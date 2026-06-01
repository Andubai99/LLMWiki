from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.pdf_parser_backends import MinerUBackend, PdfParseRequest, PdfParserBackendError


def request_for(output_dir: Path) -> PdfParseRequest:
    return PdfParseRequest(
        root=Path("."),
        source_id="src_mineru",
        raw_path=Path("sources/raw/src_mineru-paper.pdf"),
        filename="paper.pdf",
        normalized_path="sources/normalized/src_mineru.md",
        metadata_path="sources/metadata/src_mineru.json",
        blocks_path="sources/blocks/src_mineru.jsonl",
        chunks_path="sources/chunks/src_mineru.jsonl",
        content=b"%PDF fake",
        options={"parser_output_dir": str(output_dir)},
    )


def test_mineru_adapter_maps_content_list_blocks():
    fixture = Path("tests/fixtures/mineru")

    result = MinerUBackend(output_dir=fixture).parse(request_for(fixture))

    assert result.backend_name == "mineru"
    assert result.metadata.title == "MinerU Structured Parsing Paper"
    assert result.metadata.parser_backend == "mineru"
    assert result.metadata.page_count == 3
    assert result.metadata.parser_artifact_paths == ["tests/fixtures/mineru/content_list.json"]
    assert result.metadata.structured_block_counts["table_like"] == 1
    assert result.metadata.structured_block_counts["equation_like"] == 1
    assert result.metadata.structured_block_counts["caption"] == 1

    title_block = next(block for block in result.blocks if block.block_type == "title")
    assert title_block.backend_type == "text"
    by_type = {block.backend_type: block for block in result.blocks if block.backend_type != "text"}
    assert by_type["table"].content_role == "table_like"
    assert by_type["table"].table_markdown.startswith("| Task | Accuracy |")
    assert by_type["equation"].content_role == "equation_like"
    assert by_type["equation"].latex == "E = mc^2"
    assert by_type["image"].content_role == "caption"
    assert by_type["image"].asset_path == "images/fig1.png"


def test_mineru_adapter_marks_headers_footers_and_page_numbers_ignored():
    fixture = Path("tests/fixtures/mineru")

    result = MinerUBackend(output_dir=fixture).parse(request_for(fixture))

    ignored = [block for block in result.blocks if block.content_role == "ignored"]
    assert {block.backend_type for block in ignored} == {"header", "footer", "page_number"}


def test_mineru_adapter_assigns_deterministic_page_block_ids_and_bbox():
    fixture = Path("tests/fixtures/mineru")

    result = MinerUBackend(output_dir=fixture).parse(request_for(fixture))

    assert result.blocks[0].block_id == "src_mineru_p001_b0001"
    assert result.blocks[3].block_id == "src_mineru_p002_b0001"
    assert result.blocks[3].page_start == 2
    assert result.blocks[3].bbox == [15, 100, 520, 240]
    assert result.blocks[3].backend_ref == "content_list:3"


def test_mineru_adapter_rejects_malformed_content_list(tmp_path):
    (tmp_path / "content_list.json").write_text('{"not": "a list"}', encoding="utf-8")

    with pytest.raises(PdfParserBackendError, match="content_list.json must contain a list"):
        MinerUBackend(output_dir=tmp_path).parse(request_for(tmp_path))


def test_precomputed_output_dir_does_not_invoke_mineru_runner(monkeypatch):
    fixture = Path("tests/fixtures/mineru")
    monkeypatch.setattr(
        "llmwiki.mineru_runner.run_mineru_command",
        lambda request: (_ for _ in ()).throw(AssertionError("precomputed output must not invoke MinerU")),
    )

    result = MinerUBackend(output_dir=fixture).parse(request_for(fixture))

    assert result.metadata.parser_backend == "mineru"
