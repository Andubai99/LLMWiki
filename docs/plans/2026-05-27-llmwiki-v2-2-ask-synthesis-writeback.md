# LLMWiki V2.2 Ask + Synthesis Writeback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `llmwiki ask "问题" --root .` so it retrieves local wiki/catalog evidence, asks the configured LLM for a citation-grounded answer, and optionally writes approved answers back as synthesis pages through staging/apply.

**Architecture:** Add a focused read-only answer layer over `retrieve_context`, then add a separate synthesis writeback layer that creates staged synthesis patches and reuses `apply_run`. Keep `retrieve` as the stable machine evidence API and keep `query` deterministic without LLM calls.

**Tech Stack:** Python standard library, SQLite catalog, existing LLM provider abstraction, pytest.

---

### Task 1: Ask Read-Only Tests

**Files:**
- Create: `tests/test_ask_workflow.py`
- Use: `tests/test_query_lint_doctor.py`

- [ ] Write tests for no matching evidence returning `insufficient_evidence` without calling the provider.
- [ ] Write tests for evidence retrieval, monkeypatched provider response, citation validation, and human output.
- [ ] Write tests for `--json` output without leaking `config/api-keys.toml` or key-like secrets.
- [ ] Write tests for unknown LLM `claim_id` returning `invalid_citations` and leaving `wiki/syntheses/` empty.
- [ ] Write tests proving non-interactive `ask` without `--writeback` does not write wiki files.
- [ ] Run `python -m pytest tests/test_ask_workflow.py -q` and verify these tests fail because `ask` does not exist.

### Task 2: Grounded Answer Layer

**Files:**
- Create: `llmwiki/answer.py`

- [ ] Add `AskOptions`, `AnswerCitation`, and `AskResult`.
- [ ] Implement `answer_question(root, question, options)` as `retrieve_context -> LLM JSON answer -> citation validation`.
- [ ] Return `status="insufficient_evidence"` without calling LLM when retrieval has no contexts.
- [ ] Build prompts containing only retrieved contexts, relationships, warnings, and answer constraints.
- [ ] Parse required LLM JSON fields: `short_answer`, `analysis`, `citations`, `uncertainties`, `conflicts`, `suggested_title`.
- [ ] Retry malformed JSON once with a repair prompt, then return `status="llm_failed"`.
- [ ] Validate every citation against retrieved `claim_id`, `source_id`, and `citation_locator`.
- [ ] Sanitize error text so secrets and key-like strings never appear in result output.
- [ ] Run `python -m pytest tests/test_ask_workflow.py -q` and verify read-only ask tests can pass once CLI is wired.

### Task 3: CLI Ask Read-Only Path

**Files:**
- Modify: `llmwiki/cli.py`

- [ ] Add `ask` to the command list and parser.
- [ ] Add flags: `--root`, `--limit`, `--json`, `--writeback`, `--no-writeback`, `--source-id`, `--page-type`, `--confidence`.
- [ ] Implement `cmd_ask` using `answer_question`.
- [ ] Human output includes `Question`, `Answer`, `Citations`, `Warnings`, and `Writeback`.
- [ ] JSON output includes `question`, `answer`, `status`, `citations`, `warnings`, and `writeback`.
- [ ] Non-interactive default skips writeback; `--no-writeback` always skips writeback.
- [ ] Run `python -m pytest tests/test_ask_workflow.py -q` and verify read-only tests pass.

### Task 4: Synthesis Writeback Tests

**Files:**
- Modify: `tests/test_ask_workflow.py`

- [ ] Add tests for `ask --writeback` creating a staging run and applying `wiki/syntheses/<slug>.md`.
- [ ] Assert synthesis frontmatter has `page_type=synthesis` and `claim_ids` from existing catalog claims.
- [ ] Assert required sections exist: `Question/Topic`, `Short Answer`, `Evidence`, `Analysis`, `Uncertainties`, `Related Pages`.
- [ ] Assert `wiki/index.md`, `wiki/log.md`, and catalog `pages` include the synthesis.
- [ ] Add apply-failure test showing run is marked failed and wiki/catalog do not keep partial mutations.
- [ ] Run `python -m pytest tests/test_ask_workflow.py -q` and verify writeback tests fail because synthesis writeback is not implemented.

### Task 5: Synthesis Writeback Layer

**Files:**
- Create: `llmwiki/synthesis.py`

- [ ] Add `SynthesisWritebackResult`.
- [ ] Implement `create_synthesis_run(root, ask_result)` for `AskResult(status="answered")` with at least one valid citation.
- [ ] Generate run ids as `run_answer_<timestamp>_<hash>`.
- [ ] Generate slugs from sanitized `suggested_title`, with question hash fallback.
- [ ] Write staging files: `run.json`, `claims.jsonl`, `triage.md`, and `patches/001-synthesis-<slug>.json`.
- [ ] Build synthesis patches with `action="upsert_page"`, `page_type="synthesis"`, target under `wiki/syntheses/`, synthetic `source_id="synthesis:<answer-id>"`, existing evidence `claim_ids`, and links to retrieved `page_path`.
- [ ] Call `apply_run(root, run_id)` for formal wiki/catalog writes.
- [ ] Mark run failed with `failed_stage="apply"` and `failure_reason` if apply fails.
- [ ] Run `python -m pytest tests/test_ask_workflow.py -q` and verify writeback tests pass after CLI wiring.

### Task 6: CLI Writeback Behavior

**Files:**
- Modify: `llmwiki/cli.py`

- [ ] `--writeback` immediately writes back valid answers through `create_synthesis_run`.
- [ ] Interactive mode without `--json` and without `--no-writeback` asks yes/no through a small confirmation helper.
- [ ] `--json` never prompts; only `--writeback` writes back.
- [ ] Writeback success output includes `Applied synthesis run` and `Page`.
- [ ] Writeback failure output preserves the answer and prints `Debug: llmwiki review <run-id> --detail --root .` when a run exists.
- [ ] Run `python -m pytest tests/test_ask_workflow.py -q`.

### Task 7: Documentation And Contract

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] Document `llmwiki ask "问题" --root .` as the V2.2 normal question workflow.
- [ ] Document `llmwiki ask "问题" --root . --writeback` for approved synthesis writeback.
- [ ] Clarify that `retrieve` is the machine evidence API and `query` remains deterministic local context.
- [ ] Clarify that `ask` may call LLM but must answer only from retrieved local evidence.
- [ ] Clarify that synthesis writeback must go through staging/apply and preserve weak/uncited/contradicting evidence.

### Task 8: Verification And Commit

- [ ] Run `python -m pytest tests/test_ask_workflow.py -q`.
- [ ] Run `python -m pytest tests/test_retrieval.py tests/test_query_lint_doctor.py -q`.
- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m llmwiki --help`.
- [ ] Confirm `.test-workspaces`, `.pytest_cache`, `config/api-keys.toml`, `state/catalog.sqlite`, and generated `wiki/syntheses/*.md` are not staged.
- [ ] Commit implementation with Chinese commit messages.
