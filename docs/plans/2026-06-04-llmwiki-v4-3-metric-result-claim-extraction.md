# LLMWiki V4.3 Metric And Result Claim Extraction Implementation Plan

## Summary

实现 `docs/specs/2026-06-03-llmwiki-v4-3-metric-result-claim-extraction-design.md`，并对齐 `docs/specs/2026-06-04-llmwiki-paper-oriented-v4-v5-roadmap-spec.md`：扩展 research-paper ingest，让 PDF 论文在现有 `ingest -> staging -> review -> apply` 路径中产生结构化 metric/result records。

V4.3 的正式 evidence 仍然是 formal claims。结构化结果元数据必须引用真实 `claim_id/source_id/citation_locator`，先写入 `staging/<run-id>/metric-results.jsonl` 供 review，再在 apply 后写入 catalog `metric_results` 表，作为 V4.4 metric timeline 的 durable query surface。

方法采用 **spec-driven + contract-first + risk-based TDD + real LLM acceptance**：

- 先用失败测试固定 `metric_result_claim.v4.3` schema、locator validation、staging/apply contract 和 catalog joins。
- 再实现 model、prompt/schema、normalization、dedupe、triage 和 apply 写表。
- 最后用 `docs/papers/` 的真实 LLM 子集验收，再跑完整 20 篇验收并记录观察文件。

计划文件执行时保存为：

`docs/plans/2026-06-04-llmwiki-v4-3-metric-result-claim-extraction.md`

## Key Decisions

- 新增 staging artifact：`staging/<run-id>/metric-results.jsonl`。
- 新增 durable catalog table：`metric_results`。
- 不把结构化 result 字段塞进现有 `claims` 表。
- 不新增 UI。
- 不实现 `llmwiki metric timeline`，该命令属于 V4.4。
- 不新增 relationship classifier 或 durable result relationships，V5.2-min 再处理。
- 不新增生产 mock provider 或 no-network LLM path。
- 不做 broad fallback。真实 acceptance 中出现失败时，先记录命令、source、错误和 artifact，再做窄修复。
- V4.3 不默认修改 source page required sections；review surface 以 `triage.md` 和 `metric-results.jsonl` 为主。

## Catalog Contract

`db.py` 需要新增 `metric_results` 到 `init_db()` 和 `REQUIRED_SCHEMA`。

建议第一版表结构：

```sql
create table if not exists metric_results (
    result_id text primary key,
    schema_version text not null,
    claim_id text not null,
    source_id text not null,
    paper_id text not null,
    claim_text text not null,
    citation_locator text not null,
    confidence_status text not null,
    evidence_block_ids text not null,
    evidence_pages text not null,
    evidence_section_path text not null,
    evidence_block_roles text not null,
    extraction_origin text not null,
    method text not null,
    dataset text not null,
    task text not null,
    metric_name text not null,
    metric_value text not null,
    metric_unit text not null,
    metric_raw_value text not null,
    metric_direction text not null,
    baseline text not null,
    comparison_value text not null,
    setting text not null,
    reported_year integer,
    is_main_result integer,
    value_normalization_status text not null,
    warnings text not null,
    created_at text not null
);
```

List fields are stored as JSON text:

- `evidence_block_ids`
- `evidence_pages`
- `evidence_section_path`
- `evidence_block_roles`
- `warnings`

Indexes:

- `idx_metric_results_claim` on `claim_id`
- `idx_metric_results_source` on `source_id`
- `idx_metric_results_paper` on `paper_id`
- `idx_metric_results_metric` on `metric_name`
- `idx_metric_results_dataset_task` on `dataset, task`

Apply rule:

- `metric_results` rows are written only during `apply_run`.
- A durable row is allowed only when its `claim_id` exists in the applied formal claims and `confidence_status == "cited"`.
- If a result candidate is weak, ambiguous, unsupported, or references a non-applied claim, it remains review-only and is not persisted to `metric_results`.

## Implementation Tasks

### 1. 保存 plan 并提交

- 新增 `docs/plans/2026-06-04-llmwiki-v4-3-metric-result-claim-extraction.md`。
- 运行 `git status --short`，确认只新增 plan。
- 提交：`docs: 添加 V4.3 指标结果抽取执行计划`。

### 2. 先写失败测试

新增测试：

- `tests/test_metric_result_model.py`
- `tests/test_metric_result_locator_validation.py`
- `tests/test_metric_result_extraction.py`
- `tests/test_metric_result_staging.py`

更新测试：

- `tests/test_init_schema.py`
- `tests/test_apply_workflow.py`
- `tests/test_pdf_chunked_ingest.py`
- `tests/test_add_pipeline.py`
- `tests/test_regression_samples.py`

测试覆盖：

- `metric_result_claim.v4.3` schema fields and defaults。
- Missing strings use `""`，missing lists use `[]`，missing booleans/year use `null`。
- Deterministic `result_id` generation after final `claim_id` assignment。
- Numeric/unit normalization: percent, ms, x, points, raw-only, ambiguous, missing。
- PDF locator parsing: `page:N;block:<block-id>;section:...`。
- Partial locator normalization from `block:<block-id>` when page/section are known.
- Invalid block id, wrong source id, missing sidecar, malformed sidecar。
- Table/caption result candidates keep `evidence_block_ids` and `evidence_block_roles`。
- LLM must not choose final `claim_id` or `result_id`; code assigns them.
- Chunk consolidation cannot create new result claims。
- `metric-results.jsonl` rows reference real staged claim ids。
- Apply writes `metric_results` only for cited applied claims。
- Weak/unsupported result candidates stay out of durable `metric_results`。
- `metric_results` rows join to `claims`, `sources`, and V4.2 paper identity fields.
- Non-PDF ingest remains compatible.
- Sanitizer does not leak API keys, raw prompts, raw LLM responses, or parser logs.

提交：`test: 固定 V4.3 指标结果抽取契约`

### 3. 实现 metric result 模型与 validator

新增模块建议：

- `src/llmwiki/ingestion/metric_results.py`

内容：

- `METRIC_RESULT_SCHEMA_VERSION = "metric_result_claim.v4.3"`
- `MetricResultClaim` dataclass。
- `MetricResultCandidate` 或内部 normalized dict helper。
- `normalize_metric_result_payload(...)`
- `normalize_metric_value(...)`
- `parse_pdf_result_locator(...)`
- `validate_pdf_result_locator(...)`
- `assign_metric_result_ids(...)`
- `dedupe_metric_results(...)`
- `serialize_metric_results_jsonl(...)`
- `read_metric_results_jsonl(...)`

设计要点：

- LLM payload 不可信，所有 fields 都要 normalize。
- LLM 不允许输出最终 `claim_id/result_id` 作为 authoritative ID。
- 用 `(claim_text, citation_locator)` 把 result candidate 映射到 deduped formal claim。
- `result_id` 建议生成：`res_<claim_id>_<ordinal>`。
- 对一个 claim 报告多个指标时，允许多个 result rows。
- `paper_id` 第一版默认 `source_id`，可从 V4.2 inventory/paper identity helper 填充。
- 只做保守 normalization，不转换不确定单位，不猜 baseline/dataset/method。

提交：`feat: 新增指标结果模型与校验器`

### 4. 扩展 PDF chunk LLM extraction

修改：

- `src/llmwiki/ingestion/llm_ingest.py`

变更：

- `LLMIngestProposal` 增加 `metric_results: list[dict[str, object]]`。
- `chunk_proposal_schema()` 增加 `metric_result_candidates`。
- `build_chunk_ingest_messages(...)` 明确抽取区域：
  - abstract;
  - method/model only when result is reported;
  - experiment/evaluation/results;
  - table-like blocks;
  - captions;
  - conclusion/discussion/limitations.
- Prompt 要求 result candidate 带 `claim_text` 和 locator，但不要输出 final ids。
- `render_chunk_evidence(...)` 保持 bounded context，并确保 table markdown/caption text 已经进入 evidence。
- `create_chunked_pdf_ingest_proposal(...)` 收集 result candidates，做 locator validation、normalization、dedupe。
- Consolidation prompt 继续禁止创建 formal claims 和 result claims，只能做 source summary/concept/entity。

Result candidate JSON shape for LLM prompt:

```json
{
  "claim_text": "...",
  "citation_locator": "block:<block_id>",
  "confidence_status": "cited",
  "extraction_origin": "table",
  "method": "...",
  "dataset": "...",
  "task": "...",
  "metric_name": "...",
  "metric_raw_value": "...",
  "metric_direction": "higher_is_better",
  "baseline": "",
  "comparison_value": "",
  "setting": "",
  "is_main_result": null,
  "warnings": []
}
```

提交：`feat: 扩展 PDF 指标结果抽取`

### 5. 写 staging artifact 和 triage 展示

修改：

- `src/llmwiki/ingestion/ingest.py`

变更：

- 在创建 run 后写 `metric-results.jsonl`。
- `run.json` 增加 bounded diagnostics：
  - `metric_result_schema`
  - `metric_result_count`
  - `metric_result_cited_count`
  - `metric_result_weak_or_unsupported_count`
  - `metric_result_invalid_locator_count`
  - `metric_result_table_or_caption_count`
- `llm-proposal.json` 保存 sanitized normalized result metadata，不保存 raw prompt。
- `triage.md` 新增 `Metric/Result Claims` 区块：
  - method;
  - dataset;
  - task;
  - metric;
  - value/raw value;
  - claim id;
  - source id;
  - locator;
  - warnings.
- Weak/ambiguous candidates必须可见，但标清楚不会 durable apply。

不做：

- 不修改 source page required sections。
- 不新增 `Reported Results` source page section，除非后续实现中发现 review 不足。

提交：`feat: 写入指标结果 staging artifact`

### 6. 实现 catalog `metric_results` 持久化

修改：

- `src/llmwiki/db.py`
- `src/llmwiki/ingestion/apply.py`
- 必要时更新 `src/llmwiki/workspace.py`、`src/llmwiki/ui/api.py`、`src/llmwiki/lint.py`

变更：

- `init_db()` 创建 `metric_results` 表和 indexes。
- `REQUIRED_SCHEMA` 包含 `metric_results`。
- `schema_status()` 能检查新表。
- `read_metric_results_jsonl(...)` 从 staging 读取 review artifact。
- `apply_run(...)` snapshot/restore catalog 现有逻辑保持有效。
- `sync_catalog(...)` 写入 durable `metric_results` rows。
- 写入前校验：
  - `claim_id` 在当前 applied claim set 中；
  - `source_id` 匹配 claim；
  - `citation_locator` 匹配 claim 或是同一 locator 的规范化形式；
  - `confidence_status == "cited"`；
  - PDF result locator 有 valid block id；
  - JSON list fields 是 list，不接受 arbitrary object。
- Duplicate apply 用 `insert or ignore` 或 `on conflict(result_id) do update`，但不得 duplicate rows。

提交：`feat: 持久化指标结果 catalog 表`

### 7. 边界、安全和文档契约

更新：

- `README.md`
- `AGENTS.md`
- `tests/test_regression_samples.py`

文档内容：

- V4.3 adds structured metric/result claim extraction。
- `metric-results.jsonl` 是 review artifact。
- `metric_results` 是 durable catalog query surface。
- `claims` 仍是 evidence source of truth。
- parser artifacts/logs/diagnostics 不是 evidence。
- V4.3 不新增 UI 和 timeline command。
- real LLM acceptance 必须使用 `docs/papers/` 子集后 full 20-paper run。

提交：`docs: 更新 V4.3 指标结果抽取契约`

### 8. 真实 LLM 子集验收

使用临时 workspace，不修改 `docs/papers/`。

注意：当前 V4.1 discovery 会把相对 source path 解析到 `--root` 下。临时 workspace 验收时应使用绝对 paper path，或把 paper 文件复制到临时 workspace。推荐使用绝对 path：

```powershell
$paperRoot = (Resolve-Path docs\papers).Path
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v43-subset
Copy-Item config\api-keys.toml .tmp\paper-v43-subset\config\api-keys.toml
.\.venv\Scripts\python.exe -m llmwiki corpus import <absolute-path-to-2-or-3-selected-papers> --root .tmp\paper-v43-subset --parser auto
.\.venv\Scripts\python.exe -m llmwiki corpus inventory --root .tmp\paper-v43-subset --json
```

检查：

- 每篇 applied source 有 formal claims。
- `staging/<run-id>/metric-results.jsonl` 存在。
- `state/catalog.sqlite` 有 `metric_results` rows。
- `metric_results` rows join to `claims`。
- result locators 有 page/block anchors。
- table/caption weak cases不被 durable apply。

如果出现真实 LLM/parser/table/locator failure：

- 先记录 observation。
- 写最小失败测试。
- 修复窄问题。
- 重跑最小命令。

提交 observation 或修复时按实际拆分，例如：

- `test: 记录 V4.3 指标结果子集验收`
- `fix: 修复 V4.3 指标结果 locator 校验`

### 9. 完整 20-paper real LLM acceptance

完整验收在 `.tmp/` 下执行，不提交 generated workspace。

建议命令：

```powershell
$paperRoot = (Resolve-Path docs\papers).Path
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v43-acceptance
Copy-Item config\api-keys.toml .tmp\paper-v43-acceptance\config\api-keys.toml
.\.venv\Scripts\python.exe -m llmwiki corpus import $paperRoot --root .tmp\paper-v43-acceptance --recursive --parser auto
.\.venv\Scripts\python.exe -m llmwiki corpus inventory --root .tmp\paper-v43-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki lint --root .tmp\paper-v43-acceptance
```

用 SQLite 查询或 bounded script 记录：

- imported paper count;
- applied source count;
- total formal claims;
- total `metric_results` rows;
- result rows per paper;
- cited result ratio;
- invalid result locator count;
- weak/unsupported result candidate count;
- rows with non-empty method/dataset/task/metric/value/baseline;
- table/caption result count.

写 sanitized observation：

`docs/specs/2026-06-04-llmwiki-v4-3-metric-result-claim-extraction-acceptance-observations.md`

不得提交：

- `.tmp/`;
- generated `sources/`;
- generated `staging/`;
- generated `wiki/`;
- generated `state/*.sqlite`;
- `config/api-keys.toml`;
- raw prompts;
- raw LLM responses;
- parser logs or parser artifact contents.

提交：`test: 记录 V4.3 指标结果真实验收`

## Test Plan

单元和 schema：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_metric_result_model.py tests\test_metric_result_locator_validation.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_init_schema.py -q
```

Ingest/staging：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_metric_result_extraction.py tests\test_metric_result_staging.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_pdf_chunked_ingest.py -q
```

Apply/catalog：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_apply_workflow.py tests\test_add_pipeline.py -q
```

文档契约：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q
```

相关回归：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_add_source.py tests\test_ingest_review.py tests\test_query_lint_doctor.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_corpus_state.py tests\test_corpus_discovery.py tests\test_corpus_runner.py tests\test_corpus_inventory.py -q
```

最终自动验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_metric_result_model.py tests\test_metric_result_locator_validation.py tests\test_metric_result_extraction.py tests\test_metric_result_staging.py tests\test_pdf_chunked_ingest.py tests\test_apply_workflow.py tests\test_add_pipeline.py tests\test_init_schema.py tests\test_regression_samples.py -q
.\.venv\Scripts\python.exe -m llmwiki clean --root .
git status --short --ignored
```

真实验收：

- subset real LLM acceptance first；
- full 20-paper real LLM acceptance before declaring V4.3 complete；
- commit only sanitized observation and narrow fixes；
- clean `.tmp/` unless explicitly preserving acceptance workspace for inspection。

## Acceptance Criteria

V4.3 完成时必须满足：

- PDF ingest can propose metric/result candidates from abstract, method-result, experiment/result, table, caption, conclusion contexts。
- `metric-results.jsonl` is written in staging for runs with result candidates。
- Applied cited result records are persisted to `metric_results`。
- Durable rows join to real `claims` and `sources`。
- Every durable PDF result has valid page/block locator。
- Invalid result locators are rejected or downgraded。
- Unsupported/ambiguous values remain weak or warning-bearing。
- Parser artifacts/logs are not evidence and are not exposed as result support。
- Existing non-PDF ingest and existing retrieval/ask behavior are not broken。
- Full 20-paper real LLM acceptance has a sanitized observation file。

## Assumptions And Defaults

- `paper_id = source_id` in V4.3。
- `metric_results` is a catalog table, not a separate generated cache。
- `metric-results.jsonl` may include weak/ambiguous review candidates, but durable `metric_results` only includes cited applied records。
- JSON list fields in SQLite are stored as JSON text。
- No source page `Reported Results` section in first implementation unless review usability forces it。
- No metric aliases in V4.3。
- No metric timeline command in V4.3。
- No claim relationship classifier in V4.3。
- Real acceptance uses local ignored API keys from `config/api-keys.toml` copied into temporary workspaces only。
