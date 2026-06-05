from __future__ import annotations

import json

from llmwiki.cli import build_parser, main
from tests.test_metric_llm_normalization_prompt import sample_bundle
from tests.test_metric_repair_query import workspace_with_metric_repair_cases


class FakeProvider:
    def complete(self, messages, schema=None):
        assert schema is not None
        content = {
            "decisions": [
                {
                    "result_ids": ["res_pdf"],
                    "claim_ids": ["clm_pdf"],
                    "source_ids": ["src_pdf"],
                    "paper_ids": ["src_pdf"],
                    "canonical_metric_name": "success rate",
                    "canonical_dataset_name": "OSWorld",
                    "canonical_task_name": "computer use",
                    "result_role": "main_result",
                    "paper_year": 2024,
                    "result_reported_year": None,
                    "timeline_year": 2024,
                    "timeline_year_basis": "paper_identity_for_main_result",
                    "comparable": True,
                    "decision_status": "auto_accepted",
                    "confidence": "high",
                    "rationale": "论文年份可用于本文主结果。",
                    "evidence_refs": [
                        {
                            "result_id": "res_pdf",
                            "claim_id": "clm_pdf",
                            "source_id": "src_pdf",
                            "citation_locator": "page:2;block:src_pdf_p002_b0001;section:Results",
                        }
                    ],
                    "warnings": [],
                }
            ]
        }
        return {"content": json.dumps(content), "provider": "fake", "model": "fake-model", "usage": {"total_tokens": 12}}


def test_cli_includes_metric_normalize_commands() -> None:
    parser = build_parser()

    args = parser.parse_args(["metric", "normalize", "--root", ".", "--json"])
    assert args.metric_command == "normalize"

    args = parser.parse_args(["metric", "normalize-status", "run_metric_normalize_20260605000000_abcd1234", "--root", "."])
    assert args.metric_command == "normalize-status"

    args = parser.parse_args(["metric", "timeline-synthesis", "run_metric_normalize_20260605000000_abcd1234", "--root", "."])
    assert args.metric_command == "timeline-synthesis"


def test_metric_normalize_dry_run_cli_outputs_json_without_staging(capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()

    assert main(["metric", "normalize", "--root", str(root), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "metric_normalization_run.v4.9"
    assert payload["mode"] == "dry_run"
    assert payload["normalization_run_id"] == ""
    assert not (root / "staging").exists()


def test_metric_normalize_cli_runs_provider_and_status_and_synthesis(monkeypatch, capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()

    monkeypatch.setattr("llmwiki.metrics.llm_normalization.create_provider", lambda config, root=None: FakeProvider())

    assert main(["metric", "normalize", "--root", str(root), "--source-id", "src_pdf", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    run_id = payload["normalization_run_id"]
    assert run_id.startswith("run_metric_normalize_")
    assert payload["summary"]["auto_accepted_decision_count"] >= 1

    assert main(["metric", "normalize-status", run_id, "--root", str(root), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["normalization_run_id"] == run_id
    assert status["summary"]["decision_count"] >= 1

    assert main(["metric", "timeline-synthesis", run_id, "--root", str(root), "--json"]) == 0
    synthesis = json.loads(capsys.readouterr().out)
    assert synthesis["schema_version"] == "metric_timeline_synthesis.v4.9"
    assert synthesis["normalization_run_id"] == run_id


def test_metric_normalize_invalid_args_return_one(capsys) -> None:
    root = workspace_with_metric_repair_cases()
    capsys.readouterr()

    assert main(["metric", "normalize", "--root", str(root), "--limit", "0"]) == 1
    assert "Metric normalize failed:" in capsys.readouterr().out

    assert main(["metric", "normalize-status", "missing_run", "--root", str(root)]) == 1
    assert "Metric normalize status failed:" in capsys.readouterr().out
