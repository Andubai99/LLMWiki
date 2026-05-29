from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path


def make_workspace() -> Path:
    root = Path(__file__).resolve().parents[1] / ".test-workspaces" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root


def disable_llm(root: Path) -> None:
    config_path = root / "config" / "config.toml"
    config = config_path.read_text(encoding="utf-8")
    config = config.replace("enabled = true", "enabled = false")
    config_path.write_text(config, encoding="utf-8", newline="\n")


def seed_contradicts_relationship(
    root: Path,
    *,
    source_id: str,
    claim_text_like: str,
    subject_title: str = "Retrieval Augmented Generation",
) -> str:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        claim = conn.execute(
            """
            select claim_id
            from claims
            where source_id = ?
              and claim_text like ?
            order by claim_id
            limit 1
            """,
            (source_id, claim_text_like),
        ).fetchone()
        if claim is None:
            raise AssertionError(f"no claim matched {source_id=} {claim_text_like=}")
        page = conn.execute(
            """
            select page_id
            from pages
            where page_type = 'concept'
              and title = ?
            order by page_id
            limit 1
            """,
            (subject_title,),
        ).fetchone()
        if page is None:
            raise AssertionError(f"no concept page matched {subject_title=}")
        conn.execute(
            """
            insert into relationships (
                subject_id, object_id, relationship_type, evidence_claim_id, source_id
            )
            values (?, ?, ?, ?, ?)
            """,
            (page["page_id"], source_id, "contradicts", claim["claim_id"], source_id),
        )
        return str(claim["claim_id"])
