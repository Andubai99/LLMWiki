from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REQUIRED_PATHS = (
    "config.toml",
    "AGENTS.md",
    "sources/raw",
    "sources/normalized",
    "wiki/index.md",
    "wiki/log.md",
    "wiki/sources",
    "wiki/concepts",
    "wiki/entities",
    "wiki/syntheses",
    "staging",
    "state",
)


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
