# LLMWiki V4.6-min Corpus Acceptance Metrics Implementation Plan

## Summary

实现 `docs/specs/2026-06-05-llmwiki-v4-6-min-corpus-acceptance-metrics-design.md`：新增只读命令 `llmwiki eval corpus-results`，把 V4.2 inventory、V4.3 durable `metric_results`、V4.4 timeline readiness、V4.5 result-evidence 质量指标汇总成一个可审计的 corpus acceptance 报告。

方法采用 **spec-driven + contract-first + risk-based TDD**。V4.6-min 不新增 UI、不调用 LLM/embedding/MinerU/parser、不执行 import/ingest/apply、不写 wiki/staging/source/state。真实验收工作区保留，不默认 clean。

## Key Changes

- 新增 CLI：
  - `llmwiki eval corpus-results --root .`
  - `llmwiki eval corpus-results --root . --json`
  - 支持 `--metric`、`--dataset`、`--task`、`--limit`、`--offset`。
- 新增只读 eval 模块：`src/llmwiki/evals/corpus_results.py`。
- 固定 schema：
  - `corpus_results_eval.v4.6`
  - `corpus_results_paper.v4.6`
  - `corpus_results_metric.v4.6`
  - `corpus_results_warning.v4.6`
- JSON 顶层输出固定为：
  - `schema_version/root/generated_at/query/summary/quality_gates/papers/metrics/timeline_readiness/warnings`
- `summary` 聚合：
  - source/paper/batch/applied counts
  - parser backend/fallback 分布
  - formal claim count、durable metric result count
  - per-paper result stats
  - joined/resolvable/context/table/caption/result-text evidence coverage
  - method/dataset/task/value/baseline 缺失计数
  - metric list count、timeline candidate count、missing year count
- `quality_gates` 使用确定性 `pass|warn|fail`：
  - catalog available
  - corpus sources present
  - batch items applied
  - no parser fallback results
  - metric results present
  - all results joined
  - all locators resolvable
  - context available
  - no result errors
  - core fields usable
  - table evidence present
  - timeline candidates present
- `limit=200`，最大 `1000`，`offset>=0`；`limit/offset` 分别应用到 `papers`、`metrics`、`timeline_readiness` 三个列表的稳定排序结果，并在 summary 中保留未分页总数。
- timeline readiness 第一版规则：
  - `row_count >= 2` 且 `paper_count >= 2` 视为 candidate。
  - 若 candidate 的 dated row 不足 2，保留 candidate 但增加 `timeline_candidate_needs_year_repair` warning。
  - 不做 metric alias、unit conversion、ranking、趋势判断或 synthesis。

## Implementation Steps

1. 保存 plan 并提交
   - 新增 `docs/plans/2026-06-05-llmwiki-v4-6-min-corpus-acceptance-metrics.md`。
   - 提交：`docs: 添加 V4.6-min 语料验收指标执行计划`。

2. 先写失败测试
   - 新增：
     - `tests/test_corpus_results_eval_model.py`
     - `tests/test_corpus_results_eval_cli.py`
     - `tests/test_corpus_results_eval_readonly.py`
   - 覆盖 JSON schema、human output、filters、pagination、quality gates、empty corpus、missing catalog、timeline readiness、read-only boundary。
   - 提交：`test: 固定 V4.6-min 语料验收指标契约`。

3. 实现只读汇总模型
   - 复用 V4.2 `build_inventory`、V4.5 `build_result_evidence_quality`、V4.4 metric list/timeline helpers。
   - 查询 catalog 时只读 `sources/claims/metric_results/ingest_runs`；不读取 raw PDF chunks。
   - `papers[]` 只输出 paper/source 级摘要，不输出完整 result rows。
   - `metrics[]` 聚合 metric/dataset/task/source/paper/year/table/caption coverage。
   - malformed JSON list、missing join、missing locator、missing sidecar 转 warning，不崩溃。
   - 提交：`feat: 新增语料验收指标只读汇总模型`。

4. 接入 CLI 和格式化
   - 在 `cli.py` 的 `eval` 命令组加入 `corpus-results`。
   - JSON 使用 `ensure_ascii=False, indent=2`。
   - human 输出包含 summary、quality gates、top papers、top metrics、timeline readiness、warnings。
   - invalid numeric args 或 catalog incompatible 返回 exit code `1`；空语料返回 exit code `0` 并输出 `no_corpus_sources` warning。
   - 提交：`feat: 接入语料验收指标 CLI`。

5. 固定只读边界
   - monkeypatch 禁止调用 LLM、embedding、MinerU、parser、add/import、ingest、apply、ask、synthesis、lint、clean、其他 eval 命令。
   - 文件快照确认不写 `wiki/`、`sources/`、`staging/`、`state/catalog.sqlite`、`state/corpus-batches/`、`state/embeddings/`、`state/ui-jobs/`、`.tmp/`。
   - 提交：`test: 固定 V4.6-min 只读验收边界`。

6. 文档和契约
   - 更新 README 和 AGENTS，说明 `eval corpus-results` 的用途、schema、只读边界、验收工作区保留规则。
   - 更新 `tests/test_regression_samples.py`。
   - 提交：`docs: 更新 V4.6-min 语料验收指标契约`。

7. 真实验收
   - 先在保留的 5 篇 MinerU 修复验收工作区 smoke：
     - `.\.venv\Scripts\python.exe -m llmwiki eval corpus-results --root .tmp\paper-v451-mineru-repair-acceptance --json`
     - `.\.venv\Scripts\python.exe -m llmwiki eval corpus-results --root .tmp\paper-v451-mineru-repair-acceptance`
   - 再创建并保留 `.tmp/paper-v46-corpus-acceptance`，复制 ignored `config/api-keys.toml`，配置 strict MinerU：
     - `mineru_command = "F:/LLMWiki/.venv/Scripts/mineru.exe"`
     - `mineru_backend = "pipeline"`
     - `mineru_method = "auto"`
     - `mineru_extra_args = ["-l", "en"]`
   - 导入完整 `docs/papers/`：
     - `.\.venv\Scripts\python.exe -m llmwiki corpus import .tmp\paper-v46-corpus-acceptance\docs\papers --root .tmp\paper-v46-corpus-acceptance --recursive --parser mineru --json`
   - 运行 JSON/human corpus-results，记录 sanitized observation：
     - `docs/specs/2026-06-05-llmwiki-v4-6-min-corpus-acceptance-metrics-observations.md`
   - 提交：`test: 记录 V4.6-min 完整语料验收指标结果`。

## Test Plan

- Unit/CLI：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_results_eval_model.py tests\test_corpus_results_eval_cli.py -q`
- Read-only：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_results_eval_readonly.py -q`
- Related regression：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_result_evidence_quality_model.py tests\test_metric_timeline_query.py tests\test_corpus_inventory.py -q`
- Docs：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Final automated verification：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_results_eval_model.py tests\test_corpus_results_eval_cli.py tests\test_corpus_results_eval_readonly.py tests\test_result_evidence_quality_model.py tests\test_metric_timeline_query.py tests\test_corpus_inventory.py tests\test_regression_samples.py -q`
  - `git status --short --ignored`
  - 不运行会删除 `.tmp` 验收工作区的 clean。

## Assumptions

- V4.6-min 不做 catalog migration。
- V4.6-min 不新增 UI、wiki writeback、timeline synthesis、metric alias、unit conversion 或自动修复。
- `corpus-results` 是 acceptance/reporting surface，不是 evidence source；evidence authority 仍来自 formal `claims` 和 durable `metric_results`。
- JSON 默认不输出完整 result rows，只输出 corpus/paper/metric/timeline readiness 摘要。
- `.tmp/paper-v46-corpus-acceptance` 和已有 V4.5/V4.5.1 验收工作区保留，方便后续追问实现细节和结果。
