from __future__ import annotations

import json

import pytest

from llmwiki.metrics.llm_normalization import (
    MetricNormalizationLLMError,
    normalize_decision_payload,
)
from llmwiki.metrics.llm_normalization_prompt import build_metric_normalization_messages, metric_normalization_schema


def sample_bundle() -> dict:
    return {
        "schema_version": "metric_evidence_bundle.v4.9",
        "bundle_id": "meb_sample",
        "candidate_group_key": "success_rate|osworld|computer_use|%|percent|higher_is_better",
        "result_count": 1,
        "paper_identities": [{"paper_id": "src_a", "source_id": "src_a", "year": 2025, "title": "Paper A"}],
        "result_rows": [
            {
                "result_id": "res_a",
                "claim_id": "clm_a",
                "source_id": "src_a",
                "paper_id": "src_a",
                "citation_locator": "line:3",
                "metric_name": "Success Rate",
                "metric_value": "34",
                "metric_unit": "%",
                "metric_raw_value": "34%",
                "metric_direction": "higher_is_better",
                "method": "Agent A",
                "dataset": "OSWorld",
                "task": "computer use",
                "reported_year": None,
                "claim_text": "Agent A reports 34% success rate on OSWorld.",
            }
        ],
        "context_refs": [
            {
                "result_id": "res_a",
                "claim_id": "clm_a",
                "source_id": "src_a",
                "citation_locator": "line:3",
                "context_preview": "Agent A reports 34% success rate on OSWorld.",
            }
        ],
        "warnings": [],
    }


def test_prompt_requires_bounded_evidence_and_structured_json() -> None:
    messages = build_metric_normalization_messages(sample_bundle())
    joined = "\n".join(message["content"] for message in messages)

    assert "只能使用 evidence bundle" in joined
    assert "不得发明 source_id、claim_id、result_id、locator、年份、指标值" in joined
    assert "不要输出 raw chain-of-thought" in joined
    assert "meb_sample" in joined
    assert metric_normalization_schema()["type"] == "object"


def test_normalize_decision_payload_accepts_valid_refs_and_rejects_fabricated_refs() -> None:
    bundle = sample_bundle()
    raw = {
        "decisions": [
            {
                "result_ids": ["res_a"],
                "claim_ids": ["clm_a"],
                "source_ids": ["src_a"],
                "paper_ids": ["src_a"],
                "canonical_metric_name": "success rate",
                "canonical_dataset_name": "OSWorld",
                "canonical_task_name": "computer use",
                "result_role": "main_result",
                "paper_year": 2025,
                "result_reported_year": None,
                "timeline_year": 2025,
                "timeline_year_basis": "paper_identity_for_main_result",
                "comparable": True,
                "decision_status": "auto_accepted",
                "confidence": "high",
                "rationale": "论文身份年份和结果上下文无冲突。",
                "evidence_refs": [
                    {
                        "result_id": "res_a",
                        "claim_id": "clm_a",
                        "source_id": "src_a",
                        "citation_locator": "line:3",
                    }
                ],
                "warnings": [],
            }
        ]
    }

    decisions, warnings = normalize_decision_payload(raw, bundle)

    assert warnings == []
    assert decisions[0]["schema_version"] == "metric_normalization_decision.v4.9"
    assert decisions[0]["decision_id"].startswith("mnd_")
    assert decisions[0]["canonical_metric_id"].startswith("met_")
    assert decisions[0]["timeline_year"] == 2025

    invalid = json.loads(json.dumps(raw))
    invalid["decisions"][0]["evidence_refs"][0]["result_id"] = "res_fake"
    with pytest.raises(MetricNormalizationLLMError):
        normalize_decision_payload(invalid, bundle)


def test_normalize_decision_payload_repairs_missing_refs_from_same_bundle() -> None:
    bundle = sample_bundle()
    raw = {
        "decisions": [
            {
                "canonical_metric_name": "",
                "canonical_dataset_name": "",
                "canonical_task_name": "",
                "result_role": "main_result",
                "paper_year": 2025,
                "timeline_year": 2025,
                "timeline_year_basis": "paper_identity_for_main_result",
                "comparable": True,
                "decision_status": "auto_accepted",
                "confidence": "high",
                "rationale": "证据包中唯一结果可恢复引用。",
                "evidence_refs": [],
                "warnings": [],
            }
        ]
    }

    decisions, warnings = normalize_decision_payload(raw, bundle)

    assert decisions[0]["result_ids"] == ["res_a"]
    assert decisions[0]["evidence_refs"][0]["claim_id"] == "clm_a"
    assert decisions[0]["canonical_metric_name"] == "Success Rate"
    assert any(warning["code"] == "missing_evidence_refs_repaired" for warning in warnings)
