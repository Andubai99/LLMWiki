from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.llm_ingest import LLMIngestProposal
from llmwiki.sources import import_source
from tests.helpers import make_workspace


def test_ingest_writes_metric_results_jsonl_and_triage(monkeypatch, capsys) -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source = root / "metric-note.md"
    source.write_text(
        "# Metric Note\n\n"
        "MethodA reports 92.3% accuracy on BenchmarkX.\n",
        encoding="utf-8",
    )
    imported = import_source(root, str(source))

    def fake_create(root: Path, source: dict[str, str], normalized_text: str) -> LLMIngestProposal:
        claim_id = f"clm_{source['source_id']}_llm_001"
        return LLMIngestProposal(
            claims=[
                {
                    "claim_id": claim_id,
                    "source_id": source["source_id"],
                    "claim_text": "MethodA reports 92.3% accuracy on BenchmarkX.",
                    "citation_locator": "line:3;paragraph:1",
                    "confidence_status": "cited",
                }
            ],
            metric_results=[
                {
                    "schema_version": "metric_result_claim.v4.3",
                    "result_id": f"res_{claim_id}_001",
                    "claim_id": claim_id,
                    "source_id": source["source_id"],
                    "paper_id": source["source_id"],
                    "claim_text": "MethodA reports 92.3% accuracy on BenchmarkX.",
                    "citation_locator": "line:3;paragraph:1",
                    "confidence_status": "cited",
                    "evidence_block_ids": [],
                    "evidence_pages": [],
                    "evidence_section_path": [],
                    "evidence_block_roles": [],
                    "extraction_origin": "abstract",
                    "method": "MethodA",
                    "dataset": "BenchmarkX",
                    "task": "",
                    "metric_name": "accuracy",
                    "metric_value": "92.3",
                    "metric_unit": "%",
                    "metric_raw_value": "92.3%",
                    "metric_direction": "higher_is_better",
                    "baseline": "",
                    "comparison_value": "",
                    "setting": "",
                    "reported_year": None,
                    "is_main_result": True,
                    "value_normalization_status": "normalized",
                    "warnings": [],
                    "created_at": "2026-06-04T00:00:00+00:00",
                }
            ],
            concept_title="Metric Note",
            aliases=[],
            entity_title=None,
            entity_aliases=[],
            duplicate_candidates=[],
            conflict_candidates=[],
            source_summary="Metric note summary.",
            concept_definition="Metric note concept.",
            provider="fake",
            model="fake-model",
            raw_content="{}",
            usage={},
        )

    monkeypatch.setattr("llmwiki.ingest.create_llm_ingest_proposal", fake_create)
    assert main(["ingest", imported.source_id, "--root", str(root)]) == 0
    run_id = capsys.readouterr().out.split("run_id=", 1)[1].splitlines()[0].strip()
    run_dir = root / "staging" / run_id

    metric_results_path = run_dir / "metric-results.jsonl"
    assert metric_results_path.exists()
    metric_results = [json.loads(line) for line in metric_results_path.read_text(encoding="utf-8").splitlines()]
    assert metric_results[0]["schema_version"] == "metric_result_claim.v4.3"
    assert metric_results[0]["claim_id"] == f"clm_{imported.source_id}_llm_001"

    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["metric_result_schema"] == "metric_result_claim.v4.3"
    assert manifest["metric_result_count"] == 1
    assert manifest["metric_result_cited_count"] == 1
    assert manifest["metric_result_table_or_caption_count"] == 0

    triage = (run_dir / "triage.md").read_text(encoding="utf-8")
    assert "Metric/Result Claims" in triage
    assert "accuracy" in triage
    assert "BenchmarkX" in triage


def test_apply_persists_only_cited_metric_results(monkeypatch, capsys) -> None:
    from tests.test_apply_workflow import valid_claim, valid_source_patch, write_manual_run

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into sources (source_id, title, source_type, raw_path, normalized_path, sha256, url, imported_at, status)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "src_manual",
                "Manual Source",
                "markdown",
                "sources/raw/src_manual.md",
                "sources/normalized/src_manual.md",
                "sha-manual",
                None,
                "2026-06-04T00:00:00+00:00",
                "imported",
            ),
        )

    weak_claim = valid_claim() | {
        "claim_id": "clm_manual_weak",
        "citation_locator": "",
        "confidence_status": "weak",
    }
    write_manual_run(root, "run_metric_results", valid_source_patch(), [valid_claim(), weak_claim])
    run_dir = root / "staging" / "run_metric_results"
    (run_dir / "metric-results.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "metric_result_claim.v4.3",
                        "result_id": "res_clm_manual_1_001",
                        "claim_id": "clm_manual_1",
                        "source_id": "src_manual",
                        "paper_id": "src_manual",
                        "claim_text": "Manual claim keeps a source locator for apply validation.",
                        "citation_locator": "line:1",
                        "confidence_status": "cited",
                        "evidence_block_ids": [],
                        "evidence_pages": [],
                        "evidence_section_path": [],
                        "evidence_block_roles": [],
                        "extraction_origin": "abstract",
                        "method": "MethodA",
                        "dataset": "BenchmarkX",
                        "task": "",
                        "metric_name": "accuracy",
                        "metric_value": "92.3",
                        "metric_unit": "%",
                        "metric_raw_value": "92.3%",
                        "metric_direction": "higher_is_better",
                        "baseline": "",
                        "comparison_value": "",
                        "setting": "",
                        "reported_year": None,
                        "is_main_result": True,
                        "value_normalization_status": "normalized",
                        "warnings": [],
                        "created_at": "2026-06-04T00:00:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "schema_version": "metric_result_claim.v4.3",
                        "result_id": "res_clm_manual_weak_001",
                        "claim_id": "clm_manual_weak",
                        "source_id": "src_manual",
                        "paper_id": "src_manual",
                        "claim_text": "Weak metric result should not become durable.",
                        "citation_locator": "",
                        "confidence_status": "weak",
                        "evidence_block_ids": [],
                        "evidence_pages": [],
                        "evidence_section_path": [],
                        "evidence_block_roles": [],
                        "extraction_origin": "abstract",
                        "method": "",
                        "dataset": "",
                        "task": "",
                        "metric_name": "accuracy",
                        "metric_value": "",
                        "metric_unit": "",
                        "metric_raw_value": "",
                        "metric_direction": "unknown",
                        "baseline": "",
                        "comparison_value": "",
                        "setting": "",
                        "reported_year": None,
                        "is_main_result": None,
                        "value_normalization_status": "missing",
                        "warnings": ["unsupported"],
                        "created_at": "2026-06-04T00:00:00+00:00",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(["apply", "run_metric_results", "--root", str(root)]) == 0

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            select mr.result_id, mr.claim_id, mr.metric_name, mr.metric_value, c.claim_text, s.title
            from metric_results mr
            join claims c on c.claim_id = mr.claim_id
            join sources s on s.source_id = mr.source_id
            order by mr.result_id
            """
        ).fetchall()

    assert [row["result_id"] for row in rows] == ["res_clm_manual_1_001"]
    assert rows[0]["claim_id"] == "clm_manual_1"
    assert rows[0]["metric_name"] == "accuracy"
    assert rows[0]["metric_value"] == "92.3"
