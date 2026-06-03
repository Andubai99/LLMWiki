# LLMWiki V2.1 Autonomous Add Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `llmwiki add <source> --root .` import, ingest, validate, apply, and summarize a single source without requiring manual `ingest`, `review`, or `apply`.

**Architecture:** Add a focused pipeline orchestration module that reuses the current source import, ingest, and apply primitives. The CLI delegates `add` to this pipeline while keeping `ingest`, `review`, and `apply` as visible internal/debug commands.

**Tech Stack:** Python standard library, SQLite catalog, pytest, current LLM provider abstraction.

---

### Task 1: Autonomous Add Tests

**Files:**
- Create: `tests/test_add_pipeline.py`
- Modify: `tests/test_add_source.py`

- [ ] Write tests showing `llmwiki add` imports, creates an LLM-backed staging run, applies wiki pages, updates catalog/index/log, and reports source/run/count/page details.
- [ ] Write tests showing duplicate already-applied sources do not create a second run or duplicate pages.
- [ ] Write tests showing missing LLM configuration and apply failures do not leak secrets and do not leave partial wiki mutations.
- [ ] Move import-only expectations to direct `import_source` tests.

### Task 2: Pipeline Module

**Files:**
- Create: `llmwiki/pipeline.py`
- Modify: `llmwiki/ingest.py`
- Modify: `llmwiki/apply.py`

- [ ] Add `AddPipelineResult` and `AddPipelineError`.
- [ ] Implement `add_and_process_source(root, locator)` as `import_source -> ingest_source(require_llm=True, trigger="add") -> apply_run -> summary`.
- [ ] Treat duplicate sources with an applied ingest run as already up to date.
- [ ] Mark existing run manifests failed when ingest/apply has produced a run and then fails.
- [ ] Add `require_llm` and `trigger` support to `ingest_source`.

### Task 3: CLI Switch

**Files:**
- Modify: `llmwiki/cli.py`

- [ ] Change `cmd_add` to call the pipeline.
- [ ] Print the V2.1 success, duplicate, and failure output shapes.
- [ ] Label `ingest`, `review`, and `apply` help text as internal/debug.

### Task 4: Test Helper Migration

**Files:**
- Modify: `tests/test_query_lint_doctor.py`
- Modify: `tests/test_llm_ingest.py`
- Modify regression tests as needed.

- [ ] Replace helper use of public `add` for import-only setup with `import_source`.
- [ ] Keep `ingest`, `review`, and `apply` test coverage intact for debug workflows.
- [ ] Add a review test for an auto-applied run.

### Task 5: Documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] Document `llmwiki add docs/example.md --root .` as the primary import workflow.
- [ ] Move `ingest`, `review`, and `apply` into advanced/internal debug documentation.
- [ ] Keep `lint` documented as a separate user-requested maintenance command.

### Task 6: Verification

- [ ] Run `python -m pytest tests/test_add_pipeline.py -q`.
- [ ] Run `python -m pytest tests/test_add_source.py tests/test_ingest_review.py tests/test_apply_workflow.py -q`.
- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m llmwiki --help`.
- [ ] Commit only tracked source, test, plan, and documentation changes.
