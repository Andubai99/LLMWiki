from __future__ import annotations

from pathlib import Path

from llmwiki.cli import main
from tests.helpers import make_workspace


def test_init_writes_default_llm_config():
    root = make_workspace()

    assert main(["init", "--root", str(root)]) == 0

    config = (root / "config.toml").read_text(encoding="utf-8")
    assert "[llm]" in config
    assert "enabled = true" in config
    assert 'provider = "openai"' in config
    assert 'model = "deepseek-v4-pro"' in config
    assert 'base_url = "https://api.deepseek.com"' in config
    assert 'api_key_env = "DEEPSEEK_API_KEY"' in config
    assert "timeout_seconds = 60" in config


def test_repository_config_has_default_llm_settings():
    config = Path("config.toml").read_text(encoding="utf-8")

    assert "[llm]" in config
    assert "enabled = true" in config
    assert 'provider = "openai"' in config
    assert 'model = "deepseek-v4-pro"' in config
    assert 'base_url = "https://api.deepseek.com"' in config
    assert 'api_key_env = "DEEPSEEK_API_KEY"' in config
    assert "timeout_seconds = 60" in config


def test_openai_provider_requires_api_key_without_leaking_secret(monkeypatch):
    from llmwiki.llm import LLMConfig
    from llmwiki.providers.base import LLMProviderError
    from llmwiki.providers.openai import OpenAIProvider

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OTHER_SECRET", "sk-do-not-print-this")
    provider = OpenAIProvider(
        LLMConfig(
            enabled=True,
            provider="openai",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY",
            timeout_seconds=60,
        )
    )

    try:
        provider.complete([{"role": "user", "content": "hello"}])
    except LLMProviderError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing API key error")

    assert "DEEPSEEK_API_KEY" in message
    assert "Missing API key" in message
    assert "sk-do-not-print-this" not in message


def test_llm_test_reports_missing_api_key_without_leaking_secret(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OTHER_SECRET", "sk-do-not-print-this")
    capsys.readouterr()

    assert main(["llm-test", "--root", str(root)]) == 1
    out = capsys.readouterr().out

    assert "LLM test failed" in out
    assert "DEEPSEEK_API_KEY" in out
    assert "sk-do-not-print-this" not in out
