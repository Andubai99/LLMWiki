from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .db import catalog_path, init_db, schema_status


REQUIRED_PATHS = (
    "config.toml",
    "AGENTS.md",
    "sources/raw",
    "sources/normalized",
    "state/catalog.sqlite",
    "wiki/index.md",
    "wiki/log.md",
    "wiki/sources",
    "wiki/concepts",
    "wiki/entities",
    "wiki/syntheses",
    "staging",
    "state",
)

DEFAULT_CONFIG = """\
[workspace]
name = "LLM Wiki"

[sources]
raw_dir = "sources/raw"
normalized_dir = "sources/normalized"

[wiki]
root = "wiki"

[staging]
root = "staging"

[catalog]
path = "state/catalog.sqlite"

[llm]
enabled = true
provider = "openai"
model = "deepseek-v4-pro"
base_url = "https://api.deepseek.com"
api_key_env = "DEEPSEEK_API_KEY"
timeout_seconds = 60
"""

DEFAULT_AGENTS = """\
# LLM Wiki Agent Contract

This repository is a local, source-backed research wiki. Treat it as a knowledge compiler workspace, not as a free-form notes folder.

## Operating Rules

- Do not modify files under `sources/raw/`.
- Do not write final wiki pages directly during ingest. Write candidate changes under `staging/<run-id>/`.
- Every substantive claim proposed for the wiki must cite a source id and a page, line, or paragraph anchor when available.
- Preserve uncertainty. If sources disagree, create a conflict note in triage instead of choosing a winner.
- Prefer updating existing concept/entity pages over creating near-duplicate pages.
- Keep Markdown readable in Obsidian.
- Treat `state/catalog.sqlite` as a rebuildable cache. The durable assets are raw sources, normalized sources, and Markdown wiki pages.
- Real LLM calls are allowed through the configured OpenAI-compatible DeepSeek provider.
- API Key values, tokens, `.env` files, and sensitive logs must never be committed.
- The DeepSeek API Key must be read from the `DEEPSEEK_API_KEY` environment variable.
- LLM output must not bypass staging, review, and apply.
- This version does not default to vector databases, MCP, Web UI, cloud sync, or team permissions.
"""

DEFAULT_INDEX = """\
---
page_type: index
title: LLM Wiki Index
aliases: []
source_count: 0
claim_ids: []
updated_at: "{updated_at}"
---

# LLM Wiki Index

## Sources

No sources applied yet.

## Concepts

No concepts applied yet.

## Entities

No entities applied yet.

## Syntheses

No syntheses applied yet.
"""

DEFAULT_LOG = """\
---
page_type: log
title: LLM Wiki Log
aliases: []
source_count: 0
claim_ids: []
updated_at: "{updated_at}"
---

# LLM Wiki Log

"""


@dataclass(frozen=True)
class WorkspaceCheck:
    root: Path
    missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing


def check_workspace(root: Path) -> WorkspaceCheck:
    missing = tuple(path for path in REQUIRED_PATHS if not (root / path).exists())
    return WorkspaceCheck(root=root, missing=missing)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for directory in (
        "sources/raw",
        "sources/normalized",
        "wiki/sources",
        "wiki/concepts",
        "wiki/entities",
        "wiki/syntheses",
        "staging",
        "state",
    ):
        (root / directory).mkdir(parents=True, exist_ok=True)

    now = utc_now()
    write_if_missing(root / "config.toml", DEFAULT_CONFIG)
    write_if_missing(root / "AGENTS.md", DEFAULT_AGENTS)
    write_if_missing(root / "wiki/index.md", DEFAULT_INDEX.format(updated_at=now))
    write_if_missing(root / "wiki/log.md", DEFAULT_LOG.format(updated_at=now))
    init_db(catalog_path(root))


def write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def workspace_health(root: Path) -> tuple[bool, list[str]]:
    result = check_workspace(root)
    problems = [f"missing {path}" for path in result.missing]
    schema_ok, schema_problems = schema_status(catalog_path(root))
    if not schema_ok:
        problems.extend(schema_problems)
    return not problems, problems
