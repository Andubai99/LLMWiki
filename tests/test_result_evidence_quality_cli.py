from __future__ import annotations

import json

from llmwiki.cli import build_parser, main
from tests.test_result_evidence_quality_model import workspace_with_result_evidence


def test_cli_includes_result_evidence_eval_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["eval", "result-evidence", "--root", ".", "--json"])
    assert args.command == "eval"
    assert args.eval_command == "result-evidence"


def test_result_evidence_cli_outputs_json_and_human(capsys) -> None:
    root = workspace_with_result_evidence()
    capsys.readouterr()

    assert main(["eval", "result-evidence", "--root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "result_evidence_quality.v4.5"
    assert payload["summary"]["metric_result_count"] == 3

    assert main(["eval", "result-evidence", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Result evidence quality" in out
    assert "Metric results: 3" in out
    assert "res_missing_value" in out
    assert "missing_metric_value" in out


def test_result_evidence_cli_filters_and_invalid_args(capsys) -> None:
    root = workspace_with_result_evidence()
    capsys.readouterr()

    assert main(["eval", "result-evidence", "--root", str(root), "--metric", "accuracy", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["metric_result_count"] == 1
    assert payload["items"][0]["result_id"] == "res_md"

    assert main(["eval", "result-evidence", "--root", str(root), "--limit", "0"]) == 1
    assert "Result evidence eval failed:" in capsys.readouterr().out
