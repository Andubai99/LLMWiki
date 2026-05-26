from __future__ import annotations

from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import os

from ..llm import LLMConfig
from .base import BaseLLMProvider, LLMProviderError


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, config: LLMConfig):
        self.config = config

    def complete(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        api_key = self._api_key()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
        }
        # Reserved for later structured output support. DeepSeek-compatible
        # chat completions may not enforce a full JSON schema today, so v1
        # accepts the parameter without adding provider-specific request fields.

        raw = self._post_chat_completion(payload, api_key)
        choices = raw.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message") or {}
        return {
            "content": str(message.get("content") or ""),
            "raw": raw,
            "provider": "openai",
            "model": str(raw.get("model") or self.config.model),
            "usage": raw.get("usage") or {},
            "finish_reason": first_choice.get("finish_reason"),
        }

    def _api_key(self) -> str:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise LLMProviderError(
                f"Missing API key environment variable {self.config.api_key_env}. "
                "Set it before running LLM commands. Do not write the key into config.toml, "
                "README, tests, logs, or source files."
            )
        return api_key

    def _post_chat_completion(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "llmwiki/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise LLMProviderError(
                self._http_error_message(exc.code, error_body, api_key)
            ) from exc
        except URLError as exc:
            raise LLMProviderError(
                "OpenAI-compatible provider request failed before receiving an HTTP response. "
                f"Reason: {exc.reason}. "
                f"Check base_url={self.config.base_url}, model={self.config.model}, "
                f"api_key_env={self.config.api_key_env}, and network connectivity."
            ) from exc
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                "OpenAI-compatible provider returned non-JSON response. "
                f"Check base_url={self.config.base_url}, model={self.config.model}, "
                f"and provider compatibility."
            ) from exc

    def _http_error_message(self, status: int, error_body: str, api_key: str) -> str:
        sanitized_body = error_body.replace(api_key, "[REDACTED_API_KEY]")
        error_type = "unknown"
        try:
            parsed = json.loads(sanitized_body)
            if isinstance(parsed, dict):
                error = parsed.get("error")
                if isinstance(error, dict):
                    error_type = str(error.get("type") or error.get("code") or "unknown")
        except json.JSONDecodeError:
            parsed = None
        details = sanitized_body[:500]
        return (
            "OpenAI-compatible provider request failed. "
            f"HTTP status={status}; error_type={error_type}; "
            f"base_url={self.config.base_url}; model={self.config.model}; "
            f"api_key_env={self.config.api_key_env}. "
            "Check that the API key environment variable is set, the model is available, "
            f"and the base URL is correct. Provider response: {details}"
        )
