from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwiki.cli import main
from tests.helpers import make_workspace, seed_contradicts_relationship
from tests.test_hybrid_retrieval import setup_seeded_workspace
from tests.test_query_lint_doctor import add_ingest_apply, fixture


DATASET = Path(__file__).resolve().parent / "evals" / "retrieval_v2_3.jsonl"
FRUIT_DATASET = Path(__file__).resolve().parent / "evals" / "retrieval_v2_4_fruits.jsonl"
SEMANTIC_FRUIT_DATASET = Path(__file__).resolve().parent / "evals" / "retrieval_v2_6_semantic_fruits.jsonl"
SELECTION_FRUIT_DATASET = Path(__file__).resolve().parent / "evals" / "retrieval_v2_7_evidence_selection_fruits.jsonl"
EVAL_FIXTURES = (
    "minimal_source.md",
    "regression_alias.md",
    "regression_conflict.md",
    "zh_alias_entity.md",
    "zh_conflict.md",
    "zh_supports.md",
)


def setup_eval_workspace(capsys: pytest.CaptureFixture[str]) -> Path:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source_ids: dict[str, str] = {}
    for name in EVAL_FIXTURES:
        source_ids[name] = add_ingest_apply(root, fixture(name))
    seed_contradicts_relationship(
        root,
        source_id=source_ids["regression_conflict.md"],
        claim_text_like="%does not require citation anchors%",
    )
    seed_contradicts_relationship(
        root,
        source_id=source_ids["zh_conflict.md"],
        claim_text_like="%不需要%citation anchors%",
    )
    capsys.readouterr()
    return root


def setup_minimal_workspace(capsys: pytest.CaptureFixture[str]) -> Path:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()
    return root


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_eval_cases_from_committed_jsonl():
    from llmwiki.retrieval_eval import load_eval_cases

    cases = load_eval_cases(DATASET)

    assert len(cases) >= 8
    assert cases[0].id == "rag_en_keyword_citation_anchors"
    assert cases[0].expected_status == "has_evidence"
    assert "clm_src_89d2888afaec_4" in cases[0].expected_claim_ids
    assert any(case.expected_status == "no_evidence" for case in cases)


def test_load_v24_fruit_eval_cases_from_committed_jsonl():
    from llmwiki.retrieval_eval import load_eval_cases

    cases = load_eval_cases(FRUIT_DATASET)

    assert [case.id for case in cases] == [
        "fruit_zh_strawberry_storage_natural",
        "fruit_zh_vitamin_c_comparison",
        "fruit_zh_apple_orange_vitamin_c",
        "fruit_zh_banana_blood_sugar",
        "fruit_zh_mango_energy_sugar",
    ]
    assert cases[0].question == "草莓应该怎么保存？"
    assert "src_99ab0495789d" in cases[0].expected_source_ids


def test_load_v26_semantic_fruit_eval_cases_from_committed_jsonl():
    from llmwiki.retrieval_eval import load_eval_cases

    cases = load_eval_cases(SEMANTIC_FRUIT_DATASET)

    assert [case.id for case in cases] == [
        "fruit_semantic_strawberry_storage",
        "fruit_semantic_post_exercise_energy",
        "fruit_semantic_blood_sugar_attention",
    ]
    assert cases[0].question == "草莓买回来怎样放才不容易坏？"
    assert "src_99ab0495789d" in cases[0].expected_source_ids


def test_load_v27_evidence_selection_eval_cases_from_committed_jsonl():
    from llmwiki.retrieval_eval import load_eval_cases

    cases = load_eval_cases(SELECTION_FRUIT_DATASET)

    assert [case.id for case in cases] == [
        "fruit_selection_vitamin_c_multi_source",
        "fruit_selection_storage_and_freshness",
        "fruit_selection_conflict_visibility",
        "fruit_selection_weak_evidence_visibility",
    ]
    assert cases[0].query_type == "comparison"
    assert "src_99ab0495789d" in cases[0].expected_source_ids
    assert "src_880c9f8a447c" in cases[0].expected_source_ids


def test_load_eval_cases_reports_jsonl_line_errors(tmp_path: Path):
    from llmwiki.retrieval_eval import load_eval_cases

    bad_dataset = tmp_path / "bad.jsonl"
    bad_dataset.write_text('{"id": "ok", "question": "valid"}\n{"id": ', encoding="utf-8")

    with pytest.raises(ValueError, match="bad.jsonl line 2"):
        load_eval_cases(bad_dataset)


def test_evaluate_retrieval_computes_metrics_and_contract(capsys):
    from llmwiki.retrieval_eval import evaluate_retrieval

    root = setup_minimal_workspace(capsys)

    summary = evaluate_retrieval(root, DATASET, limit=5)
    data = summary.to_dict()

    assert data["schema_version"] == "eval.retrieval.v2.3"
    assert data["case_count"] == len(summary.cases)
    assert data["summary"]["hit_at_5"] >= 0
    assert data["summary"]["recall_at_5"] >= 0
    assert data["summary"]["precision_at_5"] >= 0
    assert data["summary"]["mrr"] >= 0
    assert data["summary"]["ndcg_at_5"] >= 0
    assert data["summary"]["map_at_5"] >= 0
    assert data["summary"]["context_precision_at_5"] >= 0
    assert data["summary"]["context_recall_at_5"] >= 0
    assert data["summary"]["coverage_at_5"] >= 0
    assert data["summary"]["source_diversity_at_5"] >= 0
    assert data["summary"]["redundancy_rate_at_5"] >= 0
    assert data["summary"]["selected_conflict_exposure_rate"] >= 0
    assert data["summary"]["weak_evidence_visibility_rate"] >= 0
    assert data["evidence_contract"]["claim_id_validity"] == 1.0
    assert data["evidence_contract"]["source_id_validity"] == 1.0
    assert data["evidence_contract"]["citation_locator_presence"] == 1.0
    assert 0 <= data["evidence_contract"]["relationship_validity"] <= 1
    assert not contains_secret_text(data)


def test_eval_retrieval_does_not_call_llm_planner_or_provider(monkeypatch, capsys):
    root = setup_minimal_workspace(capsys)

    def fail_provider(*args, **kwargs):
        raise AssertionError("retrieval eval must not call an LLM provider or planner")

    monkeypatch.setattr("llmwiki.llm.create_provider", fail_provider)
    monkeypatch.setattr("llmwiki.planner.create_provider", fail_provider)
    monkeypatch.setattr("llmwiki.embeddings.create_embedding_provider", fail_provider)

    assert main(["eval", "retrieval", "--root", str(root), "--dataset", str(DATASET)]) == 0
    out = capsys.readouterr().out

    assert "Retrieval eval:" in out
    assert "Cases:" in out


def test_eval_no_evidence_case_passes_when_contexts_are_empty(capsys, tmp_path: Path):
    from llmwiki.retrieval_eval import evaluate_retrieval

    root = setup_minimal_workspace(capsys)
    dataset = write_jsonl(
        tmp_path / "negative.jsonl",
        [
            {
                "id": "negative",
                "question": "zzzz_nonexistent_qqq",
                "expected_status": "no_evidence",
            }
        ],
    )

    result = evaluate_retrieval(root, dataset, limit=5).cases[0]

    assert result.passed
    assert result.failure_stage is None
    assert result.returned_count == 0


def test_eval_classifies_unexpected_evidence_for_negative_case(capsys, tmp_path: Path):
    from llmwiki.retrieval_eval import evaluate_retrieval

    root = setup_minimal_workspace(capsys)
    dataset = write_jsonl(
        tmp_path / "unexpected.jsonl",
        [
            {
                "id": "unexpected",
                "question": "retrieval citation anchors",
                "expected_status": "no_evidence",
            }
        ],
    )

    result = evaluate_retrieval(root, dataset, limit=5).cases[0]

    assert not result.passed
    assert result.failure_stage == "unexpected_evidence"


def test_eval_classifies_ranking_miss_for_wrong_expected_source(capsys, tmp_path: Path):
    from llmwiki.retrieval_eval import evaluate_retrieval

    root = setup_minimal_workspace(capsys)
    dataset = write_jsonl(
        tmp_path / "ranking-miss.jsonl",
        [
            {
                "id": "wrong_source",
                "question": "retrieval citation anchors",
                "expected_status": "has_evidence",
                "expected_source_ids": ["src_missing_expected"],
            }
        ],
    )

    result = evaluate_retrieval(root, dataset, limit=5).cases[0]

    assert not result.passed
    assert result.failure_stage == "ranking_miss"


def test_eval_classifies_relationship_miss(capsys, tmp_path: Path):
    from llmwiki.retrieval_eval import evaluate_retrieval

    root = setup_minimal_workspace(capsys)
    dataset = write_jsonl(
        tmp_path / "relationship-miss.jsonl",
        [
            {
                "id": "missing_relationship",
                "question": "retrieval citation anchors",
                "expected_status": "has_evidence",
                "expected_source_ids": ["src_89d2888afaec"],
                "must_expose_relationship_types": ["similar_to"],
            }
        ],
    )

    result = evaluate_retrieval(root, dataset, limit=5).cases[0]

    assert not result.passed
    assert result.failure_stage == "relationship_miss"


def test_eval_cli_outputs_human_and_json_reports(capsys):
    root = setup_eval_workspace(capsys)

    assert main(["eval", "retrieval", "--root", str(root), "--dataset", str(DATASET), "--limit", "5"]) == 0
    human = capsys.readouterr().out
    assert "Retrieval eval:" in human
    assert "Core metrics:" in human
    assert "Evidence contract:" in human

    assert (
        main(
            [
                "eval",
                "retrieval",
                "--root",
                str(root),
                "--dataset",
                str(DATASET),
                "--limit",
                "5",
                "--json",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == "eval.retrieval.v2.3"
    assert data["dataset"].endswith("retrieval_v2_3.jsonl")
    assert "summary" in data
    assert "evidence_contract" in data
    assert isinstance(data["cases"], list)
    assert not contains_secret_text(data)


def test_evaluate_v24_natural_chinese_case_includes_hybrid_diagnostics(capsys, tmp_path: Path):
    from llmwiki.retrieval_eval import evaluate_retrieval

    root = setup_seeded_workspace()
    capsys.readouterr()
    dataset = write_jsonl(
        tmp_path / "fruit-v24.jsonl",
        [
            {
                "id": "fruit_zh_strawberry_storage_natural",
                "question": "草莓应该怎么保存？",
                "expected_status": "has_evidence",
                "expected_source_ids": ["src_99ab0495789d"],
                "expected_page_ids": ["concept:草莓"],
                "expected_terms": ["草莓", "保存", "冷藏"],
                "must_expose_relationship_types": ["supports"],
            }
        ],
    )

    summary = evaluate_retrieval(root, dataset, limit=5)
    data = summary.to_dict()
    case = data["cases"][0]

    assert data["operational"]["llm_calls"] == 0
    assert case["passed"]
    assert case["failure_stage"] is None
    assert case["diagnostics"]["retrievers"]["catalog_title_alias"]["candidate_count"] > 0
    assert "vector" in case["diagnostics"]["retrievers"]
    assert case["diagnostics"]["retrievers"]["vector"]["index_present"] is False
    assert case["diagnostics"]["fusion"]["method"] == "rrf"
    assert not contains_secret_text(data)


def test_evaluate_v27_selection_metrics_include_rerank_and_selection_diagnostics(capsys, tmp_path: Path):
    from llmwiki.retrieval_eval import evaluate_retrieval

    root = setup_seeded_workspace()
    capsys.readouterr()
    dataset = write_jsonl(
        tmp_path / "fruit-v27.jsonl",
        [
            {
                "id": "formula_selection_rerank_diagnostics",
                "question": "chemical formula water",
                "expected_status": "has_evidence",
                "expected_source_ids": ["src_formula"],
                "expected_terms": ["formula"],
            }
        ],
    )

    summary = evaluate_retrieval(root, dataset, limit=5)
    data = summary.to_dict()
    case = data["cases"][0]

    assert "ndcg_at_5" in data["summary"]
    assert "map_at_5" in data["summary"]
    assert data["summary"]["source_diversity_at_5"] > 0
    assert data["summary"]["coverage_at_5"] > 0
    assert "reranking" in case["diagnostics"]
    assert "selection" in case["diagnostics"]
    assert case["diagnostics"]["selection"]["selected_count"] == case["returned_count"]


def test_eval_cli_returns_nonzero_for_missing_catalog(capsys):
    root = make_workspace()

    assert main(["eval", "retrieval", "--root", str(root), "--dataset", str(DATASET)]) == 1
    out = capsys.readouterr().out

    assert "Retrieval eval failed:" in out
    assert not contains_secret_text(out)


def test_retrieve_result_includes_v27_diagnostics(capsys):
    root = setup_eval_workspace(capsys)

    assert main(["retrieve", "retrieval citation anchors", "--root", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["schema_version"] == "retrieval.v2.7"
    assert set(("question", "contexts", "relationships", "warnings")).issubset(data)
    assert data["diagnostics"]["query_terms"]
    assert "query_features" in data["diagnostics"]
    assert "retrievers" in data["diagnostics"]
    assert "vector" in data["diagnostics"]["retrievers"]
    assert "fusion" in data["diagnostics"]
    assert "reranking" in data["diagnostics"]
    assert "selection" in data["diagnostics"]
    assert data["diagnostics"]["candidate_count"] >= data["diagnostics"]["returned_count"]
    assert data["diagnostics"]["failure_stage"] is None
    context = data["contexts"][0]
    assert context["rank"] == 1
    assert context["confidence_status"] == "cited"
    assert context["page_type"] in {"source", "concept", "entity", "synthesis"}


def contains_secret_text(value: object) -> bool:
    text = json.dumps(value, ensure_ascii=False)
    return "config/api-keys.toml" in text or "sk-" in text
