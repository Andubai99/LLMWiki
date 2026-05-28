from __future__ import annotations

import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.query_analysis import analyze_query
from llmwiki.retrievers import (
    BM25ClaimRetriever,
    CatalogTitleAliasRetriever,
    ExactFormulaSymbolRetriever,
    GraphRelationshipRetriever,
    HybridRetriever,
    RetrievalCandidate,
    RetrievalFilters,
    RetrieverResult,
    reciprocal_rank_fusion,
)
from llmwiki.retrieval import retrieve_context
from tests.helpers import make_workspace


def connect_catalog(root: Path):
    conn = sqlite3.connect(root / "state" / "catalog.sqlite")
    conn.row_factory = sqlite3.Row
    return conn


def setup_seeded_workspace() -> Path:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    with connect_catalog(root) as conn:
        seed_source(
            conn,
            source_id="src_99ab0495789d",
            title="草莓：酸甜可口的浆果类水果",
            concept_id="concept:草莓",
            concept_title="草莓",
            concept_path="wiki/concepts/草莓.md",
            claims=[
                (
                    "clm_strawberry_overview",
                    "草莓是一种常见的浆果类水果，颜色鲜红，味道酸甜。",
                    "line:5;section:1. 概述;paragraph:1",
                    "cited",
                ),
                (
                    "clm_strawberry_storage",
                    "草莓适合冷藏保存，购买后应尽快食用，并尽量保持干燥。",
                    "line:86;section:5.2 冷藏保存;paragraph:21",
                    "cited",
                ),
                (
                    "clm_strawberry_vitamin_c",
                    "草莓含有较丰富的维生素 C。",
                    "line:21;section:2.1 维生素 C;paragraph:5",
                    "cited",
                ),
            ],
            aliases=["草莓", "浆果类水果"],
        )
        seed_source(
            conn,
            source_id="src_880c9f8a447c",
            title="橙子：富含维生素 C 的柑橘类水果",
            concept_id="concept:橙子",
            concept_title="橙子",
            concept_path="wiki/concepts/橙子.md",
            claims=[
                (
                    "clm_orange_vitamin_c",
                    "橙子富含维生素 C，是常见的柑橘类水果。",
                    "line:23;section:2.1 维生素 C;paragraph:6",
                    "cited",
                )
            ],
            aliases=["橙子", "柑橘类水果"],
        )
        seed_source(
            conn,
            source_id="src_formula",
            title="Formula Notes",
            concept_id="concept:formula",
            concept_title="Formula",
            concept_path="wiki/concepts/formula.md",
            claims=[
                ("clm_h2o", "H₂O is the chemical formula for water.", "line:1", "cited"),
                ("clm_emc2", "E=mc² relates energy and mass.", "line:2", "cited"),
                ("clm_alpha_beta", "The α/β ratio compares two parameters.", "line:3", "cited"),
            ],
            aliases=["H₂O", "E=mc²", "α/β"],
        )
        seed_source(
            conn,
            source_id="src_weak",
            title="Weak Notes",
            concept_id="concept:weak",
            concept_title="Weak",
            concept_path="wiki/concepts/weak.md",
            claims=[
                ("clm_weak_storage", "草莓可能适合常温保存很久。", "line:1", "weak"),
            ],
            aliases=["弱证据"],
        )
    return root


def seed_source(
    conn,
    *,
    source_id: str,
    title: str,
    concept_id: str,
    concept_title: str,
    concept_path: str,
    claims: list[tuple[str, str, str, str]],
    aliases: list[str],
) -> None:
    conn.execute(
        """
        insert into sources (source_id, title, source_type, raw_path, normalized_path, sha256, url, imported_at, status)
        values (?, ?, 'markdown', ?, ?, ?, null, '2026-05-28T00:00:00+00:00', 'imported')
        """,
        (source_id, title, f"sources/raw/{source_id}.md", f"sources/normalized/{source_id}.md", source_id),
    )
    conn.execute(
        """
        insert into pages (page_id, path, page_type, title, aliases, updated_at)
        values (?, ?, 'source', ?, '[]', '2026-05-28T00:00:00+00:00')
        """,
        (source_id, f"wiki/sources/{source_id}.md", title),
    )
    conn.execute(
        """
        insert into pages (page_id, path, page_type, title, aliases, updated_at)
        values (?, ?, 'concept', ?, ?, '2026-05-28T00:00:00+00:00')
        """,
        (concept_id, concept_path, concept_title, str(aliases)),
    )
    conn.execute("insert into links (from_page, to_page, link_type) values (?, ?, 'mentions')", (source_id, concept_id))
    conn.execute("insert into links (from_page, to_page, link_type) values (?, ?, 'supports')", (concept_id, source_id))
    for alias in [concept_title, *aliases]:
        conn.execute(
            "insert into aliases (alias, target_type, target_id, normalized_alias) values (?, 'concept', ?, ?)",
            (alias, concept_id, alias.casefold()),
        )
    for claim_id, claim_text, locator, confidence in claims:
        conn.execute(
            """
            insert into claims (claim_id, source_id, claim_text, citation_locator, confidence_status, created_at)
            values (?, ?, ?, ?, ?, '2026-05-28T00:00:00+00:00')
            """,
            (claim_id, source_id, claim_text, locator, confidence),
        )
        conn.execute(
            "insert into claims_fts (claim_id, claim_text, source_id, citation_locator) values (?, ?, ?, ?)",
            (claim_id, claim_text, source_id, locator),
        )
        conn.execute(
            """
            insert into relationships (subject_id, object_id, relationship_type, evidence_claim_id, source_id)
            values (?, ?, 'supports', ?, ?)
            """,
            (concept_id, source_id, claim_id, source_id),
        )


def test_bm25_claim_retriever_finds_english_claim():
    root = setup_seeded_workspace()
    query = analyze_query("chemical formula water")

    with connect_catalog(root) as conn:
        result = BM25ClaimRetriever().retrieve(conn, query, limit=5, filters=RetrievalFilters())

    assert any(candidate.claim_id == "clm_h2o" for candidate in result.candidates)
    assert all("bm25_fts" in candidate.retrievers for candidate in result.candidates)


def test_catalog_title_alias_retriever_handles_natural_chinese_question():
    root = setup_seeded_workspace()
    query = analyze_query("草莓应该怎么保存？", catalog_terms=["草莓", "橙子"])

    with connect_catalog(root) as conn:
        result = CatalogTitleAliasRetriever().retrieve(conn, query, limit=5, filters=RetrievalFilters())

    claim_ids = {candidate.claim_id for candidate in result.candidates}
    assert "clm_strawberry_storage" in claim_ids
    assert "clm_orange_vitamin_c" not in claim_ids
    assert any("alias_exact:草莓" in candidate.reasons for candidate in result.candidates)


def test_exact_formula_symbol_retriever_preserves_symbols():
    root = setup_seeded_workspace()
    query = analyze_query("H₂O 和 α/β ratio")

    with connect_catalog(root) as conn:
        result = ExactFormulaSymbolRetriever().retrieve(conn, query, limit=5, filters=RetrievalFilters())

    claim_ids = {candidate.claim_id for candidate in result.candidates}
    assert {"clm_h2o", "clm_alpha_beta"} <= claim_ids
    assert any("exact_span:H₂O" in reason for candidate in result.candidates for reason in candidate.reasons)


def test_exact_formula_symbol_retriever_does_not_pollute_plain_alias_matches():
    root = setup_seeded_workspace()
    query = analyze_query("草莓应该怎么保存？", catalog_terms=["草莓", "橙子"])

    with connect_catalog(root) as conn:
        result = ExactFormulaSymbolRetriever().retrieve(conn, query, limit=20, filters=RetrievalFilters())

    claim_ids = {candidate.claim_id for candidate in result.candidates}
    assert "clm_strawberry_storage" in claim_ids
    assert "clm_orange_vitamin_c" not in claim_ids


def test_graph_retriever_expands_one_hop_from_seed_candidates():
    root = setup_seeded_workspace()
    seed = RetrievalCandidate(
        claim_id="clm_strawberry_storage",
        source_id="src_99ab0495789d",
        claim_text="草莓适合冷藏保存，购买后应尽快食用，并尽量保持干燥。",
        citation_locator="line:86;section:5.2 冷藏保存;paragraph:21",
        confidence_status="cited",
        page_id="src_99ab0495789d",
        page_path="wiki/sources/src_99ab0495789d.md",
        page_type="source",
        raw_score=1.0,
        retriever_rank=1,
        retrievers=["seed"],
        reasons=["seed"],
    )

    with connect_catalog(root) as conn:
        result = GraphRelationshipRetriever([seed]).retrieve(
            conn,
            analyze_query("草莓保存"),
            limit=10,
            filters=RetrievalFilters(),
        )

    claim_ids = {candidate.claim_id for candidate in result.candidates}
    assert "clm_strawberry_vitamin_c" in claim_ids
    assert all("graph_relationship" in candidate.retrievers for candidate in result.candidates)


def test_rrf_merges_duplicate_claims_and_reasons():
    left = RetrievalCandidate(
        claim_id="clm_same",
        source_id="src_a",
        claim_text="same",
        citation_locator="line:1",
        confidence_status="cited",
        page_id="src_a",
        page_path="wiki/sources/src_a.md",
        page_type="source",
        raw_score=0.5,
        retriever_rank=1,
        retrievers=["bm25_fts"],
        reasons=["bm25_fts"],
    )
    right = RetrievalCandidate(
        claim_id="clm_same",
        source_id="src_a",
        claim_text="same",
        citation_locator="line:1",
        confidence_status="cited",
        page_id="src_a",
        page_path="wiki/sources/src_a.md",
        page_type="source",
        raw_score=0.9,
        retriever_rank=1,
        retrievers=["catalog_title_alias"],
        reasons=["alias_exact:same"],
    )

    fused = reciprocal_rank_fusion(
        [
            RetrieverResult("bm25_fts", [left]),
            RetrieverResult("catalog_title_alias", [right]),
        ]
    )

    assert len(fused) == 1
    assert fused[0].claim_id == "clm_same"
    assert fused[0].raw_score > 0
    assert fused[0].retrievers == ["bm25_fts", "catalog_title_alias"]
    assert "alias_exact:same" in fused[0].reasons


def test_hybrid_retriever_respects_source_page_type_and_confidence_filters():
    root = setup_seeded_workspace()
    query = analyze_query("草莓保存", catalog_terms=["草莓"])

    with connect_catalog(root) as conn:
        result = HybridRetriever().retrieve(
            conn,
            query,
            limit=10,
            filters=RetrievalFilters(
                source_id="src_99ab0495789d",
                page_type="concept",
                confidence="cited",
            ),
        )

    assert result.candidates
    assert all(candidate.source_id == "src_99ab0495789d" for candidate in result.candidates)
    assert all(candidate.page_type == "concept" for candidate in result.candidates)
    assert all(candidate.confidence_status == "cited" for candidate in result.candidates)


def test_retrieve_ranks_specific_natural_chinese_evidence_before_generic_page_claims():
    root = setup_seeded_workspace()

    result = retrieve_context(root, "草莓应该怎么保存？", limit=1)

    assert result["contexts"][0]["claim_id"] == "clm_strawberry_storage"
