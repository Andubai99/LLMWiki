from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from llmwiki.answer import AnswerCitation, AskResult
from llmwiki.cli import main
from tests.helpers import make_workspace


class FakeProvider:
    def __init__(self, payload: dict[str, object], calls: list[list[dict[str, str]]]) -> None:
        self.payload = payload
        self.calls = calls

    def complete(self, messages: list[dict[str, str]], schema=None) -> dict[str, object]:
        self.calls.append(messages)
        return {
            "provider": "openai",
            "model": "deepseek-v4-flash",
            "content": json.dumps(self.payload, ensure_ascii=False),
            "finish_reason": "stop",
            "usage": {"total_tokens": 12},
        }


class SequenceProvider:
    def __init__(self, payloads: list[dict[str, object]], calls: list[list[dict[str, str]]]) -> None:
        self.payloads = payloads
        self.calls = calls

    def complete(self, messages: list[dict[str, str]], schema=None) -> dict[str, object]:
        self.calls.append(messages)
        payload = self.payloads.pop(0)
        return {
            "provider": "openai",
            "model": "deepseek-v4-flash",
            "content": json.dumps(payload, ensure_ascii=False),
            "finish_reason": "stop",
            "usage": {"total_tokens": 12},
        }


def seed_workspace() -> Path:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into sources (
                source_id, title, source_type, raw_path, normalized_path,
                sha256, url, imported_at, status
            )
            values (
                'src_doc', 'RAG Notes', 'markdown',
                'sources/raw/src_doc.md', 'sources/normalized/src_doc.md',
                'src_doc_hash', null, '2026-05-30T00:00:00+00:00', 'imported'
            )
            """
        )
        conn.execute(
            """
            insert into pages (page_id, path, page_type, title, aliases, updated_at)
            values ('src_doc', 'wiki/sources/src_doc.md', 'source', 'RAG Notes', '[]', '2026-05-30T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            insert into claims (claim_id, source_id, claim_text, citation_locator, confidence_status, created_at)
            values (
                'clm_rag_anchor', 'src_doc',
                'RAG answers need citation anchors so claims remain auditable.',
                'line:1', 'cited', '2026-05-30T00:00:00+00:00'
            )
            """
        )
        conn.execute(
            """
            insert into claims_fts (claim_id, claim_text, source_id, citation_locator)
            values (
                'clm_rag_anchor',
                'RAG answers need citation anchors so claims remain auditable.',
                'src_doc', 'line:1'
            )
            """
        )
    return root


def ask_result() -> AskResult:
    return AskResult(
        question="Why do RAG answers need citation anchors?",
        status="answered",
        answer="RAG answers need citation anchors so claims remain auditable.",
        analysis="The retrieved claim ties answer traceability to citation anchors.",
        citations=[
            AnswerCitation(
                claim_id="clm_rag_anchor",
                source_id="src_doc",
                citation_locator="line:1",
                page_path="wiki/sources/src_doc.md",
            )
        ],
        suggested_title="RAG Citation Anchors",
        contexts=[
            {
                "claim_id": "clm_rag_anchor",
                "source_id": "src_doc",
                "claim_text": "RAG answers need citation anchors so claims remain auditable.",
                "citation_locator": "line:1",
                "confidence_status": "cited",
                "page_path": "wiki/sources/src_doc.md",
                "page_type": "source",
                "relationship_type": "supports",
            }
        ],
    )


def plan_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "synthesis_plan.v2.8",
        "status": "planned",
        "action": "create",
        "target_page_id": "synthesis-rag-citation-anchors",
        "target_path": "wiki/syntheses/rag-citation-anchors.md",
        "title": "RAG Citation Anchors",
        "topic_key": "rag-citation-anchors",
        "aliases": ["Citation Anchors"],
        "evidence": [
            {
                "role": "supports",
                "claim_id": "clm_rag_anchor",
                "source_id": "src_doc",
                "citation_locator": "line:1",
                "page_path": "wiki/sources/src_doc.md",
            }
        ],
        "sections": {
            "scope": "Why citation anchors matter in RAG answers.",
            "current_answer": "RAG answers need citation anchors so claims remain auditable.",
            "analysis": "The source-backed evidence supports traceable answers.",
            "conflicts_and_limits": [],
            "open_questions": [],
        },
        "related_pages": ["wiki/sources/src_doc.md"],
        "relationships": [
            {
                "subject_id": "synthesis-rag-citation-anchors",
                "object_id": "clm_rag_anchor",
                "relationship_type": "supports",
                "evidence_claim_id": "clm_rag_anchor",
                "source_id": "src_doc",
            }
        ],
        "candidate_pages": [],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def patch_provider(monkeypatch, payload: dict[str, object]) -> list[list[dict[str, str]]]:
    from llmwiki import synthesis_planner

    calls: list[list[dict[str, str]]] = []

    def fake_create_provider(config, root=None):
        return FakeProvider(payload, calls)

    monkeypatch.setattr(synthesis_planner, "create_provider", fake_create_provider)
    return calls


def patch_sequence_provider(monkeypatch, payloads: list[dict[str, object]]) -> list[list[dict[str, str]]]:
    from llmwiki import synthesis_planner

    calls: list[list[dict[str, str]]] = []

    def fake_create_provider(config, root=None):
        return SequenceProvider(list(payloads), calls)

    monkeypatch.setattr(synthesis_planner, "create_provider", fake_create_provider)
    return calls


def test_create_plan_validates_catalog_backed_evidence(monkeypatch):
    from llmwiki.synthesis_planner import SynthesisPlanningOptions, plan_synthesis_writeback

    root = seed_workspace()
    calls = patch_provider(monkeypatch, plan_payload())

    plan = plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())

    assert calls
    assert plan.action == "create"
    assert plan.target_path == "wiki/syntheses/rag-citation-anchors.md"
    assert plan.evidence_claim_ids == ["clm_rag_anchor"]
    assert plan.to_dict()["schema_version"] == "synthesis_plan.v2.8"


def test_update_plan_requires_existing_synthesis_target(monkeypatch):
    from llmwiki.synthesis_planner import SynthesisPlanningOptions, plan_synthesis_writeback

    root = seed_workspace()
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into pages (page_id, path, page_type, title, aliases, updated_at)
            values (
                'synthesis-existing', 'wiki/syntheses/existing.md',
                'synthesis', 'Existing Synthesis', '[]', '2026-05-30T00:00:00+00:00'
            )
            """
        )
    (root / "wiki" / "syntheses" / "existing.md").write_text(
        "---\npage_type: synthesis\ntitle: \"Existing Synthesis\"\naliases: []\nsource_count: 1\nclaim_ids: ['clm_rag_anchor']\nupdated_at: \"2026-05-30T00:00:00+00:00\"\n---\n\n# Existing Synthesis\n\n## Question/Topic\n\nRAG\n\n## Short Answer\n\nOld answer.\n\n## Evidence\n\n- `clm_rag_anchor`\n\n## Analysis\n\nOld analysis.\n\n## Uncertainties\n\n- None.\n\n## Related Pages\n\n- [[wiki/sources/src_doc.md]]\n",
        encoding="utf-8",
        newline="\n",
    )
    payload = plan_payload(
        action="update",
        target_page_id="synthesis-existing",
        target_path="wiki/syntheses/existing.md",
        title="Existing Synthesis",
        relationships=[
            {
                "subject_id": "synthesis-existing",
                "object_id": "clm_rag_anchor",
                "relationship_type": "supports",
                "evidence_claim_id": "clm_rag_anchor",
                "source_id": "src_doc",
            }
        ],
    )
    patch_provider(monkeypatch, payload)

    plan = plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())

    assert plan.action == "update"
    assert plan.target_page_id == "synthesis-existing"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"evidence": [{"role": "supports", "claim_id": "clm_missing", "source_id": "src_doc", "citation_locator": "line:1", "page_path": "wiki/sources/src_doc.md"}]}, "unknown claim"),
        ({"evidence": [{"role": "supports", "claim_id": "clm_rag_anchor", "source_id": "src_missing", "citation_locator": "line:1", "page_path": "wiki/sources/src_doc.md"}]}, "source_id mismatch"),
        ({"evidence": [{"role": "supports", "claim_id": "clm_rag_anchor", "source_id": "src_doc", "citation_locator": "line:1", "page_path": "wiki/sources/missing.md"}]}, "page_path mismatch"),
    ],
)
def test_plan_rejects_forged_evidence(monkeypatch, override, message):
    from llmwiki.synthesis_planner import (
        SynthesisPlanningError,
        SynthesisPlanningOptions,
        plan_synthesis_writeback,
    )

    root = seed_workspace()
    patch_provider(monkeypatch, plan_payload(**override))

    with pytest.raises(SynthesisPlanningError, match=message):
        plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())


def test_needs_review_plan_is_valid_but_not_applyable(monkeypatch):
    from llmwiki.synthesis_planner import SynthesisPlanningOptions, plan_synthesis_writeback

    root = seed_workspace()
    patch_provider(
        monkeypatch,
        plan_payload(
            status="needs_review",
            action="needs_review",
            warnings=["Multiple plausible synthesis targets."],
        ),
    )

    plan = plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())

    assert plan.action == "needs_review"
    assert plan.status == "needs_review"
    assert plan.warnings == ["Multiple plausible synthesis targets."]
    assert list((root / "staging").glob("*")) == []


def test_plan_output_does_not_leak_secret_paths_or_api_keys(monkeypatch):
    from llmwiki.synthesis_planner import (
        SynthesisPlanningError,
        SynthesisPlanningOptions,
        plan_synthesis_writeback,
    )

    root = seed_workspace()
    patch_provider(
        monkeypatch,
        plan_payload(
            sections={
                "scope": "config/api-keys.toml",
                "current_answer": "sk-test-secret",
                "analysis": "The source-backed evidence supports traceable answers.",
                "conflicts_and_limits": [],
                "open_questions": [],
            }
        ),
    )

    with pytest.raises(SynthesisPlanningError) as excinfo:
        plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())

    message = str(excinfo.value)
    assert "config/api-keys.toml" not in message
    assert "sk-test-secret" not in message


def test_invalid_schema_plan_gets_one_repair_attempt(monkeypatch):
    from llmwiki.synthesis_planner import SynthesisPlanningOptions, plan_synthesis_writeback

    root = seed_workspace()
    invalid = plan_payload(
        schema_version="1.0",
        status="success",
        target_page_id="wiki/syntheses/RAG Citation Anchors",
        sections=[
            {
                "heading": "Answer",
                "content": "RAG answers need citation anchors.",
                "evidence_ids": ["clm_rag_anchor"],
            }
        ],
    )
    valid = plan_payload()
    calls = patch_sequence_provider(monkeypatch, [invalid, valid])

    plan = plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())

    assert plan.schema_version == "synthesis_plan.v2.8"
    assert plan.status == "planned"
    assert plan.action == "create"
    assert len(calls) == 2
    repair_prompt = calls[1][-1]["content"]
    assert "synthesis_plan.v2.8" in repair_prompt
    assert "planned" in repair_prompt
    assert "needs_review" in repair_prompt
    assert "Original invalid output" in repair_prompt


def test_synthesis_plan_repair_failure_returns_sanitized_error(monkeypatch):
    from llmwiki.synthesis_planner import (
        SynthesisPlanningError,
        SynthesisPlanningOptions,
        plan_synthesis_writeback,
    )

    root = seed_workspace()
    calls = patch_sequence_provider(
        monkeypatch,
        [
            plan_payload(schema_version="1.0", status="success"),
            plan_payload(schema_version="1.0", status="success"),
        ],
    )

    with pytest.raises(SynthesisPlanningError) as excinfo:
        plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())

    assert len(calls) == 2
    assert "Invalid synthesis plan schema_version" in str(excinfo.value)


def test_invalid_relationship_type_gets_schema_repair(monkeypatch):
    from llmwiki.synthesis_planner import SynthesisPlanningOptions, plan_synthesis_writeback

    root = seed_workspace()
    invalid = plan_payload(
        relationships=[
            {
                "subject_id": "synthesis-rag-citation-anchors",
                "object_id": "clm_rag_anchor",
                "relationship_type": "",
                "evidence_claim_id": "clm_rag_anchor",
                "source_id": "src_doc",
            }
        ]
    )
    valid = plan_payload()
    calls = patch_sequence_provider(monkeypatch, [invalid, valid])

    plan = plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())

    assert plan.relationships[0].relationship_type == "supports"
    assert len(calls) == 2
    repair_prompt = calls[1][-1]["content"]
    assert "relationship_type must be one of" in repair_prompt
    assert "supports" in repair_prompt
    assert "refines" in repair_prompt


def test_related_page_object_gets_schema_repair(monkeypatch):
    from llmwiki.synthesis_planner import SynthesisPlanningOptions, plan_synthesis_writeback

    root = seed_workspace()
    invalid = plan_payload(
        related_pages=[
            {
                "page_id": "src_doc",
                "path": "wiki/sources/src_doc.md",
                "relationship_type": "similar_to",
            }
        ]
    )
    valid = plan_payload()
    calls = patch_sequence_provider(monkeypatch, [invalid, valid])

    plan = plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())

    assert plan.related_pages == ["wiki/sources/src_doc.md"]
    assert len(calls) == 2
    repair_prompt = calls[1][-1]["content"]
    assert "related_pages must be an array of existing page path strings" in repair_prompt


def test_blank_relationship_endpoints_get_schema_repair(monkeypatch):
    from llmwiki.synthesis_planner import SynthesisPlanningOptions, plan_synthesis_writeback

    root = seed_workspace()
    invalid = plan_payload(
        relationships=[
            {
                "subject_id": "",
                "object_id": "",
                "relationship_type": "similar_to",
                "evidence_claim_id": "",
                "source_id": "src_doc",
            }
        ]
    )
    valid = plan_payload()
    calls = patch_sequence_provider(monkeypatch, [invalid, valid])

    plan = plan_synthesis_writeback(root, ask_result(), SynthesisPlanningOptions())

    assert plan.relationships[0].subject_id == "synthesis-rag-citation-anchors"
    assert plan.relationships[0].object_id == "clm_rag_anchor"
    assert len(calls) == 2
    repair_prompt = calls[1][-1]["content"]
    assert "subject_id and object_id must be existing catalog identifiers" in repair_prompt
