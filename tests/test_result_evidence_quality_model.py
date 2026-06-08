from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.evals.result_evidence import (
    RESULT_EVIDENCE_ITEM_SCHEMA_VERSION,
    RESULT_EVIDENCE_SCHEMA_VERSION,
    ResultEvidenceFilterError,
    build_result_evidence_quality,
    validate_limit_offset,
)
from tests.test_metric_timeline_query import insert_metric_result, insert_source
from tests.helpers import make_workspace


PDF_BLOCK_ID = "src_pdf_p002_b0001"


def workspace_with_result_evidence() -> Path:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    insert_source(root, source_id="src_pdf", title="PDF Results Paper", source_type="pdf")
    insert_source(root, source_id="src_md", title="Markdown Results Paper", source_type="md")

    blocks_dir = root / "sources" / "blocks"
    blocks_dir.mkdir(parents=True, exist_ok=True)
    blocks_dir.joinpath("src_pdf.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "source_block.v2.9.2",
                "source_id": "src_pdf",
                "block_id": PDF_BLOCK_ID,
                "block_type": "table",
                "page_start": 2,
                "page_end": 2,
                "order": 1,
                "text_raw": "Agent A reaches 42.1% success rate on OSWorld.",
                "text_clean": "Agent A reaches 42.1% success rate on OSWorld.",
                "section_path": ["Results"],
                "warnings": [],
                "content_role": "content",
                "table_markdown": "| Method | Success Rate |\n| Agent A | 42.1% |",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    metadata_dir = root / "sources" / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.joinpath("src_pdf.json").write_text(
        json.dumps(
            {
                "schema_version": "source_metadata.v2.9.2",
                "source_id": "src_pdf",
                "parser_backend": "pypdf",
                "parser_backend_fallback_from": "mineru",
                "parser_backend_warnings": ["MinerU parser failed; falling back to pypdf"],
                "parser_quality": {"warning_count": 1, "issues": ["fallback"]},
                "paper_identity": {"authors": ["A. Researcher"], "venue_or_status": "2024"},
            }
        ),
        encoding="utf-8",
    )
    normalized = root / "sources" / "normalized" / "src_md.md"
    normalized.parent.mkdir(parents=True, exist_ok=True)
    normalized.write_text(
        "# Markdown Results Paper\n"
        "Agent B setup.\n"
        "Agent B reports accuracy of 80.0% on OtherSet.\n",
        encoding="utf-8",
    )

    insert_metric_result(
        root,
        result_id="res_pdf",
        claim_id="clm_pdf",
        source_id="src_pdf",
        metric_name="Success Rate",
        metric_value="42.1",
        metric_raw_value="42.1%",
        reported_year=2024,
        method="Agent A",
        dataset="OSWorld",
        task="computer use",
        locator=f"page:2;block:{PDF_BLOCK_ID};section:Results",
    )
    insert_metric_result(
        root,
        result_id="res_md",
        claim_id="clm_md",
        source_id="src_md",
        metric_name="Accuracy",
        metric_value="80.0",
        metric_raw_value="80.0%",
        reported_year=2024,
        method="Agent B",
        dataset="OtherSet",
        task="classification",
        locator="line:3",
    )
    insert_metric_result(
        root,
        result_id="res_missing_value",
        claim_id="clm_missing_value",
        source_id="src_pdf",
        metric_name="Success Rate",
        metric_value="",
        metric_raw_value="not reported",
        reported_year=2024,
        method="",
        dataset="OSWorld",
        task="",
        locator=f"page:2;block:{PDF_BLOCK_ID};section:Results",
    )
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            "update metric_results set evidence_block_ids = ?, evidence_block_roles = ? where result_id = ?",
            (json.dumps([PDF_BLOCK_ID, "src_pdf_p002_b0002"]), json.dumps(["table", "caption"]), "res_pdf"),
        )
        conn.execute(
            "update metric_results set evidence_block_ids = ?, evidence_block_roles = ? where result_id = ?",
            (json.dumps([PDF_BLOCK_ID]), json.dumps(["table"]), "res_missing_value"),
        )
    return root


def test_result_evidence_schema_versions_and_limit_validation() -> None:
    assert RESULT_EVIDENCE_SCHEMA_VERSION == "result_evidence_quality.v4.5"
    assert RESULT_EVIDENCE_ITEM_SCHEMA_VERSION == "result_evidence_item.v4.5"
    assert validate_limit_offset(limit=None, offset=None) == (200, 0, [])

    limit, offset, warnings = validate_limit_offset(limit=5000, offset=3)
    assert limit == 1000
    assert offset == 3
    assert warnings[0]["code"] == "limit_clamped"

    for kwargs in ({"limit": 0, "offset": 0}, {"limit": 10, "offset": -1}):
        try:
            validate_limit_offset(**kwargs)
        except ResultEvidenceFilterError:
            pass
        else:
            raise AssertionError("invalid limit/offset must fail")


def test_result_evidence_quality_summary_and_items() -> None:
    root = workspace_with_result_evidence()

    payload = build_result_evidence_quality(root).to_dict()

    assert payload["schema_version"] == "result_evidence_quality.v4.5"
    assert payload["summary"]["source_count"] == 2
    assert payload["summary"]["paper_count"] == 2
    assert payload["summary"]["metric_result_count"] == 3
    assert payload["summary"]["joined_result_count"] == 3
    assert payload["summary"]["resolvable_locator_count"] == 3
    assert payload["summary"]["context_available_count"] == 3
    assert payload["summary"]["pdf_result_count"] == 2
    assert payload["summary"]["markdown_result_count"] == 1
    assert payload["summary"]["table_result_count"] == 2
    assert payload["summary"]["caption_result_count"] == 1
    assert payload["summary"]["missing_normalized_value_count"] == 1
    assert payload["summary"]["missing_method_count"] == 1
    assert payload["summary"]["missing_task_count"] == 1
    assert payload["summary"]["parser_metadata_source_count"] == 1
    assert payload["summary"]["parser_diagnostic_source_count"] == 1
    assert payload["summary"]["parser_backend_result_counts"] == {"pypdf": 2, "unknown": 1}
    assert payload["summary"]["parser_fallback_result_count"] == 2

    first = payload["items"][0]
    assert first["schema_version"] == "result_evidence_item.v4.5"
    assert first["result_id"] == "res_pdf"
    assert first["claim_id"] == "clm_pdf"
    assert first["source_id"] == "src_pdf"
    assert first["locator_status"] == "resolved"
    assert first["context_status"] == "available"
    assert "42.1%" in first["context_preview"]
    assert first["context_page"] == 2
    assert first["context_block_id"] == PDF_BLOCK_ID
    assert first["context_block_role"] == "table"
    assert first["evidence_block_roles"] == ["table", "caption"]
    assert first["parser_backend"] == "pypdf"
    assert first["parser_backend_fallback_from"] == "mineru"
    assert any(diagnostic["code"] == "parser_fallback_observed" for diagnostic in first["diagnostics"])


def test_result_evidence_filters_and_pagination() -> None:
    root = workspace_with_result_evidence()

    payload = build_result_evidence_quality(
        root,
        metric="accuracy",
        dataset="otherset",
        task="classification",
        limit=1,
        offset=0,
    ).to_dict()

    assert payload["summary"]["metric_result_count"] == 1
    assert payload["items"][0]["result_id"] == "res_md"
    assert payload["items"][0]["context_status"] == "available"
    assert "80.0%" in payload["items"][0]["context_preview"]


def test_result_evidence_reports_missing_claim_join() -> None:
    root = workspace_with_result_evidence()
    insert_metric_result(
        root,
        result_id="res_orphan",
        claim_id="clm_orphan",
        source_id="src_pdf",
        metric_name="Success Rate",
        metric_value="50.0",
        metric_raw_value="50.0%",
        reported_year=2024,
        locator=f"page:2;block:{PDF_BLOCK_ID}",
    )
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute("delete from claims where claim_id = 'clm_orphan'")

    payload = build_result_evidence_quality(root).to_dict()

    orphan = next(item for item in payload["items"] if item["result_id"] == "res_orphan")
    assert orphan["locator_status"] == "unresolved"
    assert any(diagnostic["code"] == "missing_claim_join" for diagnostic in orphan["diagnostics"])
    assert payload["summary"]["error_count"] >= 1
