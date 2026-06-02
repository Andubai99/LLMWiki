from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import secrets
import threading
from collections.abc import Callable

from .models import UiWarning, sanitize_ui_text


UI_JOB_SCHEMA_VERSION = "ui_job.v3.3"
JOB_STATE_DIR = Path("state") / "ui-jobs"


@dataclass
class UiJob:
    job_id: str = ""
    job_type: str = "add_source"
    status: str = "pending"
    source_input: str = ""
    source_kind: str = ""
    requested_parser: str | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    source_id: str = ""
    run_id: str = ""
    question: str = ""
    ask_options: dict[str, object] = field(default_factory=dict)
    parent_job_id: str = ""
    writeback_mode: str = ""
    stage: str = "queued"
    result: dict[str, object] = field(default_factory=dict)
    failure_stage: str = ""
    failure_reason: str = ""
    warnings: list[UiWarning] = field(default_factory=list)
    schema_version: str = UI_JOB_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["schema_version"] = UI_JOB_SCHEMA_VERSION
        payload["warnings"] = [warning.to_dict() for warning in self.warnings]
        return sanitize_job_payload(payload)


@dataclass
class JobLoadResult:
    jobs: list[UiJob] = field(default_factory=list)
    warnings: list[UiWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "jobs": [job.to_dict() for job in self.jobs],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


class UiJobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def create_add_source_job(self, source_input: str, parser: str | None = None) -> UiJob:
        return create_add_source_job(self.root, source_input, parser=parser)

    def create_ask_job(self, request: object) -> UiJob:
        return create_ask_job(self.root, request)

    def create_synthesis_preview_job(self, ask_job_id: str) -> UiJob:
        return create_synthesis_preview_job(self.root, ask_job_id)

    def create_synthesis_writeback_job(self, ask_job_id: str, *, writeback_mode: str = "auto") -> UiJob:
        return create_synthesis_writeback_job(self.root, ask_job_id, writeback_mode=writeback_mode)

    def load_jobs(self, *, limit: int | None = None) -> JobLoadResult:
        result = load_jobs(self.root)
        if limit is not None:
            result.jobs = result.jobs[:limit]
        return result

    def save_job(self, job: UiJob) -> UiJob:
        return save_job(self.root, job)

    def update_job(self, job: UiJob, **updates: object) -> UiJob:
        return update_job(self.root, job, **updates)


class UiJobManager:
    def __init__(
        self,
        root: Path,
        *,
        worker: Callable[[UiJob], UiJob] | None = None,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self.root = root.resolve()
        self.worker = worker
        self.poll_interval_seconds = poll_interval_seconds
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="llmwiki-ui-job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def enqueue(self, job: UiJob) -> UiJob:
        return save_job(self.root, job)

    def run_pending_once(self) -> bool:
        if self.worker is None:
            raise RuntimeError("UiJobManager requires a worker before running jobs.")
        if not self._lock.acquire(blocking=False):
            return False
        try:
            job = next_pending_job(self.root)
            if job is None:
                return False
            self.worker(job)
            return True
        finally:
            self._lock.release()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            ran = self.run_pending_once()
            if not ran:
                self._stop_event.wait(self.poll_interval_seconds)


def create_add_source_job(root: Path, source_input: str, parser: str | None = None) -> UiJob:
    job = UiJob(
        job_id=new_job_id(),
        job_type="add_source",
        status="pending",
        source_input=source_input,
        source_kind=source_kind(source_input),
        requested_parser=parser or None,
        created_at=now_iso(),
        stage="queued",
    )
    return save_job(root, job)


def create_ask_job(root: Path, request: object) -> UiJob:
    question = str(getattr(request, "question", ""))
    ask_options = {
        "limit": getattr(request, "limit", 8),
        "source_id": getattr(request, "source_id", None),
        "page_type": getattr(request, "page_type", None),
        "confidence": getattr(request, "confidence", None),
    }
    job = UiJob(
        job_id=new_job_id(),
        job_type="ask_question",
        status="pending",
        created_at=now_iso(),
        question=question,
        ask_options=ask_options,
        stage="queued",
    )
    return save_job(root, job)


def create_synthesis_preview_job(root: Path, ask_job_id: str) -> UiJob:
    job = UiJob(
        job_id=new_job_id(),
        job_type="synthesis_preview",
        status="pending",
        created_at=now_iso(),
        parent_job_id=ask_job_id,
        stage="queued",
    )
    return save_job(root, job)


def create_synthesis_writeback_job(root: Path, ask_job_id: str, *, writeback_mode: str = "auto") -> UiJob:
    job = UiJob(
        job_id=new_job_id(),
        job_type="synthesis_writeback",
        status="pending",
        created_at=now_iso(),
        parent_job_id=ask_job_id,
        writeback_mode=writeback_mode,
        stage="queued",
    )
    return save_job(root, job)


def next_pending_job(root: Path) -> UiJob | None:
    pending = [job for job in load_jobs(root).jobs if job.status == "pending"]
    if not pending:
        return None
    pending.sort(key=lambda job: (job.created_at, job.job_id))
    return pending[0]


def load_jobs(root: Path) -> JobLoadResult:
    warnings: list[UiWarning] = []
    jobs: list[UiJob] = []
    directory = jobs_dir(root)
    if not directory.exists():
        return JobLoadResult(jobs=[], warnings=[])
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("job file is not a JSON object")
            jobs.append(job_from_dict(payload))
        except Exception as exc:
            warnings.append(
                UiWarning(
                    level="warning",
                    category="ui_job",
                    message=f"Could not read UI job {path.name}: {sanitize_ui_text(exc)}",
                )
            )
    jobs.sort(key=lambda job: job.created_at, reverse=True)
    return JobLoadResult(jobs=jobs, warnings=warnings)


def save_job(root: Path, job: UiJob) -> UiJob:
    directory = jobs_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = job_path(root, job.job_id)
    path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return job


def update_job(root: Path, job: UiJob, **updates: object) -> UiJob:
    for key, value in updates.items():
        if not hasattr(job, key):
            raise AttributeError(f"unknown UiJob field: {key}")
        setattr(job, key, value)
    return save_job(root, job)


def mark_stale_running_jobs_interrupted(root: Path) -> int:
    result = load_jobs(root)
    changed = 0
    for job in result.jobs:
        if job.status != "running":
            continue
        job.status = "interrupted"
        job.stage = "interrupted"
        job.finished_at = job.finished_at or now_iso()
        job.warnings.append(
            UiWarning(
                level="warning",
                category="ui_job",
                message="Previous UI process exited before this job reported completion.",
            )
        )
        save_job(root, job)
        changed += 1
    return changed


def prune_jobs(root: Path, *, keep: int = 200) -> int:
    result = load_jobs(root)
    removed = 0
    for job in result.jobs[keep:]:
        path = job_path(root, job.job_id)
        if path.exists():
            path.unlink()
            removed += 1
    return removed


def job_path(root: Path, job_id: str) -> Path:
    return jobs_dir(root) / f"{job_id}.json"


def jobs_dir(root: Path) -> Path:
    return root.resolve() / JOB_STATE_DIR


def job_from_dict(payload: dict[str, object]) -> UiJob:
    warnings = [
        warning_from_dict(item)
        for item in payload.get("warnings", [])
        if isinstance(item, dict)
    ]
    return UiJob(
        job_id=str(payload.get("job_id", "")),
        job_type=str(payload.get("job_type", "add_source")),
        status=str(payload.get("status", "pending")),
        source_input=str(payload.get("source_input", "")),
        source_kind=str(payload.get("source_kind", "")),
        requested_parser=optional_str(payload.get("requested_parser")),
        created_at=str(payload.get("created_at", "")),
        started_at=optional_str(payload.get("started_at")),
        finished_at=optional_str(payload.get("finished_at")),
        source_id=str(payload.get("source_id", "")),
        run_id=str(payload.get("run_id", "")),
        question=str(payload.get("question", "")),
        ask_options=payload.get("ask_options", {}) if isinstance(payload.get("ask_options", {}), dict) else {},
        parent_job_id=str(payload.get("parent_job_id", "")),
        writeback_mode=str(payload.get("writeback_mode", "")),
        stage=str(payload.get("stage", "queued")),
        result=payload.get("result", {}) if isinstance(payload.get("result", {}), dict) else {},
        failure_stage=str(payload.get("failure_stage", "")),
        failure_reason=str(payload.get("failure_reason", "")),
        warnings=warnings,
    )


def warning_from_dict(payload: dict[str, object]) -> UiWarning:
    return UiWarning(
        level=str(payload.get("level", "warning")),
        category=str(payload.get("category", "general")),
        message=str(payload.get("message", "")),
    )


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def source_kind(source_input: str) -> str:
    lowered = source_input.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return "url"
    return "local_path"


def new_job_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"job_{timestamp}_{secrets.token_hex(4)}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_job_payload(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): sanitize_job_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_job_payload(item) for item in value]
    if isinstance(value, str):
        return sanitize_ui_text(value)
    return value
