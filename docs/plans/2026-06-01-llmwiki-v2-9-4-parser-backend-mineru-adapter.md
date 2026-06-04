# LLMWiki V2.9.4 Parser Backend + MinerU Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: write failing tests first, verify failure, implement, verify pass, then commit. Split commits by feature/function.

**Goal:** Add a PDF parser backend boundary and optional MinerU adapter while keeping pypdf as the default parser path.

**Architecture:** PDF import selects a parser backend, normalizes backend-native output into existing metadata/block/chunk sidecars, then reuses the current chunked LLM ingest, staging, apply, retrieval, and ask pipeline. MinerU is opt-in through config or hidden advanced add options; read-only eval commands never invoke MinerU.

**Tech Stack:** Python stdlib `dataclasses/json/pathlib/subprocess`, existing pypdf parsing, existing LLMWiki source sidecars, pytest fixtures/monkeypatching.

---

## Implementation Tasks

### Task 1: Save The Plan

- [ ] Create this plan at `docs/plans/2026-06-01-llmwiki-v2-9-4-parser-backend-mineru-adapter.md`.
- [ ] Run `git status --short`; expect only the plan file.
- [ ] Commit with `git commit -m "docs: 保存 V2.9.4 执行计划"`.

### Task 2: Parser Backend Interfaces

- [ ] Add failing tests in `tests/test_pdf_parser_backends.py` for backend selection, pypdf availability, unknown backend rejection, explicit MinerU unavailable failure, and `auto` fallback warning behavior.
- [ ] Create `llmwiki/pdf_parser_backends.py` with `PdfParseRequest`, `ParserArtifact`, `PdfParseResult`, `PdfParserBackend`, `PypdfBackend`, `MinerUBackend`, `load_pdf_parser_config(root)`, and `select_pdf_parser_backend(root, requested_backend=None)`.
- [ ] Extend `llmwiki/workspace.py::DEFAULT_CONFIG` with `[pdf_parser]`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_parser_backends.py tests/test_llm_provider.py -q`.
- [ ] Commit with `git commit -m "feat: 增加 PDF parser backend 接口"`.

### Task 3: Refactor Existing pypdf Parser Behind Backend

- [ ] Extend parser/backend and PDF block tests to assert `PypdfBackend.parse(...)` matches current pypdf parsing behavior.
- [ ] Modify `llmwiki/pdf_blocks.py` so `parse_pdf_source(...)` delegates page extraction through `PypdfBackend` without changing downstream metadata/block behavior.
- [ ] Preserve V2.9.1/V2.9.2/V2.9.3 loader compatibility.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_blocks.py tests/test_pdf_quality.py tests/test_pdf_parser_backends.py -q`.
- [ ] Commit with `git commit -m "refactor: 将 pypdf PDF 解析接入 backend"`.

### Task 4: Generated Parser Artifact Directory

- [ ] Add `tests/test_pdf_parser_artifacts.py` for artifact directory creation, gitignore coverage, metadata artifact paths, and cleanup-safe generated paths.
- [ ] Update `.gitignore` to ignore `sources/parser-artifacts/*` while preserving `.gitkeep`.
- [ ] Update workspace initialization to create `sources/parser-artifacts`.
- [ ] Extend `SourceMetadata` with parser backend fields and structured block counts.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_parser_artifacts.py tests/test_regression_samples.py::test_gitignore_excludes_generated_workspace_content -q`.
- [ ] Commit with `git commit -m "feat: 增加 PDF parser artifact 目录"`.

### Task 5: MinerU Fixture Adapter

- [ ] Add small committed MinerU fixtures under `tests/fixtures/mineru/`.
- [ ] Add `tests/test_mineru_adapter.py` covering content type mapping, ignored blocks, deterministic ids, bbox/page preservation, and malformed content-list failure.
- [ ] Implement fixture/output parsing in `MinerUBackend.parse(...)`.
- [ ] Do not require real MinerU installation in tests.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_mineru_adapter.py tests/test_pdf_parser_backends.py -q`.
- [ ] Commit with `git commit -m "feat: 增加 MinerU 输出适配器"`.

### Task 6: Source Import Backend Selection

- [ ] Extend add-source/add-pipeline tests for default pypdf, hidden `--parser mineru`, explicit MinerU unavailable failure, and `auto` fallback metadata.
- [ ] Modify `llmwiki/sources.py` to accept parser options from `import_source(...)`.
- [ ] Modify pipeline and CLI so `llmwiki add <pdf> --parser mineru` and `--parser-output-dir <path>` are advanced/debug options hidden from normal help.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_add_source.py tests/test_add_pipeline.py -q` and `.\.venv\Scripts\python.exe -m llmwiki --help`.
- [ ] Commit with `git commit -m "feat: 在 add 中接入 PDF parser 选择"`.

### Task 7: Normalized Markdown And Chunk Prompts

- [ ] Extend source chunk, PDF block, and chunked ingest tests for MinerU ignored-block exclusion and structured payload inclusion.
- [ ] Extend `SourceBlock` with optional backend fields: `parser_backend`, `backend_ref`, `backend_type`, `bbox`, `asset_path`, `html`, `latex`, `markdown`, `table_markdown`.
- [ ] Update render/chunk code to use normalized text plus structured text payloads where present.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_source_chunks.py tests/test_pdf_blocks.py tests/test_pdf_chunked_ingest.py -q`.
- [ ] Commit with `git commit -m "feat: 支持 MinerU 结构化 blocks 入 chunk"`.

### Task 8: Parser Diagnostics In Staging And Source Pages

- [ ] Extend ingest/review tests for run manifest, triage, source page parser backend diagnostics, and artifact non-evidence behavior.
- [ ] Modify `llmwiki/ingest.py` to render backend diagnostics from metadata.
- [ ] Ensure review/detail output is secret-safe and does not dump large MinerU JSON.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ingest_review.py tests/test_add_pipeline.py -q`.
- [ ] Commit with `git commit -m "feat: 暴露 parser backend 诊断"`.

### Task 9: Lint And PDF Quality Eval

- [ ] Extend PDF lint tests for unknown backend, missing artifacts, ignored blocks entering prompts, and structured blocks without text payload.
- [ ] Extend PDF quality eval tests for backend distribution, MinerU count, artifact completeness, fallback count, structured block counts, and locator validity by backend.
- [ ] Modify `llmwiki/pdf_quality.py` and `llmwiki/lint.py`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_lint.py tests/test_pdf_quality_eval.py tests/test_query_lint_doctor.py -q`.
- [ ] Commit with `git commit -m "feat: 增加 parser backend 质量检查"`.

### Task 10: Retrieval And Ask Regression

- [ ] Extend retrieval/ask tests so MinerU-derived claims retrieve normally, paper title remains searchable, citations stay catalog-backed, and parser artifacts are not returned as evidence.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_ask_workflow.py tests/test_retrieval_eval.py -q`.
- [ ] Commit with `git commit -m "test: 固定 MinerU parser 检索回归"`.

### Task 11: Documentation And Agent Contract

- [ ] Update README and AGENTS with pypdf default, optional MinerU backend, generated parser artifacts, normalized block/chunk contract, and V2.9.4 non-goals.
- [ ] Update docs regression assertions.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_regression_samples.py -q`.
- [ ] Commit with `git commit -m "docs: 更新 V2.9.4 parser backend 说明"`.

### Task 12: Optional Real MinerU Acceptance

- [ ] If MinerU is installed, run a small `.tmp\papers-v294-mineru` acceptance with one paper and `--parser mineru`.
- [ ] If MinerU is not installed, record the skip in the final report and rely on fixture-based adapter tests.
- [ ] Do not commit `.tmp`, generated parser artifacts, sidecars, catalog, wiki pages, embeddings, or secrets.
- [ ] Commit only a sanitized observation note if useful.

### Task 13: Final Verification And Cleanup

- [ ] Run grouped tests for parser backend, MinerU adapter, PDF blocks/chunks/ingest, PDF lint/eval, retrieval, and ask.
- [ ] Run full verification: `.\.venv\Scripts\python.exe -m pytest -q`, `.\.venv\Scripts\python.exe -m llmwiki --help`, and `.\.venv\Scripts\python.exe -m llmwiki eval pdf-quality --root . --json`.
- [ ] Clean generated `.test-workspaces`, `.pytest_cache`, `.tmp`, parser artifacts, generated source/wiki/staging/state/vector files.
- [ ] Confirm `git status --short` does not include secrets or generated files.
- [ ] Commit any remaining repo changes by feature/function or list the blocker.

## Assumptions And Defaults

- `pypdf` remains the default parser backend.
- `--parser` and `--parser-output-dir` are advanced/debug `add` options hidden from normal help.
- Explicit `--parser mineru` fails hard when MinerU is unavailable or invalid.
- `default_backend = "auto"` may try MinerU when enabled and fall back to pypdf with visible warnings.
- MinerU tests use documented output-style fixture JSON; real MinerU installation is optional.
- Backend-native artifacts remain generated ignored files under `sources/parser-artifacts/`.
- V2.9.4 does not implement OCR, table cell evidence, figure understanding, equation semantic interpretation, new retrievers, new database tables, or `page_type="paper"`.
