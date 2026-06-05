# LLMWiki V4.9 LLM 指标归一化与时间线综合验收观察

日期：2026-06-05

## 目标

本次验收验证 V4.9 的 CLI-first LLM 指标归一化流程是否能在不重跑 MinerU、parser、corpus import、ingest、apply 的前提下，复用既有 `.tmp/paper-v46-corpus-acceptance` durable `metric_results`，生成 staging-only 的指标归一化决策、时间线点和中文时间线综合预览。

## 验收工作区

- Root: `.tmp/paper-v46-corpus-acceptance`
- 复用已有 V4.6 full-corpus acceptance workspace。
- 未重新运行 MinerU、parser、corpus import、ingest、apply。
- 未运行会删除该验收工作区的 clean。

## 执行命令

```powershell
.\.venv\Scripts\python.exe -m llmwiki metric normalize --root .tmp\paper-v46-corpus-acceptance --dry-run --json
.\.venv\Scripts\python.exe -m llmwiki metric normalize --root .tmp\paper-v46-corpus-acceptance --json --max-groups 8
.\.venv\Scripts\python.exe -m llmwiki metric normalize-status run_metric_normalize_20260605141915_d6d6d379 --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric timeline-synthesis run_metric_normalize_20260605141915_d6d6d379 --root .tmp\paper-v46-corpus-acceptance --json
```

## Dry-run 观察

- Durable metric result count: 414
- Candidate group count: 195
- Evidence bundle count: 195
- Repair proposal count: 644
- Estimated prompt tokens: 284115
- Estimated completion tokens: 136500

全量 normalize 预计需要 195 次候选组级 LLM 处理，token 规模较大。根据 V4.6 之后固定的昂贵验收规则，本阶段没有执行 full 195-group LLM run，而是使用 `--max-groups 8` 做真实 LLM bounded smoke。

## Bounded LLM Smoke 观察

- Run id: `run_metric_normalize_20260605141915_d6d6d379`
- Provider: `openai`
- Model: `deepseek-v4-flash`
- Provider calls: 8
- LLM total tokens: 17637
- Evidence bundles processed: 8
- Decisions: 17
- Auto accepted decisions: 15
- Needs review decisions: 2
- Blocked decisions: 0
- Conflict decisions: 0
- Timeline groups: 5
- Timeline points: 7
- Warning count: 401

Warning 主要来自上游数据质量诊断，例如 missing baseline、missing normalized metric value、ambiguous label、conservative metric variant grouping。V4.9 另记录了 `missing_evidence_refs_repaired`：真实 LLM 输出中有决策遗漏 evidence refs，但这些 refs 可从同一个 evidence bundle 中安全回填；系统已回填并保留 warning。

## Timeline Synthesis 观察

`timeline-synthesis` 未再次调用 LLM，只读取 normalize staging run。输出为中文短说明，并保留 timeline point 的真实 `result_id`、`claim_id`、`source_id`、`paper_id` 和 `citation_locator`。

示例综合：

> 已生成 5 条候选时间线和 7 个时间线点。示例：accuracy / ScreenSpot-Pro, ScreenSpot-V2, OSWorld-G / GUI agent task 在 2025 有结果，引用 res_clm_src_5fecff38940c_llm_182_001 / clm_src_5fecff38940c_llm_182 / src_5fecff38940c / page:9;block:src_5fecff38940c_p009_b0003;section:4.3 Discussion and Ablation。

## Staging Artifacts

Normalize run 写入并保留：

- `run.json`
- `evidence-bundles.jsonl`
- `llm-normalization-decisions.jsonl`
- `timeline-groups.jsonl`
- `timeline-points.jsonl`
- `timeline-synthesis.json`
- `warnings.jsonl`
- `triage.md`

写入范围限定在 `.tmp/paper-v46-corpus-acceptance/staging/run_metric_normalize_20260605141915_d6d6d379/`。未写入 `state/catalog.sqlite`、`wiki/`、`sources/`、`state/corpus-batches/`、`state/embeddings/` 或 `state/ui-jobs/`。

## 结论

V4.9 的关键链路已通过真实 LLM bounded smoke：

- `--dry-run` 可以不调用 LLM、不写 staging 地估算候选组和成本。
- `normalize` 可以基于已有 catalog-backed metric results 构造 evidence bundle，调用 LLM 生成归一化决策，并写入 staging-only artifacts。
- `normalize-status` 可以只读汇总 run 状态。
- `timeline-synthesis` 可以只读生成中文时间线预览，并保留可审计 evidence refs。
- 本阶段未执行 full 195-group LLM run；该 full run 应只在阶段 closure 或需要完整结果质量评估时执行。
