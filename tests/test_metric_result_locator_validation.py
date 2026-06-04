from __future__ import annotations

import pytest

from llmwiki.ingestion.metric_results import MetricResultValidationError, validate_pdf_result_locator
from llmwiki.pdf_blocks import SourceBlock


def block(
    block_id: str = "src_pdf_p004_b0012",
    *,
    page: int = 4,
    section_path: list[str] | None = None,
    block_type: str = "paragraph",
    content_role: str = "content",
) -> SourceBlock:
    return SourceBlock(
        source_id="src_pdf",
        block_id=block_id,
        block_type=block_type,
        page_start=page,
        page_end=page,
        order=12,
        text_raw="MethodA reaches 92.3% accuracy on BenchmarkX.",
        text_clean="MethodA reaches 92.3% accuracy on BenchmarkX.",
        section_path=section_path or ["Results"],
        content_role=content_role,
    )


def test_pdf_result_locator_normalizes_block_only_locator() -> None:
    source_block = block(block_type="table")
    validation = validate_pdf_result_locator(
        "block:src_pdf_p004_b0012",
        source_id="src_pdf",
        blocks_by_id={source_block.block_id: source_block},
        allowed_block_ids={source_block.block_id},
    )

    assert validation.valid is True
    assert validation.normalized_locator == "page:4;block:src_pdf_p004_b0012;section:Results"
    assert validation.evidence_block_ids == ["src_pdf_p004_b0012"]
    assert validation.evidence_pages == [4]
    assert validation.evidence_section_path == ["Results"]
    assert validation.evidence_block_roles == ["table"]
    assert validation.warnings == []


def test_pdf_result_locator_accepts_normalized_page_block_locator() -> None:
    source_block = block(section_path=["Experiments", "Main Results"])
    validation = validate_pdf_result_locator(
        "page:4;block:src_pdf_p004_b0012;section:Experiments",
        source_id="src_pdf",
        blocks_by_id={source_block.block_id: source_block},
        allowed_block_ids={source_block.block_id},
    )

    assert validation.valid is True
    assert validation.normalized_locator == "page:4;block:src_pdf_p004_b0012;section:Experiments"


def test_pdf_result_locator_preserves_valid_auxiliary_evidence_blocks() -> None:
    table = block(block_id="src_pdf_p004_b0012", block_type="table", content_role="table_like")
    caption = block(block_id="src_pdf_p004_b0013", block_type="caption", content_role="caption")
    heading = block(block_id="src_pdf_p004_b0011", block_type="section_heading")
    result_text = block(block_id="src_pdf_p004_b0014", block_type="paragraph")
    validation = validate_pdf_result_locator(
        "block:src_pdf_p004_b0012",
        source_id="src_pdf",
        blocks_by_id={item.block_id: item for item in (heading, table, caption, result_text)},
        allowed_block_ids={heading.block_id, table.block_id, caption.block_id, result_text.block_id},
        auxiliary_block_ids=[caption.block_id, heading.block_id, result_text.block_id, table.block_id],
    )

    assert validation.evidence_block_ids == [
        table.block_id,
        caption.block_id,
        heading.block_id,
        result_text.block_id,
    ]
    assert validation.evidence_pages == [4]
    assert validation.evidence_block_roles == ["table", "caption", "section_heading", "paragraph"]


def test_pdf_result_locator_rejects_unknown_or_out_of_chunk_block() -> None:
    source_block = block()

    with pytest.raises(MetricResultValidationError, match="unknown block"):
        validate_pdf_result_locator(
            "block:not_real",
            source_id="src_pdf",
            blocks_by_id={source_block.block_id: source_block},
            allowed_block_ids={source_block.block_id},
        )

    with pytest.raises(MetricResultValidationError, match="outside allowed chunk"):
        validate_pdf_result_locator(
            "block:src_pdf_p004_b0012",
            source_id="src_pdf",
            blocks_by_id={source_block.block_id: source_block},
            allowed_block_ids=set(),
        )


def test_pdf_result_locator_rejects_page_mismatch_and_ignored_blocks() -> None:
    source_block = block(content_role="ignored")

    with pytest.raises(MetricResultValidationError, match="ignored"):
        validate_pdf_result_locator(
            "block:src_pdf_p004_b0012",
            source_id="src_pdf",
            blocks_by_id={source_block.block_id: source_block},
            allowed_block_ids={source_block.block_id},
        )

    content_block = block()
    with pytest.raises(MetricResultValidationError, match="page mismatch"):
        validate_pdf_result_locator(
            "page:5;block:src_pdf_p004_b0012",
            source_id="src_pdf",
            blocks_by_id={content_block.block_id: content_block},
            allowed_block_ids={content_block.block_id},
        )
