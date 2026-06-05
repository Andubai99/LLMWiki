from __future__ import annotations

import json

from llmwiki.cli import main
from tests.test_corpus_results_eval_model import workspace_with_corpus_results
from tests.test_metric_timeline_readonly import snapshot_workspace


def test_corpus_results_eval_does_not_write_workspace_files(capsys) -> None:
    root = workspace_with_corpus_results()
    capsys.readouterr()
    before = snapshot_workspace(root)

    assert main(["eval", "corpus-results", "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)

    assert snapshot_workspace(root) == before


def test_corpus_results_eval_does_not_call_mutating_or_provider_surfaces(monkeypatch, capsys) -> None:
    root = workspace_with_corpus_results()
    capsys.readouterr()

    def forbidden(*args, **kwargs):
        raise AssertionError("corpus-results eval must be read-only")

    import llmwiki.cli as cli
    import llmwiki.corpus.runner as corpus_runner
    import llmwiki.ingestion.apply as apply_mod
    import llmwiki.ingestion.ingest as ingest_mod
    import llmwiki.ingestion.pipeline as pipeline
    import llmwiki.llm as llm
    import llmwiki.pdf.mineru_runner as mineru_runner
    import llmwiki.pdf.parser_backends as parser_backends
    import llmwiki.synthesis as synthesis_engine
    import llmwiki.vector.embeddings as embeddings

    monkeypatch.setattr(pipeline, "add_and_process_source", forbidden)
    monkeypatch.setattr(apply_mod, "apply_run", forbidden)
    monkeypatch.setattr(ingest_mod, "ingest_source", forbidden)
    monkeypatch.setattr(corpus_runner, "import_corpus", forbidden)
    monkeypatch.setattr(corpus_runner, "retry_corpus", forbidden)
    monkeypatch.setattr(llm, "create_provider", forbidden)
    monkeypatch.setattr(embeddings, "create_embedding_provider", forbidden)
    monkeypatch.setattr(mineru_runner, "run_mineru_command", forbidden)
    monkeypatch.setattr(parser_backends, "select_pdf_parser_backend", forbidden)
    monkeypatch.setattr(synthesis_engine, "create_synthesis_run", forbidden)
    monkeypatch.setattr(cli, "cmd_ask", forbidden)
    monkeypatch.setattr(cli, "cmd_eval_retrieval", forbidden)
    monkeypatch.setattr(cli, "cmd_eval_pdf_quality", forbidden)
    monkeypatch.setattr(cli, "cmd_eval_result_evidence", forbidden)
    monkeypatch.setattr(cli, "cmd_clean", forbidden)
    monkeypatch.setattr(cli, "cmd_lint", forbidden)

    assert main(["eval", "corpus-results", "--root", str(root), "--json"]) == 0
    json.loads(capsys.readouterr().out)
