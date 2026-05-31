from __future__ import annotations

from llmwiki.pdf_blocks import SourceBlock
from llmwiki.source_chunks import (
    CHUNK_SCHEMA_VERSION,
    build_source_chunks,
    estimate_tokens,
)


def block(
    order: int,
    block_type: str,
    text: str,
    section_path: list[str] | None = None,
) -> SourceBlock:
    return SourceBlock(
        source_id="src_pdf",
        block_id=f"src_pdf_p001_b{order:04d}",
        block_type=block_type,
        page_start=1,
        page_end=1,
        order=order,
        text_raw=text,
        text_clean=text,
        section_path=section_path or [],
    )


def test_chunker_builds_section_aware_chunks_without_llm():
    blocks = [
        block(1, "title", "OSWorld: Benchmarking Multimodal Agents"),
        block(2, "authors", "Alice Example"),
        block(3, "section_heading", "Abstract", ["Abstract"]),
        block(4, "abstract", "OSWorld evaluates computer-use agents.", ["Abstract"]),
        block(5, "section_heading", "Introduction", ["Introduction"]),
        block(6, "paragraph", "The benchmark includes desktop tasks.", ["Introduction"]),
        block(7, "section_heading", "Conclusion", ["Conclusion"]),
        block(8, "paragraph", "Agents remain far behind human performance.", ["Conclusion"]),
    ]

    chunks = build_source_chunks("src_pdf", blocks, target_tokens=30, max_tokens=60)

    assert chunks
    assert all(chunk.schema_version == CHUNK_SCHEMA_VERSION for chunk in chunks)
    assert chunks[0].chunk_type == "metadata_summary"
    assert chunks[0].block_ids == ["src_pdf_p001_b0001", "src_pdf_p001_b0002", "src_pdf_p001_b0004"]
    assert any(chunk.chunk_type == "section_claim_extraction" for chunk in chunks)
    assert all("src_pdf_p001_b0005" in chunk.context_block_ids for chunk in chunks if chunk.section_path == ["Introduction"])
    assert all(chunk.token_estimate <= 60 for chunk in chunks)


def test_chunker_splits_long_section_by_paragraph_order():
    blocks = [
        block(1, "title", "Long Paper"),
        block(2, "section_heading", "Method", ["Method"]),
        block(3, "paragraph", "A" * 120, ["Method"]),
        block(4, "paragraph", "B" * 120, ["Method"]),
        block(5, "paragraph", "C" * 120, ["Method"]),
    ]

    chunks = build_source_chunks("src_pdf", blocks, target_tokens=40, max_tokens=80)
    method_chunks = [chunk for chunk in chunks if chunk.section_path == ["Method"]]

    assert len(method_chunks) >= 2
    assert all(chunk.chunk_type == "long_section_part" for chunk in method_chunks)
    flattened = [block_id for chunk in method_chunks for block_id in chunk.block_ids]
    assert flattened == ["src_pdf_p001_b0003", "src_pdf_p001_b0004", "src_pdf_p001_b0005"]


def test_chunker_marks_single_huge_block_without_crossing_sections():
    huge = "X" * 800
    blocks = [
        block(1, "title", "Huge Block Paper"),
        block(2, "section_heading", "Results", ["Results"]),
        block(3, "paragraph", huge, ["Results"]),
    ]

    chunks = build_source_chunks("src_pdf", blocks, target_tokens=40, max_tokens=80)
    huge_chunks = [chunk for chunk in chunks if chunk.chunk_type == "large_block_split"]

    assert huge_chunks
    assert huge_chunks[0].block_ids == ["src_pdf_p001_b0003"]
    assert "large_block_split" in huge_chunks[0].warnings


def test_estimate_tokens_uses_four_character_rule():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
