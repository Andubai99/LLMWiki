from __future__ import annotations

import json
from typing import Any


def build_metric_normalization_messages(bundle: dict[str, Any]) -> list[dict[str, str]]:
    bundle_json = json.dumps(bundle, ensure_ascii=False, indent=2)
    return [
        {
            "role": "system",
            "content": (
                "你是 LLMWiki 的指标归一化审计器。只能使用 evidence bundle 中的信息，"
                "不得补充外部知识。不得发明 source_id、claim_id、result_id、locator、年份、指标值。"
                "不得把 parser diagnostics 当作 evidence。对低置信度判断必须降级。"
                "不要输出 raw chain-of-thought，只输出简短 rationale 和 schema-valid JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请根据这个 evidence bundle 归一化指标、数据集、任务、结果角色和 timeline_year。"
                "如果结果是本文主结果或本文消融，且没有冲突证据，可以用 paper_year 作为 timeline_year。"
                "如果结果是 baseline 或 prior_work，不要默认使用当前论文年份，除非证据明确支持。"
                "输出 JSON，顶层字段为 decisions。\n\n"
                f"evidence bundle:\n{bundle_json}"
            ),
        },
    ]


def metric_normalization_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "result_ids": {"type": "array", "items": {"type": "string"}},
                        "claim_ids": {"type": "array", "items": {"type": "string"}},
                        "source_ids": {"type": "array", "items": {"type": "string"}},
                        "paper_ids": {"type": "array", "items": {"type": "string"}},
                        "canonical_metric_name": {"type": "string"},
                        "canonical_dataset_name": {"type": "string"},
                        "canonical_task_name": {"type": "string"},
                        "result_role": {"type": "string"},
                        "paper_year": {"type": ["integer", "null"]},
                        "result_reported_year": {"type": ["integer", "null"]},
                        "timeline_year": {"type": ["integer", "null"]},
                        "timeline_year_basis": {"type": "string"},
                        "comparable": {"type": "boolean"},
                        "decision_status": {"type": "string"},
                        "confidence": {"type": "string"},
                        "rationale": {"type": "string"},
                        "evidence_refs": {"type": "array", "items": {"type": "object"}},
                        "warnings": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": [
                        "result_ids",
                        "claim_ids",
                        "source_ids",
                        "paper_ids",
                        "canonical_metric_name",
                        "canonical_dataset_name",
                        "canonical_task_name",
                        "result_role",
                        "timeline_year",
                        "comparable",
                        "decision_status",
                        "confidence",
                        "evidence_refs",
                    ],
                },
            }
        },
        "required": ["decisions"],
    }
