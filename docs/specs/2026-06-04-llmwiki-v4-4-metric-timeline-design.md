# LLMWiki V4.4 Metric Timeline Design

Date: 2026-06-04

Status: planning spec

## 1. Summary

V4.4 turns V4.3 `metric_results` into an auditable metric evolution query surface.

The goal is to let a user ask:

```text
How has <metric> changed across this research corpus?
```

and receive a source-backed timeline table derived from durable catalog rows, not raw PDF chunks or a new LLM summary.

V4.4 is CLI-first and read-only. It does not add UI, does not call a chat LLM, does not re-run ingest, and does not write wiki pages. It reads `state/catalog.sqlite metric_results`, joins each row back to formal claims, sources, source pages, and paper identity metadata, then returns stable human and JSON outputs for later V4/V5 workflows.

## 2. Background

V4.1 added corpus import orchestration. V4.2 added paper identity and corpus inventory. V4.3 added structured metric/result extraction:

```text
PDF ingest
-> staging/<run-id>/metric-results.jsonl
-> apply
-> state/catalog.sqlite metric_results
```

V4.4 is the first user-facing workflow that proves those structured result rows are useful. It should answer timeline and result-evolution questions from compiled wiki/catalog knowledge:

- Which papers report this metric?
- Which method reported which value?
- Which datasets and tasks appear in the result records?
- How do reported values change over paper years?
- Which rows have weak metadata, missing year, missing value, or duplicate-looking results?

V4.4 should not broaden into research synthesis. A later phase can use timeline rows as evidence for narrative synthesis, trend detection, gap detection, and maintenance planning.

## 3. Product Goal

Given an imported same-domain paper corpus, the user can run:

```powershell
llmwiki metric timeline "success rate" --root .
llmwiki metric timeline "success rate" --dataset "OSWorld" --root .
llmwiki metric timeline "success rate" --task "computer use" --json --root .
llmwiki metric list --root .
llmwiki metric list --root . --json
```

The command returns rows such as:

```text
Year | Paper | Method | Dataset | Task | Metric | Value | Baseline | Claim | Locator
2024 | ...   | ...    | ...     | ...  | ...    | ...   | ...      | clm_... | page:...
2025 | ...   | ...    | ...     | ...  | ...    | ...   | ...      | clm_... | page:...
```

Each non-warning timeline row must be traceable to:

- `result_id` from `metric_results`;
- `claim_id` from `claims`;
- `source_id` from `sources`;
- `citation_locator`;
- source/page metadata when available.

## 4. Scope

V4.4 includes:

- a new CLI command group for metric timeline queries;
- a read-only timeline query module over `metric_results`;
- a metric list/discovery command for choosing available metric names;
- stable JSON schemas for timeline and metric list output;
- human-readable CLI tables;
- conservative lexical matching over metric, dataset, task, method, source, paper, and year filters;
- warnings for empty results, missing fields, duplicate-looking rows, and ambiguous metric variants;
- tests for schema, filtering, ordering, no-write boundary, and CLI formatting;
- real-corpus acceptance over the 20 local papers after V4.3 extraction.

V4.4 does not include:

- UI;
- chat LLM calls;
- embedding provider calls;
- raw PDF chunk search as evidence;
- metric alias auto-merge;
- metric unit conversion beyond V4.3 stored fields;
- trend/gap/synthesis generation;
- wiki writeback;
- result extraction changes except narrow bug fixes needed to make timeline rows valid;
- relationship classification;
- conflict resolution;
- paper identity catalog migration.

## 5. Command Contract

### 5.1 Timeline

Canonical command:

```powershell
llmwiki metric timeline "<metric>" --root .
```

Options:

```text
--dataset <text>
--task <text>
--method <text>
--source-id <source-id>
--paper-id <paper-id>
--year-from <year>
--year-to <year>
--limit <n>
--offset <n>
--json
```

Defaults:

- `limit = 100`;
- maximum `limit = 500`;
- `offset >= 0`;
- missing `--root` follows the existing CLI root default behavior;
- the positional metric is required for `timeline`;
- filters are AND-ed together.

Exit behavior:

- return exit code `0` for a valid empty timeline with warnings;
- return exit code `1` only for invalid arguments, invalid catalog schema, or unreadable workspace state;
- do not create state or cache files.

### 5.2 Metric List

Canonical command:

```powershell
llmwiki metric list --root .
```

Options:

```text
--query <text>
--dataset <text>
--task <text>
--limit <n>
--offset <n>
--json
```

Purpose:

- show available metric names from `metric_results`;
- show row counts and source diversity;
- help the user choose a metric query before running `timeline`;
- expose possible metric variants without merging them.

V4.4 should not automatically convert `metric list` output into alias rules.

## 6. Data Sources

Timeline rows must be derived from durable catalog-backed result records:

```text
metric_results
-> claims
-> sources
-> pages/source pages when available
-> paper identity metadata through existing V4.2 inventory helpers when available
```

Required joins:

- `metric_results.claim_id = claims.claim_id`;
- `metric_results.source_id = claims.source_id`;
- `metric_results.source_id = sources.source_id`;
- source page path should be read from catalog pages when available.

Rows that cannot join to a formal claim and source must not appear as normal timeline rows. They may be counted in warnings if the catalog contains inconsistent state.

V4.4 must not:

- inspect raw PDF files;
- read parser artifacts as evidence;
- call PDF parsers;
- call MinerU;
- call ingest/apply;
- call retrieval over raw chunks;
- use raw normalized text as a substitute for a missing formal result claim.

## 7. Matching Rules

First-version matching is conservative and deterministic.

### 7.1 Normalization

For metric, dataset, task, and method filters:

1. Unicode casefold.
2. Trim surrounding whitespace.
3. Collapse internal whitespace to one space.
4. Remove punctuation only for the normalized comparison key.
5. Preserve original display values in output.

The implementation may provide helper names such as:

```text
normalize_metric_query(text)
normalize_timeline_filter(text)
```

### 7.2 Metric Match

A timeline row matches the requested metric when either:

- `metric_name` casefolds exactly to the requested metric; or
- the normalized comparison key is equal.

V4.4 must not:

- infer that `acc` means `accuracy`;
- infer that `success` means `success rate`;
- merge `pass@1`, `pass rate`, and `success rate`;
- use domain-specific boosts;
- call an LLM or embedding model for metric expansion.

If multiple metric display forms share the same normalized key, the response should include a warning listing the variants.

### 7.3 Dataset, Task, And Method Filters

Dataset, task, and method filters use the same exact-or-normalized equality rule.

The first implementation should avoid substring matching by default because substring matching can silently mix unrelated benchmarks or methods. If the implementation plan chooses to add substring matching, it must be opt-in and tested separately.

### 7.4 Year Filters

Year filtering should use the best available timeline year:

1. `metric_results.reported_year`;
2. V4.2 paper identity year;
3. source/import year only as a sorting fallback, not as a reported scientific year.

Rows with no year should be excluded only when the requested year range cannot safely include them. The response should add a warning count for rows skipped because of missing year.

## 8. Sorting Rules

Timeline output must be stable.

Default sort:

1. timeline year, ascending;
2. rows with known year before rows with unknown year;
3. source title, ascending;
4. `source_id`, ascending;
5. `result_id`, ascending.

When timeline year is missing, the row still appears after dated rows unless a year filter excludes it.

V4.4 must not sort by "best" value or claim that one method wins. Direction-aware ranking belongs to a later comparison/trend phase.

## 9. JSON Schema

### 9.1 Timeline Response

Schema version:

```text
metric_timeline.v4.4
```

Required top-level fields:

```text
schema_version
root
generated_at
query
item_count
warning_count
items
warnings
```

`query` fields:

```text
metric
normalized_metric
dataset
task
method
source_id
paper_id
year_from
year_to
limit
offset
```

`items` must be a list of `metric_timeline_item.v4.4`.

Missing strings use `""`; missing integers use `null`; missing lists use `[]`.

### 9.2 Timeline Item

Schema version:

```text
metric_timeline_item.v4.4
```

Required fields:

```text
schema_version
result_id
claim_id
source_id
paper_id
source_title
paper_title
authors
year
reported_year
doi
arxiv_id
page_path
claim_text
citation_locator
confidence_status
method
dataset
task
metric_name
metric_value
metric_unit
metric_raw_value
metric_direction
baseline
comparison_value
setting
is_main_result
value_normalization_status
extraction_origin
evidence_block_ids
evidence_pages
warnings
created_at
```

Rules:

- `year` is the paper identity year when available.
- `reported_year` is the result-level year from V4.3 when available.
- `timeline_year` may be added if the implementation wants to expose the effective sort year, but it must not replace `year` or `reported_year`.
- `authors`, `evidence_block_ids`, `evidence_pages`, and `warnings` are lists.
- `is_main_result` is `true`, `false`, or `null`.

### 9.3 Metric List Response

Schema version:

```text
metric_list.v4.4
```

Required top-level fields:

```text
schema_version
root
generated_at
query
metric_count
warning_count
metrics
warnings
```

Metric item fields:

```text
metric_name
normalized_metric
row_count
source_count
paper_count
dataset_count
task_count
year_min
year_max
example_result_id
example_claim_id
warnings
```

Metric list output is for discovery. It is not evidence by itself.

## 10. Human Output

`llmwiki metric timeline` human output should be compact and readable in PowerShell.

Suggested sections:

```text
Metric timeline: success rate
Filters: dataset=OSWorld task=...
Rows: 12

Year  Paper                         Method       Dataset   Task       Metric        Value   Baseline  Claim     Locator
2024  ...                           ...          ...       ...        success rate  42.1%   ...       clm_...   page:...

Warnings:
- 2 rows have missing paper year.
- Metric variants share this normalized key: Success Rate, success-rate.
```

Human output may truncate long titles, claim ids, and locators for display, but JSON output must preserve full values.

`llmwiki metric list` human output should show:

```text
Metric                  Rows  Sources  Papers  Year range
success rate            12    6        6       2024-2026
accuracy                8     5        5       2023-2026
```

## 11. Warning Contract

Warnings should be structured in JSON and readable in human output.

Recommended warning fields:

```text
code
message
result_id
claim_id
source_id
details
```

Warning codes:

```text
catalog_unavailable
metric_results_missing
no_catalog_backed_result
missing_year
missing_metric_value
missing_claim_join
missing_source_join
ambiguous_metric_variants
duplicate_result_candidate
invalid_filter
limit_clamped
```

Warnings must be sanitized. They must not expose API keys, raw prompts, raw LLM responses, parser logs, parser artifacts, or local secret file contents.

## 12. Duplicate-Looking Rows

V4.4 should not merge or delete rows.

It may warn about duplicate-looking rows when multiple timeline items share:

```text
source_id
normalized metric_name
normalized method
normalized dataset
normalized task
metric_value or metric_raw_value
citation_locator
```

Duplicate warnings are diagnostic. They must not suppress source-backed rows unless a later spec defines a reviewed merge behavior.

## 13. Evidence And Safety Boundaries

V4.4 is read-only.

`metric timeline` and `metric list` must not call:

- LLM providers;
- embedding providers;
- MinerU;
- parser execution;
- add/import;
- ingest;
- apply;
- ask;
- synthesis;
- lint;
- eval;
- clean.

They must not write:

- `wiki/`;
- `sources/`;
- `staging/`;
- `state/catalog.sqlite`;
- `state/corpus-batches/`;
- `state/embeddings/`;
- `state/ui-jobs/`;
- `.tmp/`.

The only acceptable output is stdout/stderr. If a later implementation adds `--output`, it must be a separate planned change with explicit write-path tests.

V4.4 rows are evidence-bearing only because they join to formal claims. Paper identity fields are metadata for ordering and display; they do not prove result values.

## 14. Relationship To Ask And Retrieve

V4.4 should not replace `llmwiki ask` or `llmwiki retrieve`.

Metric evolution questions should prefer the timeline query path:

```text
metric question
-> metric_results timeline query
-> source-backed rows
-> optional future synthesis
```

`ask` integration is out of scope for V4.4. A later phase may let ask planning detect metric-evolution questions and call timeline internally, but that must preserve the same catalog-backed row contract.

## 15. Error Behavior

Invalid arguments should fail clearly:

- invalid year: exit code `1`;
- negative offset: exit code `1`;
- non-positive limit: exit code `1`;
- catalog missing or incompatible schema: exit code `1`;
- root not initialized: follow existing CLI behavior.

Valid empty results should not fail:

```text
No catalog-backed result claim found for this metric.
```

JSON empty result should return:

```json
{
  "schema_version": "metric_timeline.v4.4",
  "item_count": 0,
  "items": [],
  "warnings": [
    {
      "code": "no_catalog_backed_result"
    }
  ]
}
```

## 16. Test Strategy

V4.4 should be implemented with spec-driven, contract-first, risk-based TDD.

Recommended tests:

- metric filter normalization and equality tests;
- timeline JSON schema tests;
- metric list JSON schema tests;
- human formatting tests;
- catalog fixture tests for joins to `metric_results`, `claims`, and `sources`;
- ordering tests with reported year, paper year, and missing year;
- filter tests for dataset, task, method, source id, paper id, and year range;
- empty-result tests;
- missing catalog or missing `metric_results` tests;
- duplicate warning tests;
- no-write boundary tests;
- monkeypatch tests proving timeline/list do not call LLM, embedding, MinerU, parser, add, ingest, apply, ask, synthesis, lint, eval, or clean;
- sanitizer tests for warning messages;
- regression tests proving V4.3 `metric_results` remains the durable input surface.

Suggested test files:

```text
tests/test_metric_timeline_model.py
tests/test_metric_timeline_query.py
tests/test_metric_timeline_cli.py
tests/test_metric_timeline_readonly.py
tests/test_regression_samples.py
```

The exact file names can be adjusted in the implementation plan.

## 17. Manual Acceptance

V4.4 acceptance should use a real V4.3-generated corpus. Unit tests are necessary but not sufficient because timeline usefulness depends on actual extracted result rows.

Recommended workflow:

```powershell
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v44-acceptance
.\.venv\Scripts\python.exe -m llmwiki corpus import docs\papers --root .tmp\paper-v44-acceptance --recursive --parser auto
.\.venv\Scripts\python.exe -m llmwiki metric list --root .tmp\paper-v44-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric timeline "<metric-from-list>" --root .tmp\paper-v44-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric timeline "<metric-from-list>" --root .tmp\paper-v44-acceptance
```

The metric used for acceptance should be selected from `metric list` output after extraction, not hardcoded before observing the corpus.

Record an acceptance observation file under `docs/specs/`, for example:

```text
docs/observations/2026-06-04-llmwiki-v4-4-metric-timeline-acceptance-observations.md
```

The observation should report:

- imported paper count;
- formal claim count;
- durable `metric_results` row count;
- metric list count;
- selected metric query;
- timeline row count;
- timeline source diversity;
- timeline paper diversity;
- rows with claim id/source id/locator;
- rows with missing year;
- rows with missing normalized value;
- duplicate-looking warning count;
- empty-result behavior for one deliberately absent metric.

Generated workspaces, source sidecars, staging, catalog, wiki output, vector cache, parser artifacts, raw prompts/responses, parser logs, and local API keys must not be committed.

## 18. Success Criteria

V4.4 is successful when:

1. A user can list available metric names from the imported corpus.
2. A user can request a metric timeline with optional dataset/task/method/year filters.
3. Timeline rows are derived entirely from durable `metric_results` joined to formal claims and sources.
4. Every non-warning row has `result_id`, `claim_id`, `source_id`, and `citation_locator`.
5. JSON output is stable enough for later UI, eval, ask integration, and synthesis planning.
6. Human output is readable in CLI.
7. Empty results return warnings without inventing narrative.
8. The commands are read-only and do not call LLM, embedding, parser, ingest, apply, ask, synthesis, eval, or clean paths.
9. Full-corpus acceptance over the 20 local papers records timeline row count and source diversity.

## 19. Open Questions For The Implementation Plan

1. Should V4.4 expose a plural alias such as `llmwiki metrics timeline`, or keep only the singular `llmwiki metric timeline` command group from the V4 roadmap?
2. Should `metric list` group variants by normalized key or show raw metric names one row at a time?
3. Should missing-year rows appear after dated rows by default, or require an `--include-missing-year` flag when year filters are present?
4. Should `timeline_year` be explicitly included in JSON, or should callers compute it from `reported_year` and paper `year`?
5. Should implementation add `--format markdown`, or should markdown export wait until synthesis/writeback work?
6. Should substring matching be added as an opt-in debug flag, or deferred until metric alias curation exists?
