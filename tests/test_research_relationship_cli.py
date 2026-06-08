from __future__ import annotations

import json

from llmwiki.cli import build_parser, main
from tests.test_metric_repair_query import workspace_with_metric_repair_cases


class FakeResearchProvider:
    def complete(self, messages, schema=None):
        assert schema is not None
        bundle_text = messages[-1]["content"].split("relationship bundle:\n", 1)[1]
        bundle = json.loads(bundle_text)
        row = bundle["result_rows"][0]
        content = {
            "edges": [
                {
                    "relationship_type": "same_metric",
                    "subject": {"entity_type": "paper", "entity_id": row["paper_id"], "label": "source paper"},
                    "object": {"entity_type": "metric", "entity_id": "success_rate", "label": "success rate"},
                    "decision_status": "auto_accepted",
                    "confidence": "high",
                    "comparability_status": "comparable",
                    "rationale": "The bundle contains a cited success rate result.",
                    "evidence_refs": [
                        {
                            "result_id": row["result_id"],
                            "claim_id": row["claim_id"],
                            "source_id": row["source_id"],
                            "paper_id": row["paper_id"],
                            "citation_locator": row["citation_locator"],
                        }
                    ],
                    "warnings": [],
                },
                {
                    "relationship_type": "not_comparable",
                    "subject": {"entity_type": "result", "entity_id": row["result_id"], "label": row["result_id"]},
                    "object": {"entity_type": "dataset", "entity_id": "osworld_variant", "label": "OSWorld variant"},
                    "decision_status": "needs_review",
                    "confidence": "medium",
                    "comparability_status": "not_comparable",
                    "rationale": "Dataset or setting may differ, so this should remain explicit.",
                    "evidence_refs": [
                        {
                            "result_id": row["result_id"],
                            "claim_id": row["claim_id"],
                            "source_id": row["source_id"],
                            "paper_id": row["paper_id"],
                            "citation_locator": row["citation_locator"],
                        }
                    ],
                    "warnings": ["dataset_setting_may_differ"],
                },
            ]
        }
        return {"content": json.dumps(content), "provider": "fake", "model": "fake-model", "usage": {"total_tokens": 21}}


def test_cli_includes_research_commands() -> None:
    parser = build_parser()

    args = parser.parse_args(["research", "graph", "--root", ".", "--dry-run", "--json"])
    assert args.research_command == "graph"

    args = parser.parse_args(["research", "graph-status", "run_research_graph_20260606000000_abcd1234", "--root", "."])
    assert args.research_command == "graph-status"

    args = parser.parse_args(["research", "synthesize", "run_research_graph_20260606000000_abcd1234", "--root", "."])
    assert args.research_command == "synthesize"


def test_research_graph_dry_run_cli_outputs_json_without_staging(capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()
    before = sorted(path.as_posix() for path in (root / "staging").glob("**/*")) if (root / "staging").exists() else []

    assert main(["research", "graph", "--root", str(root), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "research_relationship_run.v5.0"
    assert payload["mode"] == "dry_run"
    assert payload["relationship_run_id"] == ""
    after = sorted(path.as_posix() for path in (root / "staging").glob("**/*")) if (root / "staging").exists() else []
    assert after == before


def test_research_graph_cli_runs_provider_status_and_synthesis(monkeypatch, capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()
    monkeypatch.setattr("llmwiki.research.relationships.create_provider", lambda config, root=None: FakeResearchProvider())

    assert main(["research", "graph", "--root", str(root), "--source-id", "src_pdf", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    run_id = payload["relationship_run_id"]
    assert run_id.startswith("run_research_graph_")
    assert payload["summary"]["accepted_edge_count"] >= 1
    assert payload["summary"]["not_comparable_edge_count"] >= 1

    assert main(["research", "graph-status", run_id, "--root", str(root), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["relationship_run_id"] == run_id
    assert status["summary"]["edge_count"] >= 1

    assert main(["research", "synthesize", run_id, "--root", str(root), "--json"]) == 0
    synthesis = json.loads(capsys.readouterr().out)
    assert synthesis["schema_version"] == "research_synthesis.v5.0"
    assert synthesis["relationship_run_id"] == run_id
    assert synthesis["evidence_refs"]


def test_research_graph_invalid_args_return_one(capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()

    assert main(["research", "graph", "--root", str(root), "--limit", "0"]) == 1
    assert "Research graph failed:" in capsys.readouterr().out

    assert main(["research", "graph-status", "missing_run", "--root", str(root)]) == 1
    assert "Research graph status failed:" in capsys.readouterr().out
