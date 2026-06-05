# LLMWiki V4.9 LLM 指标归一化与时间线综合执行计划

## Summary

实现 `docs/specs/2026-06-05-llmwiki-v4-9-llm-metric-normalization-timeline-synthesis-design.md`：新增 CLI-first 的 `llmwiki metric normalize`，让 LLM 基于已有 evidence bundle 自动完成指标名、数据集、任务、年份、结果角色和时间线可比性判断，并生成 staging-only 时间线预览。

方法采用 **spec-driven + contract-first + risk-based TDD**。V4.9 不重跑 MinerU/parser/corpus import/ingest/apply，不修改 catalog，不写 wiki，不提交 `.tmp` 验收工作区。提交按功能拆分，commit summary 使用 conventional prefix，例如 `docs:`、`test:`、`feat:`。

## Key Changes

- 新增命令：
  - `llmwiki metric normalize --root . [--json] [--metric <text>] [--dataset <text>] [--task <text>] [--source-id <id>] [--paper-id <id>] [--limit <n>] [--offset <n>] [--max-groups <n>] [--max-results-per-group <n>] [--reuse-run <run-id>] [--dry-run]`
  - `llmwiki metric normalize-status <normalization-run-id> --root . [--json]`
  - `llmwiki metric timeline-synthesis <normalization-run-id> --root . [--json] [--metric <canonical-metric-id>]`
- 新增模块：`src/llmwiki/metrics/llm_normalization.py`、`src/llmwiki/metrics/llm_normalization_prompt.py`，并扩展 `metrics/formatting.py` 和 `cli.py`。
- 固定 schema：`metric_normalization_run.v4.9`、`metric_evidence_bundle.v4.9`、`metric_normalization_decision.v4.9`、`metric_timeline_group.v4.9`、`metric_timeline_point.v4.9`、`metric_timeline_synthesis.v4.9`、`metric_normalization_warning.v4.9`。
- Staging artifacts 只允许写：`run.json`、`evidence-bundles.jsonl`、`llm-normalization-decisions.jsonl`、`timeline-groups.jsonl`、`timeline-points.jsonl`、`timeline-synthesis.json`、`warnings.jsonl`、`triage.md`。
- `--dry-run` 只构造候选分组和估算，不调用 LLM，不写 staging；正式 `normalize` 调用配置好的 LLM provider 并写 staging run。
- `high` 和无冲突 `medium` 可进入自动时间线预览；`low`、冲突、证据不足必须降级。
- `timeline-synthesis` 第一版只读取 normalize 已生成结果，不再次调用 LLM。

## Implementation Steps

1. 保存 plan 并提交：`docs: 添加 V4.9 LLM 指标归一化执行计划`。
2. 先写失败测试：新增 V4.9 model、bundle、prompt、CLI、staging、readonly、timeline synthesis 测试，覆盖 schema、bundle 构造、prompt 边界、LLM JSON 解析/修复、年份推断、role 判断、自动归一化、timeline group/point、staging、只读/写边界。
3. 实现 evidence bundle 和 dry-run：从 durable `metric_results` join formal `claims/sources`，复用 V4.2 inventory、V4.7 canonicalization 和 V4.8 repair proposals；所有 context 必须 bounded 且带 locator。
4. 实现 LLM prompt、schema 校验和决策模型：解析 `metric_normalization_decision.v4.9`，校验 evidence refs，固定年份和 baseline/prior work 降级规则。
5. 实现 staging normalize run：创建 `run_metric_normalize_<YYYYMMDDHHMMSS>_<hash>` 并写完整 artifacts；`normalize-status` 只读汇总。
6. 实现 timeline group、point 和 synthesis preview：根据 LLM decisions 生成时间线预览，中文 synthesis 必须引用 result/claim/source/citation。
7. 接入 CLI 和格式化：新增 `normalize`、`normalize-status`、`timeline-synthesis`，JSON 使用 `ensure_ascii=False, indent=2`，human 输出展示 summary、decision counts、timeline 和 warnings。
8. 固定安全边界：`--dry-run`、status、synthesis 零 LLM/零写入；正式 normalize 只允许调用 LLM 并写 `staging/<normalization-run-id>/`，禁止 MinerU、parser、import、ingest、apply、ask、writeback、clean。
9. 更新 README、AGENTS、`tests/test_regression_samples.py`，说明 V4.9 是 LLM 自动归一化和 timeline preview，不是 durable apply。
10. 复用 `.tmp/paper-v46-corpus-acceptance` 做真实验收，记录 sanitized observation 到 `docs/specs/2026-06-05-llmwiki-v4-9-llm-metric-normalization-timeline-synthesis-observations.md`。

## Test Plan

- Model/schema：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_llm_normalization_model.py -q`
- Bundle/prompt：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_llm_normalization_bundles.py tests\test_metric_llm_normalization_prompt.py -q`
- CLI/staging/synthesis：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_llm_normalization_cli.py tests\test_metric_llm_normalization_staging.py tests\test_metric_timeline_synthesis.py -q`
- Boundary：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_llm_normalization_readonly.py -q`
- Related regression：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_canonicalization_query.py tests\test_metric_repair_query.py tests\test_result_evidence_quality_model.py tests\test_corpus_inventory.py -q`
- Docs：`.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Final automated verification：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_llm_normalization_model.py tests\test_metric_llm_normalization_bundles.py tests\test_metric_llm_normalization_prompt.py tests\test_metric_llm_normalization_cli.py tests\test_metric_llm_normalization_staging.py tests\test_metric_llm_normalization_readonly.py tests\test_metric_timeline_synthesis.py tests\test_metric_canonicalization_query.py tests\test_metric_repair_query.py tests\test_result_evidence_quality_model.py tests\test_corpus_inventory.py tests\test_regression_samples.py -q`
- `git status --short --ignored`
- 不运行会删除 `.tmp` 验收 workspace 的 clean。

## Assumptions And Defaults

- V4.9 默认使用配置好的真实 LLM provider；测试中使用 monkeypatch fake provider。
- `high` 和无冲突 `medium` 决策可进入自动 timeline preview；`low` 不进入自动可比时间线。
- `baseline` 和 `prior_work` 不默认使用当前论文年份，除非 evidence bundle 中有明确年份或 source identity。
- `timeline-synthesis` 第一版只读取 normalize run 结果，不二次调用 LLM。
- V4.9 不做 durable overlay，不更新 `metric_results`，不改变 `llmwiki metric timeline` 现有行为。
- `.tmp/paper-v46-corpus-acceptance` 继续保留，V4.9 不重跑 full corpus import。
- API key、raw prompt、raw LLM response、parser logs、parser artifacts、PDF 原料、catalog DB、source sidecars、acceptance staging artifacts 不提交。
