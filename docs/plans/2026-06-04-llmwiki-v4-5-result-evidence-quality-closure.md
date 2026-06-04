# LLMWiki V4.5-min Result Evidence Quality Closure Implementation Plan

## Summary

实现 `docs/specs/2026-06-04-llmwiki-v4-5-result-evidence-quality-closure-design.md`：新增只读 `llmwiki eval result-evidence`，评估 V4.3 `metric_results` 和 V4.4 timeline rows 是否能解析回可检查的 source context。

方法采用 **spec-driven + contract-first + risk-based TDD**。V4.5-min 只做 result evidence quality closure，不做 OCR、视觉图表理解、通用 table semantic parser、metric alias、timeline synthesis、UI 或 catalog migration。提交按功能拆分，commit summary 使用 `docs:`、`test:`、`feat:` 等 conventional prefix。

## Key Changes

- 新增命令：
  - `llmwiki eval result-evidence --root .`
  - `llmwiki eval result-evidence --root . --json`
  - filters: `--source-id`、`--paper-id`、`--metric`、`--dataset`、`--task`、`--limit`、`--offset`
- 新增只读评估模块，放在 `src/llmwiki/evals/result_evidence.py`：
  - schema/model: `result_evidence_quality.v4.5`、`result_evidence_item.v4.5`
  - query: read-only join `metric_results`、`claims`、`sources`、`pages`，复用 V4.2 inventory metadata
  - locator: PDF `page:N;block:<block-id>` 和 Markdown/text `line:N`
  - diagnostics: locator/context/value/table/caption/parser metadata quality
- 默认实现选择：
  - JSON 默认包含 paginated per-row `items`，`limit=200`，最大 `1000`
  - `context_preview` 固定 bounded 500 chars，不新增 `--context-chars`
  - parser fallback 计入 `parser_diagnostic_source_count`，并在 affected rows 加 `parser_fallback_observed` warning
  - `missing_baseline` 作为 `info`，不计入 warning
  - unit tests 使用 synthetic catalog/sidecar fixtures，不提交真实 PDF 或生成态 acceptance outputs
- 输出只读，除 stdout/stderr 外不写任何文件；`--output` 不在 V4.5-min 实现。

## Implementation Steps

1. 保存 plan 并提交
   - 新增 `docs/plans/2026-06-04-llmwiki-v4-5-result-evidence-quality-closure.md`
   - 提交：`docs: 添加 V4.5 结果证据质量执行计划`

2. 先写失败测试
   - 新增：
     - `tests/test_result_evidence_quality_model.py`
     - `tests/test_result_evidence_quality_locator.py`
     - `tests/test_result_evidence_quality_cli.py`
     - `tests/test_result_evidence_quality_readonly.py`
   - 覆盖 schema、summary counts、PDF locator resolution、Markdown line locator resolution、malformed/missing sidecar、value support diagnostics、table/caption diagnostics、filters、CLI JSON/human output、read-only boundary。
   - 提交：`test: 固定 V4.5 结果证据质量契约`

3. 实现 result evidence quality 模型和评估逻辑
   - 新增 `src/llmwiki/evals/result_evidence.py`
   - 查询前调用 catalog schema 检查；catalog 缺失或 schema incompatible 返回失败路径
   - 复用 V4.4 `normalize_timeline_key` / filter equality，避免 substring 或 alias expansion
   - PDF context 从 `sources/blocks/<source-id>.jsonl` 读取 `text_clean`，fallback 到 `table_markdown/markdown/text_raw`，路径必须 workspace-bounded
   - Markdown/text context 从 catalog `normalized_path` 读取 `line:N` 周围 bounded lines，路径必须在 `sources/normalized/`
   - 生成 diagnostics：join、locator、context、missing metric value、raw-only value、missing method/dataset/task/baseline、value visibility、table/caption support、parser fallback/quality warning
   - 提交：`feat: 新增结果证据质量评估模型`

4. 接入 CLI 和格式化
   - 修改 `cli.py` 的 `eval` subparser，新增 `result-evidence`
   - 新增或就地实现 human formatter：summary first，再列 compact diagnostic rows
   - JSON 使用 `json.dumps(..., ensure_ascii=False, indent=2)`
   - invalid `limit/offset` 返回 exit code `1`
   - quality warnings/errors 不导致 exit code `1`
   - 提交：`feat: 接入结果证据质量评估命令`

5. 固定只读边界和文档契约
   - `test_result_evidence_quality_readonly.py` monkeypatch 禁止调用 LLM、embedding、MinerU、parser、add/import、ingest、apply、ask、synthesis、lint、clean
   - 文件快照确认命令不写 `wiki/`、`sources/`、`staging/`、`state/catalog.sqlite`、`state/corpus-batches/`、`state/embeddings/`、`state/ui-jobs/`、`.tmp/`
   - README 增加 V4.5-min 命令说明；AGENTS 增加 V4.5 只读边界和 5-paper acceptance 保留规则
   - 更新 `tests/test_regression_samples.py`
   - 提交：`docs: 更新 V4.5 结果证据质量契约`

6. 五篇真实 acceptance
   - 使用 `.tmp/paper-v45-acceptance`，不要在完成后自动 clean
   - 复制本地 ignored `config/api-keys.toml` 到临时 workspace config
   - 将固定 5 篇复制到 `.tmp/paper-v45-acceptance/input-papers/`：
     - `2404.07972.pdf`
     - `2409.08264.pdf`
     - `2501.16150.pdf`
     - `2506.16042.pdf`
     - `2509.15221.pdf`
   - 运行：
     - `llmwiki corpus import input-papers --root .tmp\paper-v45-acceptance --recursive --parser auto`
     - `llmwiki metric list --root .tmp\paper-v45-acceptance --json`
     - `llmwiki metric timeline "<metric-from-list>" --root .tmp\paper-v45-acceptance --json`
     - `llmwiki eval result-evidence --root .tmp\paper-v45-acceptance --json`
     - `llmwiki eval result-evidence --root .tmp\paper-v45-acceptance`
   - 记录 sanitized observation：
     - `docs/specs/2026-06-04-llmwiki-v4-5-result-evidence-quality-acceptance-observations.md`
   - observation 记录 imported paper count、selected filenames、formal claims、durable result rows、joined rows、locator/context counts、table/caption counts、missing value/method/dataset/task/baseline counts、top diagnostic codes、selected timeline metric result。
   - 提交：`test: 记录 V4.5 结果证据质量真实验收`

## Test Plan

- Unit/model/locator：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_result_evidence_quality_model.py tests\test_result_evidence_quality_locator.py -q`
- CLI/read-only：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_result_evidence_quality_cli.py tests\test_result_evidence_quality_readonly.py -q`
- Related V4 regression：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_timeline_model.py tests\test_metric_timeline_query.py tests\test_metric_result_staging.py tests\test_init_schema.py -q`
- Docs/contract：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Final automated verification：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_result_evidence_quality_model.py tests\test_result_evidence_quality_locator.py tests\test_result_evidence_quality_cli.py tests\test_result_evidence_quality_readonly.py tests\test_metric_timeline_model.py tests\test_metric_timeline_query.py tests\test_regression_samples.py -q`
  - `git status --short --ignored`

## Assumptions And Defaults

- V4.5-min acceptance uses only the fixed 5-paper subset, not full 20 papers。
- Do not run default `llmwiki clean --root .` after acceptance; preserve `.tmp/paper-v45-acceptance` for user inspection。
- Do not commit `.tmp/`, generated source/wiki/staging/state files, copied API keys, parser artifacts, raw prompts/responses, parser logs, or real PDFs。
- `eval result-evidence` is read-only and local; it must not call LLM、embedding、parser、ingest/apply、ask/synthesis、lint、clean、or raw PDF retrieval。
- Diagnostics are evaluation output, not formal evidence and not wiki claims。
- Missing baseline is info; missing method/dataset/task and missing/unsupported values are warnings; invalid joins/locators/context are errors。
