from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def make_config(**overrides):
    from llmwiki.pdf_parser_backends import PdfParserConfig

    values = {
        "mineru_command": "mineru",
        "mineru_method": "",
        "mineru_backend": "",
        "mineru_api_url": "",
        "mineru_timeout_seconds": 1800,
        "mineru_max_log_chars": 40,
        "mineru_extra_args": (),
    }
    values.update(overrides)
    return PdfParserConfig(**values)


def test_build_mineru_command_uses_safe_argument_list(tmp_path):
    from llmwiki.mineru_runner import MinerUCommandRequest, build_mineru_command

    request = MinerUCommandRequest(
        root=tmp_path,
        source_id="src_pdf",
        raw_path=tmp_path / "paper.pdf",
        output_root=tmp_path / "out",
        config=make_config(
            mineru_method="auto",
            mineru_backend="pipeline",
            mineru_api_url="https://example.test/api?api_key=secret",
            mineru_extra_args=("--lang", "en"),
        ),
    )

    command = build_mineru_command(request)

    assert command == [
        "mineru",
        "-p",
        str(tmp_path / "paper.pdf"),
        "-o",
        str(tmp_path / "out"),
        "-m",
        "auto",
        "-b",
        "pipeline",
        "--api-url",
        "https://example.test/api?api_key=secret",
        "--lang",
        "en",
    ]


def test_build_mineru_command_uses_resolved_command(tmp_path):
    from llmwiki.mineru_runner import MinerUCommandRequest, build_mineru_command

    resolved = tmp_path / ".venv" / "Scripts" / "mineru.exe"
    request = MinerUCommandRequest(
        root=tmp_path,
        source_id="src_pdf",
        raw_path=tmp_path / "paper.pdf",
        output_root=tmp_path / "out",
        config=make_config(mineru_command="mineru"),
        resolved_command=str(resolved),
        command_source="workspace_venv",
    )

    command = build_mineru_command(request)

    assert command[0] == str(resolved)


def test_run_mineru_command_uses_shell_false_and_discovers_output(tmp_path):
    from llmwiki.mineru_runner import MinerUCommandRequest, run_mineru_command

    output_root = tmp_path / "artifacts"

    def fake_run(command, **kwargs):
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 1800
        nested = output_root / "paper" / "auto"
        nested.mkdir(parents=True)
        (nested / "content_list.json").write_text("[]", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = run_mineru_command(
        MinerUCommandRequest(
            root=tmp_path,
            source_id="src_pdf",
            raw_path=tmp_path / "paper.pdf",
            output_root=output_root,
            config=make_config(),
            resolved_command=str(tmp_path / ".venv" / "Scripts" / "mineru.exe"),
            command_source="workspace_venv",
        ),
        runner=fake_run,
    )

    assert result.returncode == 0
    assert result.command_source == "workspace_venv"
    assert result.timed_out is False
    assert len(result.content_list_candidates) == 1
    assert result.content_list_candidates[0].name == "content_list.json"


def test_discover_mineru_command_prefers_configured_absolute_path(monkeypatch, tmp_path):
    from llmwiki.mineru_runner import discover_mineru_command

    configured = tmp_path / "tools" / "mineru.exe"
    configured.parent.mkdir()
    configured.write_text("mineru", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda command: str(tmp_path / "wrong.exe"))

    result = discover_mineru_command(tmp_path, make_config(mineru_command=str(configured)))

    assert result.available is True
    assert result.command == str(configured)
    assert result.command_source == "configured_path"


def test_discover_mineru_command_uses_path_when_available(monkeypatch, tmp_path):
    from llmwiki.mineru_runner import discover_mineru_command

    monkeypatch.setattr("shutil.which", lambda command: "C:/Tools/mineru.exe" if command == "mineru" else None)

    result = discover_mineru_command(tmp_path, make_config())

    assert result.available is True
    assert result.command == "C:/Tools/mineru.exe"
    assert result.command_source == "PATH"


def test_discover_mineru_command_finds_workspace_windows_venv(monkeypatch, tmp_path):
    from llmwiki.mineru_runner import discover_mineru_command

    mineru = tmp_path / ".venv" / "Scripts" / "mineru.exe"
    mineru.parent.mkdir(parents=True)
    mineru.write_text("mineru", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda command: None)

    result = discover_mineru_command(tmp_path, make_config())

    assert result.available is True
    assert result.command == str(mineru)
    assert result.command_source == "workspace_venv"


def test_discover_mineru_command_finds_workspace_posix_venv(monkeypatch, tmp_path):
    from llmwiki.mineru_runner import discover_mineru_command

    mineru = tmp_path / ".venv" / "bin" / "mineru"
    mineru.parent.mkdir(parents=True)
    mineru.write_text("mineru", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda command: None)

    result = discover_mineru_command(tmp_path, make_config())

    assert result.available is True
    assert result.command == str(mineru)
    assert result.command_source == "workspace_venv"


def test_discover_mineru_command_not_found(monkeypatch, tmp_path):
    from llmwiki.mineru_runner import discover_mineru_command

    monkeypatch.setattr("shutil.which", lambda command: None)

    result = discover_mineru_command(tmp_path, make_config(mineru_command="missing-mineru"))

    assert result.available is False
    assert result.command == "missing-mineru"
    assert result.command_source == "not_found"
    assert result.warnings


def test_sanitize_parser_log_redacts_secrets_and_truncates():
    from llmwiki.mineru_runner import sanitize_parser_log

    text = "token sk-1234567890abcdef api_key=very-secret config/api-keys.toml " + ("x" * 100)

    sanitized = sanitize_parser_log(text, max_chars=50)

    assert "sk-123" not in sanitized
    assert "very-secret" not in sanitized
    assert "config/api-keys.toml" not in sanitized
    assert len(sanitized) <= 50
    assert "[redacted" in sanitized


def test_discover_and_select_content_lists_prefers_nonempty_v1(tmp_path):
    from llmwiki.mineru_runner import discover_mineru_content_lists, select_mineru_content_list

    (tmp_path / "paper" / "v2").mkdir(parents=True)
    (tmp_path / "paper" / "v2" / "content_list_v2.json").write_text("[1]", encoding="utf-8")
    (tmp_path / "paper" / "auto").mkdir(parents=True)
    expected = tmp_path / "paper" / "auto" / "paper_content_list.json"
    expected.write_text("[2]", encoding="utf-8")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "content_list.json").write_text("", encoding="utf-8")

    candidates = discover_mineru_content_lists(tmp_path, pdf_stem="paper")

    assert expected in candidates
    assert select_mineru_content_list(candidates, pdf_stem="paper") == expected


def test_select_content_list_rejects_ambiguous_candidates(tmp_path):
    from llmwiki.mineru_runner import MinerUCommandError, select_mineru_content_list

    first = tmp_path / "a" / "content_list.json"
    second = tmp_path / "b" / "content_list.json"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("[1]", encoding="utf-8")
    second.write_text("[2]", encoding="utf-8")

    with pytest.raises(MinerUCommandError, match="Ambiguous MinerU content-list outputs"):
        select_mineru_content_list([first, second], pdf_stem="paper")


def test_run_mineru_command_timeout_is_safe(tmp_path):
    from llmwiki.mineru_runner import MinerUCommandRequest, run_mineru_command

    def timeout_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=1, output="sk-timeout-secret", stderr="config/api-keys.toml")

    result = run_mineru_command(
        MinerUCommandRequest(
            root=tmp_path,
            source_id="src_pdf",
            raw_path=tmp_path / "paper.pdf",
            output_root=tmp_path / "out",
            config=make_config(mineru_timeout_seconds=1),
        ),
        runner=timeout_run,
    )

    assert result.returncode == -1
    assert result.timed_out is True
    assert "timed out" in " ".join(result.warnings).lower()
    assert "sk-timeout-secret" not in result.stdout_snippet
    assert "config/api-keys.toml" not in result.stderr_snippet
