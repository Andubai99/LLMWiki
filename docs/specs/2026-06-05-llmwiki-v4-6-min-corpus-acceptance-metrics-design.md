# LLMWiki V4.6-min Corpus Acceptance Metrics Design

Date: 2026-06-05

## 1. Summary

V4.6-min adds a CLI-first, read-only corpus acceptance report for paper-oriented LLMWiki work:

```powershell
llmwiki eval corpus-results --root . --json
llmwiki eval corpus-results --root .
```

The goal is to answer one question:

> Given an imported research corpus, is the corpus good enough to support source-backed metric evolution and later V5 research intelligence work?

V4.6-min aggregates existing V4 surfaces instead of re-extracting knowledge:

- V4.2 `corpus inventory` paper identity and duplicate warnings;
- V4.3 durable `metric_results`;
- V4.4 `metric list` / timeline-readiness primitives;
- V4.5 `result-evidence` join, locator, context, parser, and missing-field diagnostics;
- V4.5.1 strict MinerU result extraction quality observations.

V4.6-min is an evaluation and reporting layer. It must not call LLM providers, embedding providers, MinerU, parser execution, add/import, ingest, apply, ask, synthesis, lint, clean, or raw PDF chunk retrieval.

## 2. Motivation

V4.5.1 proved that the fixed 5-paper strict MinerU subset can produce useful durable result records:

- 5/5 papers applied;
- 1777 formal claims;
- 91 durable `metric_results`;
- 91/91 joined and locator-resolved rows;
- parser backend distribution `{"mineru": 91}`;
- parser fallback count `0`;
- table result count `51`;
- caption result count `1`;
- missing method/dataset/task counts `0`;
- missing normalized value count `19`;
- error count `0`.

That is enough to trust the extraction path on a small subset, but not enough to know whether the broader `docs/papers` corpus is ready. V4.6-min should make corpus-wide readiness measurable before moving into V5 relation classification, conflict detection, maintenance planning, or living synthesis updates.

## 3. Scope

V4.6-min implements one read-only command:

```powershell
llmwiki eval corpus-results --root . [--json]
```

Optional filters are allowed only if they stay simple and read-only:

```powershell
--metric <text>
--dataset <text>
--task <text>
--limit <n>
--offset <n>
```

If filters are included in the first implementation, they should use the same conservative normalized equality rules as V4.4/V4.5. If implementation cost is high, first version may omit filters except `--json`; the implementation plan should decide.

V4.6-min does not add:

- UI or dashboard pages;
- new catalog tables or schema migration;
- new extraction prompts;
- metric alias curation;
- unit conversion;
- trend/gap/synthesis generation;
- relation classification;
- conflict detection;
- maintenance planning;
- wiki writeback;
- automatic repairs.

## 4. Command Contract

### 4.1 CLI

Human output:

```powershell
llmwiki eval corpus-results --root .
```

JSON output:

```powershell
llmwiki eval corpus-results --root . --json
```

Exit behavior:

- exit `0` when evaluation completes, even if quality warnings are found;
- exit `1` for invalid arguments, missing catalog, incompatible schema, or unreadable bounded sidecar files needed for local diagnostics;
- empty corpus exits `0` with a `no_corpus_sources` warning.

### 4.2 Schema Versions

Top-level response:

```text
corpus_results_eval.v4.6
```

Nested item schemas:

```text
corpus_results_paper.v4.6
corpus_results_metric.v4.6
corpus_results_warning.v4.6
```

V4.6-min must preserve original machine/audit values:

- `source_id`;
- `paper_id`;
- `claim_id`;
- `result_id`;
- `citation_locator`;
- `parser_backend`;
- `parser_backend_fallback_from`;
- `confidence_status`;
- metric names, dataset names, task names, method names as stored.

Human output may use Chinese labels in future, but JSON keys and machine values remain stable English identifiers.

## 5. JSON Shape

Top-level JSON:

```json
{
  "schema_version": "corpus_results_eval.v4.6",
  "root": "F:/LLMWiki/.tmp/paper-v46-corpus-acceptance",
  "generated_at": "2026-06-05T00:00:00+00:00",
  "query": {
    "metric": "",
    "dataset": "",
    "task": "",
    "limit": 200,
    "offset": 0
  },
  "summary": {},
  "quality_gates": [],
  "papers": [],
  "metrics": [],
  "timeline_readiness": [],
  "warnings": []
}
```

Missing strings use `""`; missing numeric values use `0` or `null` according to meaning; missing lists use `[]`; missing dicts use `{}`.

The command should not include raw prompts, raw LLM responses, parser logs, parser artifact paths beyond already sanitized catalog/metadata fields, or API key paths/values.

## 6. Summary Metrics

The `summary` object should include:

```text
corpus_source_count
pdf_source_count
non_pdf_source_count
applied_source_count
failed_batch_item_count
pending_batch_item_count
skipped_batch_item_count
duplicate_paper_warning_count
paper_identity_warning_count
parser_backend_distribution
parser_fallback_source_count
parser_fallback_result_count
formal_claim_count
metric_result_count
metric_result_count_per_paper_min
metric_result_count_per_paper_max
metric_result_count_per_paper_mean
metric_result_count_per_paper_median
papers_with_zero_metric_results
joined_result_count
resolvable_locator_count
context_available_count
result_locator_error_count
table_result_count
caption_result_count
result_text_context_count
unique_table_block_count
unique_caption_block_count
missing_method_count
missing_dataset_count
missing_task_count
missing_value_count
missing_baseline_count
result_warning_count
result_error_count
metric_list_count
timeline_ready_metric_count
timeline_candidate_row_count
timeline_source_diversity_max
timeline_paper_diversity_max
missing_year_count
```

Definitions:

- `corpus_source_count`: number of catalog-backed sources included in evaluation.
- `applied_source_count`: catalog sources with applied ingest runs or applied status.
- `failed_batch_item_count`: failed V4.1 batch items observed in `state/corpus-batches/`; batch-only items do not become papers.
- `parser_backend_distribution`: source-level parser backend distribution from metadata/inventory.
- `parser_fallback_result_count`: result rows whose source metadata shows parser fallback.
- `metric_result_count`: durable rows in catalog `metric_results` after joins/filters.
- `papers_with_zero_metric_results`: catalog papers that are applied but have no durable metric result rows.
- `table_result_count`: result rows whose primary or auxiliary evidence roles include `table`.
- `caption_result_count`: result rows whose primary or auxiliary evidence roles include `caption`.
- `unique_table_block_count`: unique table block ids referenced by durable result evidence.
- `unique_caption_block_count`: unique caption block ids referenced by durable result evidence.
- `timeline_ready_metric_count`: metric groups that meet the first-version timeline readiness policy.

## 7. Per-Paper Items

Each `papers[]` item should summarize one catalog-backed paper/source:

```json
{
  "schema_version": "corpus_results_paper.v4.6",
  "source_id": "src_xxx",
  "paper_id": "src_xxx",
  "title": "...",
  "authors": [],
  "year": 2025,
  "doi": "",
  "arxiv_id": "2509.15221",
  "source_type": "pdf",
  "applied_status": "applied",
  "applied_run_id": "run_xxx",
  "parser_backend": "mineru",
  "parser_backend_fallback_from": "",
  "formal_claim_count": 0,
  "metric_result_count": 0,
  "joined_result_count": 0,
  "resolvable_locator_count": 0,
  "context_available_count": 0,
  "table_result_count": 0,
  "caption_result_count": 0,
  "missing_method_count": 0,
  "missing_dataset_count": 0,
  "missing_task_count": 0,
  "missing_value_count": 0,
  "missing_baseline_count": 0,
  "top_metrics": [],
  "warnings": []
}
```

`papers[]` should be sorted by:

1. descending `metric_result_count`;
2. title;
3. `source_id`.

The report should explicitly show papers with zero metric results because they are important corpus acceptance failures or out-of-scope paper types.

## 8. Per-Metric Items

Each `metrics[]` item should summarize one normalized metric group, reusing V4.4 grouping semantics:

```json
{
  "schema_version": "corpus_results_metric.v4.6",
  "metric_name": "success rate",
  "normalized_metric": "successrate",
  "row_count": 12,
  "source_count": 3,
  "paper_count": 3,
  "dataset_count": 4,
  "task_count": 6,
  "method_count": 8,
  "year_min": 2013,
  "year_max": 2025,
  "missing_year_count": 0,
  "table_result_count": 0,
  "caption_result_count": 0,
  "timeline_ready": true,
  "timeline_readiness_reason": "paper_count>=2 and year_count>=2",
  "example_result_id": "res_xxx",
  "example_claim_id": "clm_xxx",
  "warnings": []
}
```

Metric groups should be sorted by:

1. descending `timeline_ready`;
2. descending `row_count`;
3. descending `paper_count`;
4. normalized metric key.

V4.6-min should not merge metric aliases. It may warn when obvious normalized variants exist, following V4.4 behavior.

## 9. Timeline Readiness

V4.6-min does not generate trends or synthesis. It only identifies candidate metrics that are likely useful for V4.4 timeline queries.

First-version readiness policy:

```text
timeline_ready = row_count >= 2 AND paper_count >= 2
```

Additional diagnostics:

- `year_count`: count of distinct non-null timeline years;
- `missing_year_count`: rows missing year;
- `source_count`;
- `paper_count`;
- `dataset_count`;
- `task_count`;
- `method_count`;
- `has_table_evidence`;
- `has_caption_evidence`;
- `has_missing_value_rows`.

If `year_count < 2` but `paper_count >= 2`, the metric should be marked as `timeline_candidate_needs_year_repair`, not as ready.

V4.6-min must not infer missing years from arbitrary numbers in claims. It may reuse V4.2 inventory year values and V4.4 timeline sorting fields.

## 10. Quality Gates

`quality_gates[]` should include deterministic pass/warn/fail checks. A failed gate does not necessarily make the command exit non-zero; it means corpus acceptance did not pass.

Recommended gates:

| Gate | Status Rule |
| --- | --- |
| `catalog_available` | fail if catalog missing or incompatible |
| `has_corpus_sources` | warn if no sources |
| `all_batch_items_applied` | warn if failed/pending/interrupted batch items exist |
| `no_parser_fallback_results` | warn if `parser_fallback_result_count > 0` |
| `metric_results_present` | warn if `metric_result_count == 0` |
| `all_results_joined` | fail if joined count < metric result count |
| `all_results_resolvable` | fail if resolvable locator count < metric result count |
| `all_results_context_available` | warn if context available count < metric result count |
| `no_result_errors` | fail if `result_error_count > 0` |
| `core_fields_usable` | warn if missing method/dataset/task/value ratio exceeds threshold |
| `table_evidence_present` | warn if table result count is 0 for PDF corpus |
| `timeline_candidates_present` | warn if timeline ready metric count is 0 |

Default threshold for `core_fields_usable`:

```text
(missing_method_count + missing_dataset_count + missing_task_count + missing_value_count) / max(metric_result_count, 1) <= 0.25
```

This threshold is intentionally loose for the first version because V4.6 is a diagnostic acceptance report, not a benchmark leaderboard.

## 11. Read-Only Boundary

V4.6-min may read:

- `state/catalog.sqlite`;
- `state/corpus-batches/`;
- `sources/metadata/*.json`;
- `sources/blocks/*.jsonl` only through bounded result-evidence context helpers;
- `sources/normalized/*` only through bounded line-locator context helpers;
- `wiki/sources/*.md` only as catalog-referenced display metadata if needed;
- existing V4.2/V4.4/V4.5 model/helper functions.

V4.6-min must not:

- call LLM providers;
- call embedding providers;
- run MinerU;
- run PDF parser backends;
- call add/import/ingest/apply;
- call ask/synthesis;
- call lint/eval subcommands through CLI recursion;
- call clean;
- write `wiki/`;
- write `sources/`;
- write `staging/`;
- write `state/catalog.sqlite`;
- write `state/corpus-batches/`;
- write `state/embeddings/`;
- write `state/ui-jobs/`;
- write `.tmp/`;
- read raw parser-native artifact content;
- expose API keys, raw prompts, raw responses, parser logs, or parser artifact contents.

Implementation should call shared read-only Python helpers directly instead of spawning subcommands.

## 12. Human Output

Human output should be compact and acceptance-oriented:

```text
Corpus result acceptance
Sources: 20 (PDF: 20, applied: 20)
Metric results: 345
Joined/resolved/context: 345/345/344
Parser backends: mineru=345
Fallback result rows: 0
Table/caption/result-text rows: 180/12/260
Missing method/dataset/task/value: 0/3/2/41
Timeline-ready metrics: 8
Warnings: 4
Errors: 0

Top papers by metric results:
...

Timeline-ready metrics:
...

Quality gates:
PASS catalog_available
WARN table_evidence_present ...
```

Human output should not print full per-result rows. JSON may include per-paper and per-metric summaries, not the full V4.5 result item list by default.

## 13. Acceptance Plan

Automated tests should use synthetic catalog workspaces and monkeypatches; they must not call real LLMs, MinerU, or parsers.

Manual/real acceptance should use:

```powershell
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v46-corpus-acceptance
.\.venv\Scripts\python.exe -m llmwiki parsers status --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki corpus import docs\papers --root .tmp\paper-v46-corpus-acceptance --recursive --parser mineru --json
.\.venv\Scripts\python.exe -m llmwiki eval corpus-results --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki eval corpus-results --root .tmp\paper-v46-corpus-acceptance
```

For this machine, strict MinerU acceptance should use the V4.5.1 working profile:

```toml
[pdf_parser]
mineru_enabled = true
mineru_command = "F:/LLMWiki/.venv/Scripts/mineru.exe"
mineru_backend = "pipeline"
mineru_method = "auto"
mineru_extra_args = ["-l", "en"]
```

The full 20-paper acceptance may take a long time. It should be recorded in:

```text
docs/observations/2026-06-05-llmwiki-v4-6-min-corpus-acceptance-metrics-observations.md
```

Record only sanitized observations:

- command summary;
- source/paper counts;
- parser backend distribution;
- result evidence summary;
- per-paper row distribution;
- top timeline-ready metrics;
- failed/warned quality gates;
- notable missing-field or caption/table coverage issues;
- workspace path retained for user inspection.

Do not commit generated workspace contents, API keys, raw prompts, raw responses, parser logs, parser artifacts, source sidecars, staging files, wiki files, or catalog databases.

As with V4.5.1, do not default to cleaning the acceptance workspace after the run if the user wants to inspect actual results.

## 14. Relationship To Other Phases

V4.6-min is the acceptance bridge from V4 to V5.

- V4.2 provides paper identity inventory.
- V4.3 provides durable metric result rows.
- V4.4 provides metric list/timeline query primitives.
- V4.5/V4.5.1 provide result-evidence quality diagnostics.
- V4.6-min aggregates these into corpus-level readiness.

V5 should not start relation classification, conflict detection, maintenance planning, or living synthesis updates until V4.6-min can show which papers, metrics, and evidence rows are trustworthy enough to operate on.

## 15. Open Questions

1. Should `timeline_ready` require at least two distinct years, or is two papers enough for first-version readiness?
   - Default: require two papers for `timeline_ready`, and separately report `year_count` / `timeline_candidate_needs_year_repair`.
2. Should survey/taxonomy statistics become a separate row category?
   - Default: no. V4.6-min reports them only if they already exist as durable `metric_results`; V4.6 does not add a new extraction category.
3. Should V4.6-min compare against previous acceptance workspaces?
   - Default: no automatic cross-workspace comparison. Observation files may manually compare V4.5.1 subset results to the new full-corpus run.
4. Should V4.6-min output full per-result detail?
   - Default: no. Use V4.5 `eval result-evidence --json` for full result-level diagnostics.
