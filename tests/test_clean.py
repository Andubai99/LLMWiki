from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from llmwiki.cli import main
from llmwiki.maintenance.clean import clean_workspace


@pytest.fixture
def temp_workspace():
    base = Path(tempfile.gettempdir()) / f"llmwiki-clean-{uuid.uuid4().hex}"
    base.mkdir()
    root = base / "workspace"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(base, ignore_errors=True)


def write_file(path: Path, text: str = "generated") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def seed_dirty_workspace(root: Path) -> dict[str, Path]:
    paths = {
        "test_workspace": write_file(root / ".test-workspaces" / "run" / "out.txt"),
        "pytest_cache": write_file(root / ".pytest_cache" / "v" / "cache.txt"),
        "tmp_workspace": write_file(root / ".tmp" / "papers" / "out.txt"),
        "pycache": write_file(root / "llmwiki" / "__pycache__" / "module.pyc"),
        "raw": write_file(root / "sources" / "raw" / "src_a-paper.pdf"),
        "normalized": write_file(root / "sources" / "normalized" / "src_a.md"),
        "metadata": write_file(root / "sources" / "metadata" / "src_a.json"),
        "blocks": write_file(root / "sources" / "blocks" / "src_a.jsonl"),
        "chunks": write_file(root / "sources" / "chunks" / "src_a.jsonl"),
        "parser_artifact": write_file(root / "sources" / "parser-artifacts" / "src_a" / "content_list.json"),
        "staging": write_file(root / "staging" / "run_src_a" / "run.json"),
        "catalog": write_file(root / "state" / "catalog.sqlite"),
        "corpus_batch": write_file(root / "state" / "corpus-batches" / "batch_a" / "batch.json"),
        "embedding": write_file(root / "state" / "embeddings" / "vectors.jsonl"),
        "ui_job": write_file(root / "state" / "ui-jobs" / "job.json"),
        "wiki_source": write_file(root / "wiki" / "sources" / "src_a.md"),
        "wiki_concept": write_file(root / "wiki" / "concepts" / "concept.md"),
        "wiki_entity": write_file(root / "wiki" / "entities" / "entity.md"),
        "wiki_synthesis": write_file(root / "wiki" / "syntheses" / "synthesis.md"),
        "wiki_index": write_file(root / "wiki" / "index.md"),
        "wiki_log": write_file(root / "wiki" / "log.md"),
        "api_keys": write_file(root / "config" / "api-keys.toml", "[llm]\napi_key='sk-local'\n"),
        "paper": write_file(root / "docs" / "papers" / "paper.pdf"),
        "venv": write_file(root / ".venv" / "Scripts" / "python.exe"),
        "thinking": write_file(root / "LLM Wiki 思考.md"),
    }
    for keep_dir in (
        root / "sources" / "raw",
        root / "sources" / "normalized",
        root / "sources" / "metadata",
        root / "sources" / "blocks",
        root / "sources" / "chunks",
        root / "sources" / "parser-artifacts",
        root / "staging",
        root / "state" / "corpus-batches",
        root / "state" / "embeddings",
        root / "state" / "ui-jobs",
        root / "wiki" / "sources",
        root / "wiki" / "concepts",
        root / "wiki" / "entities",
        root / "wiki" / "syntheses",
    ):
        write_file(keep_dir / ".gitkeep", "")
    return paths


def test_clean_default_removes_cache_only(temp_workspace, capsys):
    root = temp_workspace
    paths = seed_dirty_workspace(root)

    assert main(["clean", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "Cleaned scope: cache" in out
    for key in ("test_workspace", "pytest_cache", "tmp_workspace", "pycache"):
        assert not paths[key].exists()
    for key in (
        "raw",
        "normalized",
        "metadata",
        "blocks",
        "chunks",
        "parser_artifact",
        "staging",
        "catalog",
        "corpus_batch",
        "embedding",
        "ui_job",
        "wiki_source",
        "wiki_concept",
        "wiki_entity",
        "wiki_synthesis",
        "wiki_index",
        "wiki_log",
        "api_keys",
        "paper",
        "venv",
        "thinking",
    ):
        assert paths[key].exists()


def test_clean_generated_preserves_gitkeep_and_user_files(temp_workspace, capsys):
    root = temp_workspace
    paths = seed_dirty_workspace(root)

    assert main(["clean", "--root", str(root), "--scope", "generated"]) == 0
    out = capsys.readouterr().out

    assert "Cleaned scope: generated" in out
    for key in (
        "raw",
        "normalized",
        "metadata",
        "blocks",
        "chunks",
        "parser_artifact",
        "staging",
        "catalog",
        "corpus_batch",
        "embedding",
        "ui_job",
        "wiki_source",
        "wiki_concept",
        "wiki_entity",
        "wiki_synthesis",
        "wiki_index",
        "wiki_log",
    ):
        assert not paths[key].exists()
    for keep in (
        root / "sources" / "raw" / ".gitkeep",
        root / "sources" / "normalized" / ".gitkeep",
        root / "sources" / "metadata" / ".gitkeep",
        root / "sources" / "blocks" / ".gitkeep",
        root / "sources" / "chunks" / ".gitkeep",
        root / "sources" / "parser-artifacts" / ".gitkeep",
        root / "staging" / ".gitkeep",
        root / "state" / "corpus-batches" / ".gitkeep",
        root / "state" / "embeddings" / ".gitkeep",
        root / "state" / "ui-jobs" / ".gitkeep",
        root / "wiki" / "sources" / ".gitkeep",
        root / "wiki" / "concepts" / ".gitkeep",
        root / "wiki" / "entities" / ".gitkeep",
        root / "wiki" / "syntheses" / ".gitkeep",
    ):
        assert keep.exists()
    for key in ("api_keys", "paper", "venv", "thinking", "test_workspace", "pytest_cache", "tmp_workspace"):
        assert paths[key].exists()


def test_clean_all_removes_cache_and_generated(temp_workspace, capsys):
    root = temp_workspace
    paths = seed_dirty_workspace(root)

    assert main(["clean", "--root", str(root), "--scope", "all"]) == 0
    out = capsys.readouterr().out

    assert "Cleaned scope: all" in out
    for key in (
        "test_workspace",
        "pytest_cache",
        "tmp_workspace",
        "pycache",
        "raw",
        "normalized",
        "metadata",
        "blocks",
        "chunks",
        "parser_artifact",
        "staging",
        "catalog",
        "corpus_batch",
        "embedding",
        "ui_job",
        "wiki_source",
        "wiki_concept",
        "wiki_entity",
        "wiki_synthesis",
        "wiki_index",
        "wiki_log",
    ):
        assert not paths[key].exists()
    for key in ("api_keys", "paper", "venv", "thinking"):
        assert paths[key].exists()


def test_clean_cache_prunes_large_generated_and_user_dirs(temp_workspace):
    root = temp_workspace
    project_pycache = write_file(root / "src" / "llmwiki" / "__pycache__" / "module.pyc")
    venv_pycache = write_file(root / ".venv" / "Lib" / "site-packages" / "pkg" / "__pycache__" / "pkg.pyc")
    git_pycache = write_file(root / ".git" / "objects" / "__pycache__" / "object.pyc")
    paper_pycache = write_file(root / "docs" / "papers" / "__pycache__" / "paper.pyc")
    doc_pycache = write_file(root / "docs" / "superpowers" / "__pycache__" / "doc.pyc")
    raw_pycache = write_file(root / "sources" / "raw" / "__pycache__" / "source.pyc")
    wiki_pycache = write_file(root / "wiki" / "concepts" / "__pycache__" / "wiki.pyc")
    state_pycache = write_file(root / "state" / "__pycache__" / "state.pyc")

    clean_workspace(root, scope="cache")

    assert not project_pycache.exists()
    assert venv_pycache.exists()
    assert git_pycache.exists()
    assert paper_pycache.exists()
    assert doc_pycache.exists()
    assert raw_pycache.exists()
    assert wiki_pycache.exists()
    assert state_pycache.exists()


def test_clean_all_preserves_generated_directory_skeleton(temp_workspace):
    root = temp_workspace
    seed_dirty_workspace(root)

    clean_workspace(root, scope="all")

    for directory in (
        root / "sources" / "raw",
        root / "sources" / "normalized",
        root / "sources" / "metadata",
        root / "sources" / "blocks",
        root / "sources" / "chunks",
        root / "sources" / "parser-artifacts",
        root / "staging",
        root / "state" / "embeddings",
        root / "state" / "ui-jobs",
        root / "wiki" / "sources",
        root / "wiki" / "concepts",
        root / "wiki" / "entities",
        root / "wiki" / "syntheses",
    ):
        assert directory.is_dir()


def test_clean_dry_run_does_not_delete(temp_workspace, capsys):
    root = temp_workspace
    paths = seed_dirty_workspace(root)

    assert main(["clean", "--root", str(root), "--scope", "all", "--dry-run"]) == 0
    out = capsys.readouterr().out

    assert "Dry run: true" in out
    assert "Would remove:" in out
    for path in paths.values():
        assert path.exists()


def test_clean_logic_lives_in_maintenance_domain(temp_workspace):
    root = temp_workspace
    paths = seed_dirty_workspace(root)

    result = clean_workspace(root, scope="cache")

    assert result.scope == "cache"
    assert not paths["test_workspace"].exists()
    assert paths["raw"].exists()
