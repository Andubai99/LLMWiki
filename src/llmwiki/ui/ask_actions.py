from __future__ import annotations

from pathlib import Path
from typing import Any

from llmwiki.ask.answer import AnswerCitation, AskOptions, AskResult, answer_question
from llmwiki.synthesis.planner import (
    SynthesisPlan,
    SynthesisPlanningError,
    SynthesisPlanningOptions,
    format_synthesis_preview,
    plan_synthesis_writeback,
    parse_synthesis_plan,
)
from llmwiki.synthesis import SynthesisWritebackError, SynthesisWritebackResult, create_synthesis_run

from .ask_models import AskUiRequest
from .jobs import (
    UiJob,
    create_synthesis_preview_job,
    create_synthesis_writeback_job,
    load_jobs,
    now_iso,
    update_job,
)
from .models import UI_SCHEMA_VERSION, sanitize_ui_text


ALLOWED_CONFIDENCE_FILTERS = {"cited", "weak"}
ALLOWED_WRITEBACK_MODES = {"auto", "create", "update"}


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


def enqueue_synthesis_preview_job(root: Path, ask_job_id: str, payload: object, job_manager: Any) -> UiJob:
    _ = payload
    ask_job = _require_answered_ask_job(root, ask_job_id)
    job = create_synthesis_preview_job(root, ask_job.job_id)
    return job_manager.enqueue(job)


def enqueue_synthesis_writeback_job(root: Path, ask_job_id: str, payload: object, job_manager: Any) -> UiJob:
    ask_job = _require_answered_ask_job(root, ask_job_id)
    writeback_mode = _writeback_mode_from_payload(payload)
    preview_job = _require_writeback_preview_job(root, ask_job.job_id)
    job = create_synthesis_writeback_job(root, ask_job.job_id, writeback_mode=writeback_mode)
    job = update_job(root, job, result={"preview_job_id": preview_job.job_id})
    return job_manager.enqueue(job)


def run_ask_job(root: Path, job: UiJob) -> UiJob:
    root = root.resolve()
    job = update_job(root, job, status="running", stage="running", started_at=now_iso())
    try:
        result = answer_question(root, job.question, _ask_options_from_job(job))
    except Exception as exc:  # pragma: no cover - exercised by tests through RuntimeError
        reason = sanitize_ui_text(str(exc) or exc.__class__.__name__)
        return update_job(
            root,
            job,
            status="failed",
            stage="ask",
            finished_at=now_iso(),
            failure_stage="ask",
            failure_reason=reason,
            result={"error": reason},
        )

    payload = _ask_result_payload(result)
    return update_job(
        root,
        job,
        status="applied",
        stage=str(payload.get("answer_status") or "answered"),
        finished_at=now_iso(),
        result=payload,
    )


def run_synthesis_preview_job(root: Path, job: UiJob) -> UiJob:
    root = root.resolve()
    job = update_job(root, job, status="running", stage="running", started_at=now_iso())
    try:
        ask_job = _require_answered_ask_job(root, job.parent_job_id)
        ask_result = _ask_result_from_job(ask_job)
        plan = plan_synthesis_writeback(
            root,
            ask_result,
            SynthesisPlanningOptions(writeback_mode=job.writeback_mode or "auto"),
        )
    except SynthesisPlanningError as exc:
        reason = sanitize_ui_text(exc)
        return update_job(
            root,
            job,
            status="failed",
            stage="synthesis_preview",
            finished_at=now_iso(),
            failure_stage="synthesis_preview",
            failure_reason=reason,
            result={"error": reason},
        )
    except AskUiActionError as exc:
        data = exc.to_dict()
        return update_job(
            root,
            job,
            status="failed",
            stage="synthesis_preview",
            finished_at=now_iso(),
            failure_stage="synthesis_preview",
            failure_reason=str(data["message"]),
            result={"error": data["message"]},
        )
    except Exception as exc:  # pragma: no cover - defensive
        reason = sanitize_ui_text(str(exc) or exc.__class__.__name__)
        return update_job(
            root,
            job,
            status="failed",
            stage="synthesis_preview",
            finished_at=now_iso(),
            failure_stage="synthesis_preview",
            failure_reason=reason,
            result={"error": reason},
        )

    payload = _synthesis_preview_payload(plan)
    return update_job(
        root,
        job,
        status="applied",
        stage=str(payload.get("preview_status") or "planned"),
        finished_at=now_iso(),
        result=payload,
    )


def run_synthesis_writeback_job(root: Path, job: UiJob) -> UiJob:
    root = root.resolve()
    job = update_job(root, job, status="running", stage="running", started_at=now_iso())
    try:
        ask_job = _require_answered_ask_job(root, job.parent_job_id)
        preview_job = _preview_job_for_writeback(root, job)
        ask_result = _ask_result_from_job(ask_job)
        plan = _synthesis_plan_from_preview_job(preview_job)
        result = create_synthesis_run(
            root,
            ask_result,
            plan=plan,
            planning_options=SynthesisPlanningOptions(writeback_mode=job.writeback_mode or "auto"),
        )
    except SynthesisWritebackError as exc:
        reason = sanitize_ui_text(exc.reason)
        return update_job(
            root,
            job,
            status="failed",
            stage=exc.stage,
            finished_at=now_iso(),
            run_id=exc.run_id or job.run_id,
            failure_stage=exc.stage,
            failure_reason=reason,
            result={
                "writeback_status": "failed",
                "run_id": exc.run_id or "",
                "failure_stage": exc.stage,
                "failure_reason": reason,
            },
        )
    except AskUiActionError as exc:
        data = exc.to_dict()
        return update_job(
            root,
            job,
            status="failed",
            stage="synthesis_writeback",
            finished_at=now_iso(),
            failure_stage="synthesis_writeback",
            failure_reason=str(data["message"]),
            result={"writeback_status": "failed", "failure_reason": data["message"]},
        )
    except Exception as exc:  # pragma: no cover - defensive
        reason = sanitize_ui_text(str(exc) or exc.__class__.__name__)
        return update_job(
            root,
            job,
            status="failed",
            stage="synthesis_writeback",
            finished_at=now_iso(),
            failure_stage="synthesis_writeback",
            failure_reason=reason,
            result={"writeback_status": "failed", "failure_reason": reason},
        )

    payload = _synthesis_writeback_payload(result, preview_job)
    return update_job(
        root,
        job,
        status="applied",
        stage=str(payload.get("writeback_status") or "applied"),
        finished_at=now_iso(),
        run_id=result.run_id,
        result=payload,
    )


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


def _writeback_mode_from_payload(payload: object) -> str:
    if not isinstance(payload, dict):
        raise AskUiActionError("invalid_payload", "Request body must be a JSON object.")
    value = payload.get("writeback_mode", "auto")
    if value is None:
        return "auto"
    if not isinstance(value, str):
        raise AskUiActionError("invalid_writeback_mode", "writeback_mode must be auto, create, or update.")
    mode = value.strip().lower() or "auto"
    if mode not in ALLOWED_WRITEBACK_MODES:
        raise AskUiActionError("invalid_writeback_mode", "writeback_mode must be auto, create, or update.")
    return mode


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


def _ask_options_from_job(job: UiJob) -> AskOptions:
    options = job.ask_options if isinstance(job.ask_options, dict) else {}
    return AskOptions(
        limit=_int_option(options.get("limit"), default=8),
        source_id=_none_or_str(options.get("source_id")),
        page_type=_none_or_str(options.get("page_type")),
        confidence=_none_or_str(options.get("confidence")),
    )


def _require_answered_ask_job(root: Path, ask_job_id: str) -> UiJob:
    for job in load_jobs(root).jobs:
        if job.job_id != ask_job_id:
            continue
        if job.job_type != "ask_question":
            raise AskUiActionError("ask_job_not_found", "Ask job was not found.", status_code=404)
        answer_status = ""
        if isinstance(job.result, dict):
            answer_status = str(job.result.get("answer_status") or "")
        if answer_status != "answered":
            raise AskUiActionError("ask_job_not_answered", "Synthesis preview requires an answered ask job.")
        return job
    raise AskUiActionError("ask_job_not_found", "Ask job was not found.", status_code=404)


def _require_writeback_preview_job(root: Path, ask_job_id: str) -> UiJob:
    preview_job = _latest_preview_job(root, ask_job_id)
    if preview_job is None:
        raise AskUiActionError("synthesis_preview_required", "Synthesis writeback requires a planned preview.")
    preview_status = str(preview_job.result.get("preview_status") or "") if isinstance(preview_job.result, dict) else ""
    action = str(preview_job.result.get("action") or "") if isinstance(preview_job.result, dict) else ""
    if preview_status == "needs_review" or action == "needs_review":
        raise AskUiActionError("synthesis_needs_review", "Synthesis preview needs review before writeback.")
    return preview_job


def _latest_preview_job(root: Path, ask_job_id: str) -> UiJob | None:
    for job in load_jobs(root).jobs:
        if job.job_type != "synthesis_preview" or job.parent_job_id != ask_job_id:
            continue
        if job.status != "applied" or not isinstance(job.result, dict):
            continue
        if str(job.result.get("preview_status") or "") in {"planned", "needs_review"}:
            return job
    return None


def _preview_job_for_writeback(root: Path, job: UiJob) -> UiJob:
    preview_job_id = ""
    if isinstance(job.result, dict):
        preview_job_id = str(job.result.get("preview_job_id") or "")
    if preview_job_id:
        for candidate in load_jobs(root).jobs:
            if candidate.job_id == preview_job_id:
                return candidate
        raise AskUiActionError("synthesis_preview_required", "Synthesis preview job was not found.")
    return _require_writeback_preview_job(root, job.parent_job_id)


def _ask_result_from_job(job: UiJob) -> AskResult:
    result = job.result if isinstance(job.result, dict) else {}
    citations = [
        AnswerCitation(
            claim_id=str(item.get("claim_id") or ""),
            source_id=str(item.get("source_id") or ""),
            citation_locator=str(item.get("citation_locator") or ""),
            page_path=str(item.get("page_path") or ""),
        )
        for item in result.get("citations", [])
        if isinstance(item, dict)
    ]
    return AskResult(
        question=str(result.get("question") or job.question),
        status=str(result.get("answer_status") or "answered"),
        answer=str(result.get("answer") or ""),
        analysis=str(result.get("analysis") or ""),
        citations=citations,
        warnings=[str(item) for item in _list_value(result.get("warnings"))],
        uncertainties=[str(item) for item in _list_value(result.get("uncertainties"))],
        conflicts=[str(item) for item in _list_value(result.get("conflicts"))],
        suggested_title=str(result.get("suggested_title") or ""),
        contexts=[item for item in _list_value(result.get("contexts")) if isinstance(item, dict)],
        relationships=[item for item in _list_value(result.get("relationships")) if isinstance(item, dict)],
        planning=result.get("planning") if isinstance(result.get("planning"), dict) else None,
        error=str(result.get("error") or ""),
    )


def _ask_result_payload(result: AskResult) -> dict[str, object]:
    return {
        "question": sanitize_ui_text(result.question),
        "answer": sanitize_ui_text(result.answer, max_chars=5000),
        "analysis": sanitize_ui_text(result.analysis, max_chars=5000),
        "answer_status": sanitize_ui_text(result.status, max_chars=80),
        "citations": [citation.to_dict() for citation in result.citations],
        "warnings": [sanitize_ui_text(warning) for warning in result.warnings],
        "uncertainties": [sanitize_ui_text(item) for item in result.uncertainties],
        "conflicts": [sanitize_ui_text(item) for item in result.conflicts],
        "planning": _bounded_payload(result.planning or {}, max_items=40),
        "contexts": _bounded_payload(result.contexts, max_items=20),
        "relationships": _bounded_payload(result.relationships, max_items=20),
        "suggested_title": sanitize_ui_text(result.suggested_title),
        "error": sanitize_ui_text(result.error),
    }


def _synthesis_preview_payload(plan: SynthesisPlan) -> dict[str, object]:
    plan_dict = plan.to_dict()
    return {
        "preview_status": sanitize_ui_text(plan.status, max_chars=80),
        "action": sanitize_ui_text(plan.action, max_chars=80),
        "target_page_id": sanitize_ui_text(plan.target_page_id),
        "target_path": sanitize_ui_text(plan.target_path),
        "title": sanitize_ui_text(plan.title),
        "evidence_claim_ids": [sanitize_ui_text(claim_id, max_chars=120) for claim_id in plan.evidence_claim_ids],
        "synthesis_plan": sanitize_job_like_payload(plan_dict),
        "preview_text": sanitize_ui_text(format_synthesis_preview(plan), max_chars=5000),
        "warnings": [sanitize_ui_text(warning) for warning in plan.warnings],
    }


def _synthesis_plan_from_preview_job(job: UiJob) -> SynthesisPlan:
    if not isinstance(job.result, dict) or not isinstance(job.result.get("synthesis_plan"), dict):
        raise AskUiActionError("synthesis_preview_required", "Synthesis preview does not contain a plan.")
    plan_payload = job.result["synthesis_plan"]
    plan = parse_synthesis_plan(json_dumps(plan_payload))
    if plan.action == "needs_review" or plan.status == "needs_review":
        raise AskUiActionError("synthesis_needs_review", "Synthesis preview needs review before writeback.")
    return plan


def _synthesis_writeback_payload(result: SynthesisWritebackResult, preview_job: UiJob) -> dict[str, object]:
    return {
        "writeback_status": sanitize_ui_text(result.status, max_chars=80),
        "run_id": sanitize_ui_text(result.run_id),
        "pages": [sanitize_ui_text(page) for page in result.pages],
        "action": sanitize_ui_text(result.action, max_chars=80),
        "synthesis_plan": sanitize_job_like_payload(result.synthesis_plan),
        "preview_job_id": sanitize_ui_text(preview_job.job_id),
        "failure_stage": "",
        "failure_reason": "",
    }


def _bounded_payload(value: object, *, max_items: int) -> object:
    if isinstance(value, list):
        return [sanitize_job_like_payload(item) for item in value[:max_items]]
    if isinstance(value, dict):
        items = list(value.items())[:max_items]
        return {str(key): sanitize_job_like_payload(item) for key, item in items}
    return sanitize_job_like_payload(value)


def sanitize_job_like_payload(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): sanitize_job_like_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_job_like_payload(item) for item in value]
    if isinstance(value, str):
        return sanitize_ui_text(value, max_chars=5000)
    return value


def _int_option(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return default


def _none_or_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def json_dumps(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
