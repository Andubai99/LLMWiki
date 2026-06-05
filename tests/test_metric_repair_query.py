from __future__ import annotations

import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.metrics.repair import build_metric_repair_plan
from tests.helpers import make_workspace
from tests.test_metric_canonicalization_query import workspace_with_canonicalization_cases
from tests.test_metric_timeline_query import insert_metric_result


def workspace_with_metric_repair_cases() -> Path:
    root = workspace_with_canonicalization_cases()
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            update metric_results
            set reported_year = null
            where source_id = 'src_pdf'
                and metric_name = 'Success Rate'
                and dataset = 'OSWorld'
                and task = 'computer use'
            """
        )
    insert_metric_result(
        root,
        result_id="res_successful_rate",
        claim_id="clm_successful_rate",
        source_id="src_md",
        metric_name="Successful Rate",
        metric_value="47.0",
        metric_raw_value="47.0%",
        reported_year=2025,
        method="Agent B",
        dataset="OSWorld",
        task="computer use",
        locator="line:3",
    )
    insert_metric_result(
        root,
        result_id="res_dataset_alias",
        claim_id="clm_dataset_alias",
        source_id="src_md",
        metric_name="Success Rate",
        metric_value="48.0",
        metric_raw_value="48.0%",
        reported_year=2025,
        method="Agent B",
        dataset="OSWorld full test",
        task="computer use",
        locator="line:3",
    )
    insert_metric_result(
        root,
        result_id="res_task_alias",
        claim_id="clm_task_alias",
        source_id="src_md",
        metric_name="Success Rate",
        metric_value="49.0",
        metric_raw_value="49.0%",
        reported_year=2025,
        method="Agent B",
        dataset="OSWorld",
        task="computer-use",
        locator="line:3",
    )
    return root


def proposals_by_type(payload: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for proposal in payload["proposals"]:
        grouped.setdefault(proposal["proposal_type"], []).append(proposal)
    return grouped


def test_metric_repair_plan_schema_summary_and_proposal_types() -> None:
    root = workspace_with_metric_repair_cases()

    payload = build_metric_repair_plan(root).to_dict()

    assert payload["schema_version"] == "metric_repair_plan.v4.8"
    assert payload["query"] == {
        "metric": "",
        "dataset": "",
        "task": "",
        "proposal_type": "",
        "limit": 200,
        "offset": 0,
    }
    assert payload["summary"]["metric_result_count"] == 9
    assert payload["summary"]["proposal_count_unpaged"] == len(payload["proposals"])
    assert payload["summary"]["year_repair_proposal_count"] >= 1
    assert payload["summary"]["value_repair_proposal_count"] == 1
    assert payload["summary"]["metric_alias_review_count"] >= 1
    assert payload["summary"]["dataset_alias_review_count"] >= 1
    assert payload["summary"]["task_alias_review_count"] >= 1
    assert payload["summary"]["blocked_vague_label_count"] >= 1

    grouped = proposals_by_type(payload)
    assert set(grouped) >= {
        "reported_year_from_paper_identity",
        "metric_value_from_v47_suggestion",
        "metric_alias_review",
        "dataset_alias_review",
        "task_alias_review",
        "blocked_vague_label",
    }

    year = grouped["reported_year_from_paper_identity"][0]
    assert year["schema_version"] == "metric_repair_proposal.v4.8"
    assert year["target"]["source_id"] == "src_pdf"
    assert year["current"]["reported_year"] is None
    assert year["suggested"]["reported_year"] == 2024
    assert year["review_status"] == "proposed"

    value = grouped["metric_value_from_v47_suggestion"][0]
    assert value["target"]["result_id"] == "res_missing_value"
    assert value["suggested"]["metric_value"] == "42.1"
    assert value["suggested"]["metric_unit"] == "%"
    assert value["risk_level"] == "medium"

    blocked = grouped["blocked_vague_label"][0]
    assert blocked["review_status"] == "blocked"
    assert blocked["risk_level"] == "high"


def test_metric_repair_plan_filters_and_projection() -> None:
    root = workspace_with_metric_repair_cases()

    payload = build_metric_repair_plan(root, metric="success rate", proposal_type="reported_year_from_paper_identity", limit=1).to_dict()

    assert payload["summary"]["proposal_count_unpaged"] >= 1
    assert len(payload["proposals"]) == 1
    assert payload["proposals"][0]["proposal_type"] == "reported_year_from_paper_identity"
    assert payload["summary"]["projected_ready_after_value_repair_count"] >= 1
    assert any(
        projection["projected_readiness_status"] in {"strict_ready", "ready_after_value_repair"}
        for projection in payload["projections"]
    )


def test_metric_repair_empty_workspace_warns() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    payload = build_metric_repair_plan(root).to_dict()

    assert payload["summary"]["proposal_count_unpaged"] == 0
    assert payload["proposals"] == []
    assert any(warning["code"] == "no_repair_proposals" for warning in payload["warnings"])
