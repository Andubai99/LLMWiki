# LLMWiki V2.7.1 Selection, Planner Repair, Confidence Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: failing tests first, implement, verify, then commit.

**Goal:** Fix V2.7 regressions around focused evidence selection, planner invalid filter repair, and locator-backed claim confidence without adding new retrievers, storage, UI, or database tables.

**Architecture:** Keep `retrieve_context` as the public retrieval API. Add selection modes inside `evidence_selection`, pass mode hints from direct retrieval and planned retrieval, make planner validation errors repairable when schema-safe, and normalize LLM claim confidence before staged patches/catalog writes.

**Tech Stack:** Python standard library, SQLite catalog, existing pytest suite, existing LLM/embedding providers.

---

## Tasks

- [ ] Add failing evidence selection tests for `focused`, `comparison`, `conflict`, and selection diagnostics.
- [ ] Implement selection modes in `llmwiki/evidence_selection.py`.
- [ ] Wire selection mode inference through `llmwiki/retrieval.py` and focused per-subquery retrieval through `llmwiki/planned_retrieval.py`.
- [ ] Add planner repair tests for invalid `confidence="high"` and implement schema-specific repair prompts.
- [ ] Add LLM ingest tests for locator-backed confidence normalization and implement the normalization.
- [ ] Split lint weak evidence reporting into missing-locator issues and locator-backed inconsistencies.
- [ ] Fix V2.7 eval dataset boundaries so real fruit eval cases do not depend on synthetic weak/conflict fixtures.
- [ ] Update README and AGENTS with V2.7.1 behavior.
- [ ] Re-run real five-document acceptance and full tests, then clean generated artifacts.

## Verification

- `.\.venv\Scripts\python.exe -m pytest tests/test_evidence_selection.py tests/test_rerankers.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_planned_retrieval.py tests/test_ask_workflow.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests/test_planner.py tests/test_llm_ingest.py tests/test_query_lint_doctor.py tests/test_retrieval_eval.py -q`
- `.\.venv\Scripts\python.exe -m pytest -q`
- `.\.venv\Scripts\python.exe -m llmwiki --help`
- Real acceptance with the five `docs/tests` fruit documents when local API keys are available.
