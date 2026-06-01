from __future__ import annotations

from pathlib import Path

from llmwiki.answer import AnswerCitation, AskResult
from llmwiki.synthesis_planner import (
    SynthesisEvidenceItem,
    SynthesisPlan,
    SynthesisRelationship,
)


def ask_result() -> AskResult:
    return AskResult(
        question="Why do RAG answers need citation anchors?",
        status="answered",
        answer="RAG answers need citation anchors so claims remain auditable.",
        analysis="Citation anchors preserve auditability.",
        citations=[
            AnswerCitation(
                claim_id="clm_rag_anchor",
                source_id="src_doc",
                citation_locator="line:1",
                page_path="wiki/sources/src_doc.md",
            ),
            AnswerCitation(
                claim_id="clm_rag_trace",
                source_id="src_doc",
                citation_locator="line:2",
                page_path="wiki/sources/src_doc.md",
            ),
        ],
        suggested_title="RAG Citation Anchors",
        contexts=[
            {"claim_id": "clm_rag_anchor"},
            {"claim_id": "clm_rag_trace"},
        ],
    )


def synthesis_plan(action: str = "create") -> SynthesisPlan:
    return SynthesisPlan(
        schema_version="synthesis_plan.v2.8",
        status="planned",
        action=action,
        target_page_id="synthesis-rag-citation-anchors",
        target_path="wiki/syntheses/rag-citation-anchors.md",
        title="RAG Citation Anchors",
        topic_key="rag-citation-anchors",
        aliases=["Citation Anchors"],
        evidence=[
            SynthesisEvidenceItem(
                role="supports",
                claim_id="clm_rag_anchor",
                source_id="src_doc",
                citation_locator="line:1",
                page_path="wiki/sources/src_doc.md",
            ),
            SynthesisEvidenceItem(
                role="supports",
                claim_id="clm_rag_trace",
                source_id="src_doc",
                citation_locator="line:2",
                page_path="wiki/sources/src_doc.md",
            ),
        ],
        sections={
            "scope": "Answers about RAG citation anchors.",
            "current_answer": "RAG answers need citation anchors so claims remain auditable.",
            "analysis": "The cited evidence supports traceable answers.",
            "conflicts_and_limits": ["Evidence is limited to one local source."],
            "open_questions": ["Whether other workflows need different anchors."],
        },
        related_pages=["wiki/sources/src_doc.md"],
        relationships=[
            SynthesisRelationship(
                subject_id="synthesis-rag-citation-anchors",
                object_id="clm_rag_anchor",
                relationship_type="supports",
                evidence_claim_id="clm_rag_anchor",
                source_id="src_doc",
            )
        ],
    )


def test_render_v2_8_page_contains_required_sections():
    from llmwiki.synthesis_pages import SynthesisPageModel, render_synthesis_page_v2_8

    model = SynthesisPageModel.from_plan(synthesis_plan(), ask_result(), run_id="run_synthesis_test")

    content = render_synthesis_page_v2_8(model)

    assert "page_type: synthesis" in content
    assert "synthesis_id: \"synthesis-rag-citation-anchors\"" in content
    assert "topic_key: \"rag-citation-anchors\"" in content
    assert "question_count: 1" in content
    assert "revision_count: 1" in content
    for section in (
        "Scope",
        "Current Answer",
        "Evidence Map",
        "Analysis",
        "Conflicts And Limits",
        "Open Questions",
        "Related Pages",
        "Revision History",
    ):
        assert f"## {section}" in content
    assert "| Role | Claim | Source | Locator | Page |" in content
    assert "`clm_rag_anchor`" in content
    assert "[[wiki/sources/src_doc.md]]" in content


def test_parse_v2_2_page_migrates_sections(tmp_path: Path):
    from llmwiki.synthesis_pages import parse_synthesis_page

    page = tmp_path / "old.md"
    page.write_text(
        """---
page_type: synthesis
title: "Old Citation Anchors"
aliases: []
source_count: 1
claim_ids: ['clm_rag_anchor']
updated_at: "2026-05-30T00:00:00+00:00"
---

# Old Citation Anchors

## Question/Topic

Why cite?

## Short Answer

Old short answer.

## Evidence

- `clm_rag_anchor` from `src_doc` at `line:1` ([[wiki/sources/src_doc.md]])

## Analysis

Old analysis.

## Uncertainties

- Old uncertainty.

## Related Pages

- [[wiki/sources/src_doc.md]]
""",
        encoding="utf-8",
        newline="\n",
    )

    model = parse_synthesis_page(page)

    assert model.title == "Old Citation Anchors"
    assert model.scope == "Why cite?"
    assert model.current_answer == "Old short answer."
    assert "Old uncertainty." in model.conflicts_and_limits
    assert model.claim_ids == ["clm_rag_anchor"]


def test_merge_appends_claims_revision_and_preserves_custom_sections(tmp_path: Path):
    from llmwiki.synthesis_pages import (
        merge_synthesis_page,
        parse_synthesis_page,
        render_synthesis_page_v2_8,
    )

    page = tmp_path / "existing.md"
    page.write_text(
        """---
page_type: synthesis
title: "RAG Citation Anchors"
aliases: []
source_count: 1
claim_ids: ['clm_rag_anchor']
synthesis_id: "synthesis-rag-citation-anchors"
topic_key: "rag-citation-anchors"
question_count: 1
revision_count: 1
updated_at: "2026-05-30T00:00:00+00:00"
---

# RAG Citation Anchors

## Scope

Earlier scope.

## Current Answer

Earlier answer.

## Evidence Map

| Role | Claim | Source | Locator | Page |
| --- | --- | --- | --- | --- |
| supports | `clm_rag_anchor` | `src_doc` | `line:1` | [[wiki/sources/src_doc.md]] |

## Analysis

Earlier analysis.

## Conflicts And Limits

- Earlier limit.

## Open Questions

- Earlier question.

## Related Pages

- [[wiki/sources/src_doc.md]]

## Revision History

- 2026-05-30T00:00:00+00:00 run_synthesis_old create: Earlier question.

## Human Notes

Keep this custom note.
""",
        encoding="utf-8",
        newline="\n",
    )
    existing = parse_synthesis_page(page)

    merged = merge_synthesis_page(existing, synthesis_plan(action="update"), ask_result(), run_id="run_synthesis_new")
    content = render_synthesis_page_v2_8(merged)

    assert merged.claim_ids == ["clm_rag_anchor", "clm_rag_trace"]
    assert merged.question_count == 2
    assert merged.revision_count == 2
    assert "run_synthesis_old" in content
    assert "run_synthesis_new" in content
    assert "## Human Notes" in content
    assert "Keep this custom note." in content


def test_merge_moves_missing_existing_claim_to_limits(tmp_path: Path):
    from llmwiki.synthesis_pages import merge_synthesis_page, parse_synthesis_page

    page = tmp_path / "existing.md"
    page.write_text(
        """---
page_type: synthesis
title: "RAG Citation Anchors"
aliases: []
source_count: 1
claim_ids: ['clm_missing']
synthesis_id: "synthesis-rag-citation-anchors"
topic_key: "rag-citation-anchors"
question_count: 1
revision_count: 1
updated_at: "2026-05-30T00:00:00+00:00"
---

# RAG Citation Anchors

## Scope

Earlier scope.

## Current Answer

Earlier answer.

## Evidence Map

- `clm_missing`

## Analysis

Earlier analysis.

## Conflicts And Limits

- Earlier limit.

## Open Questions

- Earlier question.

## Related Pages

- [[wiki/sources/src_doc.md]]

## Revision History

- Old revision.
""",
        encoding="utf-8",
        newline="\n",
    )

    merged = merge_synthesis_page(parse_synthesis_page(page), synthesis_plan(action="update"), ask_result(), run_id="run_synthesis_new")

    assert "clm_missing" not in merged.claim_ids
    assert any("clm_missing" in item for item in merged.conflicts_and_limits)
