# LLMWiki V4.5-min Result Evidence Quality Closure Design

Date: 2026-06-04

Status: planning spec

## 1. Summary

V4.5-min closes the evidence-quality gaps that make V4.3 structured result records and V4.4 metric timelines hard to trust, inspect, or evaluate.

The goal is not broad PDF understanding. The goal is a deterministic, source-backed quality closure for metric/result evidence:

```text
metric_results rows
-> formal claims
-> source locators
-> PDF page/block or Markdown line context
-> local quality diagnostics
-> result evidence report
```

V4.5-min should add one read-only evaluation surface:

```powershell
llmwiki eval result-evidence --root .
llmwiki eval result-evidence --root . --json
```

The report should verify that applied metric/result records can be inspected back to their source context. It must not call LLM providers, embedding providers, MinerU, parser execution, add/import, ingest, apply, ask, synthesis, or clean.

## 2. Background

V4.3 added structured metric/result extraction:

```text
staging/<run-id>/metric-results.jsonl
-> apply
-> state/catalog.sqlite metric_results
```

V4.4 added metric timeline queries over durable `metric_results`. V4.4 full-corpus acceptance showed that timeline output works:

- 20/20 papers applied after retrying one transient provider/network failure;
- 237 durable `metric_results` rows;
- 237 rows joined to `claims` and `sources`;
- `success rate` timeline returned 69 rows across 15 papers;
- every selected timeline row had `result_id`, `claim_id`, `source_id`, and `citation_locator`.

The next bottleneck is evidence quality, not query mechanics. Timeline rows can exist while still being hard to audit if:

- the locator does not resolve to readable source context;
- table/caption blocks do not expose enough normalized text;
- `metric_value` is missing or only raw text is available;
- result metadata such as method/dataset/task/baseline is sparse;
- table-derived or caption-derived result claims cannot be distinguished from ordinary text claims;
- parser fallback diagnostics exist but are not summarized in result evidence quality terms.

V4.5-min should make these quality issues measurable and inspectable before moving to V4.6 corpus acceptance metrics or V5 relation/maintenance work.

V4.5-min acceptance should use a fixed 5-paper subset from `docs/papers/`, not the full 20-paper corpus. The purpose is faster inspection and discussion of concrete result-evidence issues before broadening the report in V4.6.

## 3. Non-Goals

V4.5-min must not implement:

- UI;
- OCR for scanned PDFs;
- visual chart interpretation;
- image-based figure reading;
- general table semantic parsing;
- table cell coordinate extraction unless already present in normalized blocks;
- metric alias curation;
- unit conversion beyond V4.3 deterministic normalized fields;
- ranking or "best method" conclusions;
- metric timeline changes except for narrow bug fixes;
- relationship classification;
- conflict detection;
- trend/gap/synthesis generation;
- wiki writeback;
- catalog migration unless a concrete V4.5 blocker proves the current fields cannot represent required diagnostics.

V4.5-min should not add speculative parser fallback designs. Fix only observed blockers recorded by tests or acceptance observations.

## 4. Product Goal

A user or evaluator can run:

```powershell
llmwiki eval result-evidence --root . --json
```

and learn whether the corpus has trustworthy metric/result evidence:

```text
Result evidence quality
Sources: 5
Metric results: 40
Resolvable locators: 40
Invalid locators: 0
Rows with source context: 40
Rows missing normalized value: 6
Table/caption rows: 4
Rows with value support warning: 3
```

For each problematic row, the report should identify:

- `result_id`;
- `claim_id`;
- `source_id`;
- `paper_id`;
- `metric_name`;
- `citation_locator`;
- problem code;
- bounded diagnostic message.

The report should help answer: "Can I trust this timeline row enough to inspect it and cite it?"

## 5. Core Concepts

- `result evidence`: a durable `metric_results` row joined to a formal claim and source, plus enough source context to inspect the reported metric/result.
- `locator resolution`: deterministic mapping from `citation_locator` to Markdown/text lines or PDF page/block context.
- `support context`: bounded source text that a human can inspect. For PDFs, this is sidecar block text, not raw parser artifact files.
- `quality diagnostic`: local, deterministic warning or error about evidence inspectability.
- `quality closure`: a narrow change that removes an observed blocker without weakening the evidence contract.

## 6. Command Contract

### 6.1 Eval Command

Canonical command:

```powershell
llmwiki eval result-evidence --root .
```

Options:

```text
--json
--source-id <source-id>
--paper-id <paper-id>
--metric <metric-name>
--dataset <dataset>
--task <task>
--limit <n>
--offset <n>
```

Defaults:

- `limit = 200`;
- maximum `limit = 1000`;
- `offset >= 0`;
- filters are AND-ed together;
- `--metric`, `--dataset`, and `--task` use the same conservative normalized equality rules as V4.4;
- human output shows summary first, then a compact diagnostics table.

Exit behavior:

- exit code `0` when evaluation completes, even if quality warnings are found;
- exit code `1` for invalid arguments, missing workspace, unavailable catalog, incompatible schema, or unreadable required catalog state;
- do not write files.

### 6.2 JSON Schema

Response schema:

```text
result_evidence_quality.v4.5
```

Top-level fields:

```text
schema_version
root
generated_at
query
summary
items
warnings
```

`summary` fields:

```text
source_count
paper_count
metric_result_count
joined_result_count
resolvable_locator_count
unresolvable_locator_count
context_available_count
missing_context_count
pdf_result_count
markdown_result_count
table_result_count
caption_result_count
missing_normalized_value_count
missing_method_count
missing_dataset_count
missing_task_count
missing_baseline_count
value_support_warning_count
parser_diagnostic_source_count
warning_count
error_count
```

Item schema:

```text
result_evidence_item.v4.5
```

Item fields:

```text
schema_version
result_id
claim_id
source_id
paper_id
source_type
paper_title
metric_name
metric_value
metric_raw_value
method
dataset
task
baseline
extraction_origin
citation_locator
confidence_status
locator_status
context_status
context_preview
context_page
context_block_id
context_block_role
evidence_block_ids
evidence_pages
diagnostics
```

Rules:

- `context_preview` must be bounded and sanitized.
- `diagnostics` must be a list of structured objects.
- Missing strings use `""`; missing lists use `[]`; missing integers use `null`.
- No raw prompts, raw LLM responses, parser logs, parser artifact contents, or API keys may appear.

## 7. Data Sources

V4.5-min may read:

- `state/catalog.sqlite`;
- `metric_results`;
- `claims`;
- `sources`;
- `pages`;
- V4.2 paper identity metadata through inventory helpers;
- `sources/blocks/<source-id>.jsonl`;
- `sources/metadata/<source-id>.json`;
- `sources/normalized/<source-id>.md` or `.txt` when catalog points to it and path is workspace-bounded.

V4.5-min must not read parser-native artifact files as evidence. Parser artifact paths may appear only as redacted diagnostics if already summarized in metadata.

V4.5-min must not inspect raw PDFs or run parsers. Raw PDFs remain source material, not a deterministic evaluation dependency.

## 8. Locator Resolution

### 8.1 PDF Locators

For PDF sources, V4.5-min should support:

```text
page:N;block:<block-id>
page:N;block:<block-id>;section:<section>
```

Resolution steps:

1. Parse page number and block id.
2. Verify `sources/blocks/<source-id>.jsonl` exists.
3. Verify block id exists in that sidecar.
4. Verify block source id matches the result `source_id`.
5. Verify block page matches the locator page when both are available.
6. Return bounded block text as `context_preview`.
7. Include block role and section path when available.

Unsupported or malformed PDF locators should produce diagnostics, not fabricated context.

### 8.2 Markdown/Text Locators

For Markdown/text sources, V4.5-min should support:

```text
line:N
line:N;section:<section>
```

Resolution steps:

1. Verify normalized path is workspace-bounded and under `sources/normalized/`.
2. Read a bounded number of lines around `line:N`.
3. Return escaped/sanitized text as `context_preview`.
4. Warn if the line number is out of range.

### 8.3 Unsupported Locators

Unsupported locators must produce:

```text
locator_status = "unsupported"
context_status = "missing"
diagnostic code = "unsupported_locator"
```

They must not be silently counted as valid evidence.

## 9. Quality Diagnostics

V4.5-min should classify diagnostics as `info`, `warning`, or `error`.

Recommended diagnostic codes:

```text
missing_metric_result_join
missing_claim_join
missing_source_join
unsupported_locator
malformed_locator
missing_block_sidecar
malformed_block_sidecar
missing_block_id
page_mismatch
missing_normalized_source
line_out_of_range
missing_context
missing_metric_value
raw_only_metric_value
missing_method
missing_dataset
missing_task
missing_baseline
value_not_visible_in_context
table_context_missing_value
caption_context_missing_statement
parser_fallback_observed
parser_quality_warning
metadata_malformed
```

Error diagnostics:

- row cannot join to claim/source;
- locator is malformed or unsupported;
- sidecar is missing or malformed;
- block id cannot be found;
- normalized line locator cannot be resolved.

Warning diagnostics:

- normalized value is missing;
- method/dataset/task/baseline is missing;
- value is not visible in bounded context;
- table/caption context appears too sparse;
- parser fallback was observed.

Info diagnostics:

- raw-only metric value;
- no baseline reported;
- non-main result.

Diagnostics are evaluation outputs, not formal evidence and not wiki claims.

## 10. Value Support Checks

V4.5-min should perform conservative local checks to improve inspectability.

Allowed:

- check whether `metric_raw_value` appears in `claim_text` or bounded source context;
- check whether normalized `metric_value` appears in `claim_text` or bounded source context;
- for percentages, check common display forms such as `42.1`, `42.1%`, and `42.10`;
- warn when no value string is visible.

Not allowed:

- infer missing values;
- convert units without explicit source text;
- read values from figure images;
- parse arbitrary table semantics to derive hidden row/column meaning;
- upgrade a weak result to cited based on local string matching.

If value support is not visible, keep the row but emit `value_not_visible_in_context`.

## 11. Table And Caption Evidence

Table/caption evidence should be evaluated only from normalized block text and existing V4.3 fields.

Table-derived row requirements:

- `extraction_origin = "table"` or table-like block role in `evidence_block_roles`;
- cited block text should include metric/value context or produce `table_context_missing_value`;
- table block id should appear in `evidence_block_ids` when available.

Caption-derived row requirements:

- `extraction_origin = "caption"` or caption-like block role in `evidence_block_roles`;
- caption text should contain the statement needed for the result or produce `caption_context_missing_statement`;
- figure/image artifact paths are not evidence.

V4.5-min should not reject applied rows. It reports quality diagnostics so V4.3 extraction can be narrowed in a later fix if needed.

## 12. Safety And Read-Only Boundary

`llmwiki eval result-evidence` must not call:

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
- clean.

It must not write:

- `wiki/`;
- `sources/`;
- `staging/`;
- `state/catalog.sqlite`;
- `state/corpus-batches/`;
- `state/embeddings/`;
- `state/ui-jobs/`;
- `.tmp/`.

It may print stdout/stderr only. If a later implementation adds `--output`, that requires a separate planned change and write-boundary tests.

## 13. Relationship To V4.6

V4.6-min should aggregate corpus acceptance metrics. V4.5-min provides the result-evidence quality primitives V4.6 needs.

V4.6 should be able to consume or reuse V4.5 metrics such as:

- result locator validity;
- context availability;
- missing normalized value count;
- table/caption result quality;
- parser diagnostic source count;
- result evidence warning/error count.

V4.5-min should not implement the full V4.6 acceptance report.

## 14. Testing Strategy

Use spec-driven, contract-first, risk-based TDD.

Recommended tests:

- JSON schema tests for `result_evidence_quality.v4.5`;
- PDF locator parsing and sidecar resolution tests;
- Markdown/text `line:N` locator resolution tests;
- malformed locator tests;
- missing/malformed sidecar tests;
- block id not found tests;
- page mismatch tests;
- value support warning tests;
- table/caption diagnostics tests;
- missing method/dataset/task/baseline diagnostics tests;
- CLI human and JSON output tests;
- filter tests for source, paper, metric, dataset, task, limit, and offset;
- no-write boundary tests;
- monkeypatch tests proving no LLM, embedding, MinerU, parser, import, ingest, apply, ask, synthesis, lint, clean calls;
- sanitizer tests for diagnostics.

Suggested files:

```text
tests/test_result_evidence_quality_model.py
tests/test_result_evidence_quality_locator.py
tests/test_result_evidence_quality_cli.py
tests/test_result_evidence_quality_readonly.py
tests/test_regression_samples.py
```

## 15. Manual Acceptance

Use a real V4.3/V4.4-generated 5-paper subset. Unit tests are necessary but not sufficient.

Default V4.5-min acceptance subset:

```text
docs/papers/2404.07972.pdf
docs/papers/2409.08264.pdf
docs/papers/2501.16150.pdf
docs/papers/2506.16042.pdf
docs/papers/2509.15221.pdf
```

The implementation should copy these five files into `.tmp/paper-v45-acceptance/input-papers/` and import that temporary directory. Do not import all 20 `docs/papers/` files for V4.5-min acceptance unless the user explicitly asks for a larger run.

Recommended workflow:

```powershell
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v45-acceptance
.\.venv\Scripts\python.exe -m llmwiki corpus import input-papers --root .tmp\paper-v45-acceptance --recursive --parser auto
.\.venv\Scripts\python.exe -m llmwiki metric list --root .tmp\paper-v45-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric timeline "<metric-from-list>" --root .tmp\paper-v45-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki eval result-evidence --root .tmp\paper-v45-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki eval result-evidence --root .tmp\paper-v45-acceptance
```

Record an acceptance observation file under `docs/specs/`, for example:

```text
docs/observations/2026-06-04-llmwiki-v4-5-result-evidence-quality-acceptance-observations.md
```

The observation should report:

- imported paper count, expected to be 5 for V4.5-min;
- selected source filenames;
- formal claim count;
- durable `metric_results` row count;
- joined result count;
- resolvable locator count;
- unresolvable locator count;
- context available count;
- missing context count;
- table/caption result count;
- missing normalized value count;
- value support warning count;
- missing method/dataset/task/baseline counts;
- parser diagnostic source count;
- top diagnostic codes;
- selected timeline metric and whether its rows pass evidence-quality checks.

Generated workspaces, source sidecars, staging, catalog, wiki output, vector cache, parser artifacts, raw prompts/responses, parser logs, and local API keys must not be committed.

Unlike the usual closeout default, do not run `llmwiki clean --root .` or delete `.tmp/paper-v45-acceptance` automatically after V4.5-min acceptance. Preserve the temporary acceptance workspace so the user can ask follow-up questions about implementation details, generated diagnostics, and concrete result rows. Clean it only after the user explicitly approves cleanup.

## 16. Success Criteria

V4.5-min is successful when:

1. `llmwiki eval result-evidence` reports deterministic quality metrics for applied `metric_results`.
2. Every quality item is traceable to `result_id`, `claim_id`, `source_id`, and `citation_locator`.
3. PDF page/block locators and Markdown/text line locators can be resolved or produce explicit diagnostics.
4. Table/caption rows receive evidence-quality diagnostics without using parser artifact files or visual interpretation.
5. Missing values and sparse method/dataset/task/baseline metadata are visible in the report.
6. The command is read-only and does not call LLM, embedding, parser, ingest, apply, ask, synthesis, lint, clean, or write paths.
7. Five-paper acceptance records result evidence quality over the fixed V4.5-min subset and preserves the acceptance workspace for user inspection.
8. V4.6 can reuse V4.5 quality metrics without re-reading raw PDFs or re-running LLM extraction.

## 17. Open Questions For The Implementation Plan

1. Should `eval result-evidence` include full per-row items by default in JSON, or require a future `--detail` flag if output becomes too large?
2. Should `context_preview` default to one block/line window, or should the command include a bounded `--context-chars` option?
3. Should parser fallback diagnostics count as warnings for every affected result row or only once per source?
4. Should missing baseline be an info diagnostic rather than a warning, since many papers do not report explicit baselines for every result?
5. Should V4.5 add a small curated fixture with table/caption blocks, or rely only on synthetic sidecar fixtures for unit tests?
