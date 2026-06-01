from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.cli import main
from tests.helpers import make_workspace


def test_load_pdf_parser_config_reads_workspace_defaults():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    from llmwiki.pdf_parser_backends import load_pdf_parser_config

    config = load_pdf_parser_config(root)

    assert config.default_backend == "pypdf"
    assert config.fallback_backend == "pypdf"
    assert config.mineru_enabled is False
    assert config.mineru_command == "mineru"
    assert config.artifact_dir == "sources/parser-artifacts"


def test_select_pypdf_backend_is_available_by_default():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    from llmwiki.pdf_parser_backends import PypdfBackend, select_pdf_parser_backend

    selection = select_pdf_parser_backend(root)

    assert isinstance(selection.backend, PypdfBackend)
    assert selection.backend.name == "pypdf"
    assert selection.fallback_from is None
    assert selection.warnings == []


def test_unknown_pdf_parser_backend_is_rejected():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    from llmwiki.pdf_parser_backends import PdfParserBackendError, select_pdf_parser_backend

    with pytest.raises(PdfParserBackendError, match="Unsupported PDF parser backend"):
        select_pdf_parser_backend(root, requested_backend="does-not-exist")


def test_explicit_mineru_backend_requires_enabled_config():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    from llmwiki.pdf_parser_backends import PdfParserBackendError, select_pdf_parser_backend

    with pytest.raises(PdfParserBackendError, match="MinerU parser backend is disabled"):
        select_pdf_parser_backend(root, requested_backend="mineru")


def test_auto_backend_falls_back_to_pypdf_when_mineru_disabled():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    config_path = root / "config" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace('default_backend = "pypdf"', 'default_backend = "auto"'),
        encoding="utf-8",
        newline="\n",
    )

    from llmwiki.pdf_parser_backends import PypdfBackend, select_pdf_parser_backend

    selection = select_pdf_parser_backend(root)

    assert isinstance(selection.backend, PypdfBackend)
    assert selection.fallback_from == "mineru"
    assert any("falling back to pypdf" in warning for warning in selection.warnings)


def test_pypdf_backend_parse_returns_pdf_parse_result(monkeypatch):
    from llmwiki.pdf_parser_backends import PdfParseRequest, PypdfBackend

    def fake_read_pdf_pages(content: bytes):
        return {"title": "A Test Paper"}, ["A Test Paper\n\nAbstract\nThis paper tests parser backends."]

    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", fake_read_pdf_pages)
    request = PdfParseRequest(
        root=Path("."),
        source_id="src_parser",
        raw_path=Path("sources/raw/src_parser-test.pdf"),
        filename="test.pdf",
        normalized_path="sources/normalized/src_parser.md",
        metadata_path="sources/metadata/src_parser.json",
        blocks_path="sources/blocks/src_parser.jsonl",
        chunks_path="sources/chunks/src_parser.jsonl",
        content=b"%PDF fake",
        options={},
    )

    result = PypdfBackend().parse(request)

    assert result.backend_name == "pypdf"
    assert result.metadata.title == "A Test Paper"
    assert result.blocks
    assert result.blocks[0].parser_backend == "pypdf"
