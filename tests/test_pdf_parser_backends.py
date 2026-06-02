from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.cli import main
from llmwiki.pdf_blocks import parse_pdf_source
from tests.helpers import make_workspace


def test_load_pdf_parser_config_reads_workspace_defaults():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    from llmwiki.pdf_parser_backends import load_pdf_parser_config

    config = load_pdf_parser_config(root)

    assert config.default_backend == "auto"
    assert config.fallback_backend == "pypdf"
    assert config.mineru_enabled is True
    assert config.mineru_command == "mineru"
    assert config.mineru_method == ""
    assert config.mineru_backend == ""
    assert config.mineru_api_url == ""
    assert config.mineru_timeout_seconds == 1800
    assert config.mineru_max_log_chars == 4000
    assert config.mineru_extra_args == ()
    assert config.artifact_dir == "sources/parser-artifacts"


def test_select_default_auto_backend_falls_back_to_pypdf_when_mineru_unavailable(monkeypatch):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    config_path = root / "config" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace('mineru_command = "mineru"', 'mineru_command = "missing-mineru"'),
        encoding="utf-8",
        newline="\n",
    )

    from llmwiki.pdf_parser_backends import PypdfBackend, select_pdf_parser_backend

    monkeypatch.setattr("shutil.which", lambda command: None)
    selection = select_pdf_parser_backend(root)

    assert isinstance(selection.backend, PypdfBackend)
    assert selection.backend.name == "pypdf"
    assert selection.fallback_from == "mineru"
    assert any("falling back to pypdf" in warning for warning in selection.warnings)


def test_unknown_pdf_parser_backend_is_rejected():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    from llmwiki.pdf_parser_backends import PdfParserBackendError, select_pdf_parser_backend

    with pytest.raises(PdfParserBackendError, match="Unsupported PDF parser backend"):
        select_pdf_parser_backend(root, requested_backend="does-not-exist")


def test_explicit_mineru_backend_requires_enabled_config():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    config_path = root / "config" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("mineru_enabled = true", "mineru_enabled = false"),
        encoding="utf-8",
        newline="\n",
    )

    from llmwiki.pdf_parser_backends import PdfParserBackendError, select_pdf_parser_backend

    with pytest.raises(PdfParserBackendError, match="MinerU parser backend is disabled"):
        select_pdf_parser_backend(root, requested_backend="mineru")


def test_auto_backend_falls_back_to_pypdf_when_mineru_disabled():
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    config_path = root / "config" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("mineru_enabled = true", "mineru_enabled = false"),
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


def test_auto_backend_invokes_mineru_runner_and_parses_nested_output(monkeypatch, tmp_path):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    fixture = Path("tests/fixtures/mineru")

    monkeypatch.setattr("shutil.which", lambda command: "C:/Tools/mineru.exe")

    def fake_run_mineru(request):
        nested = request.output_root / "paper" / "auto"
        nested.mkdir(parents=True)
        (nested / "content_list.json").write_text((fixture / "content_list.json").read_text(encoding="utf-8"), encoding="utf-8")
        from llmwiki.mineru_runner import MinerUCommandResult

        return MinerUCommandResult(
            command=["mineru", "-p", str(request.raw_path), "-o", str(request.output_root)],
            output_root=request.output_root,
            returncode=0,
            duration_seconds=0.25,
            stdout_snippet="ok",
            stderr_snippet="",
            content_list_candidates=[nested / "content_list.json"],
        )

    monkeypatch.setattr("llmwiki.mineru_runner.run_mineru_command", fake_run_mineru)

    result = parse_pdf_source(
        source_id="src_auto_mineru",
        content=b"%PDF fake",
        filename="paper.pdf",
        raw_path="sources/raw/src_auto_mineru-paper.pdf",
        normalized_path="sources/normalized/src_auto_mineru.md",
        metadata_path="sources/metadata/src_auto_mineru.json",
        blocks_path="sources/blocks/src_auto_mineru.jsonl",
        chunks_path="sources/chunks/src_auto_mineru.jsonl",
        root=root,
    )

    assert result.metadata.parser_backend == "mineru"
    assert result.metadata.title == "MinerU Structured Parsing Paper"
    assert result.metadata.parser_command_invoked is True
    assert result.metadata.parser_content_list_path.endswith("content_list.json")
    assert result.metadata.parser_backend_fallback_from is None


def test_auto_backend_falls_back_to_pypdf_when_mineru_parse_fails(monkeypatch):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    monkeypatch.setattr("shutil.which", lambda command: "C:/Tools/mineru.exe")

    def failing_run(request):
        from llmwiki.mineru_runner import MinerUCommandResult

        return MinerUCommandResult(
            command=["mineru"],
            output_root=request.output_root,
            returncode=1,
            duration_seconds=0.1,
            stdout_snippet="",
            stderr_snippet="failed",
            warnings=["MinerU command exited with code 1"],
        )

    def fake_read_pdf_pages(content: bytes):
        return {"title": "Fallback Paper"}, ["Fallback Paper\n\nAbstract\nFallback text."]

    monkeypatch.setattr("llmwiki.mineru_runner.run_mineru_command", failing_run)
    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", fake_read_pdf_pages)

    result = parse_pdf_source(
        source_id="src_auto_fallback",
        content=b"%PDF fake",
        filename="fallback.pdf",
        raw_path="sources/raw/src_auto_fallback-paper.pdf",
        normalized_path="sources/normalized/src_auto_fallback.md",
        metadata_path="sources/metadata/src_auto_fallback.json",
        blocks_path="sources/blocks/src_auto_fallback.jsonl",
        chunks_path="sources/chunks/src_auto_fallback.jsonl",
        root=root,
    )

    assert result.metadata.parser_backend == "pypdf"
    assert result.metadata.parser_backend_fallback_from == "mineru"
    assert "MinerU" in result.metadata.parser_backend_fallback_reason


def test_explicit_pypdf_does_not_invoke_mineru(monkeypatch):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    monkeypatch.setattr("shutil.which", lambda command: "C:/Tools/mineru.exe")
    monkeypatch.setattr(
        "llmwiki.mineru_runner.discover_mineru_command",
        lambda root, config: (_ for _ in ()).throw(AssertionError("explicit pypdf must not discover MinerU")),
    )
    monkeypatch.setattr(
        "llmwiki.mineru_runner.run_mineru_command",
        lambda request: (_ for _ in ()).throw(AssertionError("explicit pypdf must not run MinerU")),
    )

    def fake_read_pdf_pages(content: bytes):
        return {"title": "Pypdf Paper"}, ["Pypdf Paper\n\nAbstract\nOnly pypdf."]

    monkeypatch.setattr("llmwiki.pdf_blocks.read_pdf_pages", fake_read_pdf_pages)

    result = parse_pdf_source(
        source_id="src_explicit_pypdf",
        content=b"%PDF fake",
        filename="pypdf.pdf",
        raw_path="sources/raw/src_explicit_pypdf-paper.pdf",
        normalized_path="sources/normalized/src_explicit_pypdf.md",
        metadata_path="sources/metadata/src_explicit_pypdf.json",
        blocks_path="sources/blocks/src_explicit_pypdf.jsonl",
        chunks_path="sources/chunks/src_explicit_pypdf.jsonl",
        root=root,
        parser_backend="pypdf",
    )

    assert result.metadata.parser_backend == "pypdf"
