# LLMWiki V4.5.1 MinerU Result Extraction Quality Repair Implementation Plan

## Summary

实现 `docs/specs/2026-06-04-llmwiki-v4-5-1-mineru-result-extraction-quality-repair-design.md`：修复严格 MinerU 验收可用性，并提升 V4.3 `metric-results` 对表格、caption、result-text block 的覆盖率。方法采用 **spec-driven + contract-first + risk-based TDD**。

V4.5.1 不新增 UI、不做 catalog migration、不改 V4.4 timeline 语义。验收工作区和结果默认保留，不运行会删除 `.tmp` 验收结果的 clean。

## Key Changes

- 修复 MinerU 可用性：
  - 修正 `.tmp` 验收 workspace 下对 repo `.venv/Scripts/mineru.exe` 的发现逻辑。
  - `llmwiki init` 生成的 `[pdf_parser]` 推荐配置改为 `mineru_backend = "pipeline"`、`mineru_method = "auto"`；`mineru_extra_args` 不全局默认加 `-l en`，只在本次 5 篇英文验收 workspace 中配置。
  - `llmwiki parsers status` 显示 MinerU command、backend、method、extra args，便于确认是否严格 MinerU 而非 fallback。
- 提升 result evidence 覆盖：
  - 为 PDF chunk 构造增加 result-focused table/caption/heading/result-text 上下文，避免表格和 caption 被普通 section chunk 淹没。
  - Prompt 明确要求从可见表格单元、caption、nearby heading 和 result text 中抽取具体数值；禁止把 `See table`、`not reported` 等占位文本作为最终 cited metric value。
  - 保留主 locator 为一个真实 block，同时把相关 table/caption/heading/result-text block 写入 `evidence_block_ids`、`evidence_block_roles`、`evidence_pages`。
  - 对 table block 分类为 `result_table`、`ablation_or_diagnostic_table`、`dataset_inventory_table`、`paper_metadata_or_reference_table`、`ambiguous_table`，优先抽取 result/ablation 类表格。
- 固定质量目标：
  - 5 篇 strict MinerU 全部 applied，且 parser backend 为 `mineru`、无 fallback rows。
  - durable `metric_results` 目标从当前 MinerU baseline 53 提升到至少 70；stretch 是达到或超过 pypdf baseline 73。
  - table result context 大于 12，caption result context 在存在相关 caption 时大于 0。
  - referenced candidate table blocks 至少 10，caption blocks 在相关时大于 0。
  - method/dataset/task/value 缺失数不差于当前 MinerU baseline；`error_count = 0`。

## Implementation Steps

1. 保存 plan 并提交
   - 新增 `docs/plans/2026-06-04-llmwiki-v4-5-1-mineru-result-extraction-quality-repair.md`。
   - 提交：`docs: 添加 V4.5.1 MinerU 结果抽取质量修复执行计划`。

2. 先写失败测试
   - 覆盖 MinerU command discovery、parser status 输出、初始化配置模板、strict MinerU acceptance profile。
   - 覆盖 result-focused chunk 构造、table/caption/heading context pairing、multi-block evidence preservation、placeholder value rejection。
   - 覆盖 staging `metric-results.jsonl`、apply 后 durable rows、result evidence quality summary。
   - 提交：`test: 固定 V4.5.1 MinerU 结果抽取修复契约`。

3. 修复 MinerU 配置与可观测性
   - 修正 `mineru_runner` 对 repo `.venv` 的查找，确保从 `.tmp` workspace 运行也能发现 `F:/LLMWiki/.venv/Scripts/mineru.exe`。
   - 更新 workspace config template 和 parser status human/json 输出。
   - 保持显式 `--parser mineru` 为 strict：MinerU 不可用或解析失败时直接失败，不 fallback。
   - 提交：`feat: 修复 MinerU 验收配置与状态输出`。

4. 增强 PDF result chunking
   - 在 chunk 构造中增加 result-focused chunk 或 result-focused context selection。
   - 表格 chunk 必须包含相邻 heading、caption、相关 result text；caption chunk 必须携带关联 table/image/formula/result text。
   - 控制 chunk 大小，避免把无关 reference table、metadata table、大段正文混入候选 evidence。
   - 提交：`feat: 增强表格与标题结果证据块构造`。

5. 增强 LLM 抽取与校验
   - 更新 chunk prompt/schema 说明，让候选输出包含 primary locator 和 auxiliary evidence block ids。
   - 校验器只接受 workspace 内、同 source、同 chunk allowed set 的 evidence block ids。
   - 如果 raw value 是占位文本但同一 evidence bundle 中有具体数值，则拒绝该候选或降级为 weak staging candidate，不写 durable `metric_results`。
   - `metric_result_from_candidate` 保留 validated auxiliary blocks，不再只保存 primary locator block。
   - 提交：`feat: 提升指标结果候选校验与多块证据保留`。

6. 增加质量对比命令或脚本化验收辅助
   - 复用现有 `eval result-evidence`，必要时补充只读统计 helper，输出 durable row count、table/caption context、missing fields、invalid locator、warnings。
   - 对比 `.tmp/paper-v45-acceptance`、`.tmp/paper-v45-mineru-acceptance` 和新 `.tmp/paper-v451-mineru-repair-acceptance`。
   - 只记录 sanitized observations，不写 raw prompt、raw response、parser log、API key。
   - 提交：`test: 固定 V4.5.1 结果证据质量对比`。

7. 更新文档契约
   - README/AGENTS 增加 V4.5.1 strict MinerU、result-focused chunk、多块 evidence、验收保留规则。
   - 更新 `tests/test_regression_samples.py` 覆盖新增文档契约。
   - 提交：`docs: 更新 V4.5.1 MinerU 质量修复契约`。

8. 真实 5 篇验收
   - 新建并保留 `.tmp/paper-v451-mineru-repair-acceptance`。
   - 复制本地 ignored `config/api-keys.toml`，配置 strict MinerU：
     - `mineru_enabled = true`
     - `mineru_command = "F:/LLMWiki/.venv/Scripts/mineru.exe"`
     - `mineru_backend = "pipeline"`
     - `mineru_method = "auto"`
     - `mineru_extra_args = ["-l", "en"]`
   - 导入固定 5 篇论文并运行 result evidence eval。
   - 记录 `docs/observations/2026-06-04-llmwiki-v4-5-1-mineru-result-extraction-quality-repair-acceptance-observations.md`。
   - 提交：`test: 记录 V4.5.1 MinerU 修复验收结果`。

## Test Plan

- MinerU/config/status：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_mineru_runner.py tests\test_pdf_parser_backends.py tests\test_parser_status_cli.py -q`
- Chunking/extraction：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_source_chunks.py tests\test_pdf_chunked_ingest.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_result_model.py tests\test_metric_result_locator_validation.py tests\test_metric_result_extraction.py tests\test_metric_result_staging.py -q`
- Apply/eval/regression：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_apply_workflow.py tests\test_add_pipeline.py tests\test_result_evidence_quality_model.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Final automated verification：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_mineru_runner.py tests\test_pdf_parser_backends.py tests\test_parser_status_cli.py tests\test_source_chunks.py tests\test_pdf_chunked_ingest.py tests\test_metric_result_model.py tests\test_metric_result_locator_validation.py tests\test_metric_result_extraction.py tests\test_metric_result_staging.py tests\test_apply_workflow.py tests\test_add_pipeline.py tests\test_result_evidence_quality_model.py tests\test_regression_samples.py -q`
  - `git status --short --ignored`
  - 不默认运行会清理 `.tmp` 验收 workspace 的 `llmwiki clean`。

## Manual Acceptance

- Baseline 对比对象：
  - `.tmp/paper-v45-acceptance`：pypdf/fallback baseline，73 durable `metric_results`。
  - `.tmp/paper-v45-mineru-acceptance`：strict MinerU baseline，53 durable `metric_results`，table context 12，caption context 0。
  - `.tmp/paper-v451-mineru-repair-acceptance`：本次修复后结果。
- 验收命令：
  - `.\.venv\Scripts\python.exe -m llmwiki parsers status --root .tmp\paper-v451-mineru-repair-acceptance`
  - `.\.venv\Scripts\python.exe -m llmwiki corpus import .tmp\paper-v451-mineru-repair-acceptance\docs\papers --root .tmp\paper-v451-mineru-repair-acceptance --recursive --parser mineru --json`
  - `.\.venv\Scripts\python.exe -m llmwiki eval result-evidence --root .tmp\paper-v451-mineru-repair-acceptance --json`
  - `.\.venv\Scripts\python.exe -m llmwiki metric list --root .tmp\paper-v451-mineru-repair-acceptance --json`
- 验收记录必须包含：
  - imported paper count、formal claim count、durable metric_results count。
  - parser_backend 分布、fallback row count。
  - table/caption/result-text evidence block coverage。
  - method/dataset/task/value/baseline missing counts。
  - invalid locator、unsupported locator、warnings、errors。
  - 与两个旧 baseline 的差异和仍未覆盖的主要原因。

## Assumptions And Defaults

- V4.5.1 不改变 `metric_results` catalog schema；只改变抽取质量、候选校验和 evidence block 填充。
- 主 locator 仍是单个真实 block；多块上下文通过 `evidence_block_ids` 表达。
- Caption 覆盖目标只在 MinerU sidecar 中存在可关联 caption 时作为硬质量目标；否则记录为 warning 和观察项。
- `.tmp` 验收结果保留给用户追问实现细节和结果，不自动清理。
- API key、raw prompt、raw LLM response、parser logs、parser artifacts、PDF 原料和生成态 workspace 不提交。
