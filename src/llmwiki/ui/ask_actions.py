from __future__ import annotations

from pathlib import Path
from typing import Any

from .ask_models import AskUiRequest
from .jobs import UiJob
from .models import UI_SCHEMA_VERSION, sanitize_ui_text


ALLOWED_CONFIDENCE_FILTERS = {"cited", "weak"}


class AskUiActionError(Exception):
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


def validate_ask_request(root: Path, payload: object) -> AskUiRequest:
    _ = root
    if not isinstance(payload, dict):
        raise AskUiActionError("invalid_payload", "Request body must be a JSON object.")

    question_value = payload.get("question")
    if not isinstance(question_value, str):
        raise AskUiActionError("invalid_question", "Question must be a non-empty string.")
    question = question_value.strip()
    if not question or _has_control_character(question):
        raise AskUiActionError("invalid_question", "Question must be a non-empty string.")

    limit = _normalize_limit(payload.get("limit", 8))
    source_id = _optional_clean_string(payload.get("source_id"), field_name="source_id")
    page_type = _optional_clean_string(payload.get("page_type"), field_name="page_type")
    confidence = _normalize_confidence(payload.get("confidence"))

    return AskUiRequest(
        question=question,
        limit=limit,
        source_id=source_id,
        page_type=page_type,
        confidence=confidence,
    )


def enqueue_ask_job(root: Path, payload: object, job_manager: Any) -> UiJob:
    request = validate_ask_request(root, payload)
    from .jobs import create_ask_job

    job = create_ask_job(root, request)
    return job_manager.enqueue(job)


def _normalize_limit(value: object) -> int:
    if isinstance(value, bool):
        raise AskUiActionError("invalid_limit", "Limit must be an integer from 1 to 20.")
    if isinstance(value, int):
        limit = value
    elif isinstance(value, str) and value.strip().isdigit():
        limit = int(value.strip())
    else:
        raise AskUiActionError("invalid_limit", "Limit must be an integer from 1 to 20.")
    if limit < 1 or limit > 20:
        raise AskUiActionError("invalid_limit", "Limit must be an integer from 1 to 20.")
    return limit


def _normalize_confidence(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AskUiActionError("invalid_confidence", "Confidence must be cited, weak, or empty.")
    confidence = value.strip().lower()
    if confidence == "":
        return None
    if confidence not in ALLOWED_CONFIDENCE_FILTERS:
        raise AskUiActionError("invalid_confidence", "Confidence must be cited, weak, or empty.")
    return confidence


def _optional_clean_string(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AskUiActionError(f"invalid_{field_name}", f"{field_name} must be a string.")
    text = value.strip()
    if text == "":
        return None
    if _has_control_character(text):
        raise AskUiActionError(f"invalid_{field_name}", f"{field_name} must not contain control characters.")
    return text


def _has_control_character(value: str) -> bool:
    return any(ord(char) < 32 for char in value)
