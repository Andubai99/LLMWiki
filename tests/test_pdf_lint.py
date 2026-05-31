from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from tests.helpers import make_workspace


def seed_pdf_source(root: Path, *, title: str = "OSWorld") -> str:
    source_id = "src_pdf"
    raw = root / "sources" / "raw" / "src_pdf-osworld.pdf"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"%PDF fake")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into sources (
                source_id, title, source_type, raw_path, normalized_path,
                sha256, url, imported_at, status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                title,
                "pdf",
                "sources/raw/src_pdf-osworld.pdf",
                "sources/normalized/src_pdf.md",
                digest,
                None,
                "2026-05-31T00:00:00+00:00",
                "imported",
            ),
        )
    return source_id


def write_pdf_sidecars(root: Path, source_id: str = "src_pdf") -> None:
    (root / "sources" / "metadata").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "blocks").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "chunks").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "metadata" / f"{source_id}.json").write_text(
        json.dumps(
            {
                "schema_version": "source_metadata.v2.9.1",
                "source_id": source_id,
                "title": "OSWorld",
                "source_type": "pdf",
                "page_count": 1,
                "raw_path": "sources/raw/src_pdf-osworld.pdf",
                "normalized_path": "sources/normalized/src_pdf.md",
                "metadata_path": "sources/metadata/src_pdf.json",
                "blocks_path": "sources/blocks/src_pdf.jsonl",
                "chunks_path": "sources/chunks/src_pdf.jsonl",
                "filename": "osworld.pdf",
                "extraction_engine": "pypdf",
                "authors": [],
                "abstract": "",
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "sources" / "blocks" / f"{source_id}.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "source_block.v2.9.1",
                "source_id": source_id,
                "block_id": "src_pdf_p001_b0001",
                "block_type": "paragraph",
                "page_start": 1,
                "page_end": 1,
                "order": 1,
                "text_raw": "OSWorld evaluates agents.",
                "text_clean": "OSWorld evaluates agents.",
                "section_path": [],
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "sources" / "chunks" / f"{source_id}.jsonl").write_text("", encoding="utf-8")


def test_lint_reports_pdf_marker_title_and_missing_sidecars(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_pdf_source(root, title="<!-- page:1 -->")
    capsys.readouterr()

    assert main(["lint", "--root", str(root)]) == 1
    out = capsys.readouterr().out

    assert "pdf parser issues:" in out
    assert "pdf marker titles: 1" in out
    assert "pdf missing sidecars: 1" in out


def test_lint_reports_pdf_claims_without_block_locators(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source_id = seed_pdf_source(root)
    write_pdf_sidecars(root, source_id)
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into claims (claim_id, source_id, claim_text, citation_locator, confidence_status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("clm_line", source_id, "Line locator is not enough for a PDF claim.", "line:1", "cited", "2026-05-31T00:00:00+00:00"),
        )
    capsys.readouterr()

    assert main(["lint", "--root", str(root)]) == 1
    out = capsys.readouterr().out

    assert "pdf claims missing page/block locator: 1" in out


def test_lint_reports_unknown_pdf_block_locator(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source_id = seed_pdf_source(root)
    write_pdf_sidecars(root, source_id)
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into claims (claim_id, source_id, claim_text, citation_locator, confidence_status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "clm_unknown",
                source_id,
                "Unknown block should be reported.",
                "page:1;block:src_pdf_p001_b9999",
                "cited",
                "2026-05-31T00:00:00+00:00",
            ),
        )
    capsys.readouterr()

    assert main(["lint", "--root", str(root)]) == 1
    out = capsys.readouterr().out

    assert "pdf claims with invalid block locator: 1" in out
