from __future__ import annotations

import sqlite3

import pytest

from llmwiki.workspace import init_workspace
from tests.helpers import make_workspace


def seed_catalog(root):
    init_workspace(root)
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
                "src_strawberry",
                "Strawberry Notes",
                "markdown",
                "sources/raw/strawberry.md",
                "sources/normalized/strawberry.md",
                "sha-strawberry",
                None,
                "2026-05-29T00:00:00Z",
                "imported",
            ),
        )
        conn.execute(
            """
            insert into claims (
                claim_id, source_id, claim_text, citation_locator,
                confidence_status, created_at
            )
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "claim_strawberry_storage",
                "src_strawberry",
                "Strawberries should be refrigerated and eaten soon after purchase.",
                "section:storage",
                "cited",
                "2026-05-29T00:00:00Z",
            ),
        )
        conn.execute(
            """
            insert into pages (page_id, path, page_type, title, aliases, updated_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "concept_strawberry",
                "wiki/concepts/strawberry.md",
                "concept",
                "Strawberry",
                '["草莓"]',
                "2026-05-29T00:00:00Z",
            ),
        )
        conn.execute(
            """
            insert into aliases (alias, target_type, target_id, normalized_alias)
            values (?, ?, ?, ?)
            """,
            ("草莓", "page", "concept_strawberry", "草莓"),
        )


def test_build_embedding_chunks_include_claim_page_and_source_metadata():
    root = make_workspace()
    seed_catalog(root)

    from llmwiki.vector_index import build_embedding_chunks

    chunks = build_embedding_chunks(root)

    by_type = {chunk.chunk_type: chunk for chunk in chunks}
    assert {"claim", "page_title", "source_title"}.issubset(by_type)

    claim = by_type["claim"]
    assert claim.chunk_id == "claim:claim_strawberry_storage"
    assert claim.text == "Strawberries should be refrigerated and eaten soon after purchase."
    assert claim.metadata["claim_id"] == "claim_strawberry_storage"
    assert claim.metadata["source_id"] == "src_strawberry"
    assert claim.metadata["citation_locator"] == "section:storage"
    assert claim.metadata["confidence_status"] == "cited"


def test_vector_index_roundtrip_and_status_detect_stale_catalog():
    root = make_workspace()
    seed_catalog(root)

    from llmwiki.vector_index import (
        VectorIndexManifest,
        build_embedding_chunks,
        catalog_fingerprint,
        load_vector_index,
        vector_index_status,
        write_vector_index,
    )

    chunks = build_embedding_chunks(root)
    vectors = [[0.1, 0.2, 0.3] for _ in chunks]
    manifest = VectorIndexManifest(
        schema_version="vector_index.v2.6",
        provider="dashscope_multimodal",
        model="model",
        dimension=3,
        chunk_count=len(chunks),
        catalog_fingerprint=catalog_fingerprint(root),
        built_at="2026-05-29T00:00:00Z",
    )

    write_vector_index(root, chunks, vectors, manifest)
    loaded = load_vector_index(root)

    assert loaded.manifest == manifest
    assert [chunk.chunk_id for chunk in loaded.chunks] == [chunk.chunk_id for chunk in chunks]
    assert loaded.vectors == vectors
    assert vector_index_status(root).index_present is True
    assert vector_index_status(root).stale is False

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into claims (
                claim_id, source_id, claim_text, citation_locator,
                confidence_status, created_at
            )
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "claim_new",
                "src_strawberry",
                "New strawberry storage evidence.",
                "section:new",
                "cited",
                "2026-05-29T00:01:00Z",
            ),
        )

    assert vector_index_status(root).stale is True


def test_load_vector_index_rejects_vector_dimension_mismatch():
    root = make_workspace()
    seed_catalog(root)

    from llmwiki.vector_index import (
        VectorIndexManifest,
        build_embedding_chunks,
        catalog_fingerprint,
        load_vector_index,
        write_vector_index,
    )

    chunks = build_embedding_chunks(root)
    manifest = VectorIndexManifest(
        schema_version="vector_index.v2.6",
        provider="dashscope_multimodal",
        model="model",
        dimension=3,
        chunk_count=len(chunks),
        catalog_fingerprint=catalog_fingerprint(root),
        built_at="2026-05-29T00:00:00Z",
    )
    write_vector_index(root, chunks, [[0.1, 0.2] for _ in chunks], manifest)

    with pytest.raises(ValueError, match="dimension"):
        load_vector_index(root)


def test_cosine_similarity_handles_normal_and_zero_vectors():
    from llmwiki.vector_index import cosine_similarity

    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([1, 0], [0, 0]) == 0.0
