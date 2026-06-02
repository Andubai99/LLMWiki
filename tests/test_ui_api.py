from __future__ import annotations

from pathlib import Path

from llmwiki.ui.models import (
    ConfigStatusResponse,
    UiWarning,
    WorkspaceStatusResponse,
    sanitize_ui_text,
    workspace_relative_path,
)


def test_sanitize_ui_text_removes_secret_patterns() -> None:
    sanitized = sanitize_ui_text("sk-abc123 config/api-keys.toml api_key=secret")

    assert "sk-" not in sanitized
    assert "config/api-keys.toml" not in sanitized
    assert "api_key=secret" not in sanitized


def test_response_dataclass_to_dict_is_stable() -> None:
    response = WorkspaceStatusResponse(
        status="ready",
        workspace_root=".",
        initialized=True,
        catalog_present=True,
        catalog_ok=True,
        required_paths={"config/config.toml": True},
        counts={"sources": 1},
        latest_runs=[],
        warnings=[UiWarning(level="warning", message="bounded")],
    )

    assert response.to_dict() == {
        "schema_version": "ui.v3.1",
        "status": "ready",
        "workspace_root": ".",
        "initialized": True,
        "catalog_present": True,
        "catalog_ok": True,
        "required_paths": {"config/config.toml": True},
        "counts": {"sources": 1},
        "latest_runs": [],
        "warnings": [{"level": "warning", "message": "bounded", "category": "general"}],
    }


def test_config_status_to_dict_does_not_expose_secret_values() -> None:
    response = ConfigStatusResponse(
        llm={"enabled": True, "provider": "openai", "model": "deepseek", "api_key_present": True},
        embedding={"enabled": True, "provider": "dashscope", "model": "embed", "api_key_present": False},
        parser={"default_backend": "auto", "fallback_backend": "pypdf", "mineru_available": False},
        vector={"index_present": False, "stale": False},
        warnings=[],
    )

    payload = response.to_dict()

    assert payload["schema_version"] == "ui.v3.1"
    assert "api_key" not in repr(payload).replace("api_key_present", "")


def test_workspace_relative_path_bounds_output(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    inside = root / "wiki" / "index.md"
    outside = tmp_path / "elsewhere.md"

    assert workspace_relative_path(root, inside) == "wiki/index.md"
    assert workspace_relative_path(root, outside) == "[outside-workspace]"
