from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


CACHE_DIRECTORIES = (
    ".test-workspaces",
    ".pytest_cache",
    ".tmp",
    ".ruff_cache",
    ".mypy_cache",
)

GENERATED_CLEAR_DIRECTORIES = (
    "sources/raw",
    "sources/normalized",
    "sources/metadata",
    "sources/blocks",
    "sources/chunks",
    "sources/parser-artifacts",
    "staging",
    "state/corpus-batches",
    "state/embeddings",
    "state/ui-jobs",
    "wiki/sources",
    "wiki/concepts",
    "wiki/entities",
    "wiki/syntheses",
)

GENERATED_FILES = (
    "state/catalog.sqlite",
    "state/catalog.sqlite-shm",
    "state/catalog.sqlite-wal",
    "wiki/index.md",
    "wiki/log.md",
)

PYCACHE_SEARCH_ROOTS = ("src", "tests", "llmwiki")

SCOPES = ("cache", "generated", "all")


@dataclass(frozen=True)
class CleanResult:
    root: Path
    scope: str
    dry_run: bool
    removed: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)


def clean_workspace(root: Path, *, scope: str = "cache", dry_run: bool = False) -> CleanResult:
    if scope not in SCOPES:
        raise ValueError(f"unknown clean scope: {scope}")
    resolved_root = root.resolve()
    removed: list[Path] = []
    kept: list[Path] = []

    if scope in {"cache", "all"}:
        for relative in CACHE_DIRECTORIES:
            target = safe_target(resolved_root, relative)
            remove_path(target, root=resolved_root, dry_run=dry_run, removed=removed)
        for target in sorted(find_pycache_directories(resolved_root)):
            remove_path(target, root=resolved_root, dry_run=dry_run, removed=removed)

    if scope in {"generated", "all"}:
        for relative in GENERATED_CLEAR_DIRECTORIES:
            target = safe_target(resolved_root, relative)
            clear_directory(target, root=resolved_root, dry_run=dry_run, removed=removed, kept=kept)
        for relative in GENERATED_FILES:
            target = safe_target(resolved_root, relative)
            remove_path(target, root=resolved_root, dry_run=dry_run, removed=removed)

    return CleanResult(
        root=resolved_root,
        scope=scope,
        dry_run=dry_run,
        removed=sorted(unique_paths(removed)),
        kept=sorted(unique_paths(kept)),
    )


def format_clean_report(result: CleanResult) -> str:
    lines = [
        f"Cleaned scope: {result.scope}",
        f"Dry run: {str(result.dry_run).lower()}",
        f"Removed count: {len(result.removed)}",
    ]
    if result.dry_run:
        lines.append("Would remove:")
    else:
        lines.append("Removed:")
    if result.removed:
        for path in result.removed:
            lines.append(f"- {display_path(result.root, path)}")
    else:
        lines.append("- none")
    if result.kept:
        lines.append("Preserved:")
        for path in result.kept:
            lines.append(f"- {display_path(result.root, path)}")
    return "\n".join(lines)


def safe_target(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    ensure_under_root(root, target)
    return target


def ensure_under_root(root: Path, target: Path) -> None:
    if target == root:
        return
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"refusing to clean path outside workspace: {target}") from exc


def find_pycache_directories(root: Path) -> list[Path]:
    results: list[Path] = []
    resolved_root = root.resolve()
    stack = [
        safe_target(resolved_root, relative)
        for relative in PYCACHE_SEARCH_ROOTS
        if (resolved_root / relative).exists()
    ]
    root_pycache = resolved_root / "__pycache__"
    if root_pycache.exists():
        stack.append(root_pycache)
    while stack:
        current = stack.pop()
        if current.name == "__pycache__":
            if current.is_dir() and not current.is_symlink():
                results.append(current.resolve())
            continue
        try:
            children = sorted(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_symlink() or not child.is_dir():
                continue
            resolved_child = child.resolve()
            ensure_under_root(resolved_root, resolved_child)
            if child.name == "__pycache__":
                results.append(resolved_child)
                continue
            stack.append(resolved_child)
    return results


def clear_directory(target: Path, *, root: Path, dry_run: bool, removed: list[Path], kept: list[Path]) -> None:
    ensure_under_root(root, Path(os.path.abspath(target)))
    if not target.exists():
        return
    if not target.is_dir():
        remove_path(target, root=root, dry_run=dry_run, removed=removed)
        return
    for child in sorted(target.iterdir()):
        if child.name == ".gitkeep":
            kept.append(child.resolve())
            continue
        remove_path(child, root=root, dry_run=dry_run, removed=removed)


def remove_path(target: Path, *, root: Path, dry_run: bool, removed: list[Path]) -> None:
    if not target.exists() and not target.is_symlink():
        return
    workspace_entry = Path(os.path.abspath(target))
    ensure_under_root(root, workspace_entry)
    if not target.is_symlink():
        ensure_under_root(root, target.resolve())
    removed.append(workspace_entry)
    if dry_run:
        return
    if target.is_symlink():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
