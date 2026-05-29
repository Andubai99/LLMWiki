from __future__ import annotations

from pathlib import Path

from .retrieval import retrieve_context


def query_context(root: Path, question: str, limit: int = 5) -> str:
    result = retrieve_context(root.resolve(), question, limit=limit)
    lines = [f"Retrieval context for: {question}", ""]
    contexts = result.get("contexts", [])
    if not contexts:
        lines.append("No matching claims found.")
        return "\n".join(lines)

    for index, context in enumerate(contexts, start=1):
        lines.append(
            f"{index}. claim_id={context['claim_id']} "
            f"source_id={context['source_id']} "
            f"citation={context['citation_locator']} "
            f"page={context['page_path']} "
            f"relationship={context['relationship_type']} "
            f"score={context['score']} "
            f"rerank={context.get('rerank_score', context['score'])} "
            f"selection={context.get('selection_reason', 'n/a')}"
        )
        lines.append(f"   {context['claim_text']}")
    warnings = result.get("warnings", [])
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)
