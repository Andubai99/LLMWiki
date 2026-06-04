# LLMWiki V4.5-min Result Evidence Quality Closure Implementation Plan

## Summary

实现 `docs/specs/2026-06-04-llmwiki-v4-5-result-evidence-quality-closure-design.md`：新增 CLI-first、只读的 `llmwiki eval result-evidence`，评估 V4.3 `metric_results` 是否能回溯到可检查的 source context，并暴露 locator、context、join、parser fallback、字段缺失等质量诊断。

V4.5-min 不新增 UI，不调用 LLM/embedding/parser，不写 wiki/source/staging/state，不做 metric alias、unit conversion、timeline ranking 或自动修复。真实验收只使用 5 篇固定论文子集，并按用户要求保留 `.tmp/paper-v45-acceptance` 供后续追问，不默认清理。

方法采用 **spec-driven + contract-first + risk-based TDD**。提交按功能拆分，commit summary 使用 conventional prefix，例如 `docs:`、`test:`、`feat:`。

## Key Changes

- 新增命令：
  - `llmwiki eval result-evidence --root .`
  - `llmwiki eval result-evidence --root . --json`
  - 支持只读过滤：`--source-id`、`--paper-id`、`--metric`、`--dataset`、`--task`、`--limit`、`--offset`
- 新增只读 eval 模块：
  - `src/llmwiki/evals/result_evidence.py`
  - 固定 schema：`result_evidence_quality.v4.5`、`result_evidence_item.v4.5`
- 数据来源：
  - 只读 `state/catalog.sqlite` 中的 `metric_results`、`claims`、`sources`、`pages`
  - V4.2 inventory helper 仅补充 paper display metadata
  - PDF block sidecar `sources/blocks/<source-id>.jsonl`
  - Markdown/text normalized source `sources/normalized/...`
  - PDF metadata sidecar `sources/metadata/<source-id>.json`
- 默认策略：
  - JSON 输出包含 summary、paginated items、warnings。
  - `limit=200`，最大 `1000`，`offset>=0`。
  - `context_preview` 固定最多 500 字符，不新增 `--context-chars`。
  - PDF locator 只支持 `page:N;block:<block-id>`，bounded scan block sidecar。
  - Markdown/text locator 只支持 `line:N`，只读取 `sources/normalized/` 下 bounded path。
  - parser fallback 计入 `parser_diagnostic_source_count`，相关 rows 加 `parser_fallback_observed` diagnostic。
  - `missing_baseline` 作为 info diagnostic，不计入 warning/error。
  - malformed sidecar、missing context、missing join 保留 row 并给 diagnostic，不伪造 context。

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
   - 覆盖 schema、summary、filters、pagination、PDF block locator、line locator、missing joins、invalid args、read-only boundary。
   - 提交：`test: 固定 V4.5 结果证据质量契约`

3. 实现 result evidence 模型和只读查询
   - 新增 `src/llmwiki/evals/result_evidence.py`
   - 实现 schema constants、filter validation、locator resolution、metadata diagnostics、summary counters、stable JSON builders。
   - 查询前检查 catalog schema；`metric_results` 缺失或 catalog 不可用走明确错误路径。
   - 所有 sidecar/normalized 读取必须 workspace bounded。
   - 提交：`feat: 新增结果证据质量只读评估`

4. 接入 CLI 和输出格式
   - 在现有 `eval` 命令组中新增 `result-evidence`。
   - JSON 使用 `json.dumps(..., ensure_ascii=False, indent=2)`。
   - human 输出先显示 summary，再显示紧凑 diagnostics table。
   - invalid numeric args 在 CLI 层返回 exit code `1`。
   - 提交：`feat: 接入结果证据质量 CLI`

5. 固定只读边界和文档契约
   - `test_result_evidence_quality_readonly.py` monkeypatch 禁止调用 LLM、embedding、MinerU、parser、add/import、ingest、apply、ask、synthesis、lint、clean 和其他 eval。
   - 文件快照确认命令不写 `wiki/`、`sources/`、`staging/`、`state/catalog.sqlite`、`state/corpus-batches/`、`state/embeddings/`、`state/ui-jobs/`、`.tmp/`。
   - README 和 AGENTS 增加 V4.5-min 只读 eval 边界和命令示例。
   - 更新 `tests/test_regression_samples.py`。
   - 提交：`docs: 更新 V4.5 结果证据质量契约`

6. 5 篇真实 LLM acceptance
   - 创建并保留 `.tmp/paper-v45-acceptance`。
   - 复制本地 ignored `config/api-keys.toml` 到临时 workspace config。
   - 复制固定 5 篇论文到 `.tmp/paper-v45-acceptance/input-papers/`：
     - `docs/papers/2404.07972.pdf`
     - `docs/papers/2409.08264.pdf`
     - `docs/papers/2501.16150.pdf`
     - `docs/papers/2506.16042.pdf`
     - `docs/papers/2509.15221.pdf`
   - 跑 corpus import，再运行：
     - `llmwiki eval result-evidence --root .tmp\paper-v45-acceptance --json`
     - `llmwiki eval result-evidence --root .tmp\paper-v45-acceptance`
   - 记录 sanitized observation：
     - `docs/specs/2026-06-04-llmwiki-v4-5-result-evidence-quality-acceptance-observations.md`
   - 记录 paper count、metric result count、resolvable/context ratio、missing joins、missing context、parser fallback count、table/caption/context availability、top diagnostics、保留 workspace 路径。
   - 不默认运行 clean 清理 `.tmp/paper-v45-acceptance`。
   - 提交：`test: 记录 V4.5 结果证据质量真实验收`

## Test Plan

- Unit/model:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_result_evidence_quality_model.py tests\test_result_evidence_quality_locator.py -q`
- CLI/read-only:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_result_evidence_quality_cli.py tests\test_result_evidence_quality_readonly.py -q`
- Related regression:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_result_model.py tests\test_metric_result_staging.py tests\test_metric_timeline_query.py tests\test_metric_timeline_cli.py -q`
- Docs/contract:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Final automated verification:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_result_evidence_quality_model.py tests\test_result_evidence_quality_locator.py tests\test_result_evidence_quality_cli.py tests\test_result_evidence_quality_readonly.py tests\test_metric_result_model.py tests\test_metric_result_staging.py tests\test_metric_timeline_query.py tests\test_metric_timeline_cli.py tests\test_regression_samples.py -q`
  - `git status --short --ignored`

## Manual Acceptance Metrics

Observation 文件记录：

- imported paper count
- formal claim count
- durable `metric_results` row count
- joined result count
- resolvable locator count and ratio
- context available count and ratio
- PDF result count / markdown result count
- table/caption-related result count
- parser fallback source count
- rows with missing normalized value
- rows with missing method/dataset/task/baseline
- rows with missing claim/source/page/block context
- top diagnostic codes and examples
- preserved acceptance workspace path

## Assumptions And Defaults

- V4.5-min 不做 catalog migration。
- V4.5-min 不修改 V4.3 extraction prompt/schema 和 V4.4 timeline query。
- `claims` 仍是 evidence source of truth；本 eval 只检查 result rows 是否能回溯到 formal claim 和 source context。
- Paper metadata 只用于 display/filter，不作为 result evidence。
- Missing baseline 是常见情况，只作为 info diagnostic。
- Empty result returns exit code `0` with warnings/summary, unless catalog unavailable or args invalid。
- `.tmp/paper-v45-acceptance` 是本次用户要求保留的验收工作区，不在 V4.5 完成后默认 clean。
