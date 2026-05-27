from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.retrieval import retrieve_context
from tests.helpers import make_workspace
from tests.test_query_lint_doctor import add_ingest_apply, fixture


def rows(root: Path, sql: str) -> list[sqlite3.Row]:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql).fetchall()


class FakeProvider:
    def __init__(self, payload: dict[str, object], calls: list[list[dict[str, str]]]) -> None:
        self.payload = payload
        self.calls = calls

    def complete(self, messages: list[dict[str, str]], schema=None) -> dict[str, object]:
        self.calls.append(messages)
        return {
            "provider": "openai",
            "model": "deepseek-v4-pro",
            "content": json.dumps(self.payload, ensure_ascii=False),
            "finish_reason": "stop",
            "usage": {"total_tokens": 12},
        }


def answer_payload(context: dict[str, object], title: str = "Citation Anchors") -> dict[str, object]:
    return {
        "short_answer": "RAG needs citation anchors so answers remain traceable to source passages.",
        "analysis": "The retrieved evidence says citation anchors preserve auditability.",
        "citations": [
            {
                "claim_id": context["claim_id"],
                "source_id": context["source_id"],
                "citation_locator": context["citation_locator"],
            }
        ],
        "uncertainties": [],
        "conflicts": [],
        "suggested_title": title,
    }


def patch_answer_provider(monkeypatch, payload: dict[str, object]) -> list[list[dict[str, str]]]:
    calls: list[list[dict[str, str]]] = []

    def fake_create_provider(config, root=None):
        return FakeProvider(payload, calls)

    monkeypatch.setattr("llmwiki.answer.create_provider", fake_create_provider)
    return calls


def setup_retrieval_workspace(root: Path) -> dict[str, object]:
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    contexts = retrieve_context(root, "RAG citation anchors", limit=1)["contexts"]
    assert contexts
    return contexts[0]


def synthesis_pages(root: Path) -> list[Path]:
    return sorted((root / "wiki" / "syntheses").glob("*.md"))


def test_ask_without_evidence_returns_insufficient_evidence_without_llm(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    calls = patch_answer_provider(monkeypatch, {})
    capsys.readouterr()

    assert main(["ask", "no matching claim should exist", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "Question: no matching claim should exist" in out
    assert "insufficient_evidence" in out
    assert "No matching claims found" in out
    assert calls == []
    assert synthesis_pages(root) == []


def test_ask_answers_from_retrieved_evidence_and_does_not_write_by_default(monkeypatch, capsys):
    root = make_workspace()
    context = setup_retrieval_workspace(root)
    calls = patch_answer_provider(monkeypatch, answer_payload(context))
    capsys.readouterr()

    assert main(["ask", "RAG citation anchors", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert calls
    assert "Question: RAG citation anchors" in out
    assert "Answer:" in out
    assert "RAG needs citation anchors" in out
    assert "Citations:" in out
    assert str(context["claim_id"]) in out
    assert str(context["source_id"]) in out
    assert str(context["citation_locator"]) in out
    assert "Warnings: none" in out
    assert "Writeback:" in out
    assert "Not written" in out
    assert synthesis_pages(root) == []


def test_ask_json_output_is_stable_and_does_not_leak_secrets(monkeypatch, capsys):
    root = make_workspace()
    context = setup_retrieval_workspace(root)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret-should-not-print")
    patch_answer_provider(monkeypatch, answer_payload(context))
    capsys.readouterr()

    assert main(["ask", "RAG citation anchors", "--root", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert set(data) == {"question", "answer", "status", "citations", "warnings", "writeback"}
    assert data["question"] == "RAG citation anchors"
    assert data["status"] == "answered"
    assert data["answer"].startswith("RAG needs citation anchors")
    assert data["citations"] == [
        {
            "claim_id": context["claim_id"],
            "source_id": context["source_id"],
            "citation_locator": context["citation_locator"],
            "page_path": context["page_path"],
        }
    ]
    assert data["writeback"] == {"status": "skipped", "run_id": None, "pages": []}
    serialized = json.dumps(data, ensure_ascii=False)
    assert "sk-test-secret-should-not-print" not in serialized
    assert "config/api-keys.toml" not in serialized
    assert synthesis_pages(root) == []


def test_ask_rejects_llm_citations_outside_retrieved_evidence(monkeypatch, capsys):
    root = make_workspace()
    setup_retrieval_workspace(root)
    patch_answer_provider(
        monkeypatch,
        {
            "short_answer": "This answer cites a claim that was not retrieved.",
            "analysis": "The citation is invalid.",
            "citations": [
                {
                    "claim_id": "clm_unknown",
                    "source_id": "src_unknown",
                    "citation_locator": "line:999",
                }
            ],
            "uncertainties": [],
            "conflicts": [],
            "suggested_title": "Invalid Citation",
        },
    )
    capsys.readouterr()

    assert main(["ask", "RAG citation anchors", "--root", str(root)]) == 1
    out = capsys.readouterr().out

    assert "invalid_citations" in out
    assert "clm_unknown" in out
    assert synthesis_pages(root) == []


def test_ask_writeback_applies_synthesis_page_and_catalog(monkeypatch, capsys):
    root = make_workspace()
    context = setup_retrieval_workspace(root)
    patch_answer_provider(monkeypatch, answer_payload(context, title="Citation Anchors"))
    capsys.readouterr()

    assert main(["ask", "RAG citation anchors", "--root", str(root), "--writeback"]) == 0
    out = capsys.readouterr().out

    page = root / "wiki" / "syntheses" / "citation-anchors.md"
    assert "Applied synthesis run: run_answer_" in out
    assert "wiki/syntheses/citation-anchors.md" in out
    assert page.exists()
    content = page.read_text(encoding="utf-8")
    assert "page_type: synthesis" in content
    assert f"claim_ids: ['{context['claim_id']}']" in content
    assert "## Question/Topic" in content
    assert "## Short Answer" in content
    assert "## Evidence" in content
    assert "## Analysis" in content
    assert "## Uncertainties" in content
    assert "## Related Pages" in content
    assert str(context["claim_id"]) in content
    assert str(context["source_id"]) in content
    assert str(context["citation_locator"]) in content

    index = (root / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "wiki/syntheses/citation-anchors.md" in index
    assert "Citation Anchors" in index
    log = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    assert "Applied ingest run `run_answer_" in log

    page_rows = rows(root, "select path, page_type, title from pages where page_type = 'synthesis'")
    assert len(page_rows) == 1
    assert page_rows[0]["path"] == "wiki/syntheses/citation-anchors.md"
    assert page_rows[0]["title"] == "Citation Anchors"
    run_rows = rows(root, "select run_id, source_id, status from ingest_runs where run_id like 'run_answer_%'")
    assert len(run_rows) == 1
    assert run_rows[0]["source_id"].startswith("synthesis:")
    assert run_rows[0]["status"] == "applied"


def test_ask_writeback_preserves_contradictions_in_synthesis(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_ingest_apply(root, fixture("minimal_source.md"))
    add_ingest_apply(root, fixture("regression_conflict.md"))
    context = retrieve_context(root, "citation anchors every workflow", limit=1)["contexts"][0]
    payload = answer_payload(context, title="Citation Anchor Conflict")
    payload["short_answer"] = "The local evidence disagrees about whether every workflow needs citation anchors."
    payload["uncertainties"] = ["Sources disagree about whether every workflow requires citation anchors."]
    payload["conflicts"] = ["A conflict is recorded between retrieved claims."]
    patch_answer_provider(monkeypatch, payload)
    capsys.readouterr()

    assert main(["ask", "citation anchors every workflow", "--root", str(root), "--writeback"]) == 0

    page = root / "wiki" / "syntheses" / "citation-anchor-conflict.md"
    content = page.read_text(encoding="utf-8")
    assert "Sources disagree about whether every workflow requires citation anchors." in content
    assert "A conflict is recorded between retrieved claims." in content


def test_ask_writeback_marks_run_failed_when_apply_rejects_patch(monkeypatch, capsys):
    from llmwiki.apply import UnsafePatchError

    root = make_workspace()
    context = setup_retrieval_workspace(root)
    patch_answer_provider(monkeypatch, answer_payload(context, title="Rejected Synthesis"))
    before_index = (root / "wiki" / "index.md").read_text(encoding="utf-8")
    before_log = (root / "wiki" / "log.md").read_text(encoding="utf-8")

    def reject_patch(*args, **kwargs):
        raise UnsafePatchError("forced synthesis rejection")

    monkeypatch.setattr("llmwiki.apply.validate_patch", reject_patch)
    capsys.readouterr()

    assert main(["ask", "RAG citation anchors", "--root", str(root), "--writeback"]) == 1
    out = capsys.readouterr().out

    assert "Writeback failed at: apply" in out
    assert "Debug: llmwiki review run_answer_" in out
    run_dir = next((root / "staging").glob("run_answer_*"))
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["trigger"] == "ask"
    assert manifest["failed_stage"] == "apply"
    assert "forced synthesis rejection" in manifest["failure_reason"]
    assert synthesis_pages(root) == []
    assert rows(root, "select path from pages where page_type = 'synthesis'") == []
    assert (root / "wiki" / "index.md").read_text(encoding="utf-8") == before_index
    assert (root / "wiki" / "log.md").read_text(encoding="utf-8") == before_log
