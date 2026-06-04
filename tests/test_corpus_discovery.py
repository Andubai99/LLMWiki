from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.corpus.discovery import discover_sources
from tests.helpers import make_workspace


def write_file(path: Path, text: str = "source") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_discover_sources_is_non_recursive_by_default_and_sorted() -> None:
    root = make_workspace()
    corpus = root / "docs" / "papers"
    b = write_file(corpus / "b.pdf")
    a = write_file(corpus / "a.md")
    write_file(corpus / "nested" / "c.pdf")
    write_file(corpus / "ignore.tmp")

    found = discover_sources(root, [str(corpus)], recursive=False)

    assert [item.path for item in found] == [a.resolve(), b.resolve()]
    assert [item.source_kind for item in found] == ["markdown", "pdf"]


def test_discover_sources_recurses_and_ignores_generated_directories() -> None:
    root = make_workspace()
    corpus = root / "docs" / "papers"
    top = write_file(corpus / "top.pdf")
    nested = write_file(corpus / "nested" / "nested.txt")
    write_file(corpus / "state" / "generated.pdf")
    write_file(corpus / ".git" / "hidden.pdf")
    write_file(corpus / ".venv" / "hidden.pdf")
    write_file(corpus / "sources" / "hidden.md")

    found = discover_sources(root, [str(corpus)], recursive=True)

    assert [item.path for item in found] == [nested.resolve(), top.resolve()]


def test_discover_sources_reads_utf8_list_file() -> None:
    root = make_workspace()
    first = write_file(root / "paper-a.pdf")
    second = write_file(root / "paper-b.html")
    list_file = root / "sources.txt"
    list_file.write_text(f"{first.name}\n{second.name}\n\n", encoding="utf-8")

    found = discover_sources(root, [], list_file=str(list_file))

    assert [item.path for item in found] == [first.resolve(), second.resolve()]


def test_discover_sources_rejects_urls_for_v4_1() -> None:
    root = make_workspace()

    with pytest.raises(ValueError, match="URL batch import is not supported"):
        discover_sources(root, ["https://example.com/paper.pdf"])
