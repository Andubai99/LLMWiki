from __future__ import annotations

import json

from llmwiki.research.relationships import build_research_graph_run, build_research_graph_status
from tests.test_metric_repair_staging import changed_paths
from tests.test_metric_timeline_readonly import snapshot_workspace
from tests.test_research_relationship_cli import FakeResearchProvider
from tests.test_metric_repair_query import workspace_with_metric_repair_cases


def test_research_graph_run_writes_only_allowed_staging_artifacts(monkeypatch) -> None:
    root = workspace_with_metric_repair_cases()
    before = snapshot_workspace(root)
    monkeypatch.setattr("llmwiki.research.relationships.create_provider", lambda config, root=None: FakeResearchProvider())

    run = build_research_graph_run(root, source_id="src_pdf")
    run_id = run.relationship_run_id

    run_dir = root / "staging" / run_id
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "relationship-bundles.jsonl",
        "relationship-edges.jsonl",
        "research-graph.json",
        "research-synthesis.json",
        "run.json",
        "triage.md",
        "warnings.jsonl",
    ]
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "research_relationship_run.v5.0"
    assert manifest["run_type"] == "research_relationship_graph"
    assert manifest["status"] == "staged"
    assert "api_key" not in json.dumps(manifest).casefold()
    assert "raw_prompt" not in json.dumps(manifest).casefold()

    after = snapshot_workspace(root)
    assert changed_paths(before, after) == {
        f"staging/{run_id}/run.json",
        f"staging/{run_id}/relationship-bundles.jsonl",
        f"staging/{run_id}/relationship-edges.jsonl",
        f"staging/{run_id}/research-graph.json",
        f"staging/{run_id}/research-synthesis.json",
        f"staging/{run_id}/warnings.jsonl",
        f"staging/{run_id}/triage.md",
    }

    status = build_research_graph_status(root, run_id).to_dict()
    assert status["relationship_run_id"] == run_id
    assert status["summary"]["edge_count"] >= 1
