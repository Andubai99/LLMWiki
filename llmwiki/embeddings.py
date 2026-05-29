from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Protocol
import tomllib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .llm import main_config_path


DEFAULT_EMBEDDING_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)


@dataclass(frozen=True)
class EmbeddingConfig:
    enabled: bool = True
    provider: str = "dashscope_multimodal"
    model: str = "tongyi-embedding-vision-flash-2026-03-06"
    endpoint_url: str = DEFAULT_EMBEDDING_ENDPOINT
    api_key_file: str = "config/api-keys.toml"
    dimension: int = 768
    timeout_seconds: int = 60


class EmbeddingProviderError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


def load_embedding_config(root: Path) -> EmbeddingConfig:
    data: dict[str, Any] = {}
    config_path = main_config_path(root)
    if config_path.exists():
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    embedding = data.get("embedding", {})
    return EmbeddingConfig(
        enabled=bool(embedding.get("enabled", True)),
        provider=str(embedding.get("provider", "dashscope_multimodal")),
        model=str(embedding.get("model", "tongyi-embedding-vision-flash-2026-03-06")),
        endpoint_url=str(embedding.get("endpoint_url", DEFAULT_EMBEDDING_ENDPOINT)),
        api_key_file=str(embedding.get("api_key_file", "config/api-keys.toml")),
        dimension=int(embedding.get("dimension", 768)),
        timeout_seconds=int(embedding.get("timeout_seconds", 60)),
    )


def create_embedding_provider(config: EmbeddingConfig, root: Path | None = None) -> EmbeddingProvider:
    if config.provider != "dashscope_multimodal":
        raise ValueError(f"Unsupported embedding provider: {config.provider}")
    return DashScopeMultimodalEmbeddingProvider(config, root=root)


class DashScopeMultimodalEmbeddingProvider:
    def __init__(self, config: EmbeddingConfig, root: Path | None = None) -> None:
        self.config = config
        self.root = root or Path.cwd()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        api_key = self._load_api_key()
        payload = {
            "model": self.config.model,
            "input": {"contents": [{"text": text} for text in texts]},
            "parameters": {"dimension": self.config.dimension},
        }
        response = self._post(payload, api_key)
        vectors = self._extract_vectors(response, expected_count=len(texts), api_key=api_key)
        return vectors

    def _load_api_key(self) -> str:
        key_path = Path(self.config.api_key_file)
        if not key_path.is_absolute():
            key_path = self.root / key_path
        try:
            data = tomllib.loads(key_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise EmbeddingProviderError(
                sanitize_embedding_error(f"Embedding API key file is unavailable: {exc}")
            ) from exc
        api_key = str(data.get("embedding", {}).get("api_key", "")).strip()
        if not api_key:
            raise EmbeddingProviderError("Embedding API key is not configured.")
        return api_key

    def _post(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.config.endpoint_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            details = _read_http_error_body(exc)
            message = f"Embedding provider HTTP error {exc.code}: {details or exc.reason}"
            raise EmbeddingProviderError(sanitize_embedding_error(message, api_key=api_key)) from exc
        except URLError as exc:
            message = f"Embedding provider request failed: {exc.reason}"
            raise EmbeddingProviderError(sanitize_embedding_error(message, api_key=api_key)) from exc
        except OSError as exc:
            message = f"Embedding provider request failed: {exc}"
            raise EmbeddingProviderError(sanitize_embedding_error(message, api_key=api_key)) from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EmbeddingProviderError(
                sanitize_embedding_error("Embedding provider returned malformed JSON.", api_key=api_key)
            ) from exc
        if not isinstance(parsed, dict):
            raise EmbeddingProviderError("Embedding provider returned an invalid response.")
        return parsed

    def _extract_vectors(
        self,
        response: dict[str, Any],
        *,
        expected_count: int,
        api_key: str,
    ) -> list[list[float]]:
        output = response.get("output")
        embeddings = output.get("embeddings") if isinstance(output, dict) else None
        if not isinstance(embeddings, list):
            raise EmbeddingProviderError("Embedding provider response has no embeddings.")
        if len(embeddings) != expected_count:
            message = f"Embedding count mismatch: expected {expected_count}, got {len(embeddings)}."
            raise EmbeddingProviderError(sanitize_embedding_error(message, api_key=api_key))

        vectors: list[list[float]] = []
        for index, item in enumerate(embeddings, start=1):
            vector = item.get("embedding") if isinstance(item, dict) else None
            if vector is None and isinstance(item, dict):
                vector = item.get("vector")
            if not isinstance(vector, list):
                raise EmbeddingProviderError(f"Embedding {index} is missing a vector.")
            if len(vector) != self.config.dimension:
                message = (
                    f"Embedding {index} dimension mismatch: expected "
                    f"{self.config.dimension}, got {len(vector)}."
                )
                raise EmbeddingProviderError(sanitize_embedding_error(message, api_key=api_key))
            try:
                vectors.append([float(value) for value in vector])
            except (TypeError, ValueError) as exc:
                raise EmbeddingProviderError(f"Embedding {index} contains non-numeric values.") from exc
        return vectors


def sanitize_embedding_error(message: str, api_key: str | None = None) -> str:
    safe = message
    if api_key:
        safe = safe.replace(api_key, "[redacted]")
    safe = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-[redacted]", safe)
    safe = safe.replace("config/api-keys.toml", "[api-key-file]")
    safe = safe.replace("config\\api-keys.toml", "[api-key-file]")
    return safe


def _read_http_error_body(exc: HTTPError) -> str:
    try:
        body = exc.read()
    except OSError:
        return ""
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("utf-8", errors="replace")
