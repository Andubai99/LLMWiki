from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any


UI_SCHEMA_VERSION = "ui.v3.3"

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]+"),
    re.compile(r"api_key\s*=\s*[^\s,;]+", re.IGNORECASE),
    re.compile(r"config[/\\]api-keys\.toml", re.IGNORECASE),
)


def sanitize_ui_text(text: object, max_chars: int = 500) -> str:
    value = str(text)
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[redacted]", value)
    if len(value) > max_chars:
        return value[: max_chars - 3] + "..."
    return value


def workspace_relative_path(root: Path, path: Path | str) -> str:
    root = root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.resolve().relative_to(root)
    except ValueError:
        return "[outside-workspace]"
    return relative.as_posix()


@dataclass(frozen=True)
class UiWarning:
    level: str
    message: str
    category: str = "general"

    def to_dict(self) -> dict[str, str]:
        return {
            "level": sanitize_ui_text(self.level, max_chars=80),
            "message": sanitize_ui_text(self.message),
            "category": sanitize_ui_text(self.category, max_chars=80),
        }


@dataclass(frozen=True)
class UiResponse:
    schema_version: str = UI_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _serialize_dataclass(self)


@dataclass(frozen=True)
class WorkspaceStatusResponse(UiResponse):
    status: str = "error"
    workspace_root: str = ""
    initialized: bool = False
    catalog_present: bool = False
    catalog_ok: bool = False
    required_paths: dict[str, bool] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    latest_runs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class SourceSummary(UiResponse):
    source_id: str = ""
    title: str = ""
    source_type: str = ""
    raw_path: str = ""
    normalized_path: str = ""
    status: str = ""
    latest_run_id: str = ""
    latest_run_status: str = ""
    latest_job_id: str = ""
    latest_job_status: str = ""
    parser_backend: str = ""
    parser_fallback: str = ""
    sidecars: dict[str, bool] = field(default_factory=dict)
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class RunSummary(UiResponse):
    run_id: str = ""
    source_id: str = ""
    status: str = ""
    run_type: str = ""
    trigger: str = ""
    created_at: str = ""
    applied_at: str = ""
    failed_stage: str = ""
    failure_reason: str = ""
    claim_count: int = 0
    patch_count: int = 0
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class PageSummary(UiResponse):
    page_id: str = ""
    title: str = ""
    page_type: str = ""
    path: str = ""
    source_id: str = ""
    claim_count: int = 0
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class JobSummary(UiResponse):
    job_id: str = ""
    job_type: str = ""
    status: str = ""
    source_input: str = ""
    source_kind: str = ""
    requested_parser: str | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    source_id: str = ""
    run_id: str = ""
    question: str = ""
    ask_options: dict[str, Any] = field(default_factory=dict)
    parent_job_id: str = ""
    writeback_mode: str = ""
    stage: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    failure_stage: str = ""
    failure_reason: str = ""
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class JobListResponse(UiResponse):
    jobs: list[JobSummary] = field(default_factory=list)
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class ConfigStatusResponse(UiResponse):
    llm: dict[str, Any] = field(default_factory=dict)
    embedding: dict[str, Any] = field(default_factory=dict)
    parser: dict[str, Any] = field(default_factory=dict)
    vector: dict[str, Any] = field(default_factory=dict)
    warnings: list[UiWarning] = field(default_factory=list)


def _serialize_dataclass(value: Any) -> Any:
    if isinstance(value, UiWarning):
        return value.to_dict()
    if isinstance(value, UiResponse):
        data = asdict(value)
        return _sanitize_payload(data)
    if isinstance(value, list):
        return [_serialize_dataclass(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_dataclass(item) for key, item in value.items()}
    if isinstance(value, str):
        return sanitize_ui_text(value)
    return value


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "warnings":
            sanitized[key] = [
                item.to_dict() if isinstance(item, UiWarning) else _serialize_dataclass(item)
                for item in value
            ]
        else:
            sanitized[key] = _serialize_dataclass(value)
    return sanitized
