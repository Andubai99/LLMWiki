from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.metrics.timeline import (
    build_metric_list,
    build_metric_timeline,
)
from tests.helpers import make_workspace


def insert_source(
    root: Path,
    *,
    source_id: str,
    title: str,
    source_type: str = "md",
    imported_at: str = "2026-06-04T00:00:00+00:00",
) -> None:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into sources (
                source_id, title, source_type, raw_path, normalized_path, sha256, url, imported_at, status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                title,
                source_type,
                f"sources/raw/{source_id}.md",
                f"sources/normalized/{source_id}.md",
                f"sha_{source_id}",
                "",
                imported_at,
                "imported",
            ),
        )
        conn.execute(
            """
            insert into pages (page_id, path, page_type, title, aliases, updated_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                f"wiki/sources/{source_id}.md",
                "source",
                title,
                "[]",
                imported_at,
            ),
        )


def insert_metric_result(
    root: Path,
    *,
    result_id: str,
    claim_id: str,
    source_id: str,
    metric_name: str,
    metric_value: str,
    metric_raw_value: str,
    reported_year: int | None,
    method: str = "Agent A",
    dataset: str = "OSWorld",
    task: str = "computer use",
    locator: str = "line:1",
    warnings: list[str] | None = None,
) -> None:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert or ignore into claims (
                claim_id, source_id, claim_text, citation_locator, confidence_status, created_at
            )
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                source_id,
                f"{method} reports {metric_name} of {metric_raw_value} on {dataset}.",
                locator,
                "cited",
                "2026-06-04T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            insert into metric_results (
                result_id, schema_version, claim_id, source_id, paper_id, claim_text, citation_locator,
                confidence_status, evidence_block_ids, evidence_pages, evidence_section_path,
                evidence_block_roles, extraction_origin, method, dataset, task, metric_name,
                metric_value, metric_unit, metric_raw_value, metric_direction, baseline,
                comparison_value, setting, reported_year, is_main_result, value_normalization_status,
                warnings, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                "metric_result_claim.v4.3",
                claim_id,
                source_id,
                source_id,
                f"{method} reports {metric_name} of {metric_raw_value} on {dataset}.",
                locator,
                "cited",
                json.dumps(["blk_1"]),
                json.dumps([1]),
                "Results",
                json.dumps({"blk_1": "text"}),
                "experiment",
                method,
                dataset,
                task,
                metric_name,
                metric_value,
                "%",
                metric_raw_value,
                "higher_is_better",
                "Baseline B",
                "",
                "",
                reported_year,
                1,
                "normalized" if metric_value else "raw_only",
                json.dumps(warnings or []),
                "2026-06-04T00:00:00+00:00",
            ),
        )


def workspace_with_metric_results() -> Path:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    insert_source(root, source_id="src_a", title="2023 Alpha Paper")
    insert_source(root, source_id="src_b", title="2024 Beta Paper")
    insert_source(root, source_id="src_c", title="Undated Gamma Paper")
    insert_metric_result(
        root,
        result_id="res_a",
        claim_id="clm_a",
        source_id="src_a",
        metric_name="Success Rate",
        metric_value="42.1",
        metric_raw_value="42.1%",
        reported_year=2023,
        method="Agent A",
    )
    insert_metric_result(
        root,
        result_id="res_b",
        claim_id="clm_b",
        source_id="src_b",
        metric_name="success-rate",
        metric_value="45.0",
        metric_raw_value="45.0%",
        reported_year=2024,
        method="Agent B",
    )
    insert_metric_result(
        root,
        result_id="res_c",
        claim_id="clm_c",
        source_id="src_c",
        metric_name="Success Rate",
        metric_value="",
        metric_raw_value="not reported",
        reported_year=None,
        method="Agent C",
    )
    insert_metric_result(
        root,
        result_id="res_acc",
        claim_id="clm_acc",
        source_id="src_a",
        metric_name="Accuracy",
        metric_value="80.0",
        metric_raw_value="80.0%",
        reported_year=2023,
        method="Agent A",
        dataset="OtherSet",
    )
    return root


def test_metric_list_groups_by_normalized_metric_and_counts_sources() -> None:
    root = workspace_with_metric_results()

    payload = build_metric_list(root).to_dict()

    assert payload["schema_version"] == "metric_list.v4.4"
    assert payload["metric_count"] == 2
    success = payload["metrics"][0]
    assert success["metric_name"] == "Success Rate"
    assert success["normalized_metric"] == "successrate"
    assert success["row_count"] == 3
    assert success["source_count"] == 3
    assert success["paper_count"] == 3
    assert success["year_min"] == 2023
    assert success["year_max"] == 2024


def test_metric_timeline_returns_joined_sorted_source_backed_rows() -> None:
    root = workspace_with_metric_results()

    payload = build_metric_timeline(root, metric="success rate").to_dict()

    assert payload["schema_version"] == "metric_timeline.v4.4"
    assert payload["item_count"] == 3
    assert [item["result_id"] for item in payload["items"]] == ["res_a", "res_b", "res_c"]
    first = payload["items"][0]
    assert first["schema_version"] == "metric_timeline_item.v4.4"
    assert first["claim_id"] == "clm_a"
    assert first["source_id"] == "src_a"
    assert first["paper_id"] == "src_a"
    assert first["source_title"] == "2023 Alpha Paper"
    assert first["paper_title"] == "2023 Alpha Paper"
    assert first["page_path"] == "wiki/sources/src_a.md"
    assert first["citation_locator"] == "line:1"
    assert first["timeline_year"] == 2023
    assert {"code": "ambiguous_metric_variants", "message": "Metric variants share normalized key: Success Rate, success-rate"} in payload["warnings"]


def test_metric_timeline_filters_year_dataset_task_method_and_paginates() -> None:
    root = workspace_with_metric_results()

    payload = build_metric_timeline(
        root,
        metric="success rate",
        dataset="OSWorld",
        task="computer use",
        method="agent b",
        year_from=2024,
        year_to=2024,
        limit=1,
        offset=0,
    ).to_dict()

    assert payload["item_count"] == 1
    assert payload["items"][0]["result_id"] == "res_b"
    assert payload["warnings"] == []


def test_metric_timeline_empty_result_is_success_with_warning() -> None:
    root = workspace_with_metric_results()

    payload = build_metric_timeline(root, metric="not a metric").to_dict()

    assert payload["item_count"] == 0
    assert payload["items"] == []
    assert payload["warnings"][0]["code"] == "no_catalog_backed_result"


def test_metric_timeline_skips_missing_claim_join_and_warns() -> None:
    root = workspace_with_metric_results()
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into metric_results (
                result_id, schema_version, claim_id, source_id, paper_id, claim_text, citation_locator,
                confidence_status, evidence_block_ids, evidence_pages, evidence_section_path,
                evidence_block_roles, extraction_origin, method, dataset, task, metric_name,
                metric_value, metric_unit, metric_raw_value, metric_direction, baseline,
                comparison_value, setting, reported_year, is_main_result, value_normalization_status,
                warnings, created_at
            )
            select 'res_orphan', schema_version, 'clm_missing', source_id, paper_id, claim_text, citation_locator,
                confidence_status, evidence_block_ids, evidence_pages, evidence_section_path,
                evidence_block_roles, extraction_origin, method, dataset, task, metric_name,
                metric_value, metric_unit, metric_raw_value, metric_direction, baseline,
                comparison_value, setting, reported_year, is_main_result, value_normalization_status,
                warnings, created_at
            from metric_results where result_id = 'res_a'
            """
        )

    payload = build_metric_timeline(root, metric="success rate").to_dict()

    assert "res_orphan" not in [item["result_id"] for item in payload["items"]]
    assert any(warning["code"] == "missing_claim_join" for warning in payload["warnings"])


def test_metric_timeline_reports_duplicate_looking_rows_without_merging() -> None:
    root = workspace_with_metric_results()
    insert_metric_result(
        root,
        result_id="res_dup",
        claim_id="clm_dup",
        source_id="src_a",
        metric_name="Success Rate",
        metric_value="42.1",
        metric_raw_value="42.1%",
        reported_year=2023,
        method="Agent A",
        locator="line:1",
    )

    payload = build_metric_timeline(root, metric="success rate").to_dict()

    assert "res_dup" in [item["result_id"] for item in payload["items"]]
    assert any(warning["code"] == "duplicate_result_candidate" for warning in payload["warnings"])
