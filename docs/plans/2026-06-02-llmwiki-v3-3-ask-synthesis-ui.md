# LLMWiki V3.3 Ask And Synthesis UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: write failing tests first, verify failure, implement, verify pass, then commit by feature/function.

**Goal:** Add the UI research loop: ask a question, display answer/citations/evidence/planning diagnostics, preview synthesis writeback, and explicitly apply synthesis through existing staging/apply code.

**Architecture:** Extend the V3.2 local UI service and `state/ui-jobs/` job model. UI POST routes enqueue jobs; worker dispatch calls existing `answer_question(...)`, `plan_synthesis_writeback(...)`, and `create_synthesis_run(...)`. UI code must not reimplement retrieval, citation validation, synthesis validation, staging, or apply.

**Tech Stack:** Python stdlib HTTP server, JSON job files, existing `src/llmwiki` domain APIs, static HTML/CSS/vanilla JS, pytest monkeypatch tests.

---

## Summary

V3.3 adds the research loop to the local UI:

- API schema becomes `ui.v3.3`; UI job schema becomes `ui_job.v3.3`.
- Reuse `state/ui-jobs/`; no SQLite schema changes.
- Keep `UiJob.status` generic: `pending/running/applied/failed/interrupted`.
- Store domain status in `job.result.answer_status`, `job.result.preview_status`, or `job.result.writeback_status`.
- Add job types: `ask_question`, `synthesis_preview`, `synthesis_writeback`.
- All ask/synthesis POST routes require `X-LLMWiki-UI-Token`.
- Preview is read-only and must not create staging/wiki/catalog changes.
- Writeback only happens after explicit UI action and only via `create_synthesis_run(...)`.
- Tests monkeypatch LLM-facing APIs; no real DeepSeek, embedding, MinerU, or network.

## Implementation Tasks

### Task 1: Save Plan

- [ ] Create this file at `docs/plans/2026-06-02-llmwiki-v3-3-ask-synthesis-ui.md`.
- [ ] Run `git status --short`; expect only this plan file.
- [ ] Commit: `docs: 保存 V3.3 执行计划`.

### Task 2: Ask Request Models And Validation

- [ ] Create `tests/test_ui_ask_actions.py` with failing tests for empty question, control characters, invalid `limit`, invalid `confidence`, default `limit=8`, preserved filters, and sanitized validation errors.
- [ ] Create `src/llmwiki/ui/ask_models.py`.
- [ ] Create `src/llmwiki/ui/ask_actions.py` with `AskUiActionError`, `AskUiRequest`, `validate_ask_request(root, payload)`, and `enqueue_ask_job(root, payload, job_manager)`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_ask_actions.py -q`.
- [ ] Commit: `feat: 增加 UI ask action 校验`.

### Task 3: Extend UI Job Schema To V3.3

- [ ] Extend `tests/test_ui_jobs.py` for `ui_job.v3.3`, backward-compatible V3.2 load, ask job persistence, synthesis preview/writeback job persistence, and malformed job warnings.
- [ ] Modify `src/llmwiki/ui/jobs.py`: set `UI_JOB_SCHEMA_VERSION = "ui_job.v3.3"`, add `question`, `ask_options`, `parent_job_id`, `writeback_mode`, and helpers `create_ask_job`, `create_synthesis_preview_job`, `create_synthesis_writeback_job`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_jobs.py tests/test_ui_ask_actions.py -q`.
- [ ] Commit: `feat: 扩展 UI job schema 到 V3.3`.

### Task 4: Ask Worker Bridge

- [ ] Extend `tests/test_ui_ask_actions.py` so `run_ask_job` calls `answer_question(...)` once, persists answered/planned-insufficient/LLM-failed/invalid-citation statuses, and sanitizes failures.
- [ ] Implement `run_ask_job(root, job)` and compact `AskResult` serialization in `src/llmwiki/ui/ask_actions.py`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_ask_actions.py tests/test_ui_jobs.py -q`.
- [ ] Commit: `feat: 增加 UI ask job worker`.

### Task 5: Ask API Endpoints

- [ ] Create `tests/test_ui_ask_api.py` for token-required `POST /api/ask`, `GET /api/ask/jobs`, `GET /api/ask/jobs/<job-id>`, `/api/session.supported_actions`, invalid JSON, no permissive CORS, and sanitized errors.
- [ ] Modify `src/llmwiki/ui/models.py`: set `UI_SCHEMA_VERSION = "ui.v3.3"` and extend `JobSummary`.
- [ ] Modify `src/llmwiki/ui/api.py`: add `list_ask_jobs(root, limit=50)` and `get_ask_job(root, job_id)`.
- [ ] Modify `src/llmwiki/ui/server.py`: route ask GET/POST and update supported actions.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_ask_api.py tests/test_ui_server_actions.py tests/test_ui_api.py -q`.
- [ ] Commit: `feat: 增加 UI ask HTTP API`.

### Task 6: Synthesis Preview Action

- [ ] Create `tests/test_ui_synthesis_actions.py` for preview requiring an answered ask job, rejecting non-answered ask jobs, calling `plan_synthesis_writeback(...)`, storing plan/preview text, preserving `needs_review`, sanitizing planner failures, and not mutating workspace files.
- [ ] Implement `SynthesisPreviewRequest`, validation, enqueue helper, and `run_synthesis_preview_job(...)` in `src/llmwiki/ui/ask_actions.py`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_synthesis_actions.py tests/test_ui_ask_actions.py -q`.
- [ ] Commit: `feat: 增加 synthesis preview UI job`.

### Task 7: Synthesis Preview API

- [ ] Extend/create `tests/test_ui_synthesis_api.py` for token-required `POST /api/ask/<job-id>/synthesis/preview`, unknown ask job `404`, non-answered ask `400`, valid preview job queueing, and sanitized responses.
- [ ] Modify `src/llmwiki/ui/server.py` to route synthesis preview POST.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_synthesis_api.py tests/test_ui_ask_api.py -q`.
- [ ] Commit: `feat: 增加 synthesis preview HTTP API`.

### Task 8: Synthesis Writeback Action

- [ ] Extend `tests/test_ui_synthesis_actions.py` for writeback requiring answered ask, valid preview job, `needs_review` prevention, `create_synthesis_run(...)` invocation, persisted run/page/action result, `SynthesisWritebackError` handling, and no direct wiki/catalog writes by UI code.
- [ ] Implement `SynthesisWritebackRequest`, validation, enqueue helper, and `run_synthesis_writeback_job(...)` in `src/llmwiki/ui/ask_actions.py`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_synthesis_actions.py -q`.
- [ ] Commit: `feat: 增加 synthesis writeback UI job`.

### Task 9: Synthesis Writeback API

- [ ] Extend `tests/test_ui_synthesis_api.py` for token-required `POST /api/ask/<job-id>/synthesis/writeback`, invalid `writeback_mode`, missing preview job, valid writeback job queueing, and `ui.v3.3`.
- [ ] Modify `src/llmwiki/ui/server.py` to route synthesis writeback POST.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_synthesis_api.py tests/test_ui_server_actions.py -q`.
- [ ] Commit: `feat: 增加 synthesis writeback HTTP API`.

### Task 10: Static Ask UI

- [ ] Extend `tests/test_ui_static.py` for ask form, question textarea, limit input, answer panel, citations table, evidence table, planning diagnostics panel, synthesis panel, ask/synthesis endpoints in JS, token header, escaping, and no secret markers.
- [ ] Modify `src/llmwiki/ui/static/index.html`, `app.js`, and `styles.css`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_static.py tests/test_ui_ask_api.py tests/test_ui_synthesis_api.py -q`.
- [ ] Commit: `feat: 增加 Ask 与 Synthesis UI`.

### Task 11: Read/Write Boundary Tests

- [ ] Extend `tests/test_ui_readonly.py`: GET `/api/ask/jobs` and `/api/ask/jobs/<id>` are read-only and do not call LLM/provider/runtime work.
- [ ] Extend `tests/test_ui_mutation_boundary.py`: `POST /api/ask` only creates UI job before worker; preview does not mutate workspace; writeback mutates only through monkeypatched `create_synthesis_run`; UI server/action layer never directly calls `apply_run`, `ingest_source`, or writes catalog/wiki.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_readonly.py tests/test_ui_mutation_boundary.py -q`.
- [ ] Commit: `test: 固定 V3.3 UI ask synthesis 边界`.

### Task 12: CLI/Server Lifecycle Regression

- [ ] Extend `tests/test_ui_cli.py` and `tests/test_ui_server.py` so `llmwiki ui --root . --no-open` starts with a dispatcher supporting `add_source`, `ask_question`, `synthesis_preview`, `synthesis_writeback`, and does not call ask/synthesis before POST.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ui_cli.py tests/test_ui_server.py tests/test_scaffold.py -q`.
- [ ] Run `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki --help`.
- [ ] Commit: `test: 固定 V3.3 UI server lifecycle`.

### Task 13: Documentation And Agent Contract

- [ ] Update `README.md` with V3.3 Ask And Synthesis UI, `POST /api/ask`, preview/writeback, and `ui.v3.3`.
- [ ] Update `AGENTS.md` so UI ask can call `answer_question` only after token-protected POST, preview is read-only, writeback only uses `create_synthesis_run`, and planner/synthesis output is not evidence.
- [ ] Update `tests/test_regression_samples.py`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_regression_samples.py -q`.
- [ ] Commit: `docs: 更新 V3.3 ask synthesis UI 说明`.

### Task 14: Verification And Smoke

- [ ] Run grouped tests:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_ask_actions.py tests/test_ui_ask_api.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_synthesis_actions.py tests/test_ui_synthesis_api.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_static.py tests/test_ui_readonly.py tests/test_ui_mutation_boundary.py tests/test_ui_cli.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_add_pipeline.py tests/test_ask_workflow.py tests/test_retrieval.py -q`
- [ ] Run full verification:
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki --help`
- [ ] Run manual smoke in a temp workspace with monkeypatched or deterministic ask/synthesis calls.
- [ ] Clean generated files:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki clean --scope all --root .`
  - `git status --short --ignored`
- [ ] Confirm no tracked or unwanted generated files remain.
- [ ] Commit any final functional remainder if needed: `feat: 完成 V3.3 ask synthesis UI`.

## Test Scenarios

- Empty ask rejected before worker.
- Valid ask queues job and returns immediately.
- Ask worker stores answered result with citations and contexts.
- Planned insufficient evidence is visible and not treated as HTTP failure.
- LLM/provider/invalid citation failures are sanitized.
- Planner diagnostics are shown but not evidence.
- Synthesis preview requires answered ask and is read-only.
- Synthesis writeback requires explicit POST and uses existing staging/apply path.
- `needs_review` prevents writeback.
- GET routes remain read-only.
- POST ask/preview/writeback require token.
- Existing V3.2 source add job flow still passes.
- No tests require real DeepSeek, embedding provider, MinerU, or network.

## Assumptions

- V3.3 does not introduce chat history or multi-turn sessions.
- V3.3 uses JSON files under `state/ui-jobs/`, not SQLite.
- V3.3 keeps one FIFO worker and no parallel workspace mutations.
- Ask/synthesis POSTs may call configured LLM through existing domain APIs only when the worker runs.
- Preview is a separate job and does not write staging/wiki/catalog.
- Writeback is a separate job and writes only through `create_synthesis_run`.
- No new retrieval, planner, synthesis, PDF, or relationship intelligence behavior is added.

