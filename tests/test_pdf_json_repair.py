from __future__ import annotations

import json
from typing import Any

import pytest

from llmwiki.llm_ingest import (
    build_json_repair_messages,
    parse_llm_json_with_repair,
)
from llmwiki.providers.base import LLMProviderError


class RepairProvider:
    def __init__(self, repair_content: str):
        self.repair_content = repair_content
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(messages)
        return {
            "provider": "fake",
            "model": "fake-repair",
            "content": self.repair_content,
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }


def test_parse_llm_json_with_repair_returns_valid_json_without_repair():
    provider = RepairProvider('{"unused": true}')
    payload, content, events, usage = parse_llm_json_with_repair(
        content='{"claims": [], "chunk_summary": "ok"}',
        provider=provider,
        schema={"type": "object"},
        response_kind="chunk",
        chunk_id="chunk_a",
    )

    assert payload == {"claims": [], "chunk_summary": "ok"}
    assert content == '{"claims": [], "chunk_summary": "ok"}'
    assert events == []
    assert usage == {}
    assert provider.calls == []


def test_parse_llm_json_with_repair_repairs_malformed_chunk_json_once():
    provider = RepairProvider('{"claims": [], "chunk_summary": "fixed"}')

    payload, content, events, usage = parse_llm_json_with_repair(
        content='{"claims": [], "chunk_summary": "broken"',
        provider=provider,
        schema={"type": "object", "required": ["claims", "chunk_summary"]},
        response_kind="chunk",
        chunk_id="chunk_a",
    )

    assert payload == {"claims": [], "chunk_summary": "fixed"}
    assert content == '{"claims": [], "chunk_summary": "fixed"}'
    assert len(provider.calls) == 1
    assert len(events) == 1
    event = events[0].to_dict()
    assert event["response_kind"] == "chunk"
    assert event["chunk_id"] == "chunk_a"
    assert event["status"] == "repaired"
    assert "Expecting" in event["error"]
    assert usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


def test_parse_llm_json_with_repair_failure_is_sanitized():
    provider = RepairProvider('{"still": "broken"')

    with pytest.raises(LLMProviderError) as exc:
        parse_llm_json_with_repair(
            content='{"api_key": "sk-secret-value", "path": "config/api-keys.toml"',
            provider=provider,
            schema={"type": "object"},
            response_kind="consolidation",
            chunk_id=None,
        )

    message = str(exc.value)
    assert "consolidation" in message
    assert "sk-secret-value" not in message
    assert "config/api-keys.toml" not in message
    assert "api_key" not in message
    assert len(provider.calls) == 1


def test_build_json_repair_messages_do_not_include_secret_markers_in_error_text():
    messages = build_json_repair_messages(
        malformed_content='{"api_key": "sk-secret-value"}',
        parse_error='Invalid JSON near config/api-keys.toml and sk-secret-value',
        schema={"type": "object"},
        response_kind="chunk",
        chunk_id="chunk_a",
    )

    serialized = json.dumps(messages)
    assert "config/api-keys.toml" not in serialized
    assert "sk-secret-value" not in serialized
    assert "Return repaired JSON only" in serialized
