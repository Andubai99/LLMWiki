from __future__ import annotations

from http.client import IncompleteRead
from pathlib import Path

from llmwiki.cli import main
from tests.helpers import make_workspace


def test_init_writes_default_llm_config():
    root = make_workspace()

    assert main(["init", "--root", str(root)]) == 0

    config = (root / "config" / "config.toml").read_text(encoding="utf-8")
    assert "[llm]" in config
    assert "enabled = true" in config
    assert 'provider = "openai"' in config
    assert 'model = "deepseek-v4-pro"' in config
    assert 'base_url = "https://api.deepseek.com"' in config
    assert 'api_key_file = "config/api-keys.toml"' in config
    assert "timeout_seconds = 60" in config
    assert (root / "config" / "api-keys.toml").exists()
    assert (root / "config" / "api-keys.example.toml").exists()


def test_repository_config_has_default_llm_settings():
    assert not Path("config.toml").exists()
    config = Path("config/config.toml").read_text(encoding="utf-8")
    api_keys_example = Path("config/api-keys.example.toml").read_text(encoding="utf-8")

    assert "[llm]" in config
    assert "enabled = true" in config
    assert 'provider = "openai"' in config
    assert 'model = "deepseek-v4-pro"' in config
    assert 'base_url = "https://api.deepseek.com"' in config
    assert 'api_key_file = "config/api-keys.toml"' in config
    assert "timeout_seconds = 60" in config
    assert "[llm]" in api_keys_example
    assert "api_key" in api_keys_example


def test_openai_provider_reads_api_key_from_local_file(monkeypatch):
    root = make_workspace()
    key_path = root / "config" / "api-keys.toml"
    key_path.parent.mkdir(parents=True)
    key_path.write_text('[llm]\napi_key = "sk-local-secret"\n', encoding="utf-8")

    from llmwiki.llm import LLMConfig
    from llmwiki.providers.openai import OpenAIProvider

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-should-not-be-used")
    provider = OpenAIProvider(
        LLMConfig(
            enabled=True,
            provider="openai",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            api_key_file="config/api-keys.toml",
            timeout_seconds=60,
        ),
        root=root,
    )
    seen: dict[str, str] = {}

    def fake_post(payload, api_key):
        assert payload["thinking"] == {"type": "disabled"}
        seen["api_key"] = api_key
        return {
            "model": "deepseek-v4-pro",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        }

    monkeypatch.setattr(provider, "_post_chat_completion", fake_post)

    result = provider.complete([{"role": "user", "content": "hello"}])

    assert result["content"] == "ok"
    assert seen["api_key"] == "sk-local-secret"


def test_openai_provider_requests_json_object_when_schema_is_supplied(monkeypatch):
    root = make_workspace()
    key_path = root / "config" / "api-keys.toml"
    key_path.parent.mkdir(parents=True)
    key_path.write_text('[llm]\napi_key = "sk-local-secret"\n', encoding="utf-8")

    from llmwiki.llm import LLMConfig
    from llmwiki.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        LLMConfig(
            enabled=True,
            provider="openai",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            api_key_file="config/api-keys.toml",
            timeout_seconds=60,
        ),
        root=root,
    )
    seen: dict[str, object] = {}

    def fake_post(payload, api_key):
        seen.update(payload)
        return {
            "model": "deepseek-v4-pro",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {},
        }

    monkeypatch.setattr(provider, "_post_chat_completion", fake_post)

    provider.complete(
        [{"role": "user", "content": "return json"}],
        schema={"type": "object"},
    )

    assert seen["response_format"] == {"type": "json_object"}
    assert seen["thinking"] == {"type": "disabled"}


def test_openai_provider_requires_local_api_key_file_without_leaking_secret(monkeypatch):
    root = make_workspace()

    from llmwiki.llm import LLMConfig
    from llmwiki.providers.base import LLMProviderError
    from llmwiki.providers.openai import OpenAIProvider

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-should-not-print-this")
    monkeypatch.setenv("OTHER_SECRET", "sk-other-do-not-print-this")
    provider = OpenAIProvider(
        LLMConfig(
            enabled=True,
            provider="openai",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            api_key_file="config/api-keys.toml",
            timeout_seconds=60,
        ),
        root=root,
    )

    try:
        provider.complete([{"role": "user", "content": "hello"}])
    except LLMProviderError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing API key error")

    assert "config/api-keys.toml" in message
    assert "Missing API key" in message
    assert "DEEPSEEK_API_KEY" not in message
    assert "sk-env-should-not-print-this" not in message
    assert "sk-other-do-not-print-this" not in message


def test_llm_test_reports_missing_api_key_without_leaking_secret(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-should-not-print-this")
    monkeypatch.setenv("OTHER_SECRET", "sk-other-do-not-print-this")
    capsys.readouterr()

    assert main(["llm-test", "--root", str(root)]) == 1
    out = capsys.readouterr().out

    assert "LLM test failed" in out
    assert "config/api-keys.toml" in out
    assert "DEEPSEEK_API_KEY" not in out
    assert "sk-env-should-not-print-this" not in out
    assert "sk-other-do-not-print-this" not in out


def test_openai_provider_wraps_incomplete_response_without_leaking_secret(monkeypatch):
    from llmwiki.llm import LLMConfig
    from llmwiki.providers.base import LLMProviderError
    from llmwiki.providers.openai import OpenAIProvider

    class BrokenResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            raise IncompleteRead(b"partial")

    def fake_urlopen(request, timeout):
        return BrokenResponse()

    monkeypatch.setattr("llmwiki.providers.openai.urlopen", fake_urlopen)
    provider = OpenAIProvider(
        LLMConfig(
            enabled=True,
            provider="openai",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            api_key_file="config/api-keys.toml",
            timeout_seconds=60,
        )
    )

    try:
        provider._post_chat_completion({"model": "deepseek-v4-pro", "messages": []}, "sk-secret")
    except LLMProviderError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected incomplete response error")

    assert "incomplete response" in message.casefold()
    assert "sk-secret" not in message


def test_openai_provider_retries_incomplete_response_once(monkeypatch):
    from llmwiki.llm import LLMConfig
    from llmwiki.providers.openai import OpenAIProvider

    class BrokenResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            raise IncompleteRead(b"partial")

    class GoodResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'{"model":"deepseek-v4-pro","choices":[{"message":{"content":"ok"},'
                b'"finish_reason":"stop"}],"usage":{}}'
            )

    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            return BrokenResponse()
        return GoodResponse()

    monkeypatch.setattr("llmwiki.providers.openai.urlopen", fake_urlopen)
    provider = OpenAIProvider(
        LLMConfig(
            enabled=True,
            provider="openai",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            api_key_file="config/api-keys.toml",
            timeout_seconds=60,
        )
    )

    result = provider._post_chat_completion(
        {"model": "deepseek-v4-pro", "messages": []},
        "sk-secret",
    )

    assert calls["count"] == 2
    assert result["choices"][0]["message"]["content"] == "ok"


def test_openai_provider_uses_complete_json_from_incomplete_response(monkeypatch):
    from llmwiki.llm import LLMConfig
    from llmwiki.providers.openai import OpenAIProvider

    body = (
        b'{"model":"deepseek-v4-pro","choices":[{"message":{"content":"ok"},'
        b'"finish_reason":"stop"}],"usage":{}}'
    )

    class IncompleteJsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            raise IncompleteRead(body)

    monkeypatch.setattr(
        "llmwiki.providers.openai.urlopen",
        lambda request, timeout: IncompleteJsonResponse(),
    )
    provider = OpenAIProvider(
        LLMConfig(
            enabled=True,
            provider="openai",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            api_key_file="config/api-keys.toml",
            timeout_seconds=60,
        )
    )

    result = provider._post_chat_completion(
        {"model": "deepseek-v4-pro", "messages": []},
        "sk-secret",
    )

    assert result["choices"][0]["message"]["content"] == "ok"
