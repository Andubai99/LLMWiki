from __future__ import annotations

from llmwiki.cli import main
from llmwiki.pdf_blocks import SourceMetadata, load_metadata_json, write_metadata_json
from tests.helpers import make_workspace


def test_workspace_init_creates_parser_artifact_directory():
    root = make_workspace()

    assert main(["init", "--root", str(root)]) == 0

    assert (root / "sources" / "parser-artifacts").is_dir()


def test_gitignore_preserves_parser_artifact_skeleton():
    gitignore = open(".gitignore", encoding="utf-8").read()

    assert "sources/parser-artifacts/*" in gitignore
    assert "!sources/parser-artifacts/.gitkeep" in gitignore


def test_metadata_roundtrip_preserves_parser_artifact_fields(tmp_path):
    metadata = SourceMetadata(
        source_id="src_artifacts",
        title="Artifact Paper",
        source_type="pdf",
        page_count=2,
        raw_path="sources/raw/src_artifacts.pdf",
        normalized_path="sources/normalized/src_artifacts.md",
        metadata_path="sources/metadata/src_artifacts.json",
        blocks_path="sources/blocks/src_artifacts.jsonl",
        chunks_path="sources/chunks/src_artifacts.jsonl",
        filename="paper.pdf",
        parser_backend="mineru",
        parser_backend_version="test-version",
        parser_backend_options={"mode": "fixture"},
        parser_artifact_paths=["sources/parser-artifacts/src_artifacts/mineru/content_list.json"],
        parser_backend_warnings=["fallback disabled"],
        parser_backend_fallback_from="mineru",
        parser_backend_fallback_reason="fixture fallback",
        structured_block_counts={"table_like": 1, "equation_like": 2},
    )
    path = tmp_path / "metadata.json"

    write_metadata_json(path, metadata)
    loaded = load_metadata_json(path)

    assert loaded.parser_backend == "mineru"
    assert loaded.parser_backend_version == "test-version"
    assert loaded.parser_artifact_paths == ["sources/parser-artifacts/src_artifacts/mineru/content_list.json"]
    assert loaded.parser_backend_warnings == ["fallback disabled"]
    assert loaded.parser_backend_fallback_from == "mineru"
    assert loaded.parser_backend_fallback_reason == "fixture fallback"
    assert loaded.structured_block_counts == {"table_like": 1, "equation_like": 2}
