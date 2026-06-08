# LLMWiki V4.7 Metric Canonicalization And Timeline Readiness Repair Design

Date: 2026-06-05

## 1. Summary

V4.7 adds a CLI-first, read-only metric canonicalization and timeline readiness repair report over existing durable `metric_results`:

```powershell
llmwiki metric canonicalize --root . --json
llmwiki metric canonicalize --root .
```

The goal is to turn V4.6 corpus acceptance output from "we have metric result rows" into "we know which metrics can safely support comparable source-backed timelines."

V4.7 must not rerun MinerU+LLM by default. It reuses the already-imported V4.6 full corpus workspace and reads existing catalog-backed rows, formal claims, source metadata, and bounded evidence context. It does not create new claims, rewrite `metric_results`, merge evidence, or write wiki pages.

## 2. Motivation

V4.6 full strict MinerU acceptance on the 20-paper corpus produced:

- 20 / 20 papers applied after failed-only retry;
- 378 formal claims;
- 414 durable `metric_results`;
- 414 / 414 joined, locator-resolved, and context-available result rows;
- parser backend distribution `{"mineru": 414}`;
- parser fallback count `0`;
- table / caption / result-text result counts: 337 / 17 / 321;
- 68 metric groups;
- 11 first-version timeline candidates;
- 63 rows missing normalized metric value;
- 320 rows missing baseline;
- 0 result errors.

This proves the evidence pipeline is usable, but it also exposes the next bottleneck:

- metric names are fragmented (`success rate`, `Average Accuracy`, `score`, `Avg`, `Overall`, etc.);
- some V4.6 timeline candidates mix datasets, tasks, units, or vague metric labels;
- missing normalized values block quantitative comparison;
- V4.6 readiness is count-based and does not decide comparability.

V4.7 should produce a deterministic, auditable report that tells the user which timelines are ready, which are only discoverable, and which need value or canonicalization repair before use.

## 3. Scope

V4.7 implements one read-only command:

```powershell
llmwiki metric canonicalize --root . [--json]
```

Optional filters:

```powershell
--metric <text>
--dataset <text>
--task <text>
--limit <n>
--offset <n>
```

V4.7 includes:

- deterministic metric name canonicalization;
- metric variant grouping without mutating original rows;
- deterministic value repair suggestions for rows missing normalized values;
- comparability grouping by canonical metric, dataset, task, unit, direction, and value scale;
- upgraded timeline readiness statuses;
- per-row repair suggestions that preserve `result_id`, `claim_id`, `source_id`, `paper_id`, and `citation_locator`.

V4.7 does not add:

- UI;
- catalog migration;
- durable `canonical_metrics` table;
- automatic catalog repair;
- wiki writeback;
- LLM-based canonicalization;
- MinerU or parser reruns;
- new extraction prompts;
- metric alias curation files that silently merge evidence;
- unit conversion across incompatible units;
- ranking, trend claims, synthesis, or conflict detection.

## 4. Command Contract

### 4.1 CLI

Human output:

```powershell
llmwiki metric canonicalize --root .
```

JSON output:

```powershell
llmwiki metric canonicalize --root . --json
```

Exit behavior:

- exit `0` when the report completes, even if readiness warnings or repair suggestions are found;
- exit `1` for invalid arguments, missing catalog, incompatible schema, or unreadable bounded sidecar/context needed for diagnostics;
- empty corpus exits `0` with `no_catalog_backed_result` and `no_canonical_metric` warnings.

### 4.2 Schema Versions

Top-level response:

```text
metric_canonicalization_report.v4.7
```

Nested schemas:

```text
canonical_metric.v4.7
metric_result_value_repair.v4.7
metric_comparability_group.v4.7
metric_timeline_readiness.v4.7
metric_canonicalization_warning.v4.7
```

V4.7 must preserve original audit values:

- `result_id`;
- `claim_id`;
- `source_id`;
- `paper_id`;
- `citation_locator`;
- `metric_name`;
- `method`;
- `dataset`;
- `task`;
- `metric_value`;
- `metric_raw_value`;
- `metric_unit`;
- `metric_direction`;
- `baseline`;
- `confidence_status`;
- parser backend fields.

Canonical fields are additional derived metadata, not replacements for stored values.

## 5. JSON Shape

Top-level JSON:

```json
{
  "schema_version": "metric_canonicalization_report.v4.7",
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
  "canonical_metrics": [],
  "comparability_groups": [],
  "timeline_readiness": [],
  "value_repairs": [],
  "warnings": []
}
```

V4.7 JSON should not include full raw context text by default. It may include short bounded snippets only when needed to explain a value repair suggestion. It must not include raw prompts, raw LLM responses, parser logs, parser artifact contents, API key paths, or API key values.

## 6. Canonicalization Rules

V4.7 canonicalization is deterministic and conservative.

### 6.1 Text Normalization

Build `canonical_metric_key` from `metric_name` using:

- Unicode NFKC normalization;
- casefolding;
- whitespace collapse;
- punctuation removal except meaningful math symbols when present;
- singular/plural normalization for simple English suffixes only when unambiguous;
- removal of wrapping punctuation and redundant parenthetical whitespace;
- preservation of the original display variant list.

Examples:

| Raw Metric | Canonical Key |
| --- | --- |
| `Success Rate` | `success_rate` |
| `success-rate` | `success_rate` |
| `overall success rate` | `overall_success_rate` |
| `Average Accuracy` | `average_accuracy` |
| `Avg` | `avg` |
| `score` | `score` |

V4.7 must not automatically treat `score`, `Avg`, `Overall`, `success rate`, and `accuracy` as synonyms. Vague labels should be marked as ambiguous unless dataset/task/unit context makes a specific comparability group clear.

### 6.2 Canonical Metric Items

Each `canonical_metrics[]` item:

```json
{
  "schema_version": "canonical_metric.v4.7",
  "canonical_metric_key": "success_rate",
  "display_name": "success rate",
  "variants": ["Success Rate", "success-rate", "success rate"],
  "row_count": 101,
  "paper_count": 13,
  "source_count": 13,
  "dataset_count": 8,
  "task_count": 9,
  "unit_count": 1,
  "direction_count": 1,
  "value_repair_suggestion_count": 0,
  "strict_comparable_group_count": 3,
  "timeline_ready_group_count": 2,
  "ambiguity_status": "clear",
  "warnings": []
}
```

`ambiguity_status` values:

- `clear`: variants are lexical variants of the same metric;
- `context_dependent`: metric is usable only after dataset/task/unit grouping;
- `ambiguous_label`: metric name is too vague, e.g. `score`, `Avg`, `Overall`;
- `conflicting_units`: same canonical key has incompatible units;
- `mixed_direction`: same canonical key has mixed `higher_is_better` / `lower_is_better` / unknown direction.

## 7. Value Repair Suggestions

V4.7 should not write repaired values into catalog. It only emits suggestions.

A value repair suggestion may be created when:

- `metric_value` is empty;
- `metric_raw_value`, `claim_text`, or bounded context contains one clear numeric value;
- the value is not a placeholder such as `See table`, `not reported`, `N/A`, `-`, or `unknown`;
- the inferred unit is compatible with `metric_unit` or the raw text.

Allowed deterministic value patterns:

- percentages: `42.1%`, `42.1 percent`;
- decimals: `0.421`;
- ratios: `42/100` when denominator is explicit;
- time values: `12.3s`, `12.3 seconds`, `4.5 min`;
- cost values: `$0.32`, `0.32 USD`;
- integer counts only when the metric label implies count or the raw value includes a count unit.

Each `value_repairs[]` item:

```json
{
  "schema_version": "metric_result_value_repair.v4.7",
  "result_id": "res_xxx",
  "claim_id": "clm_xxx",
  "source_id": "src_xxx",
  "paper_id": "src_xxx",
  "citation_locator": "page:3;block:src_xxx_p003_b0004",
  "metric_name": "success rate",
  "metric_raw_value": "42.1%",
  "current_metric_value": "",
  "suggested_metric_value": "42.1",
  "suggested_metric_unit": "%",
  "suggested_value_scale": "percent",
  "repair_confidence": "high",
  "repair_source": "metric_raw_value",
  "snippet": "Agent A reaches 42.1% success rate on OSWorld.",
  "warnings": []
}
```

`repair_confidence` values:

- `high`: one clear numeric value in `metric_raw_value`;
- `medium`: one clear numeric value in claim or bounded context;
- `low`: multiple numeric values exist but one is strongly tied to metric label;
- `none`: no suggestion emitted.

Rows with multiple competing numeric values should receive an ambiguity warning, not a repair.

## 8. Comparability Groups

V4.7 should distinguish "same metric label" from "same comparable timeline series."

Build `comparability_group_key` from:

```text
canonical_metric_key
normalized_dataset
normalized_task
normalized_metric_unit
metric_direction
value_scale
```

`value_scale` examples:

- `percent`;
- `ratio`;
- `raw_number`;
- `seconds`;
- `minutes`;
- `usd`;
- `count`;
- `unknown`.

Each `comparability_groups[]` item:

```json
{
  "schema_version": "metric_comparability_group.v4.7",
  "comparability_group_key": "success_rate|osworld|computer_use|%|higher_is_better|percent",
  "canonical_metric_key": "success_rate",
  "display_name": "success rate",
  "dataset": "OSWorld",
  "task": "computer use",
  "metric_unit": "%",
  "metric_direction": "higher_is_better",
  "value_scale": "percent",
  "row_count": 12,
  "paper_count": 4,
  "source_count": 4,
  "year_count": 4,
  "missing_value_count": 0,
  "value_repair_suggestion_count": 0,
  "table_result_count": 8,
  "caption_result_count": 1,
  "readiness_status": "strict_ready",
  "warnings": []
}
```

Comparability grouping must keep source-backed row IDs available in JSON through compact references or counts. Full per-result detail remains available through V4.5 `eval result-evidence --json`.

## 9. Timeline Readiness Repair

V4.7 upgrades V4.6 count-based readiness into status-based readiness.

`timeline_readiness[]` item:

```json
{
  "schema_version": "metric_timeline_readiness.v4.7",
  "canonical_metric_key": "success_rate",
  "comparability_group_key": "success_rate|osworld|computer_use|%|higher_is_better|percent",
  "display_name": "success rate",
  "row_count": 12,
  "paper_count": 4,
  "year_count": 4,
  "missing_value_count": 0,
  "value_repair_suggestion_count": 0,
  "readiness_status": "strict_ready",
  "readiness_reason": "same canonical metric, dataset, task, unit, direction, value scale; >=2 papers and >=2 years",
  "blocking_reasons": [],
  "warning_reasons": []
}
```

Readiness statuses:

- `strict_ready`: same canonical metric/dataset/task/unit/direction/value scale, at least 2 papers, at least 2 years, and no missing value rows;
- `ready_after_value_repair`: same comparable group and enough papers/years, but missing values have deterministic high/medium repair suggestions;
- `discoverable_not_comparable`: same canonical metric has enough rows/papers but splits across datasets, tasks, units, or directions;
- `needs_canonical_review`: metric label is vague or variants are not safely mergeable;
- `needs_value_repair`: missing values block quantitative comparison and no safe repair suggestion exists for all missing rows;
- `needs_year_repair`: enough papers but fewer than 2 distinct years;
- `not_ready_single_paper`: only one paper/source contributes;
- `not_ready_empty`: no catalog-backed rows.

V4.7 must not generate trend claims. It only reports readiness and blocking reasons.

## 10. Summary Metrics

`summary` should include:

```text
metric_result_count
canonical_metric_count
canonical_metric_ambiguous_count
comparability_group_count
strict_ready_timeline_count
ready_after_value_repair_count
discoverable_not_comparable_count
needs_canonical_review_count
needs_value_repair_count
value_repair_suggestion_count
high_confidence_value_repair_count
medium_confidence_value_repair_count
missing_value_count
unrepaired_missing_value_count
conflicting_unit_group_count
mixed_direction_group_count
parser_fallback_result_count
result_error_count
warning_count
```

The V4.6 baseline for `.tmp/paper-v46-corpus-acceptance` should be included in acceptance observations:

- `metric_result_count = 414`;
- V4.6 `metric_list_count = 68`;
- V4.6 `timeline_candidate_count = 11`;
- V4.6 `missing_normalized_value_count = 63`;
- V4.6 `parser_fallback_result_count = 0`;
- V4.6 `error_count = 0`.

## 11. Read-Only Boundary

V4.7 may read:

- `state/catalog.sqlite`;
- V4.2 inventory metadata;
- V4.5 result-evidence helper output;
- bounded normalized source/context helpers;
- generated sidecars needed only for bounded context diagnostics.

V4.7 must not:

- call LLM providers;
- call embedding providers;
- run MinerU;
- run PDF parser backends;
- call add/import/ingest/apply;
- call ask/synthesis;
- call lint/clean;
- call other eval subcommands through CLI recursion;
- write `wiki/`;
- write `sources/`;
- write `staging/`;
- write `state/catalog.sqlite`;
- write `state/corpus-batches/`;
- write `state/embeddings/`;
- write `state/ui-jobs/`;
- write `.tmp/`;
- expose API keys, raw prompts, raw responses, parser logs, or parser artifact contents.

Implementation should call shared read-only Python helpers directly. It should not shell out to existing CLI commands.

## 12. Human Output

Human output should be compact:

```text
Metric canonicalization
Metric results: 414
Canonical metrics: 52
Comparability groups: 91
Strict-ready timelines: 7
Ready after value repair: 3
Needs canonical review: 8
Needs value repair: 12
Value repair suggestions: 31

Strict-ready groups:
...

Value repair suggestions:
...

Ambiguous metrics:
...
```

Human output must not print all 414 rows by default. JSON may include paginated summary items and compact row references.

## 13. Acceptance Reuse

V4.7 defaults to reusing preserved acceptance results. Do not rerun MinerU+LLM for V4.7 unless the implementation unexpectedly changes ingest, chunking, prompts, parser behavior, candidate validation, or apply-time persistence, which are out of scope for this spec.

Acceptance levels:

- L0: unit tests for canonical key normalization, value parsing, comparability grouping, and readiness statuses.
- L1: synthetic catalog tests for JSON schema, warnings, CLI filters, and read-only boundaries.
- L2: run `llmwiki metric canonicalize --root .tmp\paper-v46-corpus-acceptance --json` and human output against the preserved full V4.6 workspace.
- L3: not needed for V4.7 unless implementation scope changes.
- L4: not needed for V4.7 unless implementation scope changes.
- L5: full 20-paper MinerU+LLM rerun is not required for V4.7 and should not be performed by default.

Manual acceptance commands:

```powershell
.\.venv\Scripts\python.exe -m llmwiki metric canonicalize --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric canonicalize --root .tmp\paper-v46-corpus-acceptance
```

Observation file:

```text
docs/observations/2026-06-05-llmwiki-v4-7-metric-canonicalization-timeline-readiness-repair-observations.md
```

Record only sanitized observations:

- V4.6 baseline metrics;
- canonical metric count;
- ambiguous metric count;
- comparability group count;
- strict-ready timeline count;
- ready-after-value-repair count;
- value repair suggestion count;
- unrepaired missing value count;
- top strict-ready groups;
- top ambiguous labels and why they are blocked;
- read-only verification result.

Do not commit `.tmp` workspace contents, API keys, source sidecars, staging files, wiki output, catalog databases, parser logs, raw prompts, raw responses, or parser artifacts.

## 14. Testing Requirements

Automated tests should cover:

- canonical key normalization for punctuation, case, whitespace, Unicode, and simple plural variants;
- vague metric label detection for `score`, `Avg`, `Overall`, and similar generic labels;
- no automatic synonym merge between `accuracy`, `success rate`, `score`, and `Avg`;
- value repair parsing for percent, decimal, ratio, time, cost, and count values;
- placeholder rejection for `See table`, `not reported`, `N/A`, `-`, and `unknown`;
- multi-number ambiguity warnings;
- comparability grouping by dataset, task, unit, direction, and value scale;
- readiness statuses for strict ready, ready after value repair, discoverable not comparable, needs canonical review, needs value repair, needs year repair, and single-paper cases;
- CLI JSON/human output;
- invalid limit/offset behavior;
- missing catalog behavior;
- read-only boundary with monkeypatches blocking LLM, embedding, MinerU, parser, import, ingest, apply, ask, synthesis, lint, clean, and CLI recursion;
- file snapshot proving no writes to workspace outputs.

## 15. Relationship To Other Phases

V4.7 is the bridge between V4.6 acceptance reporting and future usable metric evolution.

- V4.6 says whether the corpus has enough result evidence.
- V4.7 says which metric groups are comparable enough for timeline use.
- A later phase may add curated alias files, catalog migrations, or staged repair apply, but V4.7 intentionally stays read-only.
- V5 research intelligence should consume strict-ready or ready-after-value-repair groups first, and treat ambiguous/discoverable groups as diagnostics rather than evidence conclusions.

## 16. Open Questions

1. Should canonical aliases eventually be curated in a committed config file?
   - Default for V4.7: no. Emit suggestions only.
2. Should ready-after-value-repair rows be usable by `llmwiki metric timeline` before repair is applied?
   - Default for V4.7: no. They are report-only until a later explicit repair/apply spec exists.
3. Should `score` and `Avg` be automatically canonicalized when dataset/task match?
   - Default for V4.7: no. Mark as `context_dependent` or `ambiguous_label`.
4. Should unit conversion be supported?
   - Default for V4.7: only identify compatible value scales; do not convert across units except parsing equivalent raw forms like `42.1%` into value `42.1` unit `%`.
