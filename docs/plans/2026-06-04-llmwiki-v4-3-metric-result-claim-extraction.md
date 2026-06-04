# LLMWiki V4.3 Metric And Result Claim Extraction Implementation Plan

## Summary

实现 `docs/specs/2026-06-03-llmwiki-v4-3-metric-result-claim-extraction-design.md`，并对齐 `docs/specs/2026-06-04-llmwiki-paper-oriented-v4-v5-roadmap-spec.md`。

目标：扩展现有 PDF ingest，让论文从 abstract、method-result、experiment/results、tables、captions、conclusion 中抽取结构化 metric/result records。formal claims 仍是 evidence source of truth；结构化结果先写入 `staging/<run-id>/metric-results.jsonl`，apply 后写入 catalog `metric_results` 表，供 V4.4 timeline 使用。

当前仓库状态注意：旧 plan 文件已被用户删除，执行时需要重新写入 `docs/plans/2026-06-04-llmwiki-v4-3-metric-result-claim-extraction.md`，并提交该 plan。

## Key Changes

- 新增 schema：`metric_result_claim.v4.3`。
- 新增 staging artifact：`staging/<run-id>/metric-results.jsonl`。
- 新增 catalog table：`metric_results`，作为 durable query surface。
- 不把结构化 result 字段写进 `claims` 表。
- 不新增 UI，不实现 V4.4 `metric timeline`，不新增 relationship classifier。
- 继续使用现有 `ingest -> staging -> review -> apply`；只有 `apply_run` 可以写 durable catalog rows。
- 真实 acceptance 必须使用 configured real LLM provider，先跑 `docs/papers/` 子集，再跑完整 20 篇。

## Implementation Changes

1. 保存 plan
   - 写入 `docs/plans/2026-06-04-llmwiki-v4-3-metric-result-claim-extraction.md`。
   - 确认 `git status --short` 只包含该 plan replacement。
   - 提交：`docs: 添加 V4.3 指标结果抽取执行计划`。

2. 先写失败测试
   - 新增 tests 覆盖 metric result model、value normalization、locator validation、PDF chunk extraction、staging artifact、apply/catalog persistence。
   - 更新 init/apply/PDF ingest 回归测试，固定 `metric_results` 表存在、apply 后 rows join 到 `claims/sources`。
   - 提交：`test: 固定 V4.3 指标结果抽取契约`。

3. 新增 metric result 模型与校验器
   - 建议新增 `src/llmwiki/ingestion/metric_results.py`。
   - 实现 `METRIC_RESULT_SCHEMA_VERSION = "metric_result_claim.v4.3"`、dataclass、payload normalization、value normalization、PDF locator parsing/validation、dedupe、JSONL read/write。
   - LLM 输出不得决定最终 `claim_id/result_id`；代码在 deduped formal claim 生成后分配。
   - `result_id` 使用稳定格式：`res_<claim_id>_<ordinal>`。
   - `paper_id` 默认 `source_id`。
   - 提交：`feat: 新增指标结果模型与校验器`。

4. 扩展 PDF chunk LLM ingest
   - 在 chunk schema 中加入 `metric_result_candidates`。
   - Prompt 明确只从 bounded chunk evidence 抽取 result candidates，覆盖 abstract、method-result、experiment/results、tables、captions、conclusion。
   - result candidate 必须包含 `claim_text`、locator、metric/method/dataset/task/value fields；缺失字段用空字符串或 null。
   - Consolidation step 继续禁止创建 claims/result claims，只做 source summary/concept/entity。
   - 无效 block id、跨 source block、缺失 locator 的 candidate 不得成为 cited durable result。
   - 提交：`feat: 扩展 PDF 指标结果抽取`。

5. 写 staging artifact 和 triage
   - `ingest_source` 写 `metric-results.jsonl`。
   - `run.json` 增加 bounded diagnostics：result count、cited count、weak/unsupported count、invalid locator count、table/caption count。
   - `triage.md` 增加 Metric/Result Claims 区块，展示 method、dataset、task、metric、value、claim id、source id、locator、warnings。
   - `llm-proposal.json` 只保存 sanitized normalized metadata，不保存 raw prompt。
   - 提交：`feat: 写入指标结果 staging artifact`。

6. 持久化 catalog `metric_results`
   - `db.py` 在 `init_db()` 和 `REQUIRED_SCHEMA` 中加入 `metric_results`。
   - 表字段保留 V4.3 schema：`result_id/schema_version/claim_id/source_id/paper_id/claim_text/citation_locator/confidence_status/evidence_block_ids/evidence_pages/evidence_section_path/evidence_block_roles/extraction_origin/method/dataset/task/metric_name/metric_value/metric_unit/metric_raw_value/metric_direction/baseline/comparison_value/setting/reported_year/is_main_result/value_normalization_status/warnings/created_at`。
   - list fields 存 JSON text；`reported_year` nullable integer；`is_main_result` nullable integer。
   - indexes：claim/source/paper/metric/dataset-task。
   - `apply_run` 从 staging 读取 `metric-results.jsonl`，只对已 applied cited formal claims 写 durable rows。
   - Duplicate apply 不产生重复 rows。
   - 提交：`feat: 持久化指标结果 catalog 表`。

7. 文档和契约
   - 更新 README、AGENTS、regression docs tests。
   - 明确 `claims` 是 evidence source of truth，`metric_results` 是结构化查询表。
   - 明确 V4.3 不新增 UI/timeline/relationship classifier。
   - 提交：`docs: 更新 V4.3 指标结果抽取契约`。

8. 真实 LLM acceptance
   - 子集验收：在 `.tmp/paper-v43-subset` 初始化临时 workspace，复制本地 ignored `config/api-keys.toml`，用 `docs/papers/` 中 2-3 篇论文跑 real LLM import。
   - 完整验收：在 `.tmp/paper-v43-acceptance` 跑完整 20 篇 `docs/papers/`。
   - 记录 sanitized observation：`docs/specs/2026-06-04-llmwiki-v4-3-metric-result-claim-extraction-acceptance-observations.md`。
   - 记录指标：paper count、formal claim count、metric_results row count、rows per paper、cited ratio、invalid locator count、weak/unsupported count、non-empty method/dataset/task/metric/value/baseline counts。
   - 如果真实失败，先记录具体 command/source/error/artifact，再写最小失败测试和窄修复。
   - 提交 observation：`test: 记录 V4.3 指标结果真实验收`。

## Test Plan

- Unit/schema:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_result_model.py tests\test_metric_result_locator_validation.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_init_schema.py -q`

- Ingest/staging:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_result_extraction.py tests\test_metric_result_staging.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_pdf_chunked_ingest.py -q`

- Apply/catalog:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_apply_workflow.py tests\test_add_pipeline.py -q`

- Docs/regression:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_add_source.py tests\test_ingest_review.py tests\test_query_lint_doctor.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_state.py tests\test_corpus_discovery.py tests\test_corpus_runner.py tests\test_corpus_inventory.py -q`

- Final:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_result_model.py tests\test_metric_result_locator_validation.py tests\test_metric_result_extraction.py tests\test_metric_result_staging.py tests\test_pdf_chunked_ingest.py tests\test_apply_workflow.py tests\test_add_pipeline.py tests\test_init_schema.py tests\test_regression_samples.py -q`
  - `.\.venv\Scripts\python.exe -m llmwiki clean --root .`
  - `git status --short --ignored`

## Assumptions And Defaults

- `paper_id = source_id` in V4.3。
- Durable `metric_results` only stores cited applied records。
- Weak/ambiguous/unsupported candidates may appear in staging/triage but not durable catalog rows。
- JSON list fields in SQLite are stored as JSON text。
- Source pages do not get a new required `Reported Results` section in V4.3。
- No metric aliases, no metric timeline command, no relationship classifier in V4.3。
- Generated `.tmp/`, `sources/`, `staging/`, `wiki/`, `state/*.sqlite`, `config/api-keys.toml`, raw prompts, raw LLM responses, parser logs, and parser artifact contents must not be committed。
