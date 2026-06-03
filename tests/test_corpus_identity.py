from __future__ import annotations

from llmwiki.corpus.identity import (
    arxiv_year,
    first_arxiv_id,
    first_doi,
    infer_year,
    normalize_title_key,
)


def test_extracts_arxiv_id_from_filename_prefix_and_url() -> None:
    assert first_arxiv_id("2404.07972.pdf") == "2404.07972"
    assert first_arxiv_id("arXiv:2404.07972v2") == "2404.07972v2"
    assert first_arxiv_id("https://arxiv.org/abs/2505.13909") == "2505.13909"
    assert first_arxiv_id("notes without arxiv id") == ""


def test_extracts_doi_and_strips_url_prefix_and_trailing_punctuation() -> None:
    assert first_doi("https://doi.org/10.1145/1234567.890).") == "10.1145/1234567.890"
    assert first_doi("doi:10.48550/arXiv.2404.07972") == "10.48550/arxiv.2404.07972"
    assert first_doi("no DOI here") == ""


def test_infers_year_from_explicit_year_before_arxiv_id() -> None:
    assert infer_year(["Published as a conference paper at ICLR 2025"], "2404.07972") == (2025, "metadata")
    assert infer_year(["agent v2 benchmark"], "2404.07972") == (2024, "arxiv_id")
    assert infer_year(["method 24 improves score 7"], "") == (None, "unknown")
    assert arxiv_year("2605.11212") == 2026


def test_normalizes_title_for_duplicate_matching_without_inventing_aliases() -> None:
    assert normalize_title_key("  OSWorld: Benchmarking  Multimodal Agents! ") == "osworld benchmarking multimodal agents"
    assert normalize_title_key("") == ""
