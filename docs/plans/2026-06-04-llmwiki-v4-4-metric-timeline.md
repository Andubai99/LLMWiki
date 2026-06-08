# LLMWiki V4.4 Metric Timeline Implementation Plan

## Summary

实现 `docs/specs/2026-06-04-llmwiki-v4-4-metric-timeline-design.md`：新增 CLI-first、只读的指标时间线查询，把 V4.3 durable `metric_results` 转成可审计的 metric evolution 输出。

方法采用 **spec-driven + contract-first + risk-based TDD**。V4.4 不新增 UI、不调用 LLM/embedding/parser、不搜索 raw PDF chunk、不写 wiki/staging/source/state。提交必须按功能拆分，commit summary 使用 conventional prefix，例如 `docs:`、`test:`、`feat:`。

## Key Changes

- 新增命令组：
  - `llmwiki metric list --root . [--query <text>] [--dataset <text>] [--task <text>] [--limit <n>] [--offset <n>] [--json]`
  - `llmwiki metric timeline "<metric>" --root . [--dataset <text>] [--task <text>] [--method <text>] [--source-id <id>] [--paper-id <id>] [--year-from <year>] [--year-to <year>] [--limit <n>] [--offset <n>] [--json]`
- 新增只读 metrics 模块，放在 `src/llmwiki/metrics/`：
  - `timeline.py`：query/model/normalization/warnings
  - `formatting.py`：JSON payload 和 human table
- 固定 schema：
  - timeline response: `metric_timeline.v4.4`
  - timeline item: `metric_timeline_item.v4.4`
  - metric list response: `metric_list.v4.4`
- 查询数据源：
  - 主表只读 `metric_results`
  - 必须 join `claims`、`sources`
  - 通过 V4.2 inventory helper 补充 paper title/authors/year/DOI/arXiv/page_path
  - metadata 只用于显示和排序，不作为 result evidence
- 默认策略：
  - 命令组只实现单数 `metric`，不加 `metrics` alias
  - `metric list` 按 normalized metric key 聚合；`metric_name` 选该组内出现次数最多、再按字典序稳定选择的显示名
  - timeline metric/dataset/task/method 使用 exact casefold 或 normalized equality，不做 substring、不做 alias expansion
  - JSON item 增加 `timeline_year`，用于暴露实际排序年份
  - 无年份 rows 默认显示在 dated rows 后；若指定 year range，则缺失年份 rows 排除并给 `missing_year` warning
  - `limit=100`，最大 `500`，`offset>=0`
  - 空结果 exit code 为 `0`，返回 `no_catalog_backed_result` warning
  - invalid args / missing catalog / incompatible schema exit code 为 `1`

## Implementation Steps

1. 保存 plan 并提交
   - 新增 `docs/plans/2026-06-04-llmwiki-v4-4-metric-timeline.md`
   - 提交：`docs: 添加 V4.4 指标时间线执行计划`

2. 先写失败测试
   - 新增：
     - `tests/test_metric_timeline_model.py`
     - `tests/test_metric_timeline_query.py`
     - `tests/test_metric_timeline_cli.py`
     - `tests/test_metric_timeline_readonly.py`
   - 覆盖 normalization、JSON schema、metric list 聚合、timeline join、排序、filters、empty result、invalid args、duplicate warnings、missing joins、read-only boundary。
   - 提交：`test: 固定 V4.4 指标时间线契约`

3. 实现 timeline 模型和只读查询
   - 新增 `src/llmwiki/metrics/timeline.py`
   - 实现 schema constants、dataclass 或稳定 dict builder、`normalize_timeline_key()`、`build_metric_list()`、`build_metric_timeline()`
   - 查询前调用 catalog schema 检查；`metric_results` 缺失或 schema incompatible 返回 `catalog_unavailable` 错误路径
   - SQL bounded 查询，先按 filters 获取候选，再在 Python 中做 normalized equality 和稳定排序
   - JSON list fields 从 `metric_results` 的 JSON text 解析；malformed 时保留 row 但追加 warning
   - 对不能 join 到 `claims/sources` 的 rows 不作为 normal items 输出，只计入 warnings
   - 提交：`feat: 新增指标时间线只读查询模型`

4. 接入 CLI 和格式化
   - 修改 `cli.py` 新增 `metric` subparser、`cmd_metric_list`、`cmd_metric_timeline`
   - 新增 `src/llmwiki/metrics/formatting.py`
   - JSON 输出使用 `json.dumps(..., ensure_ascii=False, indent=2)`
   - human output 使用紧凑表格；长 title/claim/locator 可截断，JSON 保留完整值
   - invalid numeric args 在 CLI 层明确返回 `1`
   - 提交：`feat: 接入指标时间线 CLI`

5. 固定只读边界和文档契约
   - `test_metric_timeline_readonly.py` monkeypatch 禁止调用 LLM、embedding、MinerU、parser、add/import、ingest、apply、ask、synthesis、lint、eval、clean
   - 文件快照确认命令不写 `wiki/`、`sources/`、`staging/`、`state/catalog.sqlite`、`state/corpus-batches/`、`state/embeddings/`、`state/ui-jobs/`、`.tmp/`
   - README 增加 V4.4 CLI 用法；AGENTS 增加 V4.4 只读 metric timeline 边界
   - 更新 `tests/test_regression_samples.py`
   - 提交：`docs: 更新 V4.4 指标时间线契约`

6. 真实 LLM acceptance
   - 使用 `.tmp/paper-v44-acceptance` 初始化临时 workspace
   - 复制本地 ignored `config/api-keys.toml` 到临时 workspace config
   - 跑完整 `docs/papers/` 20 篇 corpus import，随后运行：
     - `llmwiki metric list --root .tmp\paper-v44-acceptance --json`
     - 从 list 中选择 row_count/source_count 较高的 metric
     - `llmwiki metric timeline "<metric-from-list>" --root .tmp\paper-v44-acceptance --json`
     - `llmwiki metric timeline "<metric-from-list>" --root .tmp\paper-v44-acceptance`
     - 对一个不存在 metric 验证 empty-result warning
   - 记录 sanitized observation：
     - `docs/observations/2026-06-04-llmwiki-v4-4-metric-timeline-acceptance-observations.md`
   - 提交：`test: 记录 V4.4 指标时间线真实验收`

## Test Plan

- Unit/query：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_timeline_model.py tests\test_metric_timeline_query.py -q`
- CLI/read-only：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_timeline_cli.py tests\test_metric_timeline_readonly.py -q`
- V4.3/V4.4 regression：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_result_model.py tests\test_metric_result_staging.py tests\test_init_schema.py -q`
- Docs/contract：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Related corpus regression：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_inventory.py tests\test_corpus_runner.py tests\test_corpus_cli.py -q`
- Final automated verification：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_timeline_model.py tests\test_metric_timeline_query.py tests\test_metric_timeline_cli.py tests\test_metric_timeline_readonly.py tests\test_metric_result_model.py tests\test_metric_result_staging.py tests\test_corpus_inventory.py tests\test_regression_samples.py -q`
  - `.\.venv\Scripts\python.exe -m llmwiki clean --root . --dry-run`
  - `.\.venv\Scripts\python.exe -m llmwiki clean --root .`
  - `git status --short --ignored`

## Manual Acceptance Metrics

Observation 文件记录：

- imported paper count
- formal claim count
- durable `metric_results` row count
- metric list count
- selected metric query
- timeline row count
- timeline source diversity
- timeline paper diversity
- rows with `result_id/claim_id/source_id/citation_locator`
- rows with missing year
- rows with missing normalized value
- duplicate-looking warning count
- absent metric empty-result warning behavior

## Assumptions And Defaults

- V4.4 不做 catalog migration；直接读取 V4.3 `metric_results`。
- 不实现 `llmwiki metrics` plural alias。
- 不实现 `--format markdown` 或 `--output`。
- 不做 metric alias curation、unit conversion、ranking、trend/gap/synthesis。
- 不调用 LLM、embedding、parser、retrieve、ask、eval。
- `metric list` 是 discovery 输出，不是 evidence。
- timeline rows 的 evidence authority 来自 joined formal `claims`，不是 paper metadata。
- 真实 acceptance 的 `.tmp/` workspace、生成态 source/wiki/staging/state、API key、副产物和 parser artifacts 不提交，验收后用默认 clean 清理缓存和临时 workspace。
