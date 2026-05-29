from __future__ import annotations

import sqlite3

from llmwiki.cli import build_parser, main
from llmwiki.vector_index import load_vector_index
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
                "src_banana",
                "Banana Notes",
                "markdown",
                "sources/raw/banana.md",
                "sources/normalized/banana.md",
                "sha-banana",
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
                "claim_banana_energy",
                "src_banana",
                "Bananas can provide quick energy after exercise.",
                "section:energy",
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
                "concept_banana",
                "wiki/concepts/banana.md",
                "concept",
                "Banana",
                '["香蕉"]',
                "2026-05-29T00:00:00Z",
            ),
        )


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(index + 1), 0.0, 0.0] for index, _ in enumerate(texts)]


def write_embedding_key(root, key: str = "sk-local-embedding-secret") -> None:
    (root / "config" / "api-keys.toml").write_text(
        f'[llm]\napi_key = ""\n\n[embedding]\napi_key = "{key}"\n',
        encoding="utf-8",
        newline="\n",
    )


def test_embeddings_status_reports_missing_index_without_provider_call(capsys):
    root = make_workspace()
    init_workspace(root)
    capsys.readouterr()

    assert main(["embeddings", "status", "--root", str(root)]) == 0

    out = capsys.readouterr().out
    assert "enabled=true" in out
    assert "index_present=false" in out
    assert "stale=true" in out


def test_embeddings_test_calls_provider_without_writing_index(monkeypatch, capsys):
    root = make_workspace()
    init_workspace(root)
    write_embedding_key(root)
    provider = FakeEmbeddingProvider()
    monkeypatch.setattr("llmwiki.embeddings.create_embedding_provider", lambda config, root=None: provider)
    capsys.readouterr()

    assert main(["embeddings", "test", "--root", str(root), "--text", "草莓应该怎么保存？"]) == 0

    out = capsys.readouterr().out
    assert provider.calls == [["草莓应该怎么保存？"]]
    assert "status=ok" in out
    assert "provider=dashscope_multimodal" in out
    assert "model=tongyi-embedding-vision-flash-2026-03-06" in out
    assert "dimension=3" in out
    assert "sk-local-embedding-secret" not in out
    assert not (root / "state" / "embeddings" / "manifest.json").exists()


def test_embeddings_rebuild_writes_index_in_batches(monkeypatch, capsys):
    root = make_workspace()
    seed_catalog(root)
    write_embedding_key(root)
    provider = FakeEmbeddingProvider()
    monkeypatch.setattr("llmwiki.embeddings.create_embedding_provider", lambda config, root=None: provider)
    capsys.readouterr()

    assert main(["embeddings", "rebuild", "--root", str(root), "--batch-size", "2"]) == 0

    out = capsys.readouterr().out
    index = load_vector_index(root)
    assert "status=rebuilt" in out
    assert index.manifest.provider == "dashscope_multimodal"
    assert index.manifest.model == "tongyi-embedding-vision-flash-2026-03-06"
    assert index.manifest.dimension == 3
    assert index.manifest.chunk_count == len(index.chunks)
    assert len(index.vectors) == len(index.chunks)
    assert provider.calls
    assert all(len(call) <= 2 for call in provider.calls)


def test_embeddings_test_missing_key_is_safe(capsys):
    root = make_workspace()
    init_workspace(root)
    capsys.readouterr()

    assert main(["embeddings", "test", "--root", str(root), "--text", "hello"]) == 1

    out = capsys.readouterr().out
    assert "Embedding test failed" in out
    assert "sk-" not in out
    assert "config/api-keys.toml" not in out


def test_embeddings_help_is_registered():
    help_text = build_parser().format_help()

    assert "embeddings" in help_text
