# LLMWiki V5.0 Research Relationship Graph Acceptance Observations

日期：2026-06-06

## Scope

本次验收实现并检查 `llmwiki research` 的 V5.0 第一版能力：

- 从已有 catalog-backed claims、durable `metric_results`、V4.2/V4.7/V4.8/V4.9 派生诊断构造关系证据包。
- 调用配置好的 LLM provider 生成 staging-only research relationship graph。
- 从 staged accepted edges 生成 evidence-grounded synthesis preview。

本次没有重跑 MinerU、PDF parser、corpus import、ingest 或 apply。验收复用保留的 `.tmp/paper-v46-corpus-acceptance`，并复用 normalization run `run_metric_normalize_20260605141915_d6d6d379`。

## Commands

Dry-run：

```powershell
.\.venv\Scripts\python.exe -m llmwiki research graph --root .tmp\paper-v46-corpus-acceptance --dry-run --json
```

Bounded real smoke：

```powershell
.\.venv\Scripts\python.exe -m llmwiki research graph --root .tmp\paper-v46-corpus-acceptance --json --max-bundles 8 --reuse-normalization-run run_metric_normalize_20260605141915_d6d6d379
.\.venv\Scripts\python.exe -m llmwiki research graph-status run_research_graph_20260606060325_d0058c48 --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki research synthesize run_research_graph_20260606060325_d0058c48 --root .tmp\paper-v46-corpus-acceptance --json
```

## Dry-Run Summary

- Mode: `dry_run`
- Durable metric results: 414
- Relationship bundles: 183
- Candidate edge estimate: 987
- Estimated prompt tokens: 262447
- Estimated completion tokens: 109800
- Provider calls: 0
- Warning count: 400

解释：全量 graph run 的估算 token 成本较高，因此本次只做 8-bundle bounded smoke，而不是全量 LLM graph run。

## Bounded Real Smoke Summary

- Relationship run id: `run_research_graph_20260606060325_d0058c48`
- Schema: `research_relationship_run.v5.0`
- Relationship bundles processed: 8
- Durable metric results visible to the run: 414
- Edge count: 6
- Accepted edge count: 1
- Needs-review edge count: 5
- Not-comparable edge count: 0
- Fabricated reference count: 0
- Unresolved locator count: 0
- Edge evidence refs: 11
- Provider: `openai`
- Model: `deepseek-v4-flash`
- Provider calls: 8
- LLM total tokens: 17810
- Warning count: 402

Edge counts by type:

- `same_benchmark`: 3
- `same_metric`: 1
- `same_task`: 1
- `compares_against`: 1

Edge counts by status:

- `auto_accepted`: 1
- `needs_review`: 5

Edge counts by confidence:

- `high`: 1
- `low`: 5

## Synthesis Preview Summary

- Synthesis schema: `research_synthesis.v5.0`
- Synthesis item count: 1
- Synthesis evidence refs: 1
- The generated preview preserved real `result_id`, `source_id`, and `citation_locator`.

Preview excerpt:

```text
- same_benchmark: src_fd1c1e7b4d46 -> OSWorld-G，证据 `res_clm_src_fd1c1e7b4d46_llm_167_001` / `src_fd1c1e7b4d46` / `page:11;block:src_fd1c1e7b4d46_p011_b0002;section:4.2 Main Results`。
```

## Boundary Check

- No MinerU/parser/corpus import/ingest/apply rerun was performed.
- `research graph --dry-run` did not call the LLM provider and did not write staging.
- Real `research graph` wrote only the V5.0 staging run under `.tmp/paper-v46-corpus-acceptance/staging/run_research_graph_20260606060325_d0058c48`.
- No durable catalog rows, wiki pages, source sidecars, vector cache, or UI job state were intentionally written by V5.0 commands.
- `.tmp/paper-v46-corpus-acceptance` was preserved for follow-up inspection.

## Interpretation

V5.0 now demonstrates the intended direction: it can convert existing metric/result evidence into cross-paper relationship edges and generate a synthesis preview that carries evidence references instead of free-form narrative.

The smoke result is intentionally conservative. Only 1 of 6 edges entered the default synthesis because low-confidence and needs-review edges are excluded from the default evidence-grounded preview. The next quality bottleneck is not the graph schema; it is relationship decision quality and bundle selection. The most useful follow-up is to improve bundle ranking and prompt examples for `not_comparable`, `compares_against`, and `same_benchmark` so that the LLM returns more high/medium-confidence edges with complete evidence refs.

## Limitations

- This was not a full 183-bundle run.
- The bounded smoke did not produce `not_comparable` edges, so that behavior is covered by automated tests rather than real smoke output.
- The result depends on the preserved `.tmp/paper-v46-corpus-acceptance` workspace and may differ if the corpus is re-ingested.
- The observation excludes raw prompts, raw LLM responses, API keys, parser logs, parser artifacts, PDF raw material, and staging JSONL contents.
