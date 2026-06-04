from __future__ import annotations

from pathlib import Path

from llmwiki.cli import COMMANDS, build_parser, main


def test_build_parser_includes_ui_command() -> None:
    parser = build_parser()
    help_text = parser.format_help()

    assert "ui" in COMMANDS
    assert "Start the local dashboard UI." in help_text


def test_ui_command_passes_server_arguments(monkeypatch, tmp_path) -> None:
    import llmwiki.cli as cli

    calls: list[dict[str, object]] = []

    def fake_serve_ui(root: Path, host: str, port: int, open_browser: bool) -> None:
        calls.append(
            {
                "root": root,
                "host": host,
                "port": port,
                "open_browser": open_browser,
            }
        )

    monkeypatch.setattr(cli, "serve_ui", fake_serve_ui)

    assert main(["ui", "--root", str(tmp_path), "--host", "127.0.0.2", "--port", "9999", "--no-open"]) == 0

    assert calls == [
        {
            "root": tmp_path.resolve(),
            "host": "127.0.0.2",
            "port": 9999,
            "open_browser": False,
        }
    ]


def test_ui_command_does_not_call_mutating_or_provider_surfaces(monkeypatch, tmp_path) -> None:
    import llmwiki.cli as cli

    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("ui command must not call this surface")

    monkeypatch.setattr(cli, "serve_ui", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "add_and_process_source", forbidden)
    monkeypatch.setattr(cli, "ingest_source", forbidden)
    monkeypatch.setattr(cli, "apply_run", forbidden)
    monkeypatch.setattr(cli, "lint_workspace", forbidden)
    monkeypatch.setattr(cli, "evaluate_retrieval", forbidden)
    monkeypatch.setattr(cli, "evaluate_pdf_quality", forbidden)
    monkeypatch.setattr(cli, "probe_mineru_status", forbidden)
    monkeypatch.setattr(cli, "create_provider", forbidden)

    assert main(["ui", "--root", str(tmp_path), "--no-open"]) == 0
