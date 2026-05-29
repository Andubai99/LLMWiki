from __future__ import annotations

from pathlib import Path
import tomllib

import pytest


def test_dashscope_embedding_provider_real_call_returns_768_dimensions():
    root = Path(__file__).resolve().parents[1]
    key_path = root / "config" / "api-keys.toml"
    if not key_path.exists():
        pytest.skip("local embedding API key file is not configured")
    data = tomllib.loads(key_path.read_text(encoding="utf-8"))
    if not str(data.get("embedding", {}).get("api_key", "")).strip():
        pytest.skip("local embedding API key is not configured")

    from llmwiki.embeddings import create_embedding_provider, load_embedding_config

    config = load_embedding_config(root)
    provider = create_embedding_provider(config, root=root)
    vectors = provider.embed_texts(["草莓应该怎么保存？"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 768
    assert all(isinstance(value, float) for value in vectors[0])
