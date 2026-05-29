from __future__ import annotations

import sqlite3

from llmwiki.cli import main
from llmwiki.retrieval import retrieve_context
from llmwiki.vector_index import (
    VectorIndexManifest,
    build_embedding_chunks,
    catalog_fingerprint,
    write_vector_index,
)
from llmwiki.workspace import init_workspace
from tests.helpers import make_workspace


class FakeEmbeddingProvider:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.vector for _ in texts]


def seed_vector_workspace():
    root = make_workspace()
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
            insert into pages (page_id, path, page_type, title, aliases, updated_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "src_strawberry",
                "wiki/sources/src_strawberry.md",
                "source",
                "Strawberry Notes",
                "[]",
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
        conn.execute("insert into links (from_page, to_page, link_type) values (?, ?, ?)", ("src_strawberry", "concept_strawberry", "mentions"))
        conn.execute("insert into links (from_page, to_page, link_type) values (?, ?, ?)", ("concept_strawberry", "src_strawberry", "supports"))
        conn.execute(
            "insert into aliases (alias, target_type, target_id, normalized_alias) values (?, ?, ?, ?)",
            ("草莓", "concept", "concept_strawberry", "草莓"),
        )
        for claim_id, text, locator in [
            (
                "claim_strawberry_storage",
                "Store strawberries in the refrigerator and eat them soon after purchase.",
                "section:storage",
            ),
            (
                "claim_strawberry_vitamin",
                "Strawberries contain vitamin C.",
                "section:nutrition",
            ),
        ]:
            conn.execute(
                """
                insert into claims (
                    claim_id, source_id, claim_text, citation_locator,
                    confidence_status, created_at
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    "src_strawberry",
                    text,
                    locator,
                    "cited",
                    "2026-05-29T00:00:00Z",
                ),
            )
            conn.execute(
                "insert into claims_fts (claim_id, claim_text, source_id, citation_locator) values (?, ?, ?, ?)",
                (claim_id, text, "src_strawberry", locator),
            )
            conn.execute(
                """
                insert into relationships (
                    subject_id, object_id, relationship_type, evidence_claim_id, source_id
                )
                values (?, ?, ?, ?, ?)
                """,
                ("concept_strawberry", "src_strawberry", "supports", claim_id, "src_strawberry"),
            )
    return root


def write_fake_index(root, *, dimension: int = 2, bad_dimension: bool = False) -> None:
    chunks = build_embedding_chunks(root)
    vectors = []
    for chunk in chunks:
        if chunk.chunk_id == "claim:claim_strawberry_storage":
            vector = [1.0, 0.0]
        elif chunk.chunk_id == "claim:claim_strawberry_vitamin":
            vector = [0.0, 1.0]
        else:
            vector = [0.2, 0.2]
        vectors.append(vector[:1] if bad_dimension else vector)
    manifest = VectorIndexManifest(
        schema_version="vector_index.v2.6",
        provider="dashscope_multimodal",
        model="fake-model",
        dimension=dimension,
        chunk_count=len(chunks),
        catalog_fingerprint=catalog_fingerprint(root),
        built_at="2026-05-29T00:00:00Z",
    )
    write_vector_index(root, chunks, vectors, manifest)


def test_vector_retriever_adds_semantic_candidate_to_retrieve(monkeypatch):
    root = seed_vector_workspace()
    write_fake_index(root)
    provider = FakeEmbeddingProvider([1.0, 0.0])
    monkeypatch.setattr("llmwiki.embeddings.create_embedding_provider", lambda config, root=None: provider)

    result = retrieve_context(root, "spoil prevention after shopping", limit=3)

    assert result["schema_version"] == "retrieval.v2.7"
    assert result["contexts"][0]["claim_id"] == "claim_strawberry_storage"
    assert result["contexts"][0]["source_id"] == "src_strawberry"
    assert result["contexts"][0]["citation_locator"] == "section:storage"
    assert "vector_semantic" in result["contexts"][0]["retrieval_reasons"]
    assert result["diagnostics"]["retrievers"]["vector"]["enabled"] is True
    assert result["diagnostics"]["retrievers"]["vector"]["index_present"] is True
    assert result["diagnostics"]["retrievers"]["vector"]["query_embedded"] is True
    assert result["diagnostics"]["retrievers"]["vector"]["candidate_count"] >= 1
    assert provider.calls == [["spoil prevention after shopping"], ["spoil prevention after shopping"]]


def test_vector_retrieval_falls_back_without_index(monkeypatch):
    root = seed_vector_workspace()

    def fail_provider(*args, **kwargs):
        raise AssertionError("missing vector index must not call embedding provider")

    monkeypatch.setattr("llmwiki.embeddings.create_embedding_provider", fail_provider)

    result = retrieve_context(root, "vitamin C", limit=3)

    assert any(context["claim_id"] == "claim_strawberry_vitamin" for context in result["contexts"])
    assert result["diagnostics"]["retrievers"]["vector"]["index_present"] is False
    assert result["diagnostics"]["retrievers"]["vector"]["query_embedded"] is False


def test_vector_retrieval_falls_back_when_provider_fails(monkeypatch):
    root = seed_vector_workspace()
    write_fake_index(root)

    class FailingProvider:
        def embed_texts(self, texts):
            raise RuntimeError("provider failure sk-secret")

    monkeypatch.setattr("llmwiki.embeddings.create_embedding_provider", lambda config, root=None: FailingProvider())

    result = retrieve_context(root, "vitamin C", limit=3)

    assert any(context["claim_id"] == "claim_strawberry_vitamin" for context in result["contexts"])
    assert any("vector retrieval failed" in warning.casefold() for warning in result["warnings"])
    assert "sk-secret" not in "\n".join(result["warnings"])
    assert result["diagnostics"]["retrievers"]["vector"]["failure_stage"] == "query_embedding_failed"


def test_vector_retrieval_falls_back_when_index_dimension_is_invalid(monkeypatch):
    root = seed_vector_workspace()
    write_fake_index(root, dimension=2, bad_dimension=True)
    monkeypatch.setattr(
        "llmwiki.embeddings.create_embedding_provider",
        lambda config, root=None: FakeEmbeddingProvider([1.0, 0.0]),
    )

    result = retrieve_context(root, "vitamin C", limit=3)

    assert any(context["claim_id"] == "claim_strawberry_vitamin" for context in result["contexts"])
    assert any("vector retrieval failed" in warning.casefold() for warning in result["warnings"])
    assert result["diagnostics"]["retrievers"]["vector"]["failure_stage"] == "index_load_failed"


def test_retrieve_cli_includes_vector_diagnostics(monkeypatch, capsys):
    root = seed_vector_workspace()
    write_fake_index(root)
    monkeypatch.setattr(
        "llmwiki.embeddings.create_embedding_provider",
        lambda config, root=None: FakeEmbeddingProvider([1.0, 0.0]),
    )
    capsys.readouterr()

    assert main(["retrieve", "spoil prevention after shopping", "--root", str(root), "--json"]) == 0

    out = capsys.readouterr().out
    assert '"schema_version": "retrieval.v2.7"' in out
    assert '"vector"' in out
    assert "claim_strawberry_storage" in out
