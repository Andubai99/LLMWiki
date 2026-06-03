# LLMWiki V2.7 Reranking + Evidence Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: write failing tests first, implement, verify, then commit.

**Goal:** Add reranking and evidence selection after V2.6 hybrid/vector recall so `retrieve`, `query`, `ask`, and retrieval eval return more focused, diverse, citation-backed evidence.

**Architecture:** `HybridRetriever candidate pool -> Reranker -> EvidenceSelector -> retrieve_context contexts -> query/ask/eval`.

**Tech Stack:** Python stdlib, SQLite catalog, existing local JSONL vector index, pytest.

---

## Tasks

- [x] Add reranker failing tests and implement `llmwiki/rerankers.py`.
- [x] Add evidence selector failing tests and implement `llmwiki/evidence_selection.py`.
- [x] Integrate reranking and evidence selection into `retrieve_context`.
- [x] Keep `query` as a human-readable `retrieve` view with rerank/selection metadata.
- [x] Preserve planned retrieval subquery provenance and coverage-aware merge.
- [x] Extend retrieval eval metrics and add `tests/evals/retrieval_v2_7_evidence_selection_fruits.jsonl`.
- [x] Add `[reranking]` defaults to repo config and new workspace config.
- [x] Update README and AGENTS contract for V2.7.
- [ ] Run full verification and final cleanup.

## Acceptance

- `retrieve_context` returns `schema_version = "retrieval.v2.7"`.
- Returned contexts keep existing evidence fields and add `candidate_rank`, `rerank_score`, `selection_reason`, `coverage_group`, and `redundancy_group`.
- Reranker/selector never create evidence; claim/source/page/locator/relationship data still come from the local catalog.
- Default reranking may use local embedding provider and vector index, but chat LLM reranking remains opt-in and disabled by default.
- Missing vector index/key/provider falls back to deterministic reranking.
- Eval keeps `eval.retrieval.v2.3` outer schema compatibility and adds V2.7 ranking/selection metrics.
