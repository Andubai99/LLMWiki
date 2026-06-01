# LLMWiki V2.9.2 PDF Quality And Paper Identity Implementation Plan

## Summary

目标是在 V2.9.1 的 PDF metadata/block/chunk 基础上，提升文本 PDF 的论文级解析质量：标题更干净、header/footer/page number 等非正文块可识别并从 chunk prompt 排除、metadata/blocks/chunks 升级到 V2.9.2 schema、source page/triage/lint/eval 暴露 PDF 质量指标。正常入口仍是 `llmwiki add <pdf> --root .`。

关键边界：

- 不新增 SQLite 表。
- 不新增 `page_type="paper"`。
- 不接 MinerU/OCR/table/figure/equation structured extraction。
- 不使用外部 metadata 网络服务。
- 不加入领域关键词规则。
- `retrieve/query/eval retrieval` 仍不调用 chat LLM。
- V2.9.1 sidecar 必须可继续读取。

## Key Changes

- 新增 `llmwiki/pdf_quality.py`：
  - `TitleCandidate`
  - `PaperIdentity`
  - `ParserQuality`
  - `score_title_candidates(...)`
  - `classify_block_roles(...)`
  - `detect_repeated_headers_footers(...)`
  - `detect_parser_created_alias(...)`
  - `evaluate_pdf_quality(root) -> PdfQualitySummary`
  - `format_pdf_quality_report(summary) -> str`
- 修改 `llmwiki/pdf_blocks.py`：
  - schema 升级到 `source_metadata.v2.9.2`、`source_block.v2.9.2`。
  - `SourceMetadata` 增加 `title_quality`、`title_candidates`、`paper_identity`、`parser_quality`。
  - `SourceBlock` 增加 `content_role`、`cleaning_operations`、`quality_flags`。
  - loader 兼容 V2.9.1 缺失字段。
  - title 选择改为候选打分。
- 修改 `llmwiki/source_chunks.py`：
  - schema 升级到 `source_chunk.v2.9.2`。
  - 默认排除 `content_role="ignored"` blocks。
  - chunks diagnostics 记录 total/content/ignored block counts。
  - loader 兼容 V2.9.1 chunks。
- 修改 `llmwiki/ingest.py`：
  - `source_parse_diagnostics` 读取 V2.9.2 metadata/parser_quality。
  - source page 增加 `Paper Metadata` 和 `Parser Quality`。
  - `triage.md` 增加 title candidates、parser warnings、identity warnings。
  - concept/entity 同名或同 alias 时，若 role 不清晰，写入 duplicate/identity warning，不静默制造 parser-created aliases。
- 修改 `llmwiki/lint.py` 和 `llmwiki/cli.py`：
  - lint 扩展 PDF parser counters。
  - CLI 增加 `llmwiki eval pdf-quality --root . [--json]`。
  - `eval pdf-quality` 只读 catalog/sidecars，不调用 LLM、embedding、网络，不写任何 workspace 文件。
- 更新 README/AGENTS 和测试；真实 20-paper acceptance 只在 `.tmp/` 临时 workspace 运行，不提交生成态文件。

## Implementation Tasks

### Task 1: 保存执行计划

- 新建本计划文件。
- 运行 `git status --short` 确认只新增计划文件。
- 提交：`docs: 保存 V2.9.2 执行计划`。

### Task 2: PDF quality 核心测试与模块

- 新建 `tests/test_pdf_quality.py`，先写失败测试：
  - parser marker `<!-- page:1 -->` 分数最低。
  - `Published as a conference paper at ICLR 2025` 被识别为 `venue_or_status_line`。
  - 作者密集行不应成为 title。
  - 真实 title-shaped candidate 得分高于 venue/header/author candidates。
  - repeated header/footer 跨页重复出现时标为 ignored。
  - page number block 标为 ignored。
  - caption/table-like/equation-like/reference/appendix block role 可识别。
- 新建 `llmwiki/pdf_quality.py`。
- 实现纯 deterministic 结构规则：
  - title candidate scoring 使用位置、长度、author-density、venue/status shape、parser marker、metadata token overlap。
  - repeated header/footer 通过跨页重复文本判断。
  - page number 通过纯数字、`Page N`、`N / M` 等通用形状判断。
  - block role 不使用任何领域关键词。
- 运行 `python -m pytest tests/test_pdf_quality.py -q`。
- 提交：`feat: 增加 PDF quality 结构分析`。

### Task 3: 升级 metadata/block schema 并保持兼容

- 扩展 `tests/test_pdf_blocks.py`，覆盖 V2.9.2 schema、metadata 字段、block 字段、V2.9.1 sidecar loader 兼容、noisy title 不覆盖高质量 title。
- 修改 `llmwiki/pdf_blocks.py`：dataclass 新字段、`parse_pdf_source` 调用 `pdf_quality`、title scoring、V2.9.2 writer。
- 运行 `python -m pytest tests/test_pdf_blocks.py tests/test_pdf_quality.py -q`。
- 提交：`feat: 升级 PDF metadata block schema`。

### Task 4: normalized markdown 与 chunker 排除 ignored blocks

- 扩展 `tests/test_source_chunks.py` 和 `tests/test_pdf_blocks.py`。
- `render_normalized_markdown_from_blocks` 跳过 ignored blocks。
- `SourceChunk` 增加 diagnostics，schema 升级到 `source_chunk.v2.9.2`，chunker 排除 ignored blocks。
- 运行 `python -m pytest tests/test_source_chunks.py tests/test_pdf_blocks.py -q`。
- 提交：`feat: 让 PDF chunker 排除非正文 blocks`。

### Task 5: PDF ingest diagnostics 与 identity warnings

- 扩展 `tests/test_pdf_chunked_ingest.py` 和 `tests/test_ingest_review.py`。
- `llm_ingest` chunk evidence 过滤 ignored blocks，consolidation prompt 增加 paper identity、section summaries、claim count per section。
- `ingest` 读取 V2.9.2 metadata fields，source page 增加 Paper Metadata / Parser Quality，duplicate candidates 增加 identity warning。
- 运行 `python -m pytest tests/test_pdf_chunked_ingest.py tests/test_ingest_review.py tests/test_add_pipeline.py -q`。
- 提交：`feat: 暴露 V2.9.2 PDF identity diagnostics`。

### Task 6: alias sanitizer 与 parser-created alias 防护

- 新增或扩展 `tests/test_pdf_identity.py`。
- PDF source 过滤 `page1`、page marker、venue/status-only string、author-list title 等 parser-created aliases。
- 保留 warning 到 duplicate/identity candidates。
- 运行 `python -m pytest tests/test_pdf_identity.py tests/test_regression_samples.py -q`。
- 提交：`fix: 过滤 PDF parser-created aliases`。

### Task 7: PDF quality eval 命令

- 新建 `tests/test_pdf_quality_eval.py`。
- 实现 `PdfQualitySummary`、`evaluate_pdf_quality`、`format_pdf_quality_report`。
- CLI 增加 `eval pdf-quality --root . [--json]`，只读、无 LLM、无 embedding、无网络。
- 运行 `python -m pytest tests/test_pdf_quality_eval.py -q` 和 `python -m llmwiki eval pdf-quality --root . --json`。
- 提交：`feat: 增加 PDF quality eval`。

### Task 8: 扩展 lint PDF parser checks

- 扩展 `tests/test_pdf_lint.py`。
- `lint` 复用 `pdf_quality.evaluate_pdf_quality` 的 counters，structural failures 计入 issue，informational warnings 不默认失败。
- 运行 `python -m pytest tests/test_pdf_lint.py tests/test_query_lint_doctor.py -q`。
- 提交：`feat: 扩展 PDF parser lint 质量检查`。

### Task 9: retrieval/ask regression 与 V2.9.1 eval 保持

- 扩展 retrieval/ask/eval 测试，保持 page/block locator 和 V2.9.1 PDF eval 数据集可用。
- 运行 `python -m pytest tests/test_retrieval.py tests/test_ask_workflow.py tests/test_retrieval_eval.py -q`。
- 提交：`test: 固定 V2.9.2 PDF retrieval 回归`。

### Task 10: 文档和 agent contract

- README 增加 V2.9.2 PDF quality 说明、`llmwiki eval pdf-quality`、sidecar schema、ignored blocks、Paper Metadata、Parser Quality。
- AGENTS 增加 structural parser rules、ignored blocks、traceability、eval pdf-quality 只读无 LLM。
- 运行 `python -m pytest tests/test_regression_samples.py -q`。
- 提交：`docs: 更新 V2.9.2 PDF quality 工作流`。

### Task 11: 真实 20-paper acceptance

- 在 `.tmp/papers-v292-acceptance` 临时 workspace 初始化并导入 `docs/papers/*.pdf`。
- 运行 lint、eval pdf-quality、embeddings rebuild、V2.9.1 PDF retrieval eval。
- 记录 sanitized note 到 `docs/superpowers/specs/2026-06-01-llmwiki-v2-9-2-pdf-acceptance-observations.md`。
- 提交：`test: 记录 V2.9.2 PDF acceptance 结果`。

### Task 12: 最终验证与清理

- 运行分组测试、全量 `pytest -q`、`python -m llmwiki --help`、`python -m llmwiki eval pdf-quality --root . --json`。
- 清理 `.test-workspaces`、`.pytest_cache`、`.tmp/papers-v292-acceptance`、生成态 source/wiki/staging/state/vector 文件。
- 确认不提交 secrets、`docs/papers`、catalog、embeddings、生成态文件。
- 如有遗漏，最终提交：`feat: 完成 V2.9.2 PDF quality and paper identity`。

## Test Plan

- Unit: title candidate scoring、block role classification、repeated header/footer/page number detection、V2.9.1 sidecar compatibility、parser-created alias detection。
- Integration: PDF import writes V2.9.2 sidecars；normalized Markdown 和 chunk prompts 排除 ignored blocks；staging/source page/triage 暴露 Paper Metadata 和 Parser Quality；PDF chunked ingest 仍只创建 page/block cited formal claims。
- CLI: `eval pdf-quality` human/JSON stable output；lint reports expanded parser counters。
- Regression: Markdown/text source locators 仍用 `line:N`；V2.9.1 retrieval eval dataset 仍通过；`retrieve/query/eval retrieval/eval pdf-quality` 不调用 chat LLM；`ask` 仍只接受 retrieved contexts。
- Real acceptance: 20 local PDFs import in `.tmp` workspace，quality eval 和 lint 通过结构性要求，生成态和 API key 不提交。

## Assumptions And Defaults

- V2.9.2 is a quality/stability slice, not a rich parsing slice.
- Structural parser rules are allowed; domain-specific keyword rules are not.
- Sidecar schema may upgrade to V2.9.2, but loaders must accept V2.9.1.
- `content_role="ignored"` blocks remain in sidecars for auditability but are excluded from normalized body and chunk claim prompts by default.
- No new catalog schema or page type.
- No network metadata enrichment.
- `eval pdf-quality` is local, deterministic, read-only, and no-LLM.
- Acceptance logs are sanitized and committed only as summary docs; `.tmp` workspace, generated artifacts, embeddings, catalog, and secrets remain untracked.
