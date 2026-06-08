from __future__ import annotations

import json
from typing import Any


def build_research_relationship_messages(bundle: dict[str, Any]) -> list[dict[str, str]]:
    bundle_json = json.dumps(bundle, ensure_ascii=False, indent=2)
    return [
        {
            "role": "system",
            "content": (
                "You are the LLMWiki research relationship auditor. Use only the provided relationship bundle. "
                "Do not invent source_id, paper_id, claim_id, result_id, citation_locator, page paths, methods, datasets, metrics, or relationships. "
                "Do not use parser diagnostics, parser logs, parser artifacts, or outside knowledge as evidence. "
                "Preserve not_comparable relationships when evidence shows different splits, settings, metric definitions, result roles, or value scales. "
                "Return only schema-valid JSON. Do not include raw chain-of-thought."
            ),
        },
        {
            "role": "user",
            "content": (
                "Build source-backed cross-paper relationship edges from this bundle. "
                "Accepted edges must cite evidence_refs that already exist in the bundle. "
                "If evidence is insufficient, use decision_status=insufficient_evidence or needs_review instead of inventing references. "
                "Top-level JSON field must be edges.\n\n"
                f"relationship bundle:\n{bundle_json}"
            ),
        },
    ]


def research_relationship_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "relationship_type": {"type": "string"},
                        "subject": {"type": "object"},
                        "object": {"type": "object"},
                        "decision_status": {"type": "string"},
                        "confidence": {"type": "string"},
                        "comparability_status": {"type": "string"},
                        "rationale": {"type": "string"},
                        "evidence_refs": {"type": "array", "items": {"type": "object"}},
                        "warnings": {"type": "array"},
                    },
                    "required": [
                        "relationship_type",
                        "subject",
                        "object",
                        "decision_status",
                        "confidence",
                        "comparability_status",
                        "evidence_refs",
                    ],
                },
            }
        },
        "required": ["edges"],
    }

