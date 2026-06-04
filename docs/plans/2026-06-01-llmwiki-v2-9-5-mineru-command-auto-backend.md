# LLMWiki V2.9.5 MinerU Command + Auto Parser Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: failing tests first, implement, verify, then commit. Split commits by feature/function.

**Goal:** Make PDF import use an `auto` parser mode that tries MinerU command invocation first and visibly falls back to pypdf when MinerU is unavailable or fails.

**Architecture:** Add a MinerU command runner boundary, extend parser backend config/selection, keep pypdf as fallback, and store command/fallback diagnostics in PDF sidecars. Parser artifacts remain generated source artifacts; downstream ingest, staging, retrieval, and ask still consume normalized blocks/chunks and catalog-backed claims.

**Tech Stack:** Python stdlib `dataclasses/json/pathlib/subprocess/shutil`, existing parser backend abstraction, existing PDF metadata/block/chunk sidecars, pytest monkeypatching.

---

## Implementation Tasks

### Task 1: Save The Plan

- [ ] Create this plan at `docs/plans/2026-06-01-llmwiki-v2-9-5-mineru-command-auto-backend.md`.
- [ ] Run `git status --short`; expect only the plan file.
- [ ] Commit with `git commit -m "docs: 保存 V2.9.5 执行计划"`.

### Task 2: Config Defaults And Parser Status Tests

- [ ] Extend `tests/test_pdf_parser_backends.py` so new workspaces default to `default_backend="auto"`, `fallback_backend="pypdf"`, `mineru_enabled=true`, and can read MinerU command config fields.
- [ ] Add `tests/test_parser_status_cli.py` for `llmwiki parsers status --root .` and `--json`.
- [ ] Assert status is read-only and does not parse PDFs, call LLMs, call embeddings, run MinerU on a document, or write workspace files.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_parser_backends.py tests/test_parser_status_cli.py -q`; expected failure before implementation.
- [ ] Commit tests with `git commit -m "test: 覆盖 V2.9.5 parser 配置和状态命令"`.

### Task 3: Config Defaults And Parser Status Implementation

- [ ] Update `llmwiki/workspace.py::DEFAULT_CONFIG` and `llmwiki/pdf_parser_backends.py::PdfParserConfig` / `load_pdf_parser_config`.
- [ ] Add read-only `llmwiki parsers status --root . [--json]` in `llmwiki/cli.py`.
- [ ] Status should probe `shutil.which(mineru_command)` only; it must not parse a document.
- [ ] Run parser config/status tests and `.\.venv\Scripts\python.exe -m llmwiki parsers status --root . --json`.
- [ ] Commit with `git commit -m "feat: 增加 parser status 和默认 auto 配置"`.

### Task 4: MinerU Command Runner Tests

- [ ] Add `tests/test_mineru_runner.py` covering command construction, optional flags, `shell=False`, log sanitization/truncation, recursive content-list discovery, candidate selection, nonzero exit, and timeout handling.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_mineru_runner.py -q`; expected failure before implementation.
- [ ] Commit tests with `git commit -m "test: 覆盖 MinerU command runner"`.

### Task 5: MinerU Command Runner Implementation

- [ ] Create `llmwiki/mineru_runner.py` with `MinerUCommandRequest`, `MinerUCommandResult`, `build_mineru_command`, `run_mineru_command`, `discover_mineru_content_lists`, `select_mineru_content_list`, `probe_mineru_status`, and `sanitize_parser_log`.
- [ ] Use argument lists and `shell=False`; enforce timeout; capture sanitized stdout/stderr snippets; discover content-list files recursively.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_mineru_runner.py -q`.
- [ ] Commit with `git commit -m "feat: 增加 MinerU command runner"`.

### Task 6: MinerUBackend Auto Invocation And pypdf Fallback

- [ ] Extend parser backend and MinerU adapter tests for automatic runner use, nested output discovery, explicit MinerU hard failure, auto fallback, explicit pypdf skip, and precomputed output-dir compatibility.
- [ ] Modify `llmwiki/pdf_parser_backends.py` and `llmwiki/pdf_blocks.py` so `auto` can fall back to pypdf after MinerU command/parse failure while explicit `mineru` cannot.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_parser_backends.py tests/test_mineru_adapter.py tests/test_pdf_blocks.py -q`.
- [ ] Commit with `git commit -m "feat: 接入 MinerU 自动调用和 pypdf fallback"`.

### Task 7: Source Import And Add Pipeline Diagnostics

- [ ] Extend add-source/add-pipeline tests for fake MinerU success, auto fallback metadata, explicit MinerU failure, explicit pypdf, and parser artifacts not becoming evidence.
- [ ] Extend `SourceMetadata` serialization with parser command diagnostics.
- [ ] Ensure command diagnostics are sanitized and snippets are bounded.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_add_source.py tests/test_add_pipeline.py tests/test_mineru_runner.py -q`.
- [ ] Commit with `git commit -m "feat: 在 add 中记录 MinerU parser 诊断"`.

### Task 8: Staging, Review, And Source Page Diagnostics

- [ ] Extend ingest/review tests for run manifest, triage, review detail, and source page parser command/fallback summaries.
- [ ] Modify `llmwiki/ingest.py` to expose selected backend, command invocation, fallback info, artifact count, and selected content-list path without dumping large JSON or secrets.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ingest_review.py tests/test_add_pipeline.py -q`.
- [ ] Commit with `git commit -m "feat: 暴露 MinerU command staging 诊断"`.

### Task 9: Lint And PDF Quality Eval

- [ ] Extend PDF lint/eval tests for missing MinerU artifacts, content-list path validity, fallback warnings, secret snippets, backend distribution, command counters, and read-only no-MinerU behavior.
- [ ] Modify `llmwiki/pdf_quality.py` and `llmwiki/lint.py` to reuse metadata/sidecar facts.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_lint.py tests/test_pdf_quality_eval.py tests/test_query_lint_doctor.py -q`.
- [ ] Commit with `git commit -m "feat: 扩展 MinerU parser 质量检查"`.

### Task 10: Retrieval, Ask, And Eval Regression

- [ ] Extend retrieval/ask/eval tests so MinerU-derived PDF claims retrieve normally, parser artifacts are not evidence, and retrieval eval does not run MinerU.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_ask_workflow.py tests/test_retrieval_eval.py -q`.
- [ ] Commit with `git commit -m "test: 固定 MinerU auto 检索回归"`.

### Task 11: Documentation And Agent Contract

- [ ] Update README and AGENTS for auto MinerU-first parser behavior, pypdf fallback/debug path, parser status, and parser artifact boundaries.
- [ ] Update docs regression assertions.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_regression_samples.py -q`.
- [ ] Commit with `git commit -m "docs: 更新 V2.9.5 MinerU 自动后端说明"`.

### Task 12: Real MinerU Acceptance

- [ ] If MinerU is installed, run a `.tmp\papers-v295-mineru-auto` acceptance with parser status, three `docs\papers` PDFs, pdf-quality eval, lint, and PDF retrieval eval.
- [ ] If MinerU is not installed, verify status reports unavailable, normal add falls back to pypdf, and explicit `--parser mineru` fails safely.
- [ ] Commit only a sanitized observation note if useful.

### Task 13: Final Verification And Cleanup

- [ ] Run grouped parser/add/lint/retrieval tests.
- [ ] Run full verification: `.\.venv\Scripts\python.exe -m pytest -q`, `.\.venv\Scripts\python.exe -m llmwiki --help`, `.\.venv\Scripts\python.exe -m llmwiki parsers status --root . --json`, and `.\.venv\Scripts\python.exe -m llmwiki eval pdf-quality --root . --json`.
- [ ] Clean `.test-workspaces`, `.pytest_cache`, `.tmp`, generated source sidecars, parser artifacts, staging, state, embeddings, and generated wiki files while preserving `.gitkeep`.
- [ ] Confirm `git status --short` does not include secrets or generated files.
- [ ] Commit any remaining repo changes by feature/function.

## Assumptions And Defaults

- Default PDF parser becomes `auto` in repo config and new workspaces.
- MinerU is optional infrastructure: recommended for research PDFs, not required for using the project.
- `auto` fallback only supports pypdf.
- Explicit `--parser mineru` never falls back.
- Explicit `--parser pypdf` never invokes MinerU.
- MinerU command defaults to `mineru -p <input_path> -o <output_path>`.
- No SQLite schema changes, no new page type, and no new OCR/table/figure/equation evidence contract.
- Automated tests do not require a real MinerU installation.
