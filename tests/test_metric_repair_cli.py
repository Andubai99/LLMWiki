from __future__ import annotations

import json

from llmwiki.cli import build_parser, main
from tests.test_metric_repair_query import workspace_with_metric_repair_cases


def test_cli_includes_metric_repair_commands() -> None:
    parser = build_parser()

    args = parser.parse_args(["metric", "repair-plan", "--root", ".", "--json"])
    assert args.command == "metric"
    assert args.metric_command == "repair-plan"

    args = parser.parse_args(["metric", "repair-status", "run_metric_repair_20260605000000_abcd1234", "--root", "."])
    assert args.metric_command == "repair-status"

    args = parser.parse_args(
        [
            "metric",
            "repair-mark",
            "run_metric_repair_20260605000000_abcd1234",
            "mrp_123456789abc",
            "--root",
            ".",
            "--status",
            "accepted",
        ]
    )
    assert args.metric_command == "repair-mark"


def test_metric_repair_plan_cli_outputs_json_human_and_stage(capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()

    assert main(["metric", "repair-plan", "--root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "metric_repair_plan.v4.8"
    assert payload["summary"]["proposal_count_unpaged"] > 0

    assert main(["metric", "repair-plan", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Metric repair plan" in out
    assert "Year repairs" in out
    assert "Value repairs" in out

    assert main(["metric", "repair-plan", "--root", str(root), "--stage", "--label", "cli", "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)
    assert staged["repair_run_id"].startswith("run_metric_repair_")
    assert (root / "staging" / staged["repair_run_id"] / "run.json").exists()


def test_metric_repair_status_and_mark_cli(capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()

    assert main(["metric", "repair-plan", "--root", str(root), "--stage", "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)
    run_id = staged["repair_run_id"]
    proposal_id = staged["proposals"][0]["proposal_id"]

    assert main(["metric", "repair-mark", run_id, proposal_id, "--root", str(root), "--status", "accepted", "--reason", "reviewed", "--json"]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["status"] == "accepted"

    assert main(["metric", "repair-status", run_id, "--root", str(root), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["summary"]["accepted_proposal_count"] == 1

    assert main(["metric", "repair-status", run_id, "--root", str(root)]) == 0
    assert "Metric repair status" in capsys.readouterr().out


def test_metric_repair_cli_invalid_args_return_one(capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()

    assert main(["metric", "repair-plan", "--root", str(root), "--limit", "0"]) == 1
    assert "Metric repair plan failed:" in capsys.readouterr().out

    assert main(["metric", "repair-status", "missing_run", "--root", str(root)]) == 1
    assert "Metric repair status failed:" in capsys.readouterr().out
