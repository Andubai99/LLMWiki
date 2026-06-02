# LLMWiki V2.9.6 MinerU Operational Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: write failing tests first, verify failure, implement, verify pass, then commit. Split commits by feature/function.

**Goal:** Make MinerU auto parsing more reliable in local workspaces: discover workspace-local MinerU executables, preserve complete sanitized MinerU failure diagnostics when auto falls back to pypdf, and expose parser backend status through status, lint, pdf-quality, staging, and source pages.

**Architecture:** Add command discovery and command-source tracking in `mineru_runner`; preserve parser attempts through backend errors and PDF metadata; render those attempts through staging/source page/lint/pdf-quality/status. Downstream blocks, chunks, LLM ingest, retrieval, and ask evidence contracts remain unchanged.

**Tech Stack:** Python stdlib, existing parser backend layer, existing sidecar metadata, pytest monkeypatch providers, existing CLI/staging/apply/catalog pipeline.

## Implementation Tasks

### Task 1: Save The Plan

- [ ] Create this plan file.
- [ ] Run `git status --short`; expect only this plan file.
- [ ] Commit: `docs: 保存 V2.9.6 执行计划`.

### Task 2: MinerU Command Discovery Tests

- [ ] Extend `tests/test_mineru_runner.py` and `tests/test_parser_status_cli.py`.
- [ ] Cover explicit absolute command priority, PATH discovery, workspace `.venv\Scripts\mineru.exe`, POSIX `.venv/bin/mineru`, not-found status, `parser_status.v2.9.6`, command source, warnings, and read-only status behavior.
- [ ] Run and confirm failure:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_mineru_runner.py tests/test_parser_status_cli.py -q`
- [ ] Commit: `test: 覆盖 MinerU 本地命令发现`.

### Task 3: Workspace-Local MinerU Discovery

- [ ] Add `MinerUDiscoveryResult` and `discover_mineru_command(root, config)` in `llmwiki/mineru_runner.py`.
- [ ] Use command sources: `configured_path`, `PATH`, `workspace_venv`, `repo_venv`, `not_found`.
- [ ] Update `MinerUBackend.available(...)` and `llmwiki parsers status` to use discovery.
- [ ] Upgrade parser status JSON schema to `parser_status.v2.9.6`.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_mineru_runner.py tests/test_parser_status_cli.py tests/test_pdf_parser_backends.py -q`
  - `.\.venv\Scripts\python.exe -m llmwiki parsers status --root . --json`
- [ ] Commit: `feat: 增加 workspace-local MinerU 发现`.

### Task 4: Use Resolved MinerU Executable

- [ ] Extend `tests/test_mineru_runner.py` and `tests/test_add_source.py`.
- [ ] Cover `build_mineru_command(...)` using the resolved command, command source storage, `shell=False`, explicit pypdf not invoking MinerU, and explicit mineru strict failure.
- [ ] Add `resolved_command` and `command_source` to `MinerUCommandRequest`.
- [ ] Ensure command diagnostics remain sanitized and bounded.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_mineru_runner.py tests/test_add_source.py -q`
- [ ] Commit: `feat: 让 MinerU 命令使用发现结果`.

### Task 5: Parser Attempt Diagnostics Tests

- [ ] Extend `tests/test_pdf_parser_backends.py`, `tests/test_add_source.py`, and `tests/test_add_pipeline.py`.
- [ ] Cover auto MinerU nonzero, timeout, missing content list, explicit mineru hard failure, V2.9.5 metadata compatibility, and secret-safe bounded attempts.
- [ ] Run and confirm failure:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_parser_backends.py tests/test_add_source.py tests/test_add_pipeline.py -q`
- [ ] Commit: `test: 覆盖 parser attempt 诊断`.

### Task 6: Preserve Parser Attempts Through Fallback

- [ ] Add `parser_backend_attempts: list[dict]` to `SourceMetadata` with backward-compatible loading.
- [ ] Let `PdfParserBackendError` carry attempts.
- [ ] Build failed MinerU attempts for command failure, timeout, missing content list, and invalid content list.
- [ ] Build successful attempts for MinerU and pypdf.
- [ ] In auto fallback, persist failed MinerU attempts plus successful pypdf attempt in final metadata while preserving legacy fallback fields.
- [ ] Attempt fields include `backend`, `status`, `command_invoked`, `command`, `command_source`, `returncode`, `timed_out`, `duration_seconds`, `stdout_snippet`, `stderr_snippet`, `content_list_candidates`, `content_list_discovery_count`, `failure_stage`, `failure_reason`, and `warnings`.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_parser_backends.py tests/test_add_source.py tests/test_add_pipeline.py -q`
- [ ] Commit: `feat: 保留 PDF parser attempt 诊断`.

### Task 7: Expose Attempts In Staging, Review, And Source Pages

- [ ] Extend `tests/test_ingest_review.py` and `tests/test_add_pipeline.py`.
- [ ] Cover `run.json` attempt summary, `triage.md` attempt summary, source page fallback/attempt summary, and secret-safe `review --detail`.
- [ ] Update `llmwiki/ingest.py` to read and render `parser_backend_attempts`.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ingest_review.py tests/test_add_pipeline.py -q`
- [ ] Commit: `feat: 在 staging 中暴露 parser attempt 诊断`.

### Task 8: Extend pdf-quality Eval And Lint

- [ ] Extend `tests/test_pdf_quality_eval.py` with MinerU discovery/attempt/fallback metrics.
- [ ] Extend `tests/test_pdf_lint.py` for fallback without attempt diagnostics, secret snippets, and complete fallback diagnostics.
- [ ] Update `llmwiki/pdf_quality.py` and `llmwiki/lint.py` to read metadata sidecars only; do not run MinerU, LLM, embedding, or write workspace files.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_quality_eval.py tests/test_pdf_lint.py tests/test_query_lint_doctor.py -q`
- [ ] Commit: `feat: 扩展 MinerU fallback 质量检查`.

### Task 9: Retrieval And Ask Regression

- [ ] Extend `tests/test_retrieval.py`, `tests/test_ask_workflow.py`, and `tests/test_retrieval_eval.py`.
- [ ] Cover fallback PDF page/block locator retrieval, parser diagnostics not returned as evidence, ask citation validation, and no MinerU/LLM calls in retrieval eval.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_ask_workflow.py tests/test_retrieval_eval.py -q`
- [ ] Commit: `test: 固定 V2.9.6 检索回归`.

### Task 10: Documentation And Agent Contract

- [ ] Update README and AGENTS with workspace-local MinerU discovery, no PATH mutation, no auto install, visible fallback attempts, and read-only parser status.
- [ ] Update docs regression assertions.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_regression_samples.py -q`
- [ ] Commit: `docs: 更新 V2.9.6 MinerU 运行诊断说明`.

### Task 11: Real PDF Acceptance

- [ ] Create `.tmp\papers-v296-mineru-hardening` and copy local ignored API keys into it.
- [ ] Verify status without manually adding `.venv\Scripts` to PATH.
- [ ] Add at least three PDFs from `docs\papers`: `2506.16042.pdf`, `2508.03923.pdf`, and `2406.08184.pdf`.
- [ ] Run lint, pdf-quality eval, and PDF foundation retrieval eval.
- [ ] Confirm workspace-local MinerU discovery or safe not-found report; visible fallback diagnostics; strict explicit MinerU failure; no secret leakage; no parser artifacts as evidence.
- [ ] Commit sanitized acceptance note only if useful: `test: 记录 V2.9.6 MinerU 验收结果`.

### Task 12: Final Verification And Cleanup

- [ ] Run grouped tests:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_mineru_runner.py tests/test_parser_status_cli.py tests/test_pdf_parser_backends.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_add_source.py tests/test_add_pipeline.py tests/test_ingest_review.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_lint.py tests/test_pdf_quality_eval.py tests/test_regression_samples.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_ask_workflow.py tests/test_retrieval_eval.py -q`
- [ ] Run full verification:
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `.\.venv\Scripts\python.exe -m llmwiki --help`
  - `.\.venv\Scripts\python.exe -m llmwiki parsers status --root . --json`
  - `.\.venv\Scripts\python.exe -m llmwiki eval pdf-quality --root . --json`
- [ ] Clean generated files and confirm `git status --short` contains no secrets or generated source/wiki/staging/state/vector files.
- [ ] Commit any remaining repo changes by feature/function, or explicitly list blockers.

## Assumptions And Defaults

- No SQLite tables, page types, or evidence-contract changes.
- `parser_backend_attempts` live in generated PDF metadata sidecars and staging diagnostics only.
- V2.9.5 flat metadata fields stay backward-compatible.
- No MinerU auto-installation, no PATH mutation, and no `.venv` commit.
- Explicit `--parser pypdf` never invokes MinerU.
- Explicit `--parser mineru` never falls back.
- Auto fallback only falls back to pypdf and must stay visible.
- Parser logs/snippets are diagnostics, not source evidence.
