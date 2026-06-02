from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import secrets

from .models import UiWarning, sanitize_ui_text


UI_JOB_SCHEMA_VERSION = "ui_job.v3.2"
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

    def load_jobs(self, *, limit: int | None = None) -> JobLoadResult:
        result = load_jobs(self.root)
        if limit is not None:
            result.jobs = result.jobs[:limit]
        return result

    def save_job(self, job: UiJob) -> UiJob:
        return save_job(self.root, job)

    def update_job(self, job: UiJob, **updates: object) -> UiJob:
        return update_job(self.root, job, **updates)


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
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize_job_payload(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): sanitize_job_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_job_payload(item) for item in value]
    if isinstance(value, str):
        return sanitize_ui_text(value)
    return value
