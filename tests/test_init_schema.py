import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.workspace import REQUIRED_PATHS
from tests.helpers import make_workspace


def workspace_dir():
    return make_workspace()


def table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "select name from sqlite_master where type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def table_columns(db_path: Path, table: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"pragma table_info({table})").fetchall()
    return [row[1] for row in rows]


def test_init_creates_workspace_files_and_schema():
    root = workspace_dir()
    assert main(["init", "--root", str(root)]) == 0

    for required in REQUIRED_PATHS:
        assert (root / required).exists(), required

    db_path = root / "state" / "catalog.sqlite"
    assert db_path.exists()

    assert {
        "sources",
        "claims",
        "aliases",
        "pages",
        "links",
        "relationships",
        "ingest_runs",
    }.issubset(table_names(db_path))

    assert table_columns(db_path, "sources") == [
        "source_id",
        "title",
        "source_type",
        "raw_path",
        "normalized_path",
        "sha256",
        "url",
        "imported_at",
        "status",
    ]
    assert table_columns(db_path, "relationships") == [
        "subject_id",
        "object_id",
        "relationship_type",
        "evidence_claim_id",
        "source_id",
    ]


def test_doctor_checks_database_schema(capsys):
    root = workspace_dir()
    assert main(["init", "--root", str(root)]) == 0

    assert main(["doctor", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Workspace OK" in out
    assert "schema OK" in out
