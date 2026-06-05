from __future__ import annotations

import json

from llmwiki.metrics.repair import (
    append_metric_repair_decision,
    build_metric_repair_plan,
    read_metric_repair_status,
    stage_metric_repair_plan,
)
from tests.test_metric_repair_query import workspace_with_metric_repair_cases
from tests.test_metric_timeline_readonly import snapshot_workspace


def changed_paths(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> set[str]:
    return {path for path in set(before) | set(after) if before.get(path) != after.get(path)}


def test_stage_metric_repair_plan_writes_only_allowed_artifacts() -> None:
    root = workspace_with_metric_repair_cases()
    before = snapshot_workspace(root)

    staged = stage_metric_repair_plan(root, build_metric_repair_plan(root), label="unit")
    run_id = staged.repair_run_id

    run_dir = root / "staging" / run_id
    assert run_id.startswith("run_metric_repair_")
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "metric-repair-decisions.jsonl",
        "metric-repair-plan.json",
        "metric-repair-proposals.jsonl",
        "run.json",
        "triage.md",
    ]
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "metric_repair_run.v4.8"
    assert manifest["run_type"] == "metric_repair_review"
    assert manifest["status"] == "staged"
    plan = json.loads((run_dir / "metric-repair-plan.json").read_text(encoding="utf-8"))
    assert plan["schema_version"] == "metric_repair_plan.v4.8"
    assert (run_dir / "metric-repair-decisions.jsonl").read_text(encoding="utf-8") == ""

    after = snapshot_workspace(root)
    assert changed_paths(before, after) == {
        f"staging/{run_id}/run.json",
        f"staging/{run_id}/metric-repair-plan.json",
        f"staging/{run_id}/metric-repair-proposals.jsonl",
        f"staging/{run_id}/metric-repair-decisions.jsonl",
        f"staging/{run_id}/triage.md",
    }


def test_repair_status_and_mark_append_decisions_without_overwriting() -> None:
    root = workspace_with_metric_repair_cases()
    staged = stage_metric_repair_plan(root, build_metric_repair_plan(root), label="unit")
    proposal_id = staged.proposals[0]["proposal_id"]

    first = append_metric_repair_decision(root, staged.repair_run_id, proposal_id, status="accepted", reason="reviewed")
    second = append_metric_repair_decision(root, staged.repair_run_id, proposal_id, status="rejected", reason="changed mind")
    status = read_metric_repair_status(root, staged.repair_run_id).to_dict()

    assert first["schema_version"] == "metric_repair_review_decision.v4.8"
    assert second["decision_id"] != first["decision_id"]
    assert status["schema_version"] == "metric_repair_plan.v4.8"
    assert status["summary"]["decision_count"] == 2
    assert status["summary"]["rejected_proposal_count"] == 1
    assert status["proposals"][0]["current_decision"]["status"] == "rejected"
    decision_lines = (root / "staging" / staged.repair_run_id / "metric-repair-decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(decision_lines) == 2
