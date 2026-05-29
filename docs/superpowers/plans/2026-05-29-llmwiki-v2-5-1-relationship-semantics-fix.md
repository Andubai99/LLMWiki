# LLMWiki V2.5.1 Relationship Semantics Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: failing tests first, then implementation, verification, and commits.

**Goal:** Fix `contradicts` semantics so negative, cautionary, or limiting claims do not automatically become contradiction relationships.

**Architecture:** The fix belongs at relationship creation time, not retrieval display time. Ingest will preserve possible conflict notes in triage, but formal `contradicts` relationships must come from explicit relationships, not negation keyword heuristics. Retrieval, query, ask, and eval keep exposing real catalog relationships.

**Tech Stack:** Python, SQLite catalog, pytest, existing LLMWiki CLI workflow.

---

## Summary

V2.5.1 changes the relationship model so `contradicts` means source-backed disagreement between claims. It disables rule-based negation conflict detection in ingest and lint, keeps explicit contradiction fixtures visible, and updates documentation to distinguish negative/caution claims from contradictory evidence.

## Implementation Tasks

### Task 1: Add failing relationship semantics tests

**Files:**
- Create: `tests/test_relationship_semantics.py`

- [ ] Write tests showing ordinary negative/caution claims do not produce conflict candidates.
- [ ] Write tests showing LLM `conflict_candidates` stay in triage/open questions and do not become formal `contradicts` relationships.
- [ ] Write tests showing lint no longer infers unresolved contradictions from `require` versus `do not require`.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest tests/test_relationship_semantics.py -q` and verify failure before implementation.
- [ ] Commit with `test: 覆盖关系语义修复`.

### Task 2: Stop rule-based contradiction creation in ingest

**Files:**
- Modify: `llmwiki/ingest.py`
- Test: `tests/test_relationship_semantics.py`, `tests/test_ingest_review.py`

- [ ] Make `find_conflict_candidates(root, claims)` return no heuristic candidates.
- [ ] Stop converting `conflict_candidates` into `contradicts` rows in `build_relationships`.
- [ ] Keep conflict text visible in source/concept/entity pages and triage.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest tests/test_relationship_semantics.py tests/test_ingest_review.py -q`.
- [ ] Commit with `fix: 停用规则式矛盾生成`.

### Task 3: Update lint contradiction semantics

**Files:**
- Modify: `llmwiki/lint.py`
- Modify: `tests/test_regression_samples.py`

- [ ] Make `unresolved_potential_contradictions(conn)` return `0` in V2.5.1.
- [ ] Update lint regression assertions so `require` versus `do not require` is not inferred as unresolved contradiction.
- [ ] Preserve recorded `contradicts` relationship reporting.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest tests/test_relationship_semantics.py tests/test_regression_samples.py -q`.
- [ ] Commit with `fix: 调整 lint 矛盾语义`.

### Task 4: Preserve explicit contradiction retrieval/eval

**Files:**
- Modify: `tests/test_retrieval.py`
- Modify: `tests/test_retrieval_eval.py`
- Modify: `tests/test_regression_samples.py`

- [ ] Update retrieval contradiction tests to seed explicit catalog `contradicts` relationships.
- [ ] Update retrieval eval setup to seed explicit contradictions for existing contradiction eval cases.
- [ ] Remove assertions that ordinary ingest of `regression_conflict.md` or `zh_conflict.md` automatically creates contradictions.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest tests/test_retrieval.py tests/test_retrieval_eval.py tests/test_regression_samples.py -q`.
- [ ] Commit with `test: 使用显式矛盾关系固定检索回归`.

### Task 5: Update docs and agent contract

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] Document that `contradicts` means source-backed claim disagreement.
- [ ] Document that negative/caution claims are not contradictions by themselves.
- [ ] Document that retrieval exposes catalog relationships but does not classify text as contradictory.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest tests/test_regression_samples.py::test_docs_describe_v1_commands_and_constraints -q`.
- [ ] Commit with `docs: 更新关系语义说明`.

### Task 6: Real fruit acceptance

- [ ] Clean generated wiki/source/staging/state artifacts without deleting `docs/tests` or user-authored source docs.
- [ ] Reinitialize and run `llmwiki add` for all five `docs/tests` documents.
- [ ] Verify negative/caution claims still exist.
- [ ] Verify `contradicts` relationships are not broadly created.
- [ ] Run representative `ask` questions and confirm ordinary negative evidence does not trigger `Contradictory evidence is present`.
- [ ] Clean `.test-workspaces` and generated artifacts after acceptance.

### Task 7: Final verification

- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest tests/test_relationship_semantics.py -q`.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest tests/test_retrieval.py tests/test_retrieval_eval.py tests/test_regression_samples.py tests/test_query_lint_doctor.py -q`.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest tests/test_ask_workflow.py -q`.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m pytest -q`.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_3.jsonl`.
- [ ] Run `.\\.venv\\Scripts\\python.exe -m llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_4_fruits.jsonl`.
- [ ] Confirm `git status --short` has no generated wiki/source/staging/state/config secret files.
- [ ] Commit any remaining tracked changes with `fix: 完成 V2.5.1 关系语义修复`.

## Assumptions

- No database migration in V2.5.1.
- No LLM relationship classifier in V2.5.1.
- `retrieve`, `query`, and `eval retrieval` remain local and deterministic.
- `ask` remains planner-first and may call the configured LLM, but answer citations still come only from retrieved local evidence.
- Explicit contradiction fixtures use catalog or staged relationships, not text keyword triggers.
