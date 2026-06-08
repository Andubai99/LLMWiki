from __future__ import annotations

import json

from llmwiki.cli import build_parser, main
from tests.helpers import make_workspace
from tests.test_corpus_results_eval_model import workspace_with_corpus_results


def test_cli_includes_corpus_results_eval_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["eval", "corpus-results", "--root", ".", "--json"])
    assert args.command == "eval"
    assert args.eval_command == "corpus-results"


def test_corpus_results_cli_outputs_json_and_human(capsys) -> None:
    root = workspace_with_corpus_results()
    capsys.readouterr()

    assert main(["eval", "corpus-results", "--root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "corpus_results_eval.v4.6"
    assert payload["summary"]["metric_result_count"] == 4
    assert payload["summary"]["timeline_candidate_count"] == 1

    assert main(["eval", "corpus-results", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Corpus results acceptance" in out
    assert "Metric results: 4" in out
    assert "Quality gates" in out
    assert "Success Rate" in out


def test_corpus_results_cli_filters_and_invalid_args(capsys) -> None:
    root = workspace_with_corpus_results()
    capsys.readouterr()

    assert main(["eval", "corpus-results", "--root", str(root), "--metric", "accuracy", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["metric_result_count"] == 1
    assert payload["metrics"][0]["metric_name"] == "Accuracy"

    assert main(["eval", "corpus-results", "--root", str(root), "--limit", "0"]) == 1
    assert "Corpus results eval failed:" in capsys.readouterr().out


def test_corpus_results_cli_empty_initialized_workspace_succeeds(capsys) -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    assert main(["eval", "corpus-results", "--root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["source_count"] == 0
    assert any(warning["code"] == "no_corpus_sources" for warning in payload["warnings"])
