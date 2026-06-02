from __future__ import annotations

import json

from llmwiki.cli import main
from llmwiki.workspace import init_workspace
from tests.helpers import make_workspace


def test_parsers_status_reports_configured_backends(monkeypatch, capsys):
    root = make_workspace()
    init_workspace(root)
    monkeypatch.setattr("shutil.which", lambda command: "C:/Tools/mineru.exe" if command == "mineru" else None)
    capsys.readouterr()

    assert main(["parsers", "status", "--root", str(root)]) == 0

    out = capsys.readouterr().out
    assert "default_backend=auto" in out
    assert "fallback_backend=pypdf" in out
    assert "mineru_enabled=true" in out
    assert "mineru_available=true" in out
    assert "mineru_command_source=PATH" in out
    assert "mineru_command=mineru" in out
    assert "pypdf_available=true" in out
    assert "artifact_dir=sources/parser-artifacts" in out


def test_parsers_status_discovers_workspace_local_mineru(monkeypatch, capsys):
    root = make_workspace()
    init_workspace(root)
    mineru = root / ".venv" / "Scripts" / "mineru.exe"
    mineru.parent.mkdir(parents=True)
    mineru.write_text("mineru", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda command: None)
    capsys.readouterr()

    assert main(["parsers", "status", "--root", str(root), "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == "parser_status.v2.9.6"
    assert data["mineru_available"] is True
    assert data["mineru_command_path"] == str(mineru)
    assert data["mineru_command_source"] == "workspace_venv"


def test_parsers_status_json_is_stable_and_read_only(monkeypatch, capsys):
    root = make_workspace()
    init_workspace(root)
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

    def forbidden(*args, **kwargs):
        raise AssertionError("status must not run MinerU on a document")

    monkeypatch.setattr("shutil.which", lambda command: None)
    monkeypatch.setattr("subprocess.run", forbidden)
    capsys.readouterr()

    assert main(["parsers", "status", "--root", str(root), "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    assert before == after
    assert data["schema_version"] == "parser_status.v2.9.6"
    assert data["default_backend"] == "auto"
    assert data["fallback_backend"] == "pypdf"
    assert data["mineru_enabled"] is True
    assert data["mineru_available"] is False
    assert data["mineru_command_source"] == "not_found"
    assert data["warnings"]
    assert data["pypdf_available"] is True
    assert data["artifact_dir"] == "sources/parser-artifacts"
