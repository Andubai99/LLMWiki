# LLMWiki V4.8 Metric Repair Review Workflow Implementation Plan

## Summary

实现 `docs/specs/2026-06-05-llmwiki-v4-8-metric-repair-review-workflow-design.md`：新增 CLI-first 的指标修复审查流程，把 V4.7 canonicalization/readiness 诊断转成可审查 repair proposals，并支持 staging-only review decisions。V4.8 不重跑 MinerU+LLM，不新增 UI，不做 catalog migration，不修改 durable `metric_results`，不改变 `llmwiki metric timeline` 行为。

方法采用 **spec-driven + contract-first + risk-based TDD**。提交按功能拆分，commit summary 使用 conventional prefix，例如 `docs:`、`test:`、`feat:`。

## Key Changes

- 新增命令：
  - `llmwiki metric repair-plan --root . [--json] [--stage] [--metric <text>] [--dataset <text>] [--task <text>] [--proposal-type <type>] [--limit <n>] [--offset <n>] [--label <text>]`
  - `llmwiki metric repair-status <repair-run-id> --root . [--json]`
  - `llmwiki metric repair-mark <repair-run-id> <proposal-id> --root . --status accepted|rejected|needs_review|blocked [--reason <text>] [--json]`
- 新增 `src/llmwiki/metrics/repair.py`，复用 V4.7 `build_metric_canonicalization_report(...)`、V4.5 `build_result_evidence_quality(...)` 和 V4.2 `build_inventory(...)`。
- 固定 schema：`metric_repair_plan.v4.8`、`metric_repair_proposal.v4.8`、`metric_repair_review_decision.v4.8`、`metric_repair_projection.v4.8`、`metric_repair_warning.v4.8`、`metric_repair_run.v4.8`。
- Proposal 类型：`reported_year_from_paper_identity`、`metric_value_from_v47_suggestion`、`metric_alias_review`、`dataset_alias_review`、`task_alias_review`、`blocked_vague_label`。
- `repair-plan` 默认只读；只有 `--stage` 写入 `staging/<repair-run-id>/`。`repair-mark` 只追加 `metric-repair-decisions.jsonl`，不写 catalog。
- `repair-run-id` 使用稳定前缀加时间戳和短 hash：`run_metric_repair_<YYYYMMDDHHMMSS>_<hash>`。
- Staging artifact 只允许 `run.json`、`metric-repair-plan.json`、`metric-repair-proposals.jsonl`、`metric-repair-decisions.jsonl`、`triage.md`。

## Implementation Steps

1. 保存 plan 并提交：`docs: 添加 V4.8 指标修复审查执行计划`。
2. 先写失败测试：新增 `tests/test_metric_repair_model.py`、`tests/test_metric_repair_query.py`、`tests/test_metric_repair_staging.py`、`tests/test_metric_repair_cli.py`、`tests/test_metric_repair_readonly.py`，覆盖 schema、proposal id determinism、year/value/alias proposals、blocked vague labels、projection、CLI、staging artifacts、decision append、read-only/write-boundary。
3. 实现 repair proposal 模型：limit/offset、deterministic proposal id、year/value/alias/dataset/task/vague-label proposals、summary 和 projection。
4. 实现 staging、status 和 decision 读写：`repair-plan --stage` 写 staging run，`repair-status` 读取 proposals + decisions，`repair-mark` append-only 追加 decision。
5. 接入 CLI 和格式化：新增 `repair-plan`、`repair-status`、`repair-mark`，JSON 使用 `ensure_ascii=False, indent=2`，human 输出只显示 summary、proposal counts、projected readiness、top proposals 和 warnings。
6. 固定边界和安全回归：report-only 命令零写入；staging 命令只写 `staging/<repair-run-id>/`；禁止调用 LLM、embedding、MinerU、parser、add/import、ingest、apply、ask、synthesis、lint、clean、CLI eval recursion。
7. 更新 README、AGENTS、`tests/test_regression_samples.py`，说明 V4.8 是 review workflow，不是 durable repair/apply。
8. 复用 `.tmp/paper-v46-corpus-acceptance` 做只读/staging 验收，记录 sanitized observation 到 `docs/specs/2026-06-05-llmwiki-v4-8-metric-repair-review-workflow-observations.md`。

## Test Plan

- Unit/model：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_repair_model.py -q`
- Query/staging/CLI：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_repair_query.py tests\test_metric_repair_staging.py tests\test_metric_repair_cli.py -q`
- Boundary：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_repair_readonly.py -q`
- Related regression：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_canonicalization_model.py tests\test_metric_canonicalization_query.py tests\test_metric_canonicalization_cli.py tests\test_result_evidence_quality_model.py tests\test_corpus_inventory.py -q`
- Docs：`.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Final automated verification：`.\.venv\Scripts\python.exe -m pytest tests\test_metric_repair_model.py tests\test_metric_repair_query.py tests\test_metric_repair_staging.py tests\test_metric_repair_cli.py tests\test_metric_repair_readonly.py tests\test_metric_canonicalization_model.py tests\test_metric_canonicalization_query.py tests\test_metric_canonicalization_cli.py tests\test_result_evidence_quality_model.py tests\test_corpus_inventory.py tests\test_regression_samples.py -q`
- `git status --short --ignored`
- 不运行会删除 `.tmp` 验收 workspace 的 clean。

## Assumptions And Defaults

- V4.8 不做 durable apply，不更新 `metric_results`。
- Accepted/rejected decisions 是 staging review metadata，不是 evidence。
- `repair-plan` 默认只读；只有 `--stage` 写 staging。
- `repair-mark` 只允许修改同一个 repair staging run 的 decisions JSONL。
- Projection v1 只承诺 year/value repair 的 projected readiness；alias/dataset/task review 只报告潜在影响。
- 所有 proposal acceptance 都必须显式执行 `repair-mark`；不自动接受 high-confidence proposal。
- `.tmp/paper-v46-corpus-acceptance` 继续保留，V4.8 不重跑 full corpus。
- API key、raw prompt、raw LLM response、parser logs、parser artifacts、PDF 原料、catalog DB、source sidecars、acceptance staging artifacts 不提交。
