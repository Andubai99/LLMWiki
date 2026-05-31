from __future__ import annotations

import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.sources import import_source
from tests.helpers import make_workspace


def fetch_rows(db_path: Path, sql: str) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql).fetchall()


def test_import_source_markdown_writes_raw_normalized_and_deduplicates(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    source = root / "minimal.md"
    source.write_text(
        "# Retrieval Notes\n\n"
        "Retrieval augmented generation links answers to source passages.\n"
        "RAG systems should preserve citation anchors.\n",
        encoding="utf-8",
    )

    first = import_source(root, str(source))
    assert not first.duplicate

    second = import_source(root, str(source))
    assert second.duplicate
    assert second.source_id == first.source_id

    rows = fetch_rows(
        root / "state" / "catalog.sqlite",
        "select source_id, title, source_type, raw_path, normalized_path, sha256, status from sources",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["source_id"].startswith("src_")
    assert row["title"] == "Retrieval Notes"
    assert row["source_type"] == "markdown"
    assert row["status"] == "imported"

    raw_path = root / row["raw_path"]
    normalized_path = root / row["normalized_path"]
    assert raw_path.exists()
    assert normalized_path.exists()
    assert raw_path.read_text(encoding="utf-8").startswith("# Retrieval Notes")

    normalized = normalized_path.read_text(encoding="utf-8")
    assert "source_id: " in normalized
    assert "<!-- line:3 -->" in normalized
    assert "[line:3]" in normalized
    assert "Retrieval augmented generation links answers" in normalized


def test_import_pdf_writes_metadata_blocks_and_block_normalized_source(monkeypatch, capsys):
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
                "OSWorld evaluates computer-use agents.\n",
            ],
        )

    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", fake_read_pdf_pages)

    source = root / "osworld.pdf"
    source.write_bytes(b"%PDF fake")

    result = import_source(root, str(source))
    assert not result.duplicate
    assert result.title == "OSWorld: Benchmarking Multimodal Agents"

    rows = fetch_rows(
        root / "state" / "catalog.sqlite",
        "select source_id, title, source_type, raw_path, normalized_path from sources",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["source_type"] == "pdf"
    assert row["title"] == "OSWorld: Benchmarking Multimodal Agents"

    metadata_path = root / "sources" / "metadata" / f"{result.source_id}.json"
    blocks_path = root / "sources" / "blocks" / f"{result.source_id}.jsonl"
    chunks_path = root / "sources" / "chunks" / f"{result.source_id}.jsonl"
    assert metadata_path.exists()
    assert blocks_path.exists()
    assert chunks_path.exists()

    normalized = (root / row["normalized_path"]).read_text(encoding="utf-8")
    assert "page_count: 1" in normalized
    assert f"metadata_path: sources/metadata/{result.source_id}.json" in normalized
    assert f"blocks_path: sources/blocks/{result.source_id}.jsonl" in normalized
    assert f"chunks_path: sources/chunks/{result.source_id}.jsonl" in normalized
    assert "<!-- block:" in normalized
    assert "<!-- page:1 -->" not in normalized
    assert "# OSWorld: Benchmarking Multimodal Agents" in normalized


def test_add_missing_file_returns_nonzero(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    assert main(["add", str(root / "missing.md"), "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "Add pipeline failed at: import" in out
    assert "Source not found" in out
