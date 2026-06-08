from __future__ import annotations

import json

from llmwiki.cli import COMMANDS, build_parser, main
from tests.test_metric_timeline_query import workspace_with_metric_results


def test_cli_includes_metric_command_group() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "metric" in COMMANDS
    assert "Query metric result timelines." in help_text

    args = parser.parse_args(["metric", "timeline", "success rate", "--root", ".", "--json"])
    assert args.command == "metric"
    assert args.metric_command == "timeline"
    assert args.metric == "success rate"

    args = parser.parse_args(["metric", "list", "--root", ".", "--json"])
    assert args.metric_command == "list"


def test_metric_list_cli_outputs_json_and_human(capsys) -> None:
    root = workspace_with_metric_results()
    capsys.readouterr()

    assert main(["metric", "list", "--root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "metric_list.v4.4"
    assert payload["metric_count"] == 2

    assert main(["metric", "list", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Metric list" in out
    assert "Success Rate" in out
    assert "Rows" in out


def test_metric_timeline_cli_outputs_json_and_human(capsys) -> None:
    root = workspace_with_metric_results()
    capsys.readouterr()

    assert main(["metric", "timeline", "success rate", "--root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "metric_timeline.v4.4"
    assert payload["item_count"] == 3

    assert main(["metric", "timeline", "success rate", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Metric timeline: success rate" in out
    assert "2023 Alpha Paper" in out
    assert "clm_a" in out
    assert "line:1" in out


def test_metric_timeline_cli_invalid_args_return_one(capsys) -> None:
    root = workspace_with_metric_results()
    capsys.readouterr()

    assert main(["metric", "timeline", "success rate", "--root", str(root), "--limit", "0"]) == 1
    assert "Metric timeline failed:" in capsys.readouterr().out

    assert main(["metric", "list", "--root", str(root), "--offset", "-1"]) == 1
    assert "Metric list failed:" in capsys.readouterr().out
