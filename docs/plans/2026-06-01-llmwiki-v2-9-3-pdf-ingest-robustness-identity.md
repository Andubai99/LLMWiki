# LLMWiki V2.9.3 PDF Ingest Robustness And Paper Identity Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: write failing tests first, verify failure, implement, verify pass, then commit. Split commits by feature/function.

**Goal:** 修复 PDF ingest 中 LLM 偶发 malformed JSON 导致整篇导入失败的问题，并修正 PDF paper title / source alias / concept-entity identity 的边界。

**Architecture:** 在 PDF chunk ingest 和 consolidation 调用外增加一次 schema-aware JSON repair，不把坏 JSON 原文持久化；把 repair diagnostics 写入 staging/run/review。PDF source page 不再把论文标题作为 formal alias，检索仍通过 `sources.title/pages.title` 命中论文标题；PDF identity warning、lint 和 `eval pdf-quality` 负责暴露可疑 alias/identity 问题。

**Tech Stack:** Python stdlib `json/dataclasses/sqlite`, existing LLM provider interface, pytest monkeypatch providers, existing staging/apply/catalog pipeline.

---

## Key Changes

- 新增或扩展 `llmwiki/llm_ingest.py` 的 JSON repair 层：
  - `LLMJsonRepairEvent`
  - `parse_llm_json_with_repair(...)`
  - `build_json_repair_messages(...)`
  - `sanitize_llm_parse_error(...)`
  - 仅 PDF chunk/consolidation path 使用；非 PDF single-pass ingest 不改默认行为。
- 扩展 `LLMIngestProposal`、`llm-proposal.json`、`run.json`、`triage.md`、`review --detail`：
  - 记录 repair count、failed repair count、response kind、chunk id、sanitized parse error。
  - 不记录 API key、`config/api-keys.toml`、完整 prompt、malformed raw JSON。
- 修改 PDF source alias 策略：
  - PDF source page formal aliases 只保留 `source_id`。
  - 论文标题保留为 page/source title，不写入 source alias。
  - Markdown/text source 原 alias 行为保持不变。
- 扩展 PDF identity quality：
  - `eval pdf-quality` 增加 source-title alias collision、paper identity overlap、LLM JSON repair counters。
  - lint 对 parser-created/source-title alias collision 报 structural issue；concept/entity 同名或同 alias 只进 identity warning，不靠规则强行合并。

## Implementation Tasks

### Task 1: 保存执行计划

- [ ] Create `docs/plans/2026-06-01-llmwiki-v2-9-3-pdf-ingest-robustness-identity.md` with this plan.
- [ ] Run `git status --short`; expect only the plan file.
- [ ] Commit:
  - `git add docs/plans/2026-06-01-llmwiki-v2-9-3-pdf-ingest-robustness-identity.md`
  - `git commit -m "docs: 保存 V2.9.3 执行计划"`

### Task 2: JSON Repair Core

- [ ] Add failing tests in `tests/test_pdf_json_repair.py`:
  - valid JSON parses without repair.
  - malformed chunk JSON triggers exactly one repair call and returns parsed object.
  - malformed JSON + malformed repair raises safe error.
  - repair event contains response kind/chunk id/sanitized error, not raw malformed content or secrets.
  - repair usage is aggregated.
- [ ] Implement helper functions in `llmwiki/llm_ingest.py`.
- [ ] Repair prompt must include only malformed response, parse error, expected JSON-only instruction, and same schema hint; do not persist that prompt.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_json_repair.py -q`
- [ ] Commit:
  - `git add llmwiki/llm_ingest.py tests/test_pdf_json_repair.py`
  - `git commit -m "feat: 增加 LLM JSON 修复层"`

### Task 3: PDF Chunk Ingest Repair

- [ ] Extend `tests/test_pdf_chunked_ingest.py`:
  - first chunk response malformed, repair response valid, final proposal has cited claims.
  - repair count appears in `llm-proposal.json`.
  - chunk prompt still only includes current chunk block ids.
  - failed repair aborts PDF add with safe message.
- [ ] Modify `create_chunked_pdf_ingest_proposal(...)` to parse each chunk through repair helper.
- [ ] Store repaired valid content in chunk records; never persist malformed raw response.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_chunked_ingest.py tests/test_pdf_json_repair.py -q`
- [ ] Commit:
  - `git add llmwiki/llm_ingest.py tests/test_pdf_chunked_ingest.py`
  - `git commit -m "fix: 修复 PDF chunk JSON 解析鲁棒性"`

### Task 4: PDF Consolidation Repair And Staging Diagnostics

- [ ] Extend `tests/test_pdf_chunked_ingest.py` and `tests/test_ingest_review.py`:
  - malformed consolidation JSON repairs once.
  - consolidation repair cannot create formal claims; claims remain chunk-derived only.
  - `run.json`, `llm-proposal.json`, `triage.md`, and `review --detail` expose repair summary.
  - safe output excludes `sk-` and `config/api-keys.toml`.
- [ ] Add `repair_events` to `LLMIngestProposal` with default empty list.
- [ ] Update `write_llm_proposal`, `write_run_manifest` extra fields, `llm_proposal_lines`, and triage rendering.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_chunked_ingest.py tests/test_ingest_review.py tests/test_add_pipeline.py -q`
- [ ] Commit:
  - `git add llmwiki/llm_ingest.py llmwiki/ingest.py tests/test_pdf_chunked_ingest.py tests/test_ingest_review.py tests/test_add_pipeline.py`
  - `git commit -m "feat: 暴露 PDF JSON 修复诊断"`

### Task 5: PDF Source Alias And Identity Warnings

- [ ] Extend `tests/test_pdf_identity.py` and `tests/test_retrieval.py`:
  - PDF source page aliases contain `source_id`, not paper title.
  - paper title remains searchable through source/page title retrieval.
  - parser-created aliases such as `page1`, page markers, author lists, and venue/status strings are filtered.
  - concept/entity same title or same alias produces identity warning, not silent duplicate formal aliases.
  - non-PDF alias behavior remains unchanged.
- [ ] Add a source-type-aware source alias helper in `llmwiki/ingest.py`.
- [ ] Extend PDF identity warning generation to include source-title/entity/concept overlap.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_identity.py tests/test_retrieval.py tests/test_add_pipeline.py -q`
- [ ] Commit:
  - `git add llmwiki/ingest.py tests/test_pdf_identity.py tests/test_retrieval.py tests/test_add_pipeline.py`
  - `git commit -m "fix: 修正 PDF source alias 与身份警告"`

### Task 6: PDF Quality Eval And Lint Counters

- [ ] Extend `tests/test_pdf_quality_eval.py`:
  - JSON has `source_title_alias_collision_count`, `paper_identity_overlap_count`, `llm_json_repair_observed_count`.
  - eval is read-only and calls no LLM/embedding provider.
- [ ] Extend `tests/test_pdf_lint.py`:
  - source-title alias collision is lint issue.
  - expected concept/entity paper identity overlap is reported as warning/info, not automatic failure.
  - repair diagnostics are visible but not themselves a lint failure unless failed repairs exist in committed staging artifacts.
- [ ] Modify `llmwiki/pdf_quality.py` and `llmwiki/lint.py`.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_quality_eval.py tests/test_pdf_lint.py tests/test_query_lint_doctor.py -q`
- [ ] Commit:
  - `git add llmwiki/pdf_quality.py llmwiki/lint.py tests/test_pdf_quality_eval.py tests/test_pdf_lint.py tests/test_query_lint_doctor.py`
  - `git commit -m "feat: 扩展 PDF identity 质量检查"`

### Task 7: Retrieval, Ask, And Eval Regression

- [ ] Extend regression tests:
  - `tests/test_retrieval.py`: paper-title query still retrieves PDF source despite title not being a source alias.
  - `tests/test_ask_workflow.py`: answer citations still require retrieved claim ids and page/block locators.
  - `tests/test_retrieval_eval.py`: PDF eval datasets still load and retrieval eval calls no chat LLM.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_ask_workflow.py tests/test_retrieval_eval.py -q`
- [ ] Commit:
  - `git add tests/test_retrieval.py tests/test_ask_workflow.py tests/test_retrieval_eval.py`
  - `git commit -m "test: 固定 PDF identity 检索回归"`

### Task 8: Documentation And Agent Contract

- [ ] Update README:
  - PDF ingest has one JSON repair attempt for chunk/consolidation output.
  - malformed LLM JSON is not persisted.
  - PDF source title is title metadata, not formal alias.
  - `eval pdf-quality` reports identity and repair diagnostics.
- [ ] Update `AGENTS.md`:
  - PDF source aliases must not include parser-created aliases or paper title aliases.
  - LLM repair may only repair JSON syntax/schema shape; it cannot create evidence or citations.
  - Repair output still must pass locator and staging validation.
- [ ] Update docs regression assertions if needed.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_regression_samples.py -q`
- [ ] Commit:
  - `git add README.md AGENTS.md tests/test_regression_samples.py`
  - `git commit -m "docs: 更新 V2.9.3 PDF ingest 说明"`

### Task 9: Real 20-Paper Acceptance

- [ ] Create temp workspace:
  - `.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\papers-v293-acceptance`
  - Copy local ignored `config/api-keys.toml` to `.tmp\papers-v293-acceptance\config\api-keys.toml`.
- [ ] Add each `docs/papers/*.pdf` into temp workspace.
- [ ] Run:
  - `.\.venv\Scripts\python.exe -m llmwiki lint --root .tmp\papers-v293-acceptance`
  - `.\.venv\Scripts\python.exe -m llmwiki eval pdf-quality --root .tmp\papers-v293-acceptance --json`
  - `.\.venv\Scripts\python.exe -m llmwiki embeddings rebuild --root .tmp\papers-v293-acceptance`
  - `.\.venv\Scripts\python.exe -m llmwiki eval retrieval --root .tmp\papers-v293-acceptance --dataset tests/evals/retrieval_v2_9_1_pdf_foundation.jsonl`
- [ ] Acceptance targets:
  - 20/20 PDFs add/apply or any failure has a repair-safe diagnostic.
  - parser marker titles: 0.
  - source title alias collisions: 0.
  - parser-created duplicate aliases: 0.
  - sidecar completeness: 1.0.
  - block locator validity: 1.0.
  - retrieval PDF foundation eval remains stable.
- [ ] If a real acceptance bug appears, write the failing test first, fix, rerun affected tests, then commit.
- [ ] Optional sanitized note:
  - `docs/observations/2026-06-01-llmwiki-v2-9-3-pdf-acceptance-observations.md`
  - Commit with `git commit -m "test: 记录 V2.9.3 PDF 验收结果"`.

### Task 10: Final Verification And Cleanup

- [ ] Run grouped tests:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_json_repair.py tests/test_pdf_chunked_ingest.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_pdf_identity.py tests/test_pdf_lint.py tests/test_pdf_quality_eval.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_ask_workflow.py tests/test_retrieval_eval.py -q`
- [ ] Run full verification:
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `.\.venv\Scripts\python.exe -m llmwiki --help`
  - `.\.venv\Scripts\python.exe -m llmwiki eval pdf-quality --root . --json`
- [ ] Clean generated files:
  - `.test-workspaces`
  - `.pytest_cache`
  - `.tmp/papers-v293-acceptance`
  - generated `sources/metadata/*`, `sources/blocks/*`, `sources/chunks/*` contents while preserving `.gitkeep`
  - generated `sources/raw/*`, `sources/normalized/*`, `staging/*`, `state/catalog.sqlite`, `state/embeddings/*`, generated `wiki/` pages/log/index
- [ ] Confirm `git status --short` does not include:
  - `config/api-keys.toml`
  - `docs/papers`
  - generated source/wiki/staging/state/vector files
- [ ] If any repo files remain changed, commit them by feature/function before finishing; if a commit is impossible, explicitly list the blocker and changed files.

## Test Plan

- Unit:
  - JSON repair parse success/failure/sanitization.
  - repair usage aggregation and event serialization.
  - PDF alias filtering and identity warning generation.
- Integration:
  - PDF chunked ingest recovers from one malformed chunk/consolidation response.
  - staging/review exposes repair diagnostics without leaking raw malformed output or secrets.
  - apply still only accepts locator-backed claims.
- Retrieval/Ask:
  - removing PDF title aliases does not break title retrieval.
  - ask citations remain restricted to retrieved catalog evidence.
- Quality:
  - `lint` and `eval pdf-quality` report source title alias collision and paper identity overlap correctly.
  - read-only eval commands do not call LLM/embedding and do not mutate workspace.
- Real acceptance:
  - 20 local PDFs import in temp workspace.
  - PDF quality metrics improve or failures are actionable and sanitized.

## Assumptions

- V2.9.3 does not add SQLite tables, page types, MinerU/OCR/table/figure/equation extraction, or external metadata services.
- JSON repair is one attempt only. If repair fails, the current source/run fails safely.
- Repair can fix JSON shape only; it cannot invent claims, block ids, locators, sources, or citations.
- PDF source page title remains searchable through `pages.title` and `sources.title`; formal source alias is limited to `source_id`.
- `retrieve/query/eval retrieval/eval pdf-quality` still do not call chat LLM.
- Execution should use small feature commits, matching the project workflow preference.
