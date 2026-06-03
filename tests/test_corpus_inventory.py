from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.corpus.inventory import build_inventory
from llmwiki.corpus.state import BatchManifest, CorpusItem, create_batch_id, item_id_for_path, write_batch, write_items
from tests.helpers import make_workspace


def seed_source(
    root: Path,
    *,
    source_id: str,
    title: str,
    raw_name: str,
    sha256: str,
    source_type: str = "pdf",
    applied: bool = True,
) -> None:
    raw_path = f"sources/raw/{source_id}-{raw_name}"
    normalized_path = f"sources/normalized/{source_id}.md"
    page_path = f"wiki/sources/{source_id}.md"
    (root / normalized_path).parent.mkdir(parents=True, exist_ok=True)
    (root / normalized_path).write_text(
        f"---\nsource_id: {source_id}\ntitle: {title}\n---\n\n"
        f"# Normalized Source: {title}\n\nDOI: 10.1145/{sha256}.2024\n",
        encoding="utf-8",
    )
    (root / page_path).parent.mkdir(parents=True, exist_ok=True)
    (root / page_path).write_text(f"# {title}\n", encoding="utf-8")
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
                source_type,
                raw_path,
                normalized_path,
                sha256,
                "",
                "2026-06-03T00:00:00+00:00",
                "imported",
            ),
        )
        conn.execute(
            "insert into pages (page_id, path, page_type, title, aliases, updated_at) values (?, ?, ?, ?, ?, ?)",
            (source_id, page_path, "source", title, "[]", "2026-06-03T00:00:00+00:00"),
        )
        if applied:
            conn.execute(
                "insert into ingest_runs (run_id, source_id, status, created_at, applied_at) values (?, ?, ?, ?, ?)",
                (
                    f"run_{source_id}",
                    source_id,
                    "applied",
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:01:00+00:00",
                ),
            )


def write_metadata(
    root: Path,
    source_id: str,
    *,
    title: str,
    authors: list[str] | None = None,
    venue_or_status: str = "Published as a conference paper at ICLR 2025",
    parser_backend: str = "mineru",
) -> None:
    path = root / "sources" / "metadata" / f"{source_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "source_metadata.v2.9.2",
                "source_id": source_id,
                "title": title,
                "source_type": "pdf",
                "filename": "2404.07972.pdf",
                "metadata_path": f"sources/metadata/{source_id}.json",
                "blocks_path": f"sources/blocks/{source_id}.jsonl",
                "chunks_path": f"sources/chunks/{source_id}.jsonl",
                "authors": authors or ["Alice Example", "Bob Example"],
                "paper_identity": {
                    "title": title,
                    "authors": authors or ["Alice Example", "Bob Example"],
                    "venue_or_status": venue_or_status,
                    "canonical_names": [title],
                    "warnings": [],
                },
                "title_quality": {"status": "selected", "selected_source": "metadata", "score": 0.9},
                "parser_backend": parser_backend,
                "parser_backend_fallback_from": "",
                "parser_quality": {"page_count": 12, "warning_count": 0},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_inventory_json_lists_catalog_sources_with_identity_fields() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_source(root, source_id="src_paper", title="OSWorld Benchmark", raw_name="2404.07972.pdf", sha256="aaa")
    write_metadata(root, "src_paper", title="OSWorld Benchmark")

    inventory = build_inventory(root)
    payload = inventory.to_dict()

    assert payload["schema_version"] == "corpus_inventory.v4.2"
    assert payload["paper_count"] == 1
    paper = payload["papers"][0]
    assert paper["schema_version"] == "paper_identity.v4.2"
    assert paper["source_id"] == "src_paper"
    assert paper["paper_id"] == "src_paper"
    assert paper["title"] == "OSWorld Benchmark"
    assert paper["title_source"] == "catalog"
    assert paper["authors"] == ["Alice Example", "Bob Example"]
    assert paper["authors_source"] == "pdf_metadata"
    assert paper["arxiv_id"] == "2404.07972"
    assert paper["arxiv_id_source"] == "filename"
    assert paper["year"] == 2025
    assert paper["year_source"] == "metadata"
    assert paper["doi"] == "10.1145/aaa.2024"
    assert paper["doi_source"] == "normalized_source"
    assert paper["metadata_path"] == "sources/metadata/src_paper.json"
    assert paper["page_path"] == "wiki/sources/src_paper.md"
    assert paper["applied_run_id"] == "run_src_paper"
    assert paper["applied_status"] == "applied"
    assert paper["parser_backend"] == "mineru"
    assert paper["identity_status"] == "complete"


def test_inventory_warns_for_malformed_metadata_and_keeps_running() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_source(root, source_id="src_bad", title="Bad Metadata Paper", raw_name="2505.13909.pdf", sha256="bbb")
    metadata = root / "sources" / "metadata" / "src_bad.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text("{not-json", encoding="utf-8")

    paper = build_inventory(root).papers[0]

    assert paper.source_id == "src_bad"
    assert paper.identity_status == "malformed_metadata"
    assert any("Malformed metadata sidecar" in warning for warning in paper.warnings)
    assert paper.arxiv_id == "2505.13909"


def test_inventory_emits_duplicate_warnings_for_same_arxiv_and_title() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_source(root, source_id="src_a", title="Shared Paper Title", raw_name="2404.07972.pdf", sha256="111")
    seed_source(root, source_id="src_b", title="Shared Paper Title", raw_name="copy-2404.07972.pdf", sha256="222")
    write_metadata(root, "src_a", title="Shared Paper Title", authors=["Alice Example"])
    write_metadata(root, "src_b", title="Shared Paper Title", authors=["Alice Example"])

    payload = build_inventory(root).to_dict()

    assert payload["duplicates"]
    assert any(item["confidence"] == "high" and item["reason"] == "same arxiv_id" for item in payload["duplicates"])
    assert any(item["duplicate_warnings"] for item in payload["papers"])


def test_inventory_includes_batch_items_separately_from_catalog_papers() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source_path = root / "papers" / "missing.pdf"
    batch_id = create_batch_id(root, [source_path.as_posix()])
    write_batch(root, BatchManifest(batch_id=batch_id, root=str(root), input_paths=["papers"], status="completed_with_failures"))
    write_items(
        root,
        batch_id,
        [
            CorpusItem(
                batch_id=batch_id,
                item_id=item_id_for_path(root, source_path),
                source_path=source_path.as_posix(),
                source_kind="pdf",
                status="failed",
                failure_reason="missing file",
                attempt_count=1,
            )
        ],
    )

    payload = build_inventory(root).to_dict()

    assert payload["paper_count"] == 0
    assert payload["batch_items"][0]["batch_id"] == batch_id
    assert payload["batch_items"][0]["status"] == "failed"
    assert payload["batch_items"][0]["failure_reason"] == "missing file"


def test_inventory_cli_json_and_human_output(capsys) -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_source(root, source_id="src_cli", title="CLI Paper", raw_name="2605.11212.pdf", sha256="ccc")
    write_metadata(root, "src_cli", title="CLI Paper", venue_or_status="")
    capsys.readouterr()

    assert main(["corpus", "inventory", "--root", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == "corpus_inventory.v4.2"
    assert data["papers"][0]["arxiv_id"] == "2605.11212"

    assert main(["corpus", "inventory", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Corpus inventory" in out
    assert "Papers: 1" in out
    assert "src_cli" in out
    assert "2605.11212" in out


def test_inventory_cli_is_read_only(monkeypatch, capsys) -> None:
    import llmwiki.cli as cli

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_source(root, source_id="src_safe", title="Safe Paper", raw_name="2406.01014.pdf", sha256="safe")

    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("corpus inventory must be read-only")

    monkeypatch.setattr(cli, "add_and_process_source", forbidden)
    monkeypatch.setattr(cli, "ingest_source", forbidden)
    monkeypatch.setattr(cli, "apply_run", forbidden)
    monkeypatch.setattr(cli, "evaluate_retrieval", forbidden)
    monkeypatch.setattr(cli, "evaluate_pdf_quality", forbidden)
    monkeypatch.setattr(cli, "probe_mineru_status", forbidden)
    monkeypatch.setattr(cli, "create_provider", forbidden)
    capsys.readouterr()

    assert main(["corpus", "inventory", "--root", str(root), "--json"]) == 0
    assert not (root / "state" / "corpus-batches").exists()
    assert not (root / "state" / "embeddings").exists()
