from __future__ import annotations

from llmwiki.ingest import Claim, build_patches, pdf_identity_warning_candidates, proposal_concept
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


def source_dict(source_id: str, title: str, source_type: str) -> dict[str, str]:
    return {
        "source_id": source_id,
        "title": title,
        "source_type": source_type,
        "raw_path": f"sources/raw/{source_id}.md",
        "normalized_path": f"sources/normalized/{source_id}.md",
        "sha256": "sha-test",
    }


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


def test_pdf_source_page_aliases_exclude_paper_title():
    patches = build_patches(
        source=source_dict("src_pdf", "OSWorld: Benchmarking Multimodal Agents", "pdf"),
        claims=[claim()],
        concept_title="OSWorld",
        aliases=["OSWorld"],
        duplicate_candidates=[],
        conflict_candidates=[],
        entity=None,
    )

    source_patch = next(patch for patch in patches if patch["page_type"] == "source")
    assert source_patch["title"] == "OSWorld: Benchmarking Multimodal Agents"
    assert source_patch["aliases"] == ["src_pdf"]


def test_markdown_source_page_aliases_still_include_title():
    patches = build_patches(
        source=source_dict("src_md", "Retrieval Notes", "markdown"),
        claims=[claim()],
        concept_title="Retrieval Notes",
        aliases=["retrieval notes"],
        duplicate_candidates=[],
        conflict_candidates=[],
        entity=None,
    )

    source_patch = next(patch for patch in patches if patch["page_type"] == "source")
    assert source_patch["aliases"] == ["Retrieval Notes", "src_md"]


def test_pdf_concept_entity_identity_overlap_is_reported():
    source = {"title": "OSWorld: Benchmarking Multimodal Agents", "source_type": "pdf"}
    proposal_with_entity = LLMIngestProposal(
        claims=[],
        concept_title="OSWorld",
        aliases=["OSWorld"],
        entity_title="OSWorld",
        entity_aliases=["OSWorld"],
        duplicate_candidates=[],
        conflict_candidates=[],
        source_summary="OSWorld summary.",
        concept_definition="OSWorld concept.",
        provider="fake",
        model="fake",
        raw_content="{}",
        usage={},
    )

    warnings = pdf_identity_warning_candidates(source, proposal_with_entity)

    assert any("concept/entity identity overlap" in warning for warning in warnings)
