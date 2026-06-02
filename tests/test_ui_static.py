from __future__ import annotations

from pathlib import Path


STATIC_ROOT = Path("src/llmwiki/ui/static")


def read_static(name: str) -> str:
    return (STATIC_ROOT / name).read_text(encoding="utf-8")


def test_index_references_dashboard_assets() -> None:
    html = read_static("index.html")

    assert 'id="dashboard-root"' in html
    assert 'id="add-source-form"' in html
    assert 'id="source-input"' in html
    assert 'id="parser-select"' in html
    assert 'id="jobs-table"' in html
    assert 'id="active-job-strip"' in html
    assert "/static/app.js" in html
    assert "/static/styles.css" in html
    assert "LLMWiki Dashboard" in html


def test_app_js_fetches_dashboard_api_endpoints() -> None:
    js = read_static("app.js")

    for endpoint in ["/api/session", "/api/status", "/api/sources", "/api/runs", "/api/pages", "/api/config", "/api/jobs", "/api/sources/add"]:
        assert endpoint in js
    assert "X-LLMWiki-UI-Token" in js
    assert "setInterval" in js


def test_parser_select_contains_supported_options() -> None:
    html = read_static("index.html")

    for value in ['value=""', 'value="auto"', 'value="pypdf"', 'value="mineru"']:
        assert value in html


def test_static_assets_do_not_embed_secret_markers() -> None:
    combined = "\n".join(read_static(name) for name in ["index.html", "app.js", "styles.css"])

    assert "config/api-keys.toml" not in combined
    assert "sk-" not in combined
