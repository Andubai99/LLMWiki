from __future__ import annotations

import json

from llmwiki.cli import build_parser, main
from tests.test_metric_canonicalization_query import workspace_with_canonicalization_cases


def test_cli_includes_metric_canonicalize_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["metric", "canonicalize", "--root", ".", "--json"])

    assert args.command == "metric"
    assert args.metric_command == "canonicalize"


def test_metric_canonicalize_cli_outputs_json_and_human(capsys) -> None:
    root = workspace_with_canonicalization_cases()
    capsys.readouterr()

    assert main(["metric", "canonicalize", "--root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "metric_canonicalization_report.v4.7"
    assert payload["summary"]["canonical_metric_count_unpaged"] == 3

    assert main(["metric", "canonicalize", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Metric canonicalization" in out
    assert "Success Rate" in out
    assert "ready_after_value_repair" in out
    assert "Value repairs" in out


def test_metric_canonicalize_cli_filters_and_invalid_args(capsys) -> None:
    root = workspace_with_canonicalization_cases()
    capsys.readouterr()

    assert main(["metric", "canonicalize", "--root", str(root), "--metric", "accuracy", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["result_count"] == 1

    assert main(["metric", "canonicalize", "--root", str(root), "--limit", "0"]) == 1
    assert "Metric canonicalization failed:" in capsys.readouterr().out
