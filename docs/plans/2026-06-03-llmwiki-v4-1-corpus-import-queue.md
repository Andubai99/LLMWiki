# LLMWiki V4.1 Corpus Import Queue Implementation Plan

## Summary

Implement `docs/specs/2026-06-03-llmwiki-v4-1-corpus-import-queue-design.md`: add a CLI-first `llmwiki corpus` command group for batch importing same-domain research papers. V4.1 only adds batch orchestration around the existing `add_and_process_source(...)` pipeline. It does not change ingest semantics, add UI routes, or implement metric/result extraction.

The method is spec-driven, contract-first, risk-based TDD. Commits should stay split by function and use conventional prefixes.

## Key Changes

- Add CLI commands:
  - `llmwiki corpus import <path> --root . [--dry-run] [--recursive] [--list-file <file>] [--fail-fast] [--parser auto|pypdf|mineru] [--json]`
  - `llmwiki corpus status [batch-id] --root . [--json]`
  - `llmwiki corpus retry <batch-id> --root . [--failed-only] [--item <item-id>] [--json]`
  - `llmwiki corpus skip <batch-id> <item-id-or-path> --root . [--reason <text>] [--json]`
- Add `src/llmwiki/corpus/`:
  - state/models for `corpus_batch.v4.1`, `corpus_item.v4.1`, and `corpus_attempt.v4.1`
  - discovery for local files, folders, and UTF-8 `--list-file`
  - runner for sequential calls to `add_and_process_source(...)`
  - formatting for human and stable JSON output
- Store generated batch state as JSON/JSONL under `state/corpus-batches/<batch-id>/`.
- Add `.gitignore` and clean generated coverage for `state/corpus-batches/`.
- Preserve all existing staging/apply, source, catalog, UI, and retrieval boundaries.

## Defaults

- Folder import is non-recursive unless `--recursive` is set.
- The first implementation supports local files, folders, and list files only; URL batch import is out of scope.
- Import and retry process sequentially; no concurrent workers.
- `--fail-fast` defaults to false.
- Retry appends attempts to the original batch instead of creating a new batch id.
- `corpus import` and `corpus retry` return exit code `1` when any item is failed or interrupted, while preserving successful item state.
- Already-applied detection uses local file SHA-256 plus `sources.sha256` and `ingest_runs.status='applied'`.

## Implementation Tasks

### Task 1: Plan Document

- Save this plan under `docs/plans/2026-06-03-llmwiki-v4-1-corpus-import-queue.md`.
- Commit: `docs: 添加 V4.1 语料导入队列执行计划`.

### Task 2: Contract Tests

- Add failing tests:
  - `tests/test_corpus_state.py`
  - `tests/test_corpus_discovery.py`
  - `tests/test_corpus_cli.py`
  - `tests/test_corpus_runner.py`
- Update:
  - `tests/test_clean.py`
  - `tests/test_regression_samples.py` only if documentation contract assertions need the new V4.1 wording.

### Task 3: State And Discovery

- Implement batch id and item id generation.
- Implement generated state read/write for `batch.json`, `items.jsonl`, `attempts.jsonl`, and `events.jsonl`.
- Implement deterministic source discovery.
- Ignore generated/project directories during discovery.
- Support source suffixes: `.md`, `.markdown`, `.txt`, `.html`, `.htm`, `.pdf`.
- Commit: `feat: 新增语料批次状态与发现模型`.

### Task 4: Runner And CLI

- Add `corpus` command group to the existing argparse CLI.
- Implement import/dry-run/status/retry/skip.
- Map `AddPipelineResult.status == "already_applied"` to `already_imported`.
- Map `AddPipelineError` to item and attempt failure rows.
- Preserve attempt history on retry.
- Mark active item and batch interrupted on `KeyboardInterrupt` where possible.
- Commit: `feat: 接入语料导入队列 CLI`.

### Task 5: Boundary And Cleanup

- Ensure dry-run and status never call LLM, parser execution, add, apply, eval, or clean.
- Ensure corpus layer does not directly write formal wiki/catalog/staging/source artifacts outside existing add pipeline calls.
- Add `state/corpus-batches/` to `.gitignore`.
- Add `state/corpus-batches` to generated clean paths.
- Commit: `test: 固定 V4.1 语料队列边界`.

### Task 6: Documentation Contract

- Update README with V4.1 CLI usage and generated state boundaries.
- Update AGENTS with V4.1 corpus import queue rules.
- Commit: `docs: 更新 V4.1 语料导入队列契约`.

## Test Plan

- Unit/contract:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_state.py tests\test_corpus_discovery.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_cli.py tests\test_corpus_runner.py -q`
- Safety/cleanup:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_clean.py tests\test_regression_samples.py -q`
- Related regressions:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_add_pipeline.py tests\test_add_source.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_ui_mutation_boundary.py tests\test_ui_readonly.py -q`
- Final verification:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_state.py tests\test_corpus_discovery.py tests\test_corpus_cli.py tests\test_corpus_runner.py tests\test_clean.py tests\test_add_pipeline.py tests\test_regression_samples.py -q`
  - `.\.venv\Scripts\python.exe -m llmwiki clean --root .`
  - `git status --short --ignored`

## Manual Acceptance

- Dry-run:
  - `.\.venv\Scripts\python.exe -m llmwiki corpus import docs\papers --root . --dry-run`
  - Expected: top-level PDFs are listed and `state/corpus-batches` is not written.
- Small real acceptance should use a temporary corpus with one or two copied sources, not the full 20-paper corpus by default.
- Confirm `corpus status`, `corpus status <batch-id> --json`, and `corpus retry <batch-id>` behave as expected.
- Clean or ignore generated state before closeout.
