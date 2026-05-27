from __future__ import annotations

from http.client import IncompleteRead
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
from pathlib import Path
import tomllib

from ..llm import LLMConfig
from .base import BaseLLMProvider, LLMProviderError


TRANSIENT_ATTEMPTS = 3


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, config: LLMConfig, root: Path | None = None):
        self.config = config
        self.root = root.resolve() if root else Path.cwd()

    def complete(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        api_key = self._api_key()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "thinking": {"type": "disabled"},
        }
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}

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
        key_path = self._api_key_path()
        try:
            data = tomllib.loads(key_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise LLMProviderError(self._missing_api_key_message()) from exc
        except tomllib.TOMLDecodeError as exc:
            raise LLMProviderError(
                f"API key config is not valid TOML: {self._display_path(key_path)}"
            ) from exc
        llm = data.get("llm", {}) if isinstance(data, dict) else {}
        api_key = str(llm.get("api_key") or "").strip() if isinstance(llm, dict) else ""
        if not api_key:
            raise LLMProviderError(self._missing_api_key_message())
        return api_key

    def _api_key_path(self) -> Path:
        path = Path(self.config.api_key_file)
        if path.is_absolute():
            return path
        return self.root / path

    def _display_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def _missing_api_key_message(self) -> str:
        key_path = self._api_key_path()
        display_path = self._display_path(key_path)
        return (
            f"Missing API key in {display_path}. "
            "Create it from config/api-keys.example.toml and set [llm].api_key. "
            "Do not commit API keys, tokens, or sensitive logs."
        )

    def _post_chat_completion(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        response_body = ""
        for attempt in range(1, TRANSIENT_ATTEMPTS + 1):
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
                break
            except HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                raise LLMProviderError(
                    self._http_error_message(exc.code, error_body, api_key)
                ) from exc
            except URLError as exc:
                if attempt < TRANSIENT_ATTEMPTS:
                    continue
                raise LLMProviderError(
                    "OpenAI-compatible provider request failed before receiving an HTTP response. "
                    f"Reason: {exc.reason}. "
                    f"Check base_url={self.config.base_url}, model={self.config.model}, "
                    f"api_key_file={self.config.api_key_file}, and network connectivity."
                ) from exc
            except IncompleteRead as exc:
                partial = self._partial_json(exc)
                if partial is not None:
                    return partial
                if attempt < TRANSIENT_ATTEMPTS:
                    continue
                raise LLMProviderError(
                    "OpenAI-compatible provider returned an incomplete response. "
                    f"Check base_url={self.config.base_url}, model={self.config.model}, "
                    f"api_key_file={self.config.api_key_file}, and network stability."
                ) from exc
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                "OpenAI-compatible provider returned non-JSON response. "
                f"Check base_url={self.config.base_url}, model={self.config.model}, "
                f"and provider compatibility."
            ) from exc

    def _partial_json(self, exc: IncompleteRead) -> dict[str, Any] | None:
        partial = exc.partial
        if not partial:
            return None
        try:
            parsed = json.loads(partial.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

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
            f"api_key_file={self.config.api_key_file}. "
            "Check that the local API key config is set, the model is available, "
            f"and the base URL is correct. Provider response: {details}"
        )
