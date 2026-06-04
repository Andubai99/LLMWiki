from __future__ import annotations

import json
from pathlib import Path

from llmwiki.cli import main
from tests.test_metric_timeline_query import workspace_with_metric_results


WATCHED_DIRS = (
    "wiki",
    "sources",
    "staging",
    "state/corpus-batches",
    "state/embeddings",
    "state/ui-jobs",
    ".tmp",
)


def snapshot_workspace(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for relative in WATCHED_DIRS:
        path = root / relative
        if not path.exists():
            continue
        for child in path.rglob("*"):
            if child.is_file():
                stat = child.stat()
                snapshot[child.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    catalog = root / "state" / "catalog.sqlite"
    if catalog.exists():
        stat = catalog.stat()
        snapshot["state/catalog.sqlite"] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def test_metric_commands_do_not_write_workspace_files(capsys) -> None:
    root = workspace_with_metric_results()
    before = snapshot_workspace(root)

    assert main(["metric", "list", "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)
    assert main(["metric", "timeline", "success rate", "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)

    after = snapshot_workspace(root)
    assert after == before


def test_metric_commands_do_not_call_mutating_or_provider_surfaces(monkeypatch, capsys) -> None:
    root = workspace_with_metric_results()

    def forbidden(*args, **kwargs):
        raise AssertionError("metric timeline/list must be read-only")

    import llmwiki.cli as cli
    import llmwiki.corpus.runner as corpus_runner
    import llmwiki.ingestion.add_pipeline as add_pipeline
    import llmwiki.ingestion.apply as apply_mod
    import llmwiki.ingestion.ingest as ingest_mod
    import llmwiki.pdf.mineru_backend as mineru_backend
    import llmwiki.pdf.parser as pdf_parser
    import llmwiki.providers.factory as provider_factory
    import llmwiki.synthesis.engine as synthesis_engine
    import llmwiki.vector.embeddings as embeddings

    monkeypatch.setattr(add_pipeline, "add_and_process_source", forbidden)
    monkeypatch.setattr(apply_mod, "apply_run", forbidden)
    monkeypatch.setattr(ingest_mod, "ingest_source", forbidden)
    monkeypatch.setattr(corpus_runner, "import_corpus", forbidden)
    monkeypatch.setattr(corpus_runner, "retry_corpus", forbidden)
    monkeypatch.setattr(provider_factory, "create_provider", forbidden)
    monkeypatch.setattr(embeddings, "create_embedding_provider", forbidden)
    monkeypatch.setattr(mineru_backend, "parse_pdf_with_mineru", forbidden, raising=False)
    monkeypatch.setattr(pdf_parser, "parse_pdf", forbidden)
    monkeypatch.setattr(synthesis_engine, "create_synthesis_run", forbidden)
    monkeypatch.setattr(cli, "cmd_ask", forbidden)
    monkeypatch.setattr(cli, "cmd_eval_retrieval", forbidden)
    monkeypatch.setattr(cli, "cmd_eval_pdf_quality", forbidden)
    monkeypatch.setattr(cli, "cmd_clean", forbidden)
    monkeypatch.setattr(cli, "cmd_lint", forbidden)

    assert main(["metric", "list", "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)
    assert main(["metric", "timeline", "success rate", "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)
