from __future__ import annotations

import json
from pathlib import Path

from llmwiki.cli import main
from llmwiki.corpus.state import read_attempts, read_batch, read_items
from llmwiki.ingestion.pipeline import AddPipelineError, AddPipelineResult
from tests.helpers import make_workspace


def write_file(path: Path, text: str = "# Paper\n\ncontent\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def ok_result(path: Path, *, status: str = "applied") -> AddPipelineResult:
    source_id = f"src_{path.stem.replace('-', '_')}"
    return AddPipelineResult(
        source_id=source_id,
        title=path.stem,
        source_duplicate=False,
        run_id=f"run_{source_id}",
        proposal_engine="llm",
        claim_count=1,
        patch_count=1,
        applied_pages=[f"wiki/sources/{source_id}.md"],
        warnings=[],
        status=status,
    )


def latest_batch_id(root: Path) -> str:
    batches = sorted((root / "state" / "corpus-batches").iterdir())
    return batches[-1].name


def test_corpus_import_continues_after_failed_item(monkeypatch, capsys) -> None:
    import llmwiki.corpus.runner as runner

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    corpus = root / "papers"
    first = write_file(corpus / "a.md")
    failed = write_file(corpus / "b.md")
    third = write_file(corpus / "c.md")

    def fake_add(root: Path, locator: str, **kwargs):  # noqa: ANN003
        path = Path(locator)
        if path == failed:
            raise AddPipelineError(stage="ingest", reason="LLM ingest is required: sk-secret-value")
        return ok_result(path)

    monkeypatch.setattr(runner, "add_and_process_source", fake_add)
    capsys.readouterr()

    assert main(["corpus", "import", str(corpus), "--root", str(root)]) == 1
    out = capsys.readouterr().out
    batch_id = latest_batch_id(root)
    items = read_items(root, batch_id)
    attempts = read_attempts(root, batch_id)

    assert "completed_with_failures" in out
    assert [item.source_path for item in items] == [
        first.resolve().as_posix(),
        failed.resolve().as_posix(),
        third.resolve().as_posix(),
    ]
    assert [item.status for item in items] == ["applied", "failed", "applied"]
    assert len(attempts) == 3
    assert "sk-secret-value" not in attempts[1].failure_reason
    assert read_batch(root, batch_id).failed_count == 1


def test_corpus_import_fail_fast_stops_after_first_failure(monkeypatch, capsys) -> None:
    import llmwiki.corpus.runner as runner

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    corpus = root / "papers"
    write_file(corpus / "a.md")
    write_file(corpus / "b.md")

    def fake_add(root: Path, locator: str, **kwargs):  # noqa: ANN003
        raise AddPipelineError(stage="ingest", reason="boom")

    monkeypatch.setattr(runner, "add_and_process_source", fake_add)
    capsys.readouterr()

    assert main(["corpus", "import", str(corpus), "--root", str(root), "--fail-fast"]) == 1
    batch_id = latest_batch_id(root)
    assert [item.status for item in read_items(root, batch_id)] == ["failed", "pending"]
    assert len(read_attempts(root, batch_id)) == 1


def test_corpus_retry_only_reprocesses_failed_items(monkeypatch, capsys) -> None:
    import llmwiki.corpus.runner as runner

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    corpus = root / "papers"
    write_file(corpus / "a.md")
    failed = write_file(corpus / "b.md")
    calls: list[str] = []

    def first_add(root: Path, locator: str, **kwargs):  # noqa: ANN003
        calls.append(Path(locator).name)
        if Path(locator) == failed:
            raise AddPipelineError(stage="ingest", reason="first failure")
        return ok_result(Path(locator))

    monkeypatch.setattr(runner, "add_and_process_source", first_add)
    capsys.readouterr()
    assert main(["corpus", "import", str(corpus), "--root", str(root)]) == 1
    batch_id = latest_batch_id(root)

    def retry_add(root: Path, locator: str, **kwargs):  # noqa: ANN003
        calls.append(f"retry:{Path(locator).name}")
        return ok_result(Path(locator))

    monkeypatch.setattr(runner, "add_and_process_source", retry_add)

    assert main(["corpus", "retry", batch_id, "--root", str(root)]) == 0
    items = read_items(root, batch_id)
    attempts = read_attempts(root, batch_id)

    assert calls == ["a.md", "b.md", "retry:b.md"]
    assert [item.status for item in items] == ["applied", "applied"]
    assert len(attempts) == 3


def test_corpus_status_json_and_skip(monkeypatch, capsys) -> None:
    import llmwiki.corpus.runner as runner

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source = write_file(root / "papers" / "a.md")

    def fake_add(root: Path, locator: str, **kwargs):  # noqa: ANN003
        raise AddPipelineError(stage="ingest", reason="boom")

    monkeypatch.setattr(runner, "add_and_process_source", fake_add)
    capsys.readouterr()
    assert main(["corpus", "import", str(source), "--root", str(root)]) == 1
    batch_id = latest_batch_id(root)
    item_id = read_items(root, batch_id)[0].item_id

    assert main(["corpus", "skip", batch_id, item_id, "--root", str(root), "--reason", "not needed"]) == 0
    assert read_items(root, batch_id)[0].status == "skipped"
    capsys.readouterr()

    assert main(["corpus", "status", batch_id, "--root", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["batch"]["batch_id"] == batch_id
    assert data["items"][0]["status"] == "skipped"


def test_corpus_skip_item_id_does_not_match_unrelated_relative_path(monkeypatch, capsys) -> None:
    import llmwiki.corpus.runner as runner

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    corpus = root / "papers"
    first = write_file(corpus / "a.md")
    failed = write_file(corpus / "b.md")

    def fake_add(root: Path, locator: str, **kwargs):  # noqa: ANN003
        path = Path(locator)
        if path == failed:
            raise AddPipelineError(stage="ingest", reason="boom")
        return ok_result(path, status="already_applied")

    monkeypatch.setattr(runner, "add_and_process_source", fake_add)
    capsys.readouterr()

    assert main(["corpus", "import", str(corpus), "--root", str(root)]) == 1
    batch_id = latest_batch_id(root)
    items = read_items(root, batch_id)
    assert [item.status for item in items] == ["already_imported", "failed"]

    assert main(["corpus", "skip", batch_id, items[1].item_id, "--root", str(root)]) == 0
    items = read_items(root, batch_id)
    assert items[0].source_path == first.resolve().as_posix()
    assert [item.status for item in items] == ["already_imported", "skipped"]
