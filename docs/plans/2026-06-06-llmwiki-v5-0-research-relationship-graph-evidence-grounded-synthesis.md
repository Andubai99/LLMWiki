# LLMWiki V5.0 Research Relationship Graph And Evidence-Grounded Synthesis Implementation Plan

## Summary

实现 `docs/specs/2026-06-06-llmwiki-v5-0-research-relationship-graph-evidence-grounded-synthesis-design.md`：新增 CLI-first 的 `llmwiki research` 命令组，把已有 catalog claims、durable `metric_results`、V4.2 inventory、V4.7/V4.8/V4.9 诊断与 staging 结果编译成 source-backed cross-paper relationship graph，并生成 evidence-grounded synthesis preview。

方法采用 **spec-driven + contract-first + risk-based TDD**。V5.0 不重跑 MinerU/parser/corpus import/ingest/apply，不做 catalog migration，不写 wiki，不新增 UI，不做 global scholarly KG，不提交 `.tmp` 验收工作区。提交按功能拆分，commit summary 使用 conventional prefix。

## Key Changes

- 新增命令：
  - `llmwiki research graph --root . [--json] [--dry-run] [--topic <text>] [--source-id <id>] [--paper-id <id>] [--relationship-type <type>] [--metric <text>] [--dataset <text>] [--task <text>] [--limit <n>] [--offset <n>] [--max-bundles <n>] [--max-results-per-bundle <n>] [--reuse-normalization-run <run-id>]`
  - `llmwiki research graph-status <relationship-run-id> --root . [--json]`
  - `llmwiki research synthesize <relationship-run-id> --root . [--json] [--topic <text>]`
- 新增 research 模块：relationship model/bundle/prompt/staging/formatting。
- 固定 schema：`research_relationship_run.v5.0`、`research_relationship_bundle.v5.0`、`research_relationship_edge.v5.0`、`research_graph.v5.0`、`research_synthesis.v5.0`、`research_relationship_warning.v5.0`。
- Real run 只写 `staging/<relationship-run-id>/` 下的 `run.json`、`relationship-bundles.jsonl`、`relationship-edges.jsonl`、`research-graph.json`、`research-synthesis.json`、`warnings.jsonl`、`triage.md`。
- Accepted edge 必须保留真实 evidence refs；`not_comparable` 是一等结果。

## Implementation Steps

1. 保存并提交本计划：`docs: 添加 V5.0 研究关系图谱执行计划`。
2. 先写失败测试，覆盖 model、bundle、prompt、CLI、staging、readonly、synthesis。
3. 实现 bundle 和 dry-run，从 catalog/V4.2/V4.7/V4.8/V4.9 只读构造 bounded relationship bundles。
4. 实现 LLM prompt 和 edge 校验，拒绝或降级 fabricated refs，代码生成稳定 `relationship_id`。
5. 实现 staging graph run 和 `graph-status`。
6. 实现 `research synthesize`，第一版只读取 staged edges，不再次调用 LLM。
7. 接入 CLI 和 JSON/human formatting。
8. 固定安全边界和写入边界。
9. 更新 README、AGENTS、regression docs tests。
10. 复用 `.tmp/paper-v46-corpus-acceptance` 做 dry-run 和 bounded real smoke，记录 sanitized observation。

## Test Plan

- `.\.venv\Scripts\python.exe -m pytest tests\test_research_relationship_model.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests\test_research_relationship_bundles.py tests\test_research_relationship_prompt.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests\test_research_relationship_cli.py tests\test_research_relationship_staging.py tests\test_research_synthesis.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests\test_research_relationship_readonly.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests\test_metric_llm_normalization_bundles.py tests\test_metric_llm_normalization_staging.py tests\test_metric_repair_query.py tests\test_metric_canonicalization_query.py tests\test_result_evidence_quality_model.py tests\test_corpus_inventory.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Final:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_research_relationship_model.py tests\test_research_relationship_bundles.py tests\test_research_relationship_prompt.py tests\test_research_relationship_cli.py tests\test_research_relationship_staging.py tests\test_research_relationship_readonly.py tests\test_research_synthesis.py tests\test_metric_llm_normalization_bundles.py tests\test_metric_llm_normalization_staging.py tests\test_metric_repair_query.py tests\test_metric_canonicalization_query.py tests\test_result_evidence_quality_model.py tests\test_corpus_inventory.py tests\test_regression_samples.py -q`
  - `git status --short`

## Assumptions And Defaults

- V5.0 第一版不做 catalog migration，不更新 durable `relationships`，不写 wiki。
- Real `research graph` 默认可调用配置好的 LLM provider；测试使用 monkeypatch fake provider。
- `research synthesize` 第一版不再次调用 LLM，只读取 staged edges。
- Accepted edge 必须有 evidence refs；low confidence edge 不进入默认 synthesis。
- `.tmp/paper-v46-corpus-acceptance` 继续保留；V5.0 不重跑 full corpus import。
- API key、raw prompt、raw LLM response、parser logs、parser artifacts、PDF 原料、catalog DB、source sidecars、acceptance staging artifacts 不提交。
