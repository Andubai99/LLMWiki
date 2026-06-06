# LLMWiki V4.5.1 MinerU Result Extraction Quality Repair Design

Date: 2026-06-04

Status: planning spec

## 1. Summary

V4.5.1 is a narrow repair stage after V4.5-min. It fixes the observed gap between parser structure and result extraction quality:

```text
MinerU produces richer table/caption/layout blocks
but V4.3 result extraction does not yet use them well enough.
```

The goal is not a new product surface. The goal is to make the same 5-paper acceptance subset run under strict MinerU, then improve metric/result extraction so durable `metric_results` rows are more complete and more often grounded in table/caption blocks.

V4.5.1 should preserve the existing source-backed contract:

- formal `claims` remain the evidence source of truth;
- `metric_results` remains a structured query surface;
- only staging/apply can create durable knowledge;
- parser artifacts and parser logs are not evidence;
- no UI, no catalog migration, no metric timeline redesign.

## 2. Background

V4.5-min added:

```powershell
llmwiki eval result-evidence --root .
llmwiki eval result-evidence --root . --json
```

The first 5-paper V4.5-min acceptance used `--parser auto` and succeeded, but the result-evidence report showed every metric result row carried parser fallback diagnostics:

```text
paper count: 5
formal claims: 864
metric_results: 73
joined results: 73
resolvable locators: 73
context available: 73
table/caption context: 0
parser diagnostic sources: 5
parser fallback rows: 73
missing value: 28
missing method: 26
missing dataset: 29
missing task: 18
missing baseline: 51
warnings: 174
errors: 0
```

A follow-up strict MinerU comparison exposed two separate facts:

1. A temporary acceptance workspace did not discover the repo `.venv` MinerU command unless `mineru_command` was configured explicitly.
2. Strict MinerU with the CLI default backend failed for all 5 papers because no content list was produced.

After configuring the temporary workspace to use:

```toml
[pdf_parser]
mineru_command = "F:/LLMWiki/.venv/Scripts/mineru.exe"
mineru_backend = "pipeline"
mineru_method = "auto"
mineru_extra_args = ["-l", "en"]
```

the same 5 papers applied successfully under strict `--parser mineru`.

MinerU pipeline comparison against the pypdf/fallback baseline:

```text
claims: 864 -> 1157
metric_results: 73 -> 53
joined results: 73 -> 53
resolvable locators: 73 -> 53
context available: 73 -> 53
table result context: 0 -> 12
caption result context: 0 -> 0
parser diagnostic sources: 5 -> 0
missing value: 28 -> 21
missing method: 26 -> 15
missing dataset: 29 -> 9
missing task: 18 -> 8
missing baseline: 51 -> 34
warnings: 174 -> 53
errors: 0 -> 0
```

This proves MinerU helps, but also shows the extraction layer is underusing the richer blocks: result count fell from 73 to 53 even though table/caption sidecars became much richer.

Additional coverage inspection over the preserved comparison workspaces found a more precise extraction gap:

```text
MinerU candidate table blocks: 55
MinerU candidate caption blocks: 79
MinerU candidate result-text blocks: 93
Referenced candidate table blocks: 3
Referenced candidate caption blocks: 0
```

These candidate counts are conservative heuristics over the 5-paper MinerU sidecars, not formal evidence. They are useful as repair baselines: V4.5.1 should noticeably raise candidate table/caption coverage while preserving strict locator validation and avoiding over-extraction from dataset inventory or unrelated appendix/reference tables.

## 3. Problem Statement

V4.5.1 must address three observed problems.

### 3.1 MinerU Operational Reliability

`llmwiki parsers status --root .` can find MinerU in the repo `.venv`, but a temporary workspace under `.tmp/` may not. This makes acceptance easy to accidentally run with fallback.

Strict `--parser mineru` also exposed that the current default MinerU backend path is not reliable for the local environment. The installed MinerU CLI defaults to `hybrid-auto-engine`, while the observed successful path is `pipeline + auto + en`.

### 3.2 Result Count Regression

MinerU produced more claims and better structured blocks, but fewer durable `metric_results` rows:

```text
pypdf/fallback: 73
MinerU pipeline: 53
```

That suggests the V4.3 chunk renderer or result prompt is better tuned for paragraph-style text than for table/caption-rich MinerU blocks.

### 3.3 Field Completeness And Table/Caption Evidence

MinerU improved missing fields, but many structured fields remain sparse:

```text
missing value: 21
missing method: 15
missing dataset: 9
missing task: 8
missing baseline: 34
```

MinerU sidecars contained many table/caption blocks:

```text
table_like blocks: 111
caption blocks: 92
```

but result evidence only used:

```text
table result context: 12
caption result context: 0
```

V4.5.1 should make table/caption context a first-class extraction source without weakening citation validation.

The most concrete evidence of underuse is that many MinerU table blocks already contain explicit values and metric headers, but they are not referenced by durable result rows. Examples include benchmark result tables for MMBench-GUI, ScreenSpot-Pro, OSWorld, WindowsAgentArena, and ablation settings. Some current table-backed rows also preserve a value as `See table`, which is not an acceptable final cited result value when the table contains visible numeric cells.

## 4. Product Goal

After V4.5.1, the user can run a strict MinerU acceptance on the fixed 5-paper subset and get a result-evidence report that shows:

- all 5 papers imported with `parser_backend = "mineru"`;
- no parser fallback rows;
- durable result rows remain fully traceable to claims/sources/locators;
- more result rows are grounded in table/caption context;
- fewer rows miss method/dataset/task/value fields;
- any remaining missing fields are explicit diagnostics, not hidden quality failures.

The point is not to maximize row count by accepting weak results. The point is to extract more of the table-backed experimental evidence that is already present in MinerU blocks.

## 5. Non-Goals

V4.5.1 must not implement:

- UI;
- new catalog tables;
- broad schema migration;
- metric alias curation;
- unit conversion beyond existing deterministic normalization;
- visual chart interpretation;
- figure-image reading;
- OCR for scanned PDFs beyond MinerU's configured parser behavior;
- full 20-paper acceptance by default;
- V4.6 corpus acceptance dashboard;
- V5 relationship classification;
- trend/gap/synthesis generation;
- wiki writeback changes;
- automatic cleanup of preserved acceptance workspaces.

V4.5.1 should not make `pypdf` worse. `pypdf` remains a debug/fallback backend, but V4.5.1 acceptance is strict MinerU.

## 6. Fixed Acceptance Dataset

V4.5.1 uses the same fixed 5 papers as V4.5-min:

```text
docs/papers/2404.07972.pdf
docs/papers/2409.08264.pdf
docs/papers/2501.16150.pdf
docs/papers/2506.16042.pdf
docs/papers/2509.15221.pdf
```

Recommended workspaces:

```text
.tmp/paper-v45-acceptance                  # existing pypdf/fallback baseline
.tmp/paper-v45-mineru-acceptance           # existing MinerU pipeline comparison
.tmp/paper-v451-mineru-repair-acceptance   # post-repair strict MinerU run
```

Do not clean these workspaces automatically. They are inspection artifacts for the current research-quality discussion.

## 7. MinerU Operational Contract

### 7.1 Strict Acceptance

V4.5.1 acceptance must use:

```powershell
.\.venv\Scripts\python.exe -m llmwiki corpus import input-papers --root .tmp\paper-v451-mineru-repair-acceptance --parser mineru
```

`--parser mineru` is required so parser failure is visible. `--parser auto` is not acceptable for V4.5.1 acceptance because fallback can hide the problem being measured.

### 7.2 Parser Configuration

The accepted local MinerU configuration for this English research-paper subset is:

```toml
[pdf_parser]
mineru_enabled = true
mineru_command = "F:/LLMWiki/.venv/Scripts/mineru.exe"
mineru_backend = "pipeline"
mineru_method = "auto"
mineru_extra_args = ["-l", "en"]
```

The implementation should make this reliable without requiring fragile manual edits. Acceptable first-version approaches:

- fix MinerU discovery so `.tmp/` workspaces can discover the repo `.venv` command;
- document and test workspace-local parser config overrides;
- add a small internal helper for acceptance setup if it does not become a new product command;
- improve `parsers status` diagnostics so it reports backend/method/extra args and makes accidental `hybrid-auto-engine` use obvious.

Do not silently change a strict MinerU failure into fallback.

### 7.3 Failure Reporting

If strict MinerU fails:

- report the source path;
- report the sanitized parser failure reason;
- record whether command discovery succeeded;
- record backend/method/extra args;
- do not expose raw parser logs, API keys, or full parser artifacts in committed docs.

## 8. Extraction Quality Repair

V4.5.1 should improve the V4.3 PDF chunked ingest path rather than introducing a separate paper pipeline.

### 8.1 Chunk Rendering

The chunk evidence renderer should preserve enough structured context for table/caption extraction:

- page number;
- block id;
- block type;
- content role;
- backend type;
- section path;
- table markdown or table-like text;
- caption text;
- nearby bounded section heading;
- nearby bounded caption/table pairing when deterministic.

Table blocks should not appear to the LLM as generic paragraphs. Captions should not be separated from the table/figure context when the sidecar ordering makes a bounded pairing clear.

Recommended rendering shape:

```text
[block id=src_xxx_p008_b0012 page=8 type=table role=table_like section=Results]
<table markdown or normalized table text>

[paired caption block id=src_xxx_p008_b0011 type=caption]
Table 2: Performance on OSWorld...
```

The LLM may use paired caption/heading context to fill `dataset`, `task`, or `metric_name`, but every durable result must still cite a real block locator and include evidence block ids.

### 8.2 Prompt Contract

The metric/result extraction prompt should explicitly prioritize:

- result tables;
- table captions;
- experiment/results sections;
- abstract headline results;
- conclusion restatements only when they contain explicit values or comparisons.

For every candidate, the prompt should ask for:

```text
claim_text
citation_locator
evidence_block_ids
evidence_block_roles
extraction_origin
method
dataset
task
metric_name
metric_value
metric_raw_value
metric_unit
baseline
comparison_value
setting
is_main_result
warnings
```

The prompt should instruct the LLM to leave fields empty rather than invent them. It should also encourage use of table headers, row labels, caption text, and section headings when they are present in the bounded chunk.

### 8.3 Candidate Validation

Validation should reject or downgrade candidates when:

- cited block id is absent;
- cited block belongs to another source;
- cited block was not included in the chunk evidence;
- numeric value is absent from both claim text and bounded context;
- `metric_raw_value`, `metric_value`, or the formal claim uses placeholder values such as `See table`, `see table`, `not reported`, or `N/A` while a concrete table cell value is visible in the cited context;
- method/dataset/task are inferred from outside the chunk;
- table row/column semantics are ambiguous.

Validation should keep warning-bearing weak candidates visible in staging/triage, but only cited applied claims should become durable `metric_results`.

For table candidates, "value visible" should be checked conservatively against the cited block text and paired context. If a concrete cell value cannot be localized, the candidate may remain weak or warning-bearing, but it should not become a cited durable result merely because the table exists.

### 8.4 Table/Caption Pairing

V4.5.1 should add deterministic table/caption pairing only when it is bounded and auditable.

Allowed pairing:

- immediately adjacent caption before or after a table block on the same page;
- same section path and nearby order window;
- table block includes its caption text in MinerU output;
- caption explicitly names a benchmark/metric needed to interpret a table.

Not allowed:

- using image pixels;
- reading chart values from figures;
- pairing distant captions across pages;
- using parser artifact paths as evidence;
- fabricating table semantics.

When pairing is used, `evidence_block_ids` should include both table and caption block ids when available.

The primary `citation_locator` remains a single real block, but auxiliary evidence must not be discarded. If the LLM or deterministic pairing identifies valid table/caption/heading support blocks, validation should preserve them in `evidence_block_ids`, `evidence_pages`, and `evidence_block_roles` as long as every auxiliary block is:

- from the same source;
- present in the chunk evidence or a bounded paired context;
- not ignored parser noise;
- relevant to interpreting the cited metric/result.

This specifically fixes the current behavior where caption support can disappear because the primary locator block overwrites auxiliary `evidence_block_ids`.

### 8.4.1 Table Coverage Classification

MinerU exposes many table-like blocks, but not every table is a metric/result target. V4.5.1 should classify table blocks before prioritizing extraction:

- `result_table`: contains method/model rows or columns plus metric/value cells for an evaluation benchmark. Prioritize extraction.
- `ablation_or_diagnostic_table`: contains metric/value cells for settings, variants, ablations, efficiency, or diagnostic slices. Extract when method/dataset/task/setting can be localized.
- `dataset_inventory_table`: describes corpus size, platform coverage, sample counts, collection methods, or task taxonomy. Usually not a metric result unless it explicitly reports an evaluation metric.
- `paper_metadata_or_reference_table`: appears in references, appendix metadata, or unrelated listings. Do not extract unless it explicitly reports evaluation results.
- `ambiguous_table`: has numbers but unclear row/column semantics. Keep weak/warning-bearing candidates only.

The classifier can be deterministic and heuristic in the first implementation. It is a prioritization aid, not evidence and not a durable catalog field unless a later spec says so.

### 8.5 Field Completeness

V4.5.1 should reduce missing fields by using bounded table/caption/heading context:

- `method`: table row label, model column, method section context, or explicit statement;
- `dataset`: table caption, benchmark name in heading, or result sentence;
- `task`: table caption, section heading, benchmark description, or explicit statement;
- `metric_name`: table header, caption, or result sentence;
- `metric_value`: table cell, result sentence, or abstract headline;
- `baseline`: comparison row/column, "compared with" phrase, or explicit baseline label.

Missing `baseline` remains common and should not block cited results by itself. Missing `metric_value` is higher risk and should produce a warning or downgrade when no source value is visible.

## 9. Evaluation And Comparison Contract

V4.5.1 should compare three runs:

```text
baseline A: V4.5 pypdf/fallback
baseline B: V4.5 strict MinerU pipeline before repair
candidate C: V4.5.1 strict MinerU pipeline after repair
```

Minimum comparison metrics:

```text
paper_count
formal_claim_count
metric_results_count
joined_result_count
resolvable_locator_count
context_available_count
table_result_count
caption_result_count
parser_fallback_source_count
parser_fallback_row_count
missing_metric_value_count
missing_method_count
missing_dataset_count
missing_task_count
missing_baseline_count
warning_count
error_count
top_metric_names
top_diagnostic_codes
```

The implementation may add a small local script or test helper to compute the comparison, but it should not become a public command unless a later spec requires it.

## 10. Success Criteria

Hard gates:

1. Strict MinerU acceptance imports 5/5 papers.
2. All imported sources report `parser_backend = "mineru"`.
3. No source falls back to `pypdf`.
4. `eval result-evidence` returns exit code `0`.
5. Every durable result row joins to formal `claims` and `sources`.
6. Every durable result row has a resolvable locator or explicit error diagnostic.
7. No raw parser logs, parser artifacts, raw prompts, raw LLM responses, or API keys are committed.

Quality targets, measured against the strict MinerU pre-repair baseline:

```text
metric_results_count: >= 53, target >= 70
table_result_count: >= 12, target > 12
caption_result_count: >= 0, target > 0 when captions support explicit results
referenced_candidate_table_blocks: >= 10, from current 3/55 baseline
referenced_candidate_caption_blocks: > 0 when captions contain benchmark/metric/result context
missing_metric_value_count: <= 21
missing_method_count: <= 15
missing_dataset_count: <= 9
missing_task_count: <= 8
missing_baseline_count: <= 34
warning_count: <= 53
error_count: 0
```

Stretch target against the pypdf/fallback baseline:

- recover or exceed 73 durable `metric_results` rows while keeping MinerU table context and lower missing-field counts.

Quality targets are not permission to over-extract. Unsupported or ambiguous table values should remain weak or warning-bearing.

Coverage targets should be reported with examples. A target is not satisfied by extracting more rows from the same already-covered table while leaving obvious result tables untouched. The observation should show at least several newly covered table blocks and any newly preserved caption support blocks.

## 11. Testing Strategy

Use spec-driven, contract-first, risk-based TDD.

Recommended test coverage:

- MinerU discovery finds repo `.venv` from `.tmp/` workspaces or clearly reports configured path requirements.
- `parsers status` reports MinerU command source, backend, method, and extra args.
- strict `--parser mineru` does not fallback to `pypdf`.
- parser config TOML stays valid UTF-8 without BOM sensitivity in test fixtures.
- chunk renderer includes block type, content role, section path, table markdown, caption text, and paired block ids.
- table-derived result candidates preserve table block ids.
- caption-supported candidates preserve caption block ids.
- invalid table/caption block ids are rejected or downgraded.
- fake LLM table candidate with method/dataset/task/value becomes a cited metric result.
- fake LLM candidate missing visible value becomes warning-bearing or weak.
- staging `metric-results.jsonl` preserves `evidence_block_ids` and `evidence_block_roles`.
- apply writes durable `metric_results` only for applied formal claims.
- `eval result-evidence` counts table/caption contexts correctly.
- existing pypdf tests still pass.

Likely test files:

```text
tests/test_parser_status_cli.py
tests/test_mineru_runner.py
tests/test_pdf_chunked_ingest.py
tests/test_metric_result_extraction.py
tests/test_metric_result_staging.py
tests/test_result_evidence_quality_model.py
tests/test_result_evidence_quality_locator.py
tests/test_add_pipeline.py
tests/test_regression_samples.py
```

## 12. Manual Acceptance

Prepare post-repair workspace:

```powershell
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v451-mineru-repair-acceptance
```

Copy the same 5 PDFs into:

```text
.tmp/paper-v451-mineru-repair-acceptance/input-papers/
```

Copy local ignored API key config into the temporary workspace:

```text
.tmp/paper-v451-mineru-repair-acceptance/config/api-keys.toml
```

Ensure parser config uses strict MinerU pipeline:

```toml
[pdf_parser]
mineru_enabled = true
mineru_backend = "pipeline"
mineru_method = "auto"
mineru_extra_args = ["-l", "en"]
```

Run:

```powershell
.\.venv\Scripts\python.exe -m llmwiki parsers status --root .tmp\paper-v451-mineru-repair-acceptance
.\.venv\Scripts\python.exe -m llmwiki corpus import input-papers --root .tmp\paper-v451-mineru-repair-acceptance --parser mineru
.\.venv\Scripts\python.exe -m llmwiki eval result-evidence --root .tmp\paper-v451-mineru-repair-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki eval result-evidence --root .tmp\paper-v451-mineru-repair-acceptance
```

Record a sanitized observation file:

```text
docs/observations/2026-06-04-llmwiki-v4-5-1-mineru-result-extraction-quality-repair-acceptance-observations.md
```

Observation must include:

- exact 5 files used;
- parser status summary;
- first strict MinerU failure if it occurs;
- final import batch id;
- applied/failed/skipped counts;
- formal claim count;
- durable metric result count;
- result-evidence summary;
- comparison table against pypdf/fallback and pre-repair MinerU baselines;
- examples of table-backed result rows;
- examples of remaining missing-field rows;
- preserved workspace paths.

Do not commit generated workspaces, source sidecars, staging, catalog, wiki output, parser artifacts, raw prompts/responses, parser logs, API keys, or raw JSON dumps.

Do not clean the comparison workspaces by default. Keep them available for user questions until explicit cleanup approval.

## 13. Documentation Updates

V4.5.1 implementation should update:

- README: strict MinerU acceptance notes and the `pipeline + auto + en` local acceptance profile.
- AGENTS: V4.5.1 boundary that strict MinerU acceptance must not fallback and generated comparison workspaces are preserved by user request.
- Regression docs test: key command/schema/boundary strings.

The docs should clearly distinguish:

- parser backend diagnostics are not evidence;
- table/caption normalized blocks can support evidence;
- parser artifacts and visual image interpretation are not evidence.

## 14. Open Questions For The Implementation Plan

1. Should repo `.venv` MinerU discovery be fixed generically, or should V4.5.1 rely on explicit `mineru_command` config in acceptance workspaces?
2. Should `mineru_backend = "pipeline"` become the default config value for newly initialized workspaces, or remain an acceptance profile only?
3. Should `mineru_extra_args = ["-l", "en"]` be defaulted for this corpus or kept manual because future corpora may be multilingual?
4. Should caption-supported rows require caption block as the primary locator, or allow table primary locator plus caption in `evidence_block_ids`?
5. Should missing baseline remain an info diagnostic in V4.5.1 quality gates, or count as a warning for result completeness?

## 15. Success Criteria

V4.5.1 is successful when:

1. Strict MinerU acceptance is reproducible on the fixed 5-paper subset.
2. MinerU output is actually used, not hidden behind `auto` fallback.
3. V4.3 extraction uses table/caption blocks more effectively.
4. Durable result rows remain source-backed and locator-valid.
5. Method/dataset/task/value completeness improves or at least does not regress from the strict MinerU baseline.
6. Result count recovers toward the pypdf/fallback baseline without accepting unsupported table values.
7. The comparison is documented with sanitized observations and preserved workspaces for follow-up inspection.
