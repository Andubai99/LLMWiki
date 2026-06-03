# LLMWiki V2.3 Retrieval Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic retrieval evaluation layer that measures `retrieve_context` quality, evidence contract validity, and failure stages.

**Architecture:** Keep `retrieve` local and backward compatible while adding additive schema/diagnostics fields. Implement a separate `retrieval_eval` module that reads committed JSONL cases, calls `retrieve_context`, validates returned evidence against the catalog, calculates retrieval/evidence metrics, and exposes the result through `llmwiki eval retrieval`.

**Tech Stack:** Python standard library, SQLite catalog via existing `llmwiki.db`, pytest, existing CLI parser.

---

### Task 1: Retrieval Eval Tests And Seed Dataset

**Files:**
- Create: `tests/test_retrieval_eval.py`
- Create: `tests/evals/retrieval_v2_3.jsonl`

- [ ] Write failing tests for JSONL parsing, metrics, failure classification, CLI JSON/human output, and secret redaction.
- [ ] Add a small committed seed dataset using only existing fixtures and deterministic expectations.
- [ ] Run `python -m pytest tests/test_retrieval_eval.py -q` and confirm the tests fail because `llmwiki.retrieval_eval` and CLI support do not exist.

### Task 2: Retrieval Diagnostics

**Files:**
- Modify: `llmwiki/retrieval.py`
- Modify: `tests/test_retrieval.py`

- [ ] Add `schema_version="retrieval.v2.3"` and `diagnostics` to retrieval output without removing existing keys.
- [ ] Add `rank`, `confidence_status`, and `page_type` to each returned context.
- [ ] Update existing retrieval JSON tests to assert backward-compatible key presence instead of exact top-level key equality.
- [ ] Run `python -m pytest tests/test_retrieval.py -q`.

### Task 3: Retrieval Eval Core

**Files:**
- Create: `llmwiki/retrieval_eval.py`
- Test: `tests/test_retrieval_eval.py`

- [ ] Implement `RetrievalEvalCase`, `RetrievalEvalResult`, `RetrievalEvalSummary`, `load_eval_cases`, `evaluate_retrieval`, and `format_eval_report`.
- [ ] Compute hit@K, recall@K, precision@K, MRR, evidence contract metrics, and primary failure stage.
- [ ] Keep eval read-only against the workspace: do not write wiki, staging, sources, or catalog rows.
- [ ] Run `python -m pytest tests/test_retrieval_eval.py -q`.

### Task 4: CLI Integration

**Files:**
- Modify: `llmwiki/cli.py`
- Test: `tests/test_retrieval_eval.py`

- [ ] Add `eval` to the command list and parser.
- [ ] Add `llmwiki eval retrieval --root . --dataset <path> [--limit N] [--json]`.
- [ ] Return exit code `0` for successful eval execution even when cases fail, and `1` for runtime/data errors.
- [ ] Run `python -m pytest tests/test_retrieval_eval.py tests/test_scaffold.py -q`.

### Task 5: Documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] Document `llmwiki eval retrieval` as a development quality command.
- [ ] State that V2.3 eval does not call LLMs by default and does not write wiki/staging/source files.
- [ ] State that retrieval changes should run the eval suite before and after changes.

### Task 6: Verification And Commit

- [ ] Run `python -m pytest tests/test_retrieval_eval.py -q`.
- [ ] Run `python -m pytest tests/test_retrieval.py tests/test_query_lint_doctor.py tests/test_ask_workflow.py -q` using the project virtualenv.
- [ ] Run `python -m pytest -q` using the project virtualenv.
- [ ] Run `python -m llmwiki --help`.
- [ ] Run `python -m llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_3.jsonl`.
- [ ] Commit only source, test, dataset, docs, and plan files; do not commit generated workspace state or secrets.
