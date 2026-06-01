from __future__ import annotations

from llmwiki.pdf_blocks import SourceBlock
from llmwiki.pdf_quality import (
    classify_block_roles,
    detect_repeated_headers_footers,
    detect_parser_created_alias,
    score_title_candidates,
)


def make_block(text: str, *, page: int = 1, order: int = 1, block_type: str = "paragraph") -> SourceBlock:
    return SourceBlock(
        source_id="src_pdf",
        block_id=f"src_pdf_p{page:03d}_b{order:04d}",
        block_type=block_type,
        page_start=page,
        page_end=page,
        order=order,
        text_raw=text,
        text_clean=text,
    )


def test_title_candidate_scoring_penalizes_parser_markers_and_metadata_noise():
    candidates = score_title_candidates(
        metadata={"title": "<!-- page:1 -->"},
        blocks=[
            make_block("Published as a conference paper at ICLR 2025", order=1),
            make_block("Alice Example, Bob Example, Carol Example, David Example", order=2),
            make_block("OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks", order=3),
            make_block("<!-- page:1 -->", order=4),
        ],
        filename="2405.00000.pdf",
    )

    assert candidates[0].text == "OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks"
    lowest = candidates[-1]
    assert lowest.text == "<!-- page:1 -->"
    assert "parser_marker" in lowest.reasons
    venue = next(item for item in candidates if item.text.startswith("Published as"))
    authors = next(item for item in candidates if item.text.startswith("Alice Example"))
    assert "venue_or_status_line" in venue.reasons
    assert "author_dense" in authors.reasons
    assert venue.score < candidates[0].score
    assert authors.score < candidates[0].score


def test_detect_repeated_headers_footers_marks_cross_page_short_repeats():
    blocks = [
        make_block("OSWorld", page=1, order=1),
        make_block("Body text page one.", page=1, order=2),
        make_block("OSWorld", page=2, order=1),
        make_block("Body text page two.", page=2, order=2),
        make_block("OSWorld", page=3, order=1),
    ]

    repeated = detect_repeated_headers_footers(blocks)

    assert repeated == {"OSWorld"}


def test_classify_block_roles_marks_ignored_page_numbers_and_structural_roles():
    blocks = [
        make_block("1", page=1, order=1),
        make_block("Page 2", page=2, order=1),
        make_block("Figure 3: Example workflow overview.", order=2),
        make_block("Table 1: Accuracy by task category.", order=3),
        make_block("E = mc² + α/β", order=4),
        make_block("[12] Alice Example. A related system. 2024.", order=5, block_type="reference"),
        make_block("Appendix A Additional Details", order=6, block_type="section_heading"),
    ]

    classified = classify_block_roles(blocks, repeated_texts=set())
    by_text = {block.text_clean: block for block in classified}

    assert by_text["1"].content_role == "ignored"
    assert "page_number" in by_text["1"].quality_flags
    assert by_text["Page 2"].content_role == "ignored"
    assert by_text["Figure 3: Example workflow overview."].content_role == "caption"
    assert by_text["Table 1: Accuracy by task category."].content_role == "table_like"
    assert by_text["E = mc² + α/β"].content_role == "equation_like"
    assert by_text["[12] Alice Example. A related system. 2024."].content_role == "reference"
    assert by_text["Appendix A Additional Details"].content_role == "appendix"


def test_detect_parser_created_alias_rejects_structural_artifacts():
    assert detect_parser_created_alias("page1")
    assert detect_parser_created_alias("<!-- page:1 -->")
    assert detect_parser_created_alias("Published as a conference paper at ICLR 2025")
    assert detect_parser_created_alias("Alice Example, Bob Example, Carol Example, David Example")
    assert not detect_parser_created_alias("OSWorld")
    assert not detect_parser_created_alias("MobileAgentBench")
