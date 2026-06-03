from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


SUPPORTED_SUFFIXES = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".html": "web",
    ".htm": "web",
    ".pdf": "pdf",
}

IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "state",
    "staging",
    "sources",
    "wiki",
    ".test-workspaces",
    ".tmp",
    "__pycache__",
}


@dataclass(frozen=True)
class DiscoveredSource:
    path: Path
    source_kind: str


def discover_sources(
    root: Path,
    inputs: list[str],
    *,
    recursive: bool = False,
    list_file: str | None = None,
) -> list[DiscoveredSource]:
    root = root.resolve()
    paths: list[Path] = []
    for locator in inputs:
        if _is_url(locator):
            raise ValueError("URL batch import is not supported in V4.1")
        paths.append(Path(locator))
    if list_file:
        list_path = Path(list_file).resolve()
        base = list_path.parent
        for line in list_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if _is_url(stripped):
                raise ValueError("URL batch import is not supported in V4.1")
            entry = Path(stripped)
            paths.append(entry if entry.is_absolute() else base / entry)

    discovered: dict[Path, DiscoveredSource] = {}
    for path in paths:
        resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
        if not resolved.exists():
            raise FileNotFoundError(str(path))
        for source in _discover_path(resolved, recursive=recursive):
            discovered[source.path] = source
    return [discovered[path] for path in sorted(discovered, key=lambda item: item.as_posix())]


def _discover_path(path: Path, *, recursive: bool) -> list[DiscoveredSource]:
    if path.is_file():
        source_kind = source_kind_for_path(path)
        return [DiscoveredSource(path=path.resolve(), source_kind=source_kind)] if source_kind else []
    if not path.is_dir():
        return []
    children = sorted(path.iterdir(), key=lambda child: child.resolve().as_posix())
    results: list[DiscoveredSource] = []
    for child in children:
        if child.is_dir():
            if child.name in IGNORED_DIRECTORIES:
                continue
            if recursive:
                results.extend(_discover_path(child, recursive=True))
            continue
        source_kind = source_kind_for_path(child)
        if source_kind:
            results.append(DiscoveredSource(path=child.resolve(), source_kind=source_kind))
    return results


def source_kind_for_path(path: Path) -> str:
    return SUPPORTED_SUFFIXES.get(path.suffix.lower(), "")


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}
