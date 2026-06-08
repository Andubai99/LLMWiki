from __future__ import annotations

import json

from llmwiki.cli import main
from tests.test_metric_llm_normalization_cli import FakeProvider
from tests.test_metric_repair_query import workspace_with_metric_repair_cases
from tests.test_metric_timeline_readonly import snapshot_workspace


def test_metric_normalization_dry_run_status_and_synthesis_are_read_only(monkeypatch, capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()
    monkeypatch.setattr("llmwiki.metrics.llm_normalization.create_provider", lambda config, root=None: FakeProvider())
    assert main(["metric", "normalize", "--root", str(root), "--source-id", "src_pdf", "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)
    before = snapshot_workspace(root)

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only V4.9 command must not call LLM or write")

    monkeypatch.setattr("llmwiki.metrics.llm_normalization.create_provider", forbidden)

    assert main(["metric", "normalize", "--root", str(root), "--dry-run", "--json"]) == 0
    json.loads(capsys.readouterr().out)
    assert main(["metric", "normalize-status", staged["normalization_run_id"], "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)
    assert main(["metric", "timeline-synthesis", staged["normalization_run_id"], "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)

    assert snapshot_workspace(root) == before


def test_metric_normalization_commands_do_not_call_forbidden_surfaces(monkeypatch, capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()

    def forbidden(*args, **kwargs):
        raise AssertionError("metric normalization must not call mutating/parser surfaces")

    import llmwiki.cli as cli
    import llmwiki.corpus.runner as corpus_runner
    import llmwiki.ingestion.pipeline as pipeline
    import llmwiki.ingestion.apply as apply_mod
    import llmwiki.ingestion.ingest as ingest_mod
    import llmwiki.pdf.mineru_runner as mineru_runner
    import llmwiki.pdf.parser_backends as parser_backends
    import llmwiki.synthesis as synthesis_engine
    import llmwiki.vector.embeddings as embeddings

    monkeypatch.setattr("llmwiki.metrics.llm_normalization.create_provider", lambda config, root=None: FakeProvider())
    monkeypatch.setattr(pipeline, "add_and_process_source", forbidden)
    monkeypatch.setattr(apply_mod, "apply_run", forbidden)
    monkeypatch.setattr(ingest_mod, "ingest_source", forbidden)
    monkeypatch.setattr(corpus_runner, "import_corpus", forbidden)
    monkeypatch.setattr(corpus_runner, "retry_corpus", forbidden)
    monkeypatch.setattr(embeddings, "create_embedding_provider", forbidden)
    monkeypatch.setattr(mineru_runner, "run_mineru_command", forbidden)
    monkeypatch.setattr(parser_backends, "select_pdf_parser_backend", forbidden)
    monkeypatch.setattr(synthesis_engine, "create_synthesis_run", forbidden)
    monkeypatch.setattr(cli, "cmd_ask", forbidden)
    monkeypatch.setattr(cli, "cmd_clean", forbidden)
    monkeypatch.setattr(cli, "cmd_lint", forbidden)

    assert main(["metric", "normalize", "--root", str(root), "--source-id", "src_pdf", "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)
    assert main(["metric", "normalize-status", staged["normalization_run_id"], "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)
    assert main(["metric", "timeline-synthesis", staged["normalization_run_id"], "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)
