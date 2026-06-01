from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class MinerUCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class MinerUCommandRequest:
    root: Path
    source_id: str
    raw_path: Path
    output_root: Path
    config: Any


@dataclass(frozen=True)
class MinerUCommandResult:
    command: list[str]
    output_root: Path
    returncode: int
    duration_seconds: float
    stdout_snippet: str
    stderr_snippet: str
    content_list_candidates: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timed_out: bool = False


def build_mineru_command(request: MinerUCommandRequest) -> list[str]:
    config = request.config
    command = [
        str(config.mineru_command),
        "-p",
        str(request.raw_path),
        "-o",
        str(request.output_root),
    ]
    if config.mineru_method:
        command.extend(["-m", str(config.mineru_method)])
    if config.mineru_backend:
        command.extend(["-b", str(config.mineru_backend)])
    if config.mineru_api_url:
        command.extend(["--api-url", str(config.mineru_api_url)])
    command.extend(str(item) for item in getattr(config, "mineru_extra_args", ()) if str(item))
    return command


def run_mineru_command(
    request: MinerUCommandRequest,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> MinerUCommandResult:
    request.output_root.mkdir(parents=True, exist_ok=True)
    command = build_mineru_command(request)
    started = time.monotonic()
    max_chars = int(getattr(request.config, "mineru_max_log_chars", 4000))
    try:
        completed = runner(
            command,
            cwd=str(request.root),
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=int(getattr(request.config, "mineru_timeout_seconds", 1800)),
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        return MinerUCommandResult(
            command=sanitize_command(command),
            output_root=request.output_root,
            returncode=-1,
            duration_seconds=duration,
            stdout_snippet=sanitize_parser_log(_safe_text(exc.output), max_chars=max_chars),
            stderr_snippet=sanitize_parser_log(_safe_text(exc.stderr), max_chars=max_chars),
            warnings=[f"MinerU command timed out after {exc.timeout} seconds"],
            timed_out=True,
        )

    duration = time.monotonic() - started
    candidates = discover_mineru_content_lists(request.output_root, pdf_stem=request.raw_path.stem)
    warnings: list[str] = []
    if completed.returncode != 0:
        warnings.append(f"MinerU command exited with code {completed.returncode}")
    if not candidates:
        warnings.append("MinerU content-list output was not found")
    return MinerUCommandResult(
        command=sanitize_command(command),
        output_root=request.output_root,
        returncode=int(completed.returncode),
        duration_seconds=duration,
        stdout_snippet=sanitize_parser_log(_safe_text(completed.stdout), max_chars=max_chars),
        stderr_snippet=sanitize_parser_log(_safe_text(completed.stderr), max_chars=max_chars),
        content_list_candidates=candidates,
        warnings=warnings,
        timed_out=False,
    )


def discover_mineru_content_lists(output_root: Path, *, pdf_stem: str = "") -> list[Path]:
    if not output_root.exists():
        return []
    names = {
        "content_list.json",
        "content_list_v2.json",
    }
    candidates = [
        path
        for path in output_root.rglob("*.json")
        if path.name in names or path.name.endswith("_content_list.json") or path.name.endswith("_content_list_v2.json")
    ]
    return sorted(candidates, key=lambda path: _candidate_sort_key(path, pdf_stem))


def select_mineru_content_list(candidates: list[Path], *, pdf_stem: str = "") -> Path:
    usable = [path for path in candidates if path.exists() and path.stat().st_size > 0]
    if not usable:
        raise MinerUCommandError("MinerU content-list output was not found")
    sorted_candidates = sorted(usable, key=lambda path: _candidate_sort_key(path, pdf_stem))
    best = sorted_candidates[0]
    tied = [
        path
        for path in sorted_candidates
        if _candidate_sort_key(path, pdf_stem)[:3] == _candidate_sort_key(best, pdf_stem)[:3]
    ]
    if len(tied) > 1:
        raise MinerUCommandError("Ambiguous MinerU content-list outputs")
    return best


def probe_mineru_status(config: Any) -> dict[str, object]:
    command_path = shutil.which(str(config.mineru_command))
    return {
        "mineru_command": str(config.mineru_command),
        "mineru_command_path": command_path or "",
        "mineru_enabled": bool(config.mineru_enabled),
        "mineru_available": bool(config.mineru_enabled and command_path),
    }


def sanitize_parser_log(text: str, *, max_chars: int) -> str:
    sanitized = _safe_text(text)
    sanitized = re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "[redacted-secret]", sanitized)
    sanitized = re.sub(r"(?i)(api[_-]?key=)[^\s&]+", r"\1[redacted-secret]", sanitized)
    sanitized = sanitized.replace("config/api-keys.toml", "[redacted-config]")
    sanitized = sanitized.replace("config\\api-keys.toml", "[redacted-config]")
    sanitized = sanitized.strip()
    if max_chars < 1:
        return ""
    if len(sanitized) > max_chars:
        return sanitized[: max(0, max_chars - 1)].rstrip() + "…"
    return sanitized


def sanitize_command(command: list[str]) -> list[str]:
    sanitized: list[str] = []
    redact_next = False
    for item in command:
        if redact_next:
            sanitized.append(_redact_url_or_secret(item))
            redact_next = False
            continue
        sanitized.append(item)
        if item == "--api-url":
            redact_next = True
    return sanitized


def _candidate_sort_key(path: Path, pdf_stem: str) -> tuple[int, int, int, str]:
    name = path.name
    is_v2 = 1 if "content_list_v2" in name or name.endswith("_content_list_v2.json") else 0
    stem_match = 0 if pdf_stem and pdf_stem.casefold() in path.as_posix().casefold() else 1
    empty = 1 if path.exists() and path.stat().st_size == 0 else 0
    return (empty, is_v2, stem_match, path.as_posix())


def _redact_url_or_secret(value: str) -> str:
    value = re.sub(r"(?i)(api[_-]?key=)[^&]+", r"\1[redacted-secret]", value)
    value = re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "[redacted-secret]", value)
    return value


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
