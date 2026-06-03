from __future__ import annotations

from pathlib import Path

from llmwiki.cli import COMMANDS, build_parser, main
from tests.helpers import make_workspace


def write_file(path: Path, text: str = "# Paper\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_cli_includes_corpus_command_group() -> None:
    parser = build_parser()
    help_text = parser.format_help()

    assert "corpus" in COMMANDS
    assert "Manage corpus import batches." in help_text
    args = parser.parse_args(["corpus", "inventory", "--root", ".", "--json"])
    assert args.corpus_command == "inventory"
    assert args.json is True


def test_corpus_import_dry_run_is_read_only(monkeypatch, capsys) -> None:
    import llmwiki.corpus.runner as runner

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    corpus = root / "papers"
    write_file(corpus / "a.md")

    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("dry-run must not call add pipeline")

    monkeypatch.setattr(runner, "add_and_process_source", forbidden)
    capsys.readouterr()

    assert main(["corpus", "import", str(corpus), "--root", str(root), "--dry-run"]) == 0
    out = capsys.readouterr().out

    assert "Dry run: true" in out
    assert "Would queue: 1" in out
    assert not (root / "state" / "corpus-batches").exists()


def test_corpus_status_without_batches_is_read_only(monkeypatch, capsys) -> None:
    import llmwiki.corpus.runner as runner

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("status must not call add pipeline")

    monkeypatch.setattr(runner, "add_and_process_source", forbidden)
    capsys.readouterr()

    assert main(["corpus", "status", "--root", str(root)]) == 0
    assert "No corpus batches." in capsys.readouterr().out


def test_corpus_dry_run_and_status_do_not_call_mutating_or_provider_surfaces(monkeypatch, capsys) -> None:
    import llmwiki.cli as cli
    import llmwiki.corpus.runner as runner

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    corpus = root / "papers"
    write_file(corpus / "a.md")

    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("corpus dry-run/status must not call this surface")

    monkeypatch.setattr(runner, "add_and_process_source", forbidden)
    monkeypatch.setattr(cli, "add_and_process_source", forbidden)
    monkeypatch.setattr(cli, "ingest_source", forbidden)
    monkeypatch.setattr(cli, "apply_run", forbidden)
    monkeypatch.setattr(cli, "evaluate_retrieval", forbidden)
    monkeypatch.setattr(cli, "evaluate_pdf_quality", forbidden)
    monkeypatch.setattr(cli, "probe_mineru_status", forbidden)
    monkeypatch.setattr(cli, "create_provider", forbidden)
    capsys.readouterr()

    assert main(["corpus", "import", str(corpus), "--root", str(root), "--dry-run"]) == 0
    assert main(["corpus", "status", "--root", str(root)]) == 0
