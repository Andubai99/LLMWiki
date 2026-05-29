from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from tests.helpers import make_workspace


def write_embedding_config(root, api_key: str = "sk-local-embedding-secret") -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "config.toml").write_text(
        """
[embedding]
enabled = true
provider = "dashscope_multimodal"
model = "tongyi-embedding-vision-flash-2026-03-06"
endpoint_url = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
api_key_file = "config/api-keys.toml"
dimension = 768
timeout_seconds = 60
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "config" / "api-keys.toml").write_text(
        f'[embedding]\napi_key = "{api_key}"\n',
        encoding="utf-8",
    )


def test_load_embedding_config_reads_repository_defaults():
    root = make_workspace()
    write_embedding_config(root)

    from llmwiki.embeddings import load_embedding_config

    config = load_embedding_config(root)

    assert config.enabled is True
    assert config.provider == "dashscope_multimodal"
    assert config.model == "tongyi-embedding-vision-flash-2026-03-06"
    assert config.dimension == 768
    assert config.api_key_file == "config/api-keys.toml"


def test_dashscope_provider_uses_multimodal_request_shape(monkeypatch):
    root = make_workspace()
    write_embedding_config(root)

    from llmwiki.embeddings import DashScopeMultimodalEmbeddingProvider, load_embedding_config

    seen: dict[str, object] = {}

    class GoodResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            vector = [0.1] * 768
            return json.dumps(
                {"output": {"embeddings": [{"embedding": vector}, {"embedding": vector}]}}
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        seen["timeout"] = timeout
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return GoodResponse()

    monkeypatch.setattr("llmwiki.embeddings.urlopen", fake_urlopen)

    provider = DashScopeMultimodalEmbeddingProvider(load_embedding_config(root), root=root)
    vectors = provider.embed_texts(["草莓应该怎么保存？", "运动后补充能量"])

    assert [len(vector) for vector in vectors] == [768, 768]
    assert seen["timeout"] == 60
    assert seen["url"] == "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
    assert seen["payload"] == {
        "model": "tongyi-embedding-vision-flash-2026-03-06",
        "input": {"contents": [{"text": "草莓应该怎么保存？"}, {"text": "运动后补充能量"}]},
        "parameters": {"dimension": 768},
    }
    assert seen["headers"]["Authorization"] == "Bearer sk-local-embedding-secret"


def test_dashscope_provider_rejects_dimension_mismatch_without_leaking_secret(monkeypatch):
    root = make_workspace()
    write_embedding_config(root, api_key="sk-embedding-secret-should-not-leak")

    from llmwiki.embeddings import (
        DashScopeMultimodalEmbeddingProvider,
        EmbeddingProviderError,
        load_embedding_config,
    )

    class BadResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"output": {"embeddings": [{"embedding": [0.1, 0.2]}]}}).encode("utf-8")

    monkeypatch.setattr("llmwiki.embeddings.urlopen", lambda request, timeout: BadResponse())

    provider = DashScopeMultimodalEmbeddingProvider(load_embedding_config(root), root=root)

    with pytest.raises(EmbeddingProviderError) as exc:
        provider.embed_texts(["草莓"])

    message = str(exc.value)
    assert "dimension" in message.casefold()
    assert "sk-embedding-secret-should-not-leak" not in message
    assert "config/api-keys.toml" not in message


def test_dashscope_provider_sanitizes_http_errors(monkeypatch):
    root = make_workspace()
    write_embedding_config(root, api_key="sk-embedding-secret-should-not-leak")

    from llmwiki.embeddings import (
        DashScopeMultimodalEmbeddingProvider,
        EmbeddingProviderError,
        load_embedding_config,
    )

    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesBody(b'{"message":"bad sk-embedding-secret-should-not-leak config/api-keys.toml"}'),
        )

    monkeypatch.setattr("llmwiki.embeddings.urlopen", fake_urlopen)

    provider = DashScopeMultimodalEmbeddingProvider(load_embedding_config(root), root=root)

    with pytest.raises(EmbeddingProviderError) as exc:
        provider.embed_texts(["草莓"])

    message = str(exc.value)
    assert "401" in message
    assert "sk-embedding-secret-should-not-leak" not in message
    assert "config/api-keys.toml" not in message


def test_create_embedding_provider_rejects_unknown_provider():
    root = make_workspace()
    write_embedding_config(root)

    from llmwiki.embeddings import EmbeddingConfig, create_embedding_provider

    config = EmbeddingConfig(
        enabled=True,
        provider="unknown",
        model="model",
        endpoint_url="https://example.test",
        api_key_file="config/api-keys.toml",
        dimension=768,
        timeout_seconds=60,
    )

    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        create_embedding_provider(config, root=root)


class BytesBody:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def close(self) -> None:
        pass
