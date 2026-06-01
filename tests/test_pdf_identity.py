from __future__ import annotations

from llmwiki.ingest import Claim, pdf_identity_warning_candidates, proposal_concept
from llmwiki.llm_ingest import LLMIngestProposal


def claim() -> Claim:
    return Claim(
        claim_id="clm_src_pdf_llm_001",
        source_id="src_pdf",
        claim_text="OSWorld evaluates computer-use agents with desktop tasks.",
        citation_locator="page:1;block:src_pdf_p001_b0004;section:Abstract",
        confidence_status="cited",
        created_at="2026-06-01T00:00:00+00:00",
    )


def proposal(aliases: list[str]) -> LLMIngestProposal:
    return LLMIngestProposal(
        claims=[],
        concept_title="OSWorld",
        aliases=aliases,
        entity_title=None,
        entity_aliases=[],
        duplicate_candidates=[],
        conflict_candidates=[],
        source_summary="OSWorld summary.",
        concept_definition="OSWorld concept.",
        provider="fake",
        model="fake",
        raw_content="{}",
        usage={},
    )


def test_pdf_parser_created_aliases_are_filtered_from_formal_concept_aliases():
    source = {"title": "OSWorld: Benchmarking Multimodal Agents", "source_type": "pdf"}
    title, aliases = proposal_concept(
        source,
        [claim()],
        proposal(
            [
                "page1",
                "<!-- page:1 -->",
                "Published as a conference paper at ICLR 2025",
                "Alice Example, Bob Example, Carol Example, David Example",
                "OSWorld",
                "MobileAgentBench",
            ]
        ),
    )

    assert title == "OSWorld"
    assert "OSWorld" in aliases
    assert "MobileAgentBench" in aliases
    assert "page1" not in aliases
    assert "<!-- page:1 -->" not in aliases
    assert not any(alias.startswith("Published as") for alias in aliases)
    assert not any(alias.startswith("Alice Example") for alias in aliases)


def test_pdf_parser_created_aliases_are_reported_as_identity_warnings():
    source = {"title": "OSWorld: Benchmarking Multimodal Agents", "source_type": "pdf"}
    warnings = pdf_identity_warning_candidates(
        source,
        proposal(["page1", "Published as a conference paper at ICLR 2025", "OSWorld"]),
    )

    assert "parser-created alias ignored: page1" in warnings
    assert "parser-created alias ignored: Published as a conference paper at ICLR 2025" in warnings
    assert not any("OSWorld" in warning for warning in warnings)


def test_non_pdf_alias_behavior_is_unchanged():
    source = {"title": "Status Notes", "source_type": "markdown"}
    title, aliases = proposal_concept(
        source,
        [claim()],
        proposal(["Published as a conference paper at ICLR 2025"]),
    )

    assert title == "OSWorld"
    assert "Published as a conference paper at ICLR 2025" in aliases
