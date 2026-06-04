from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llmwiki.ingestion.pipeline import AddPipelineError, AddPipelineResult, add_and_process_source

from .jobs import UiJob, create_add_source_job, now_iso, update_job
from .models import UI_SCHEMA_VERSION, sanitize_ui_text


ALLOWED_PARSERS = {"auto", "pypdf", "mineru"}


class UiActionError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = sanitize_ui_text(message)
        self.status_code = status_code

    def to_dict(self) -> dict[str, str | int]:
        return {
            "schema_version": UI_SCHEMA_VERSION,
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
        }


@dataclass(frozen=True)
class AddSourceRequest:
    source: str
    parser: str | None
    source_kind: str


def validate_add_source_request(root: Path, payload: object) -> AddSourceRequest:
    if not isinstance(payload, dict):
        raise UiActionError("invalid_payload", "Request body must be a JSON object.")

    source_value = payload.get("source")
    if not isinstance(source_value, str):
        raise UiActionError("invalid_source", "Source must be a string.")
    source = source_value.strip()
    if not source or _has_control_character(source):
        raise UiActionError("invalid_source", "Source must be a non-empty path or URL.")
    if _is_forbidden_source(root, source):
        raise UiActionError("forbidden_source", "This source path is not allowed.")

    parser = _normalize_parser(payload.get("parser"))
    source_kind = _source_kind(source)
    if source_kind == "local_path":
        candidate = _resolve_source_path(root, source)
        if candidate.exists() and candidate.is_dir():
            raise UiActionError("directory_not_supported", "Directory import is not supported in V3.2.")

    return AddSourceRequest(source=source, parser=parser, source_kind=source_kind)


def enqueue_add_source_job(root: Path, payload: object, job_manager: Any) -> UiJob:
    request = validate_add_source_request(root, payload)
    job = create_add_source_job(root, request.source, parser=request.parser)
    return job_manager.enqueue(job)


def run_add_source_job(root: Path, job: UiJob) -> UiJob:
    root = root.resolve()
    job = update_job(root, job, status="running", stage="running", started_at=now_iso())
    try:
        result = add_and_process_source(root, job.source_input, parser_backend=job.requested_parser)
    except AddPipelineError as exc:
        return update_job(
            root,
            job,
            status="failed",
            stage=exc.stage,
            finished_at=now_iso(),
            source_id=exc.source_id or job.source_id,
            run_id=exc.run_id or job.run_id,
            failure_stage=exc.stage,
            failure_reason=sanitize_ui_text(exc.reason),
            result=_pipeline_error_result(exc),
        )
    except Exception as exc:  # pragma: no cover - exercised by tests through RuntimeError
        reason = sanitize_ui_text(str(exc) or exc.__class__.__name__)
        return update_job(
            root,
            job,
            status="failed",
            stage="worker",
            finished_at=now_iso(),
            failure_stage="worker",
            failure_reason=reason,
            result={"error": reason},
        )

    return update_job(
        root,
        job,
        status="applied",
        stage="applied",
        finished_at=now_iso(),
        source_id=result.source_id,
        run_id=result.run_id,
        result=_pipeline_result_payload(result),
    )


def _pipeline_result_payload(result: AddPipelineResult) -> dict[str, object]:
    return {
        "pipeline_status": sanitize_ui_text(result.status, max_chars=80),
        "title": sanitize_ui_text(result.title),
        "source_duplicate": result.source_duplicate,
        "proposal_engine": sanitize_ui_text(result.proposal_engine, max_chars=80),
        "claim_count": result.claim_count,
        "patch_count": result.patch_count,
        "applied_pages": [sanitize_ui_text(page) for page in result.applied_pages],
        "warnings": [sanitize_ui_text(warning) for warning in result.warnings],
    }


def _pipeline_error_result(error: AddPipelineError) -> dict[str, object]:
    payload: dict[str, object] = {
        "stage": sanitize_ui_text(error.stage, max_chars=80),
        "reason": sanitize_ui_text(error.reason),
    }
    if error.debug_command:
        payload["debug_command"] = sanitize_ui_text(error.debug_command)
    return payload


def _normalize_parser(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise UiActionError("invalid_parser", "Parser must be one of default, auto, pypdf, or mineru.")
    parser = value.strip().lower()
    if parser == "":
        return None
    if parser not in ALLOWED_PARSERS:
        raise UiActionError("invalid_parser", "Parser must be one of default, auto, pypdf, or mineru.")
    return parser


def _source_kind(source: str) -> str:
    lowered = source.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return "url"
    return "local_path"


def _has_control_character(value: str) -> bool:
    return any(ord(char) < 32 for char in value)


def _resolve_source_path(root: Path, source: str) -> Path:
    path = Path(source)
    if path.is_absolute():
        return path
    return root.resolve() / path


def _is_forbidden_source(root: Path, source: str) -> bool:
    if _source_kind(source) == "url":
        return False
    candidate = _resolve_source_path(root, source)
    forbidden = (root.resolve() / "config" / "api-keys.toml").resolve()
    try:
        return candidate.resolve() == forbidden
    except OSError:
        return source.replace("\\", "/").lower() == "config/api-keys.toml"
