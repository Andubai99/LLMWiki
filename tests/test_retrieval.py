from __future__ import annotations

import json
from pathlib import Path

from llmwiki.cli import main
from tests.helpers import make_workspace
from tests.test_query_lint_doctor import add_ingest_apply, fixture


def test_retrieve_json_schema_and_python_api(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source_id = add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()

    assert main(["retrieve", "retrieval citation anchors", "--root", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["question"] == "retrieval citation anchors"
    assert {"question", "contexts", "relationships", "warnings"}.issubset(data)
    assert data["schema_version"] == "retrieval.v2.4"
    assert "diagnostics" in data
    assert data["contexts"]
    context = data["contexts"][0]
    assert {
        "claim_id",
        "source_id",
        "citation_locator",
        "claim_text",
        "page_path",
        "relationship_type",
        "score",
    }.issubset(context)
    assert context["rank"] == 1
    assert context["confidence_status"] == "cited"
    assert context["page_type"] in {"source", "concept", "entity", "synthesis"}
    assert context["source_id"] == source_id
    assert context["citation_locator"].startswith("line:")
    assert context["page_path"].startswith("wiki/")
    assert isinstance(context["score"], float)
    assert "retrieval_reasons" in context

    from llmwiki.retrieval import retrieve_context

    api_result = retrieve_context(root, "retrieval citation anchors")
    assert api_result["contexts"]
    assert api_result["contexts"][0]["source_id"] == source_id


def test_retrieve_finds_english_claim_and_respects_limit(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()

    assert main(["retrieve", "RAG citation anchors", "--root", str(root), "--json", "--limit", "1"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert len(data["contexts"]) == 1
    assert "citation anchors" in data["contexts"][0]["claim_text"]


def test_retrieve_finds_chinese_claim(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    chinese_source = root / "chinese-retrieval.md"
    chinese_source.write_text(
        "# 中文检索样例\n\n"
        "检索 增强 生成 需要 引用 锚点 来 支持 审计 追踪。\n",
        encoding="utf-8",
    )
    add_ingest_apply(root, chinese_source)
    capsys.readouterr()

    assert main(["retrieve", "检索 增强 生成 引用 锚点", "--root", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert any("检索 增强 生成" in context["claim_text"] for context in data["contexts"])


def test_retrieve_expands_rag_aliases(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("regression_alias.md"))
    capsys.readouterr()

    assert main(["retrieve", "RAG duplicate page", "--root", str(root), "--json"]) == 0
    rag_data = json.loads(capsys.readouterr().out)
    assert any("retrieval augmented generation" in c["claim_text"].casefold() for c in rag_data["contexts"])

    assert main(["retrieve", "retrieval augmented generation alias", "--root", str(root), "--json"]) == 0
    expanded_data = json.loads(capsys.readouterr().out)
    assert any("RAG is an alias" in c["claim_text"] for c in expanded_data["contexts"])


def test_retrieve_outputs_contradicts_relationships(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    add_ingest_apply(root, fixture("regression_conflict.md"))
    capsys.readouterr()

    assert main(["retrieve", "citation anchors every workflow", "--root", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert any(item["relationship_type"] == "contradicts" for item in data["relationships"])
    assert any(context["relationship_type"] == "contradicts" for context in data["contexts"])
    assert any("contradict" in warning.casefold() for warning in data["warnings"])


def test_retrieve_prompt_contains_answer_constraints(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()

    assert main(["retrieve", "Why cite RAG claims?", "--root", str(root), "--format", "prompt"]) == 0
    prompt = capsys.readouterr().out

    assert "Question:" in prompt
    assert "Evidence:" in prompt
    assert "source_id" in prompt
    assert "citation_locator" in prompt
    assert "page_path" in prompt
    assert "relationship_type" in prompt
    assert "Only answer from the evidence" in prompt
    assert "insufficient evidence" in prompt
    assert "contradicts" in prompt
    assert "weak/uncited" in prompt


def test_retrieve_empty_result_warns_without_error(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()

    assert main(["retrieve", "no matching claim should exist", "--root", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["contexts"] == []
    assert data["warnings"]


def test_retrieve_filters_by_source_page_type_and_confidence(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source_id = add_ingest_apply(root, fixture("minimal_source.md"))
    capsys.readouterr()

    assert (
        main(
            [
                "retrieve",
                "retrieval citation anchors",
                "--root",
                str(root),
                "--json",
                "--source-id",
                source_id,
                "--page-type",
                "concept",
                "--confidence",
                "cited",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)

    assert data["contexts"]
    assert all(context["source_id"] == source_id for context in data["contexts"])
    assert all(context["page_path"].startswith("wiki/concepts/") for context in data["contexts"])
