from __future__ import annotations

import json
from typing import Any

from .relationships import ResearchRelationshipRun, ResearchSynthesisResponse


def format_research_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def research_relationship_payload(response: ResearchRelationshipRun) -> dict[str, Any]:
    return response.to_dict()


def research_synthesis_payload(response: ResearchSynthesisResponse) -> dict[str, Any]:
    return response.to_dict()


def format_research_graph(response: ResearchRelationshipRun) -> str:
    payload = response.to_dict()
    summary = payload["summary"]
    lines = [
        "Research relationship graph",
        f"Run: {payload.get('relationship_run_id') or 'none'}",
        f"Mode: {payload.get('mode') or ''}",
        f"Bundles: {summary.get('relationship_bundle_count', payload.get('relationship_bundle_count', 0))}",
        f"Edges: {summary.get('edge_count', 0)}",
        f"Accepted: {summary.get('accepted_edge_count', 0)}",
        f"Needs review: {summary.get('needs_review_edge_count', 0)}",
        f"Not comparable: {summary.get('not_comparable_edge_count', 0)}",
        "",
        "Edges",
        "Type | Status | Subject | Object | Evidence",
    ]
    edges = payload["relationship_edges"]
    if not edges:
        lines.append("none | | | |")
    for edge in edges[:30]:
        ref = (edge.get("evidence_refs") or [{}])[0]
        evidence = ref.get("result_id") or ref.get("claim_id") or ""
        lines.append(
            " | ".join(
                [
                    clip(str(edge.get("relationship_type") or ""), 20),
                    clip(str(edge.get("decision_status") or ""), 16),
                    clip(str(edge.get("subject", {}).get("label") or ""), 24),
                    clip(str(edge.get("object", {}).get("label") or ""), 24),
                    clip(str(evidence), 24),
                ]
            )
        )
    warning_lines = warning_text_lines(payload["warnings"])
    if warning_lines:
        lines.extend(["", "Warnings:", *warning_lines[:30]])
    return "\n".join(lines)


def format_research_synthesis(response: ResearchSynthesisResponse) -> str:
    payload = response.to_dict()
    lines = [
        "Research synthesis",
        f"Run: {payload['relationship_run_id']}",
        f"Items: {payload['summary'].get('synthesis_item_count', 0)}",
        f"Evidence refs: {payload['summary'].get('synthesis_evidence_ref_count', 0)}",
        "",
        str(payload.get("synthesis") or ""),
        "",
        "Evidence refs",
        "Result | Claim | Source | Locator",
    ]
    refs = payload["evidence_refs"]
    if not refs:
        lines.append("none | | |")
    for ref in refs[:30]:
        lines.append(
            " | ".join(
                [
                    clip(str(ref.get("result_id") or ""), 18),
                    clip(str(ref.get("claim_id") or ""), 18),
                    clip(str(ref.get("source_id") or ""), 16),
                    clip(str(ref.get("citation_locator") or ""), 32),
                ]
            )
        )
    return "\n".join(lines)


def clip(value: str, length: int) -> str:
    return value if len(value) <= length else value[: max(0, length - 1)] + "…"


def warning_text_lines(warnings: list[dict[str, Any]]) -> list[str]:
    return [f"- {warning.get('code')}: {warning.get('message')}" for warning in warnings]
