# LLMWiki V2.4 Hybrid Local Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: write failing tests first, verify failure, implement, verify pass, then commit.

**Goal:** Replace the ad hoc local retrieval implementation with deterministic hybrid retrieval that supports natural Chinese, mixed Unicode, formulas/symbols, catalog title/alias matching, graph expansion, and RRF fusion while preserving source-backed evidence contracts.

**Architecture:** Add query analysis and retriever modules behind the existing `retrieve_context(...)` API. Keep `retrieve`, `ask`, and eval evidence grounded in catalog claims; switch `query` to format `retrieve_context` instead of maintaining a separate weak search path.

**Tech Stack:** Python standard library, SQLite FTS5, pytest, existing LLMWiki CLI/catalog modules.

---

### Task 1: Query Analysis Tests

**Files:**
- Create: `tests/test_query_analysis.py`
- Later create: `llmwiki/query_analysis.py`

- [ ] Write failing tests for natural Chinese, full-width folding, formula spans, symbol spans, and emoji spans.
- [ ] Run `python -m pytest tests/test_query_analysis.py -q` and confirm the tests fail because `llmwiki.query_analysis` does not exist.

### Task 2: Unicode-Aware Query Analysis

**Files:**
- Create: `llmwiki/query_analysis.py`
- Test: `tests/test_query_analysis.py`

- [ ] Implement `RetrievalQuery`, `normalize_unicode`, and `analyze_query`.
- [ ] Use NFKC normalization, casefolding, conservative Chinese stop terms, deterministic expansions, catalog-term longest matching, CJK n-grams, and exact/formula/symbol span preservation.
- [ ] Run `python -m pytest tests/test_query_analysis.py -q`.
- [ ] Commit with `feat: 增加 Unicode 查询分析`.

### Task 3: Hybrid Retriever Tests

**Files:**
- Create: `tests/test_hybrid_retrieval.py`
- Later create: `llmwiki/retrievers.py`

- [ ] Add deterministic catalog seeding helpers.
- [ ] Write failing tests for BM25/FTS, catalog title/alias retrieval, exact/formula/symbol retrieval, graph expansion, RRF fusion, and filters.
- [ ] Run `python -m pytest tests/test_hybrid_retrieval.py -q` and confirm missing retriever classes fail.

### Task 4: Retriever Abstraction

**Files:**
- Create: `llmwiki/retrievers.py`
- Test: `tests/test_hybrid_retrieval.py`

- [ ] Implement `RetrievalFilters`, `RetrievalCandidate`, `RetrieverResult`, retriever classes, `HybridRetriever`, and `reciprocal_rank_fusion`.
- [ ] Run `python -m pytest tests/test_hybrid_retrieval.py tests/test_query_analysis.py -q`.
- [ ] Commit with `feat: 增加混合本地 retriever`.

### Task 5: Switch Retrieve To Hybrid

**Files:**
- Modify: `llmwiki/retrieval.py`
- Modify: `tests/test_retrieval.py`
- Modify: `tests/test_retrieval_eval.py`

- [ ] Load catalog terms, call `analyze_query`, run `HybridRetriever`, assemble V2.4 contexts and diagnostics.
- [ ] Preserve old retrieval fields and evidence-contract behavior.
- [ ] Update schema expectations to `retrieval.v2.4`.
- [ ] Run `python -m pytest tests/test_retrieval.py tests/test_retrieval_eval.py tests/test_hybrid_retrieval.py -q`.
- [ ] Commit with `feat: 将 retrieve 切换为混合检索`.

### Task 6: Switch Query To Retrieve

**Files:**
- Modify: `llmwiki/query.py`
- Modify: `tests/test_query_lint_doctor.py`
- Test: `tests/test_hybrid_retrieval.py`

- [ ] Make `query_context` call `retrieve_context`.
- [ ] Format claim id, source id, citation locator, page path, relationship type, score, and claim text.
- [ ] Add regression for `query "草莓应该怎么保存？"` with deterministic fruit catalog.
- [ ] Run `python -m pytest tests/test_query_lint_doctor.py tests/test_hybrid_retrieval.py -q`.
- [ ] Commit with `feat: 让 query 复用 retrieve`.

### Task 7: V2.4 Eval Datasets

**Files:**
- Create: `tests/evals/retrieval_v2_4_fruits.jsonl`
- Modify: `tests/test_retrieval_eval.py`

- [ ] Add fruit natural/comparison eval cases using source ids/page ids/expected terms.
- [ ] Add deterministic Unicode/formula eval coverage in tests.
- [ ] Assert V2.4 diagnostics include retriever and fusion information.
- [ ] Run `python -m pytest tests/test_retrieval_eval.py tests/test_hybrid_retrieval.py -q`.
- [ ] Commit with `test: 增加 V2.4 检索评测数据`.

### Task 8: Natural Chinese Ask Regression

**Files:**
- Modify: `tests/test_ask_workflow.py`

- [ ] Seed deterministic strawberry storage catalog.
- [ ] Monkeypatch `llmwiki.answer.create_provider`.
- [ ] Assert `llmwiki ask "草莓应该怎么保存？" --no-writeback --json` returns `answered`, calls provider, cites strawberry claims, and does not write synthesis pages.
- [ ] Run `python -m pytest tests/test_ask_workflow.py tests/test_hybrid_retrieval.py -q`.
- [ ] Commit with `test: 覆盖自然中文 ask 证据召回`.

### Task 9: Documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] Document hybrid local retrieval, query-as-retrieve, retrieval eval, no LLM calls in retrieval, and V2.5 boundary.
- [ ] Run `python -m pytest tests/test_regression_samples.py -q`.
- [ ] Commit with `docs: 更新 V2.4 检索说明`.

### Task 10: Final Verification

- [ ] Run `python -m pytest tests/test_query_analysis.py -q`.
- [ ] Run `python -m pytest tests/test_hybrid_retrieval.py tests/test_retrieval.py tests/test_retrieval_eval.py -q`.
- [ ] Run `python -m pytest tests/test_query_lint_doctor.py tests/test_ask_workflow.py -q`.
- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m llmwiki --help`.
- [ ] Run `python -m llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_3.jsonl`.
- [ ] If fruit catalog exists, run `retrieve`, `query`, and V2.4 eval against it.
- [ ] Confirm generated wiki/source/staging/state files are not staged.
