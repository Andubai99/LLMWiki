from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..workspace import utc_now


BATCH_SCHEMA_VERSION = "corpus_batch.v4.1"
ITEM_SCHEMA_VERSION = "corpus_item.v4.1"
ATTEMPT_SCHEMA_VERSION = "corpus_attempt.v4.1"


@dataclass
class BatchManifest:
    batch_id: str
    root: str
    input_paths: list[str]
    status: str = "pending"
    item_count: int = 0
    started_count: int = 0
    applied_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    already_imported_count: int = 0
    interrupted_count: int = 0
    active_item_id: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    schema_version: str = BATCH_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BatchManifest":
        payload = dict(data)
        payload.setdefault("schema_version", BATCH_SCHEMA_VERSION)
        payload.setdefault("created_at", utc_now())
        payload.setdefault("updated_at", payload["created_at"])
        payload.setdefault("status", "pending")
        payload.setdefault("item_count", 0)
        payload.setdefault("started_count", 0)
        payload.setdefault("applied_count", 0)
        payload.setdefault("failed_count", 0)
        payload.setdefault("skipped_count", 0)
        payload.setdefault("already_imported_count", 0)
        payload.setdefault("interrupted_count", 0)
        payload.setdefault("active_item_id", "")
        payload.setdefault("options", {})
        return cls(**payload)


@dataclass
class CorpusItem:
    batch_id: str
    item_id: str
    source_path: str
    source_kind: str
    status: str = "pending"
    source_id: str = ""
    latest_run_id: str = ""
    parser_requested: str = ""
    parser_backend: str = ""
    attempt_count: int = 0
    failure_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    schema_version: str = ITEM_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CorpusItem":
        payload = dict(data)
        payload.setdefault("schema_version", ITEM_SCHEMA_VERSION)
        payload.setdefault("status", "pending")
        payload.setdefault("source_id", "")
        payload.setdefault("latest_run_id", "")
        payload.setdefault("parser_requested", "")
        payload.setdefault("parser_backend", "")
        payload.setdefault("attempt_count", 0)
        payload.setdefault("failure_reason", "")
        payload.setdefault("warnings", [])
        payload.setdefault("created_at", utc_now())
        payload.setdefault("updated_at", payload["created_at"])
        return cls(**payload)


@dataclass
class CorpusAttempt:
    batch_id: str
    item_id: str
    attempt_id: str
    status: str
    started_at: str = field(default_factory=utc_now)
    ended_at: str = ""
    source_id: str = ""
    run_id: str = ""
    parser_requested: str = ""
    parser_backend: str = ""
    failure_stage: str = ""
    failure_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    schema_version: str = ATTEMPT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CorpusAttempt":
        payload = dict(data)
        payload.setdefault("schema_version", ATTEMPT_SCHEMA_VERSION)
        payload.setdefault("started_at", utc_now())
        payload.setdefault("ended_at", "")
        payload.setdefault("source_id", "")
        payload.setdefault("run_id", "")
        payload.setdefault("parser_requested", "")
        payload.setdefault("parser_backend", "")
        payload.setdefault("failure_stage", "")
        payload.setdefault("failure_reason", "")
        payload.setdefault("warnings", [])
        return cls(**payload)


def corpus_batches_dir(root: Path) -> Path:
    return root.resolve() / "state" / "corpus-batches"


def batch_dir(root: Path, batch_id: str) -> Path:
    return corpus_batches_dir(root) / batch_id


def batch_path(root: Path, batch_id: str) -> Path:
    return batch_dir(root, batch_id) / "batch.json"


def items_path(root: Path, batch_id: str) -> Path:
    return batch_dir(root, batch_id) / "items.jsonl"


def attempts_path(root: Path, batch_id: str) -> Path:
    return batch_dir(root, batch_id) / "attempts.jsonl"


def events_path(root: Path, batch_id: str) -> Path:
    return batch_dir(root, batch_id) / "events.jsonl"


def create_batch_id(root: Path, input_paths: list[str]) -> str:
    seed = "\n".join([root.resolve().as_posix(), *input_paths, utc_now()])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    timestamp = utc_now().replace("-", "").replace(":", "").replace(".", "")
    timestamp = timestamp.replace("+", "Z").replace("T", "T")
    safe_timestamp = "".join(ch for ch in timestamp if ch.isalnum() or ch in {"T", "Z"})
    return f"batch_{safe_timestamp}_{digest}"


def item_id_for_path(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        key = resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        key = resolved_path.as_posix()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"item_{digest}"


def write_batch(root: Path, manifest: BatchManifest) -> None:
    target_dir = batch_dir(root, manifest.batch_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest.updated_at = utc_now()
    batch_path(root, manifest.batch_id).write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read_batch(root: Path, batch_id: str) -> BatchManifest:
    data = json.loads(batch_path(root, batch_id).read_text(encoding="utf-8"))
    return BatchManifest.from_dict(data)


def write_items(root: Path, batch_id: str, items: list[CorpusItem]) -> None:
    target_dir = batch_dir(root, batch_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(item.to_dict(), ensure_ascii=False) + "\n" for item in items)
    items_path(root, batch_id).write_text(text, encoding="utf-8", newline="\n")


def read_items(root: Path, batch_id: str) -> list[CorpusItem]:
    path = items_path(root, batch_id)
    if not path.exists():
        return []
    return [
        CorpusItem.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_attempt(root: Path, attempt: CorpusAttempt) -> None:
    target_dir = batch_dir(root, attempt.batch_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    with attempts_path(root, attempt.batch_id).open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(attempt.to_dict(), ensure_ascii=False) + "\n")


def read_attempts(root: Path, batch_id: str) -> list[CorpusAttempt]:
    path = attempts_path(root, batch_id)
    if not path.exists():
        return []
    return [
        CorpusAttempt.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_event(root: Path, *, batch_id: str, item_id: str = "", event_type: str, message: str) -> None:
    target_dir = batch_dir(root, batch_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": utc_now(),
        "batch_id": batch_id,
        "item_id": item_id,
        "event_type": event_type,
        "message": message,
    }
    with events_path(root, batch_id).open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(root: Path, batch_id: str) -> list[dict[str, Any]]:
    path = events_path(root, batch_id)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def list_batch_ids(root: Path) -> list[str]:
    base = corpus_batches_dir(root)
    if not base.exists():
        return []
    return sorted(path.name for path in base.iterdir() if (path / "batch.json").exists())


def update_counts(manifest: BatchManifest, items: list[CorpusItem]) -> BatchManifest:
    manifest.item_count = len(items)
    manifest.started_count = sum(1 for item in items if item.attempt_count > 0)
    manifest.applied_count = sum(1 for item in items if item.status == "applied")
    manifest.failed_count = sum(1 for item in items if item.status == "failed")
    manifest.skipped_count = sum(1 for item in items if item.status == "skipped")
    manifest.already_imported_count = sum(1 for item in items if item.status == "already_imported")
    manifest.interrupted_count = sum(1 for item in items if item.status == "interrupted")
    return manifest
