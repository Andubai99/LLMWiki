from __future__ import annotations

import json

from llmwiki.metrics.llm_normalization import (
    build_metric_normalization_run,
    build_metric_normalization_status,
)
from tests.test_metric_llm_normalization_cli import FakeProvider
from tests.test_metric_repair_staging import changed_paths
from tests.test_metric_repair_query import workspace_with_metric_repair_cases
from tests.test_metric_timeline_readonly import snapshot_workspace


def test_metric_normalization_run_writes_only_allowed_staging_artifacts(monkeypatch) -> None:
    root = workspace_with_metric_repair_cases()
    before = snapshot_workspace(root)
    monkeypatch.setattr("llmwiki.metrics.llm_normalization.create_provider", lambda config, root=None: FakeProvider())

    run = build_metric_normalization_run(root, source_id="src_pdf")
    run_id = run.normalization_run_id

    run_dir = root / "staging" / run_id
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "evidence-bundles.jsonl",
        "llm-normalization-decisions.jsonl",
        "run.json",
        "timeline-groups.jsonl",
        "timeline-points.jsonl",
        "timeline-synthesis.json",
        "triage.md",
        "warnings.jsonl",
    ]
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "metric_normalization_run.v4.9"
    assert manifest["run_type"] == "metric_llm_normalization"
    assert manifest["status"] == "staged"
    assert "api_key" not in json.dumps(manifest).casefold()
    assert "raw_prompt" not in json.dumps(manifest).casefold()

    after = snapshot_workspace(root)
    assert changed_paths(before, after) == {
        f"staging/{run_id}/run.json",
        f"staging/{run_id}/evidence-bundles.jsonl",
        f"staging/{run_id}/llm-normalization-decisions.jsonl",
        f"staging/{run_id}/timeline-groups.jsonl",
        f"staging/{run_id}/timeline-points.jsonl",
        f"staging/{run_id}/timeline-synthesis.json",
        f"staging/{run_id}/warnings.jsonl",
        f"staging/{run_id}/triage.md",
    }

    status = build_metric_normalization_status(root, run_id).to_dict()
    assert status["normalization_run_id"] == run_id
    assert status["summary"]["decision_count"] >= 1
