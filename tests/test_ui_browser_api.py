from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from llmwiki.cli import main
from tests.helpers import make_workspace


def seed_browser_catalog(root: Path) -> None:
    assert main(["init", "--root", str(root)]) == 0

    (root / "sources" / "normalized" / "src_text.md").write_text(
        "\n".join(
            [
                "line 1 intro",
                "line 2 setup",
                "line 3 target storage evidence",
                "line 4 after",
                "line 5 end",
            ]
        ),
        encoding="utf-8",
    )
    (root / "sources" / "blocks" / "src_pdf.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "source_block.v2.9.2",
                "source_id": "src_pdf",
                "block_id": "src_pdf_p001_b0001",
                "block_type": "text",
                "page_start": 1,
                "page_end": 1,
                "order": 1,
                "text_raw": "PDF raw block text",
                "text_clean": "PDF clean block evidence",
                "section_path": ["Abstract"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "sources" / "metadata" / "src_pdf.json").write_text(
        json.dumps(
            {
                "source_id": "src_pdf",
                "parser_backend": "mineru",
                "parser_backend_fallback_from": "pypdf",
                "page_count": 1,
                "block_count": 1,
                "chunk_count": 0,
                "metadata_path": "sources/metadata/src_pdf.json",
                "blocks_path": "sources/blocks/src_pdf.jsonl",
                "chunks_path": "sources/chunks/src_pdf.jsonl",
                "parser_backend_attempts": [{"stderr": "do not expose"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "wiki" / "sources" / "src_text.md").write_text("# Text Source\n", encoding="utf-8")
    (root / "wiki" / "sources" / "src_pdf.md").write_text("# PDF Source\n", encoding="utf-8")
    (root / "wiki" / "concepts" / "fruit.md").write_text(
        "# Fruit\n\nConcept markdown is page text, not formal evidence.\n",
        encoding="utf-8",
    )
    (root / "wiki" / "syntheses" / "fruit.md").write_text(
        "# Fruit Synthesis\n\nSynthesis narrative text is not a claim.\n",
        encoding="utf-8",
    )

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.executemany(
            """
            insert into sources (
                source_id, title, source_type, raw_path, normalized_path,
                sha256, url, imported_at, status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "src_text",
                    "Text Source",
                    "markdown",
                    "sources/raw/src_text.md",
                    "sources/normalized/src_text.md",
                    "sha-text",
                    "",
                    "2026-06-03T00:00:00Z",
                    "imported",
                ),
                (
                    "src_pdf",
                    "PDF Source",
                    "pdf",
                    "sources/raw/src_pdf.pdf",
                    "sources/normalized/src_pdf.md",
                    "sha-pdf",
                    "",
                    "2026-06-03T00:01:00Z",
                    "imported",
                ),
                (
                    "src_out",
                    "Outside Source",
                    "markdown",
                    "../outside.md",
                    "../outside-normalized.md",
                    "sha-out",
                    "",
                    "2026-06-03T00:02:00Z",
                    "imported",
                ),
            ],
        )
        conn.executemany(
            """
            insert into claims (
                claim_id, source_id, claim_text, citation_locator, confidence_status, created_at
            )
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("clm_line", "src_text", "Storage claim from text", "line:3", "cited", "2026-06-03T01:00:00Z"),
                (
                    "clm_pdf",
                    "src_pdf",
                    "PDF block claim",
                    "page:1;block:src_pdf_p001_b0001;section:Abstract",
                    "cited",
                    "2026-06-03T01:01:00Z",
                ),
                ("clm_weak", "src_text", "Weak unsupported claim", "chapter:1", "weak", "2026-06-03T01:02:00Z"),
                ("clm_out", "src_out", "Outside path claim", "line:1", "cited", "2026-06-03T01:03:00Z"),
            ],
        )
        conn.executemany(
            """
            insert into pages (page_id, path, page_type, title, aliases, updated_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("src_text", "wiki/sources/src_text.md", "source", "Text Source", "[]", "now"),
                ("src_pdf", "wiki/sources/src_pdf.md", "source", "PDF Source", "[]", "now"),
                ("concept:fruit", "wiki/concepts/fruit.md", "concept", "Fruit", '["Fruit Alias"]', "now"),
                ("synthesis-fruit", "wiki/syntheses/fruit.md", "synthesis", "Fruit Synthesis", "[]", "now"),
            ],
        )
        conn.executemany(
            "insert into links (from_page, to_page, link_type) values (?, ?, ?)",
            [
                ("src_text", "concept:fruit", "mentions"),
                ("concept:fruit", "src_text", "supports"),
                ("synthesis-fruit", "concept:fruit", "mentions"),
            ],
        )
        conn.executemany(
            """
            insert into relationships (
                subject_id, object_id, relationship_type, evidence_claim_id, source_id
            )
            values (?, ?, ?, ?, ?)
            """,
            [
                ("concept:fruit", "src_text", "supports", "clm_line", "src_text"),
                ("concept:fruit", "src_pdf", "contradicts", "clm_pdf", "src_pdf"),
                ("synthesis-fruit", "concept:fruit", "supports", "clm_line", "src_text"),
            ],
        )
        conn.executemany(
            "insert into ingest_runs (run_id, source_id, status, created_at, applied_at) values (?, ?, ?, ?, ?)",
            [
                ("run_text", "src_text", "applied", "2026-06-03T02:00:00Z", "2026-06-03T02:01:00Z"),
                ("run_pdf", "src_pdf", "applied", "2026-06-03T02:02:00Z", "2026-06-03T02:03:00Z"),
            ],
        )


def test_source_detail_returns_bounded_catalog_and_sidecar_summary() -> None:
    from llmwiki.ui.browser_api import get_source_detail

    root = make_workspace()
    seed_browser_catalog(root)

    payload = get_source_detail(root, "src_pdf").to_dict()

    assert payload["schema_version"] == "ui.v3.4"
    assert payload["source"]["source_id"] == "src_pdf"
    assert payload["latest_run"]["run_id"] == "run_pdf"
    assert payload["source_page"]["page_id"] == "src_pdf"
    assert payload["sidecars"] == {"metadata": True, "blocks": True, "chunks": False}
    assert payload["metadata"] == {
        "parser_backend": "mineru",
        "parser_backend_fallback_from": "pypdf",
        "page_count": 1,
        "block_count": 1,
        "chunk_count": 0,
        "metadata_path": "sources/metadata/src_pdf.json",
        "blocks_path": "sources/blocks/src_pdf.jsonl",
        "chunks_path": "sources/chunks/src_pdf.jsonl",
    }
    assert payload["claim_counts"] == {"cited": 1}
    assert payload["claims"][0]["claim_id"] == "clm_pdf"
    assert payload["relationships"][0]["relationship_type"] == "contradicts"
    assert "parser_backend_attempts" not in repr(payload)


def test_page_detail_distinguishes_markdown_text_from_related_claims() -> None:
    from llmwiki.ui.browser_api import get_page_detail

    root = make_workspace()
    seed_browser_catalog(root)

    payload = get_page_detail(root, "concept:fruit").to_dict()

    assert payload["schema_version"] == "ui.v3.4"
    assert payload["page"]["page_id"] == "concept:fruit"
    assert payload["aliases"] == ["Fruit Alias"]
    assert "Concept markdown is page text" in payload["markdown"]
    assert payload["markdown_is_evidence"] is False
    assert {claim["claim_id"] for claim in payload["related_claims"]} == {"clm_line", "clm_pdf"}
    assert {link["link_type"] for link in payload["outgoing_links"]} == {"supports"}
    assert {item["relationship_type"] for item in payload["relationships"]} == {"supports", "contradicts"}


def test_claim_list_filters_and_preserves_relationship_visibility() -> None:
    from llmwiki.ui.browser_api import list_claims

    root = make_workspace()
    seed_browser_catalog(root)

    query_payload = list_claims(root, query="storage", confidence="cited").to_dict()
    relationship_payload = list_claims(root, relationship_type="contradicts").to_dict()
    page_payload = list_claims(root, page_type="concept").to_dict()

    assert [claim["claim_id"] for claim in query_payload["claims"]] == ["clm_line"]
    assert [claim["claim_id"] for claim in relationship_payload["claims"]] == ["clm_pdf"]
    assert {claim["claim_id"] for claim in page_payload["claims"]} == {"clm_line", "clm_pdf"}
    assert relationship_payload["claims"][0]["relationship_types"] == ["contradicts"]


def test_relationship_list_filters_by_claim_and_page() -> None:
    from llmwiki.ui.browser_api import list_relationships

    root = make_workspace()
    seed_browser_catalog(root)

    by_claim = list_relationships(root, claim_id="clm_line").to_dict()
    by_page = list_relationships(root, page_id="synthesis-fruit").to_dict()

    assert {item["relationship_type"] for item in by_claim["relationships"]} == {"supports"}
    assert by_page["relationships"][0]["subject_id"] == "synthesis-fruit"
    assert by_page["relationships"][0]["evidence_claim_id"] == "clm_line"


def test_claim_detail_resolves_markdown_line_context() -> None:
    from llmwiki.ui.browser_api import get_claim_detail

    root = make_workspace()
    seed_browser_catalog(root)

    payload = get_claim_detail(root, "clm_line").to_dict()

    assert payload["claim"]["claim_id"] == "clm_line"
    assert payload["claim"]["source_id"] == "src_text"
    assert payload["claim"]["citation_locator"] == "line:3"
    assert payload["locator_context"]["status"] == "resolved"
    assert payload["locator_context"]["kind"] == "line"
    assert payload["locator_context"]["start_line"] == 1
    assert payload["locator_context"]["end_line"] == 5
    assert "line 3 target storage evidence" in payload["locator_context"]["text"]
    assert payload["relationships"][0]["relationship_type"] == "supports"


def test_claim_detail_resolves_pdf_block_context() -> None:
    from llmwiki.ui.browser_api import get_claim_detail

    root = make_workspace()
    seed_browser_catalog(root)

    payload = get_claim_detail(root, "clm_pdf").to_dict()

    assert payload["locator_context"]["status"] == "resolved"
    assert payload["locator_context"]["kind"] == "pdf_block"
    assert payload["locator_context"]["block_id"] == "src_pdf_p001_b0001"
    assert payload["locator_context"]["page"] == 1
    assert "PDF clean block evidence" in payload["locator_context"]["text"]
    assert payload["relationships"][0]["relationship_type"] == "contradicts"


def test_claim_detail_warns_for_unsupported_and_outside_locators() -> None:
    from llmwiki.ui.browser_api import get_claim_detail

    root = make_workspace()
    seed_browser_catalog(root)

    unsupported = get_claim_detail(root, "clm_weak").to_dict()
    outside = get_claim_detail(root, "clm_out").to_dict()

    assert unsupported["locator_context"]["status"] == "unsupported_locator"
    assert unsupported["locator_context"]["text"] == ""
    assert unsupported["warnings"]
    assert outside["locator_context"]["status"] == "outside_workspace"
    assert outside["locator_context"]["text"] == ""
    assert outside["source"]["normalized_path"] == "[outside-workspace]"


def test_claim_detail_warns_for_malformed_pdf_sidecar() -> None:
    from llmwiki.ui.browser_api import get_claim_detail

    root = make_workspace()
    seed_browser_catalog(root)
    (root / "sources" / "blocks" / "src_pdf.jsonl").write_text("{bad json", encoding="utf-8")

    payload = get_claim_detail(root, "clm_pdf").to_dict()

    assert payload["locator_context"]["status"] == "malformed_sidecar"
    assert payload["locator_context"]["text"] == ""
    assert payload["warnings"]
    assert "bad json" not in repr(payload)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 201},
        {"limit": 0},
        {"offset": -1},
        {"relationship_type": "invented"},
    ],
)
def test_claim_list_rejects_invalid_filters(kwargs: dict[str, object]) -> None:
    from llmwiki.ui.browser_api import UiBrowserError, list_claims

    root = make_workspace()
    seed_browser_catalog(root)

    with pytest.raises(UiBrowserError) as exc_info:
        list_claims(root, **kwargs)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "invalid_request"


def test_missing_catalog_and_missing_ids_use_stable_errors() -> None:
    from llmwiki.ui.browser_api import UiBrowserError, get_claim_detail, get_source_detail

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    with pytest.raises(UiBrowserError) as missing_claim:
        get_claim_detail(root, "missing")
    assert missing_claim.value.status_code == 404
    assert missing_claim.value.code == "not_found"

    (root / "state" / "catalog.sqlite").unlink()
    with pytest.raises(UiBrowserError) as missing_catalog:
        get_source_detail(root, "src_missing")
    assert missing_catalog.value.status_code == 409
    assert missing_catalog.value.code == "catalog_unavailable"
