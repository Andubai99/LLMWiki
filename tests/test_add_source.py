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


def test_add_missing_file_returns_nonzero(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    assert main(["add", str(root / "missing.md"), "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "Add pipeline failed at: import" in out
    assert "Source not found" in out
