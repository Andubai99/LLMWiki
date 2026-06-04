from __future__ import annotations

import json
from pathlib import Path

from llmwiki.evals.result_evidence import resolve_line_locator, resolve_pdf_locator
from tests.test_metric_timeline_query import insert_source
from tests.helpers import make_workspace
from llmwiki.cli import main


def test_resolve_pdf_locator_returns_bounded_block_context() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    insert_source(root, source_id="src_pdf", title="PDF", source_type="pdf")
    block_id = "src_pdf_p003_b0007"
    block_path = root / "sources" / "blocks" / "src_pdf.jsonl"
    block_path.parent.mkdir(parents=True, exist_ok=True)
    block_path.write_text(
        json.dumps(
            {
                "source_id": "src_pdf",
                "block_id": block_id,
                "block_type": "paragraph",
                "page_start": 3,
                "page_end": 3,
                "text_clean": "The method reports 91.2% accuracy.",
                "text_raw": "The method reports 91.2% accuracy.",
                "section_path": ["Experiments"],
                "content_role": "content",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    resolved = resolve_pdf_locator(root, "src_pdf", f"page:3;block:{block_id};section:Experiments")

    assert resolved["locator_status"] == "resolved"
    assert resolved["context_status"] == "available"
    assert resolved["context_page"] == 3
    assert resolved["context_block_id"] == block_id
    assert "91.2%" in resolved["context_preview"]
    assert resolved["diagnostics"] == []


def test_resolve_pdf_locator_reports_missing_block_and_page_mismatch() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    insert_source(root, source_id="src_pdf", title="PDF", source_type="pdf")
    block_path = root / "sources" / "blocks" / "src_pdf.jsonl"
    block_path.parent.mkdir(parents=True, exist_ok=True)
    block_path.write_text(
        json.dumps(
            {
                "source_id": "src_pdf",
                "block_id": "src_pdf_p002_b0001",
                "block_type": "paragraph",
                "page_start": 2,
                "page_end": 2,
                "text_clean": "Result text.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    missing = resolve_pdf_locator(root, "src_pdf", "page:2;block:missing")
    assert missing["locator_status"] == "unresolved"
    assert any(diagnostic["code"] == "missing_block_id" for diagnostic in missing["diagnostics"])

    mismatch = resolve_pdf_locator(root, "src_pdf", "page:3;block:src_pdf_p002_b0001")
    assert mismatch["locator_status"] == "unresolved"
    assert any(diagnostic["code"] == "page_mismatch" for diagnostic in mismatch["diagnostics"])


def test_resolve_line_locator_reads_bounded_normalized_context() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    insert_source(root, source_id="src_md", title="MD", source_type="md")
    normalized_path = root / "sources" / "normalized" / "src_md.md"
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_text("line one\nline two\nline three reports 80.0% accuracy\n", encoding="utf-8")

    resolved = resolve_line_locator(root, source_id="src_md", normalized_path="sources/normalized/src_md.md", locator="line:3")

    assert resolved["locator_status"] == "resolved"
    assert resolved["context_status"] == "available"
    assert resolved["context_page"] is None
    assert "80.0%" in resolved["context_preview"]
    assert resolved["diagnostics"] == []


def test_resolve_line_locator_rejects_out_of_bounds_or_unbounded_path() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    insert_source(root, source_id="src_md", title="MD", source_type="md")
    normalized_path = root / "sources" / "normalized" / "src_md.md"
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_text("line one\n", encoding="utf-8")

    out_of_range = resolve_line_locator(root, source_id="src_md", normalized_path="sources/normalized/src_md.md", locator="line:4")
    assert out_of_range["locator_status"] == "unresolved"
    assert any(diagnostic["code"] == "line_out_of_range" for diagnostic in out_of_range["diagnostics"])

    outside = resolve_line_locator(root, source_id="src_md", normalized_path="config/config.toml", locator="line:1")
    assert outside["locator_status"] == "unresolved"
    assert any(diagnostic["code"] == "missing_normalized_source" for diagnostic in outside["diagnostics"])
