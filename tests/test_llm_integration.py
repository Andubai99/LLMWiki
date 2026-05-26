from __future__ import annotations

import os

import pytest

from llmwiki.cli import main
from tests.helpers import make_workspace


def test_llm_test_calls_real_deepseek_api(capsys):
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        pytest.fail("DEEPSEEK_API_KEY is required for the real DeepSeek llm-test integration test")

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    assert main(["llm-test", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "provider=openai" in out
    assert "model=deepseek-v4-pro" in out
    assert "base_url=https://api.deepseek.com" in out
    assert "real_call=true" in out
    assert "content_summary=" in out
    assert api_key not in out
