from __future__ import annotations

from pathlib import Path


STATIC_ROOT = Path("src/llmwiki/ui/static")


def read_static(name: str) -> str:
    return (STATIC_ROOT / name).read_text(encoding="utf-8")


def test_index_references_dashboard_assets() -> None:
    html = read_static("index.html")

    assert 'id="dashboard-root"' in html
    assert "/static/app.js" in html
    assert "/static/styles.css" in html
    assert "LLMWiki Dashboard" in html


def test_app_js_fetches_dashboard_api_endpoints() -> None:
    js = read_static("app.js")

    for endpoint in ["/api/status", "/api/sources", "/api/runs", "/api/pages", "/api/config"]:
        assert endpoint in js


def test_static_assets_do_not_embed_secret_markers() -> None:
    combined = "\n".join(read_static(name) for name in ["index.html", "app.js", "styles.css"])

    assert "config/api-keys.toml" not in combined
    assert "sk-" not in combined
