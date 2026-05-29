from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from llmwiki.cli import main
from tests.helpers import make_workspace


def _repo_api_key() -> str:
    key_file = Path(__file__).resolve().parents[1] / "config" / "api-keys.toml"
    if not key_file.exists():
        return ""
    data = tomllib.loads(key_file.read_text(encoding="utf-8"))
    llm = data.get("llm", {}) if isinstance(data, dict) else {}
    return str(llm.get("api_key") or "").strip() if isinstance(llm, dict) else ""


def test_llm_test_calls_real_deepseek_api(capsys):
    api_key = _repo_api_key()
    if not api_key:
        pytest.fail("config/api-keys.toml with [llm].api_key is required for the real DeepSeek llm-test integration test")

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "config" / "api-keys.toml").write_text(
        f"[llm]\napi_key = {json.dumps(api_key)}\n",
        encoding="utf-8",
        newline="\n",
    )
    capsys.readouterr()

    assert main(["llm-test", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "provider=openai" in out
    assert "model=deepseek-v4-flash" in out
    assert "base_url=https://api.deepseek.com" in out
    assert "real_call=true" in out
    assert "content_summary=" in out
    assert api_key not in out
