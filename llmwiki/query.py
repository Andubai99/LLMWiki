from __future__ import annotations

import re
from pathlib import Path

from .db import catalog_path, connect


def query_context(root: Path, question: str, limit: int = 5) -> str:
    root = root.resolve()
    rows = search_claims(root, question, limit)
    lines = [f"Retrieval context for: {question}", ""]
    if not rows:
        lines.append("No matching claims found.")
        return "\n".join(lines)

    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. claim_id={row['claim_id']} source_id={row['source_id']} "
            f"citation={row['citation_locator']}"
        )
        lines.append(f"   {row['claim_text']}")
    return "\n".join(lines)


def search_claims(root: Path, question: str, limit: int) -> list[dict[str, str]]:
    terms = query_terms(question)
    if not terms:
        return []
    fts_query = " OR ".join(terms)
    with connect(catalog_path(root)) as conn:
        try:
            rows = conn.execute(
                """
                select claim_id, claim_text, source_id, citation_locator
                from claims_fts
                where claims_fts match ?
                order by bm25(claims_fts)
                limit ?
                """,
                (fts_query, limit),
            ).fetchall()
        except Exception:
            rows = []
        if not rows:
            like = f"%{terms[0]}%"
            rows = conn.execute(
                """
                select claim_id, claim_text, source_id, citation_locator
                from claims
                where lower(claim_text) like ?
                order by created_at
                limit ?
                """,
                (like, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def query_terms(question: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_]{3,}", question.casefold())
    return list(dict.fromkeys(terms))
