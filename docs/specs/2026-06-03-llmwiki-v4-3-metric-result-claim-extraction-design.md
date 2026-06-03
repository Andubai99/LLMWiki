# LLMWiki V4.3 Metric And Result Claim Extraction Design

## 1. Summary

V4.3 extends ingest so that research papers can produce source-backed structured metric/result claim candidates.

The goal is not to make LLMWiki write a paper summary. The goal is to make each imported paper expose auditable result statements such as:

```text
Paper P reports metric M with value V on dataset D/task T using method A.
```

Every cited metric/result claim must keep a valid source locator. For PDF sources, this means a page/block locator such as:

```text
page:5;block:src_xxx_p005_b0012;section:Experiments
```

V4.3 focuses on extraction from:

- abstract;
- method/model sections;
- experiment/evaluation/results sections;
- tables;
- captions;
- conclusion/discussion/limitations sections.

V4.3 keeps the existing ingest -> staging -> review -> apply discipline. It does not add UI, does not add a metric timeline command, does not perform paper identity migration, and does not bypass existing apply safety.

## 2. Background

V4's wider goal is to turn a same-field research corpus into a local source-backed wiki that can answer:

- Which papers report this metric?
- How did this metric evolve across these papers?
- Which method, dataset, task, and setting produced a given result?
- Which papers disagree or report incompatible values?

V4.1 added corpus import orchestration. V4.2 added paper identity and corpus inventory. V4.3 adds the missing extraction layer: formal claims plus structured result metadata that can later feed V4.4 metric timeline queries.

The older V3/V5 roadmap used a different V4.3 label for MinerU acceptance closure. This spec follows the current V4 research corpus direction and the user-facing V4.3 requirement: metric/result claim extraction.

## 3. Non-Goals

V4.3 must not implement:

- UI changes;
- metric timeline CLI/API;
- automatic conflict resolution;
- automatic paper merge or duplicate source deletion;
- new external metadata services;
- hosted vector databases;
- LLM-based reranking for metric timeline;
- broad page type migration such as `paper`, `method`, `dataset`, `metric`, or `result`;
- direct writes to `wiki/`, `state/catalog.sqlite`, or formal catalog tables outside existing apply paths;
- metric/result claims without source-backed locators.

V4.3 may introduce generated/staging artifacts for structured result metadata, but formal knowledge still flows through normal staging/apply.

## 4. Core Terms

- `metric`: a named measurement, for example accuracy, F1, error rate, latency, win rate, BLEU, success rate, or domain-specific score.
- `result`: a reported metric value under a method/model, dataset/benchmark, task, and setting.
- `metric/result claim`: a formal natural-language claim that reports a metric/result and can be cited.
- `structured result metadata`: machine-readable fields attached to a metric/result claim, such as `metric_name`, `metric_value`, `dataset`, `method`, and `task`.
- `locator`: an audit anchor into the original source. For PDFs, locators must use page/block anchors.
- `origin`: the paper region where the result was extracted, such as `abstract`, `method`, `experiment`, `table`, `caption`, or `conclusion`.

## 5. Evidence Contract

Metric/result extraction must obey the existing evidence contract.

1. A cited metric/result claim requires a real `source_id`, `claim_id`, `claim_text`, `confidence_status`, and `citation_locator`.
2. For PDF sources, the cited locator must include a page and a valid block id from the PDF block sidecar.
3. The block id must belong to the source being ingested.
4. The cited text, table-like text, or caption context must support the metric/result claim.
5. Parser diagnostics, parser logs, parser artifact paths, metadata fields, and parser backend attempts are audit data, not evidence.
6. LLM output is not evidence by itself. It can only propose claims grounded in provided source context.
7. Ambiguous or unsupported metric values must remain weak/uncited and must not be upgraded into cited result claims.
8. If a result is inferred by combining distant contexts, the combined support must be explicit and locators must preserve all involved blocks. If support cannot be localized, the result must stay weak.

## 6. Extraction Sources

### 6.1 Abstract

Abstracts often contain headline results. V4.3 should extract result claims from abstract blocks when:

- the metric/result is explicitly stated;
- the method/model or paper contribution can be identified from local context;
- the result value is present or the result is a qualitative comparison with clear wording;
- the locator points to the abstract block.

Abstract-derived result claims should usually set `extraction_origin = "abstract"` and may set `is_main_result = true` when the wording clearly indicates a headline result.

### 6.2 Method And Model Sections

Method sections can define the method/model being evaluated. V4.3 should extract metric/result claims from method sections only when the section actually reports an evaluated result.

Method descriptions without measured values should not become metric/result claims. They can remain ordinary claims.

Examples that can become result claims:

- "On Benchmark X, our method reaches 92.3% accuracy."
- "The model reduces inference latency to 24 ms under setting S."

Examples that should not become result claims:

- "We use accuracy as the main metric."
- "The method consists of three modules."

### 6.3 Experiment, Evaluation, And Results Sections

Experiment/result sections are the primary extraction target. V4.3 should capture:

- metric name;
- reported value;
- method/model;
- dataset/benchmark;
- task;
- setting or split;
- baseline or comparator when explicitly stated;
- comparison direction when explicitly stated.

For PDF papers, every extracted result should cite the block that states the result. If the result depends on an adjacent heading for dataset/task context, the structured metadata may include the section path, but the formal claim must still be supported by the cited block text or table context.

### 6.4 Tables

Tables are evidence when their normalized table-like text or table markdown supports the result.

V4.3 should support table-derived result claims when:

- the table block has a valid page/block id;
- the table text includes the metric/value row or column needed for the claim;
- the method/model and dataset/task can be read from the table, caption, section path, or nearby bounded context;
- the claim text does not invent values that are absent from the table context.

Table-derived claims should record:

- `extraction_origin = "table"`;
- the table block id in `evidence_block_ids`;
- any caption block id used in `evidence_block_ids`;
- warnings when table parsing appears lossy.

If a table is too malformed to identify row/column semantics, V4.3 may preserve a weak candidate and warning, but it must not create a cited result claim.

### 6.5 Captions

Captions can support result claims only for statements actually present in the caption.

Allowed:

- a figure caption says a method improves a metric by a stated amount;
- a table caption states the benchmark, metric, or setting needed to interpret the table.

Not allowed:

- using a figure image or parser artifact path as evidence;
- inferring numeric values from a plot image unless the value is explicitly represented in normalized text;
- creating result claims from visual interpretation.

Caption-supported result claims should include the caption block id and any linked table/figure block id when available.

### 6.6 Conclusion, Discussion, And Limitations

Conclusion and discussion sections often restate results or limitations. V4.3 should extract:

- clearly stated headline results;
- limitations about metrics or benchmarks;
- qualitative result comparisons when source wording is explicit.

Conclusion-derived candidates should dedupe against earlier abstract/table/experiment claims. If the conclusion only paraphrases an earlier result and lacks value/context, prefer the earlier stronger locator.

## 7. Structured Result Metadata

V4.3 should introduce a stable first-version schema for structured result metadata.

Recommended schema version:

```text
metric_result_claim.v4.3
```

Recommended fields:

```text
schema_version
result_id
claim_id
source_id
paper_id
claim_text
citation_locator
confidence_status
evidence_block_ids
evidence_pages
evidence_section_path
evidence_block_roles
extraction_origin
metric_name
metric_value
metric_unit
metric_raw_value
metric_direction
method
dataset
task
baseline
comparison_value
setting
reported_year
is_main_result
value_normalization_status
warnings
created_at
```

Field rules:

- `claim_id` must reference a formal claim in the same staging run.
- `paper_id` defaults to `source_id` until a durable paper identity table exists.
- `metric_name` must preserve the source-visible metric label when possible.
- `metric_value` is normalized only when deterministic.
- `metric_raw_value` preserves the source expression.
- `metric_unit` can be `%`, `ms`, `seconds`, `tokens`, `samples`, `score`, `ratio`, or an explicit source unit.
- `metric_direction` is one of `higher_is_better`, `lower_is_better`, `neutral`, or `unknown`.
- `is_main_result` is `true`, `false`, or `null`.
- `reported_year` should come from V4.2 paper identity unless the source explicitly reports a separate year for the benchmark/result.
- `warnings` is a list of bounded, sanitized messages.

Missing strings should be `""`; missing lists should be `[]`; missing booleans may be `null`; missing year should be `null`.

## 8. Formal Claims And Structured Metadata

The existing formal claim layer remains the source of truth for evidence-backed statements.

V4.3 should not replace `claims.jsonl`. Instead:

- every cited result record must map to a formal claim in `claims.jsonl`;
- the formal `claim_text` should be readable without structured fields;
- structured result metadata should reference the formal `claim_id`;
- if a formal claim is rejected by validation, its structured result metadata must be rejected too;
- if a metric result is useful but unsupported, it can appear as weak/uncited triage material but must not be applied as a cited result.

Recommended staging artifact:

```text
staging/<run-id>/metric-results.jsonl
```

The implementation plan may decide whether to add a generated post-apply cache or a catalog table. The first version should avoid changing the existing `claims` table unless V4.4 timeline requirements force durable query support immediately.

## 9. Ingest Flow

V4.3 should extend the existing PDF chunked ingest path rather than creating a separate paper ingestion pipeline.

Recommended flow:

```text
PDF blocks/chunks
-> chunk evidence rendering
-> LLM chunk extraction with metric_result_candidates
-> schema validation and locator normalization
-> result candidate dedupe
-> consolidation without new evidence invention
-> staging claims.jsonl + metric-results.jsonl + triage.md
-> review
-> apply
```

The chunk prompt should expose enough bounded context for:

- section path;
- page number;
- block id;
- block role;
- table-like text or table markdown;
- caption text;
- neighboring heading context when already part of the chunk renderer.

The LLM must be instructed to emit no result candidate when the metric, value, or locator cannot be supported by the provided chunk context.

## 10. Locator Validation

V4.3 should add stricter locator validation for metric/result candidates.

For PDF candidates:

1. Parse `citation_locator`.
2. Verify `page:N` exists in sidecar metadata.
3. Verify `block:<block-id>` exists in `sources/blocks/<source-id>.jsonl`.
4. Verify the block id belongs to the current source.
5. Verify the block id was present in the chunk evidence given to the LLM, or is an allowed adjacent caption/table block explicitly included by the renderer.
6. Normalize partial valid locators when deterministic. For example, `block:src_xxx_p003_b0007` can become `page:3;block:src_xxx_p003_b0007;section:Results` if page and section are known from the block sidecar.
7. Reject or downgrade invalid locators. Do not silently coerce a wrong block id into another block.

For Markdown/text sources, `line:N` remains valid. V4.3 is paper-focused, but it should not break non-PDF ingest.

## 11. Value Normalization

V4.3 should normalize values conservatively.

Allowed deterministic normalization:

- `92.3%` -> `metric_value = "92.3"`, `metric_unit = "%"` and `metric_raw_value = "92.3%"`;
- `0.923` with source saying accuracy/rate -> keep raw unless percent conversion is explicitly stated;
- `24 ms` -> `metric_value = "24"`, `metric_unit = "ms"`;
- `1.2x` -> `metric_value = "1.2"`, `metric_unit = "x"`;
- `+3.4 points` -> comparison value with unit `points`.

Not allowed:

- converting units without enough context;
- inferring missing baselines;
- turning ranks, table row numbers, figure labels, or footnote numbers into metric values;
- guessing whether higher or lower is better without source wording or metric convention already encoded locally.

`value_normalization_status` should be:

- `normalized`: deterministic numeric/unit normalization succeeded;
- `raw_only`: raw expression is preserved but no normalized value is safe;
- `ambiguous`: multiple possible values or unclear row/column interpretation;
- `missing`: no value was present.

## 12. Deduplication

Metric/result extraction should dedupe redundant candidates without hiding source diversity.

Deduplication keys should include:

- `source_id`;
- normalized `metric_name`;
- normalized `method`;
- normalized `dataset`;
- normalized `task`;
- normalized `metric_value` or `metric_raw_value`;
- locator block id.

Rules:

- exact same `claim_text` and locator can collapse to one formal claim;
- same result repeated in abstract and experiment sections should prefer the richer experiment/table locator, while preserving abstract mention as secondary evidence when useful;
- table plus caption candidates should merge only when they refer to the same result;
- conclusion restatements should not create duplicates unless they add a distinct limitation or comparison;
- duplicates across papers are not merged in V4.3. They remain separate source-backed results for V4.4/V5 comparison.

## 13. Relationship Seeds

V4.3 may prepare relationship candidates but should be conservative about applying new relationships.

Useful relationship concepts include:

- `reports_metric`: paper or method reports a metric/result;
- `evaluates_on`: method/result uses a dataset or benchmark;
- `uses_metric`: experiment/result uses a metric;
- `compares_against`: method/result compares against a baseline;
- `supports`: table/caption supports a result claim.

Unless a future implementation plan explicitly maps these into existing catalog relationship tables with validation, V4.3 should keep them as staging/triage candidates rather than durable formal relationships.

## 14. Safety And Security

V4.3 must preserve existing safety boundaries.

- Do not write final wiki pages directly during ingest.
- Do not write catalog rows directly from the extraction layer.
- Do not fabricate citations, claim ids, source ids, paper ids, block ids, metric values, baselines, datasets, or methods.
- Do not expose API keys, config secrets, raw prompts, raw LLM responses, or full parser logs in committed docs, tests, wiki pages, or UI responses.
- Do not use parser artifacts as retrieval evidence.
- Do not let LLM output choose parser backend, block ids, chunk boundaries, or page numbers.
- Do not add domain-specific query rules or hardcoded metric boosts.
- Keep weak, ambiguous, and conflicting claims visible.

## 15. Review And Wiki Output

V4.3 should make review output understandable.

`triage.md` should include a metric/result section with:

- result count;
- cited result count;
- weak/ambiguous result count;
- result rows showing method, dataset, task, metric, value, claim id, source id, and locator;
- warnings for invalid locators, lossy tables, missing values, and ambiguous normalization.

Source wiki pages may include a compact "Reported Results" section after apply, but only for applied cited claims. The section must cite the same claim/source locator and must not invent narrative beyond the formal claim.

If implementation chooses not to change source page rendering in V4.3, `triage.md` and staging artifacts are the minimum acceptance surface.

## 16. Retrieval And Timeline Readiness

V4.3 should make V4.4 possible.

After V4.3, a future timeline command should be able to retrieve rows with:

- metric name;
- value;
- method;
- dataset/task;
- paper identity;
- paper year;
- claim id;
- source id;
- locator;
- warnings.

The first V4.3 implementation does not need to implement the timeline command. It should, however, keep structured result metadata stable enough that V4.4 does not need to re-run ingest for all papers merely to learn basic metric/result fields.

## 17. Testing Strategy

V4.3 should be implemented with spec-driven, contract-first, risk-based TDD.

Recommended tests:

- unit tests for metric value normalization;
- unit tests for PDF locator parsing and normalization;
- unit tests for invalid block ids, missing sidecars, malformed sidecars, and unsupported locators;
- chunk prompt/static tests ensuring metric/result extraction instructions mention abstract, method, experiment, table, caption, and conclusion regions;
- fake LLM tests for valid result candidates from abstract blocks;
- fake LLM tests for table-derived result claims with page/block locators;
- fake LLM tests for caption-supported result claims;
- fake LLM tests where invalid locators are rejected or downgraded;
- consolidation tests proving consolidation cannot invent new result claims;
- staging tests proving `metric-results.jsonl` records reference real `claims.jsonl` claim ids;
- apply boundary tests proving extraction does not directly mutate `wiki/` or `state/catalog.sqlite`;
- regression tests proving non-PDF ingest still works;
- sanitizer tests proving warnings do not leak secrets, raw prompts, raw LLM responses, or full parser logs.

Recommended test files:

```text
tests/test_metric_result_identity.py
tests/test_metric_result_extraction.py
tests/test_metric_result_locator_validation.py
tests/test_metric_result_staging.py
tests/test_pdf_chunked_ingest.py
tests/test_regression_samples.py
```

The exact file names may be adjusted to match implementation structure.

## 18. Acceptance Metrics

V4.3 acceptance should report:

- number of imported papers tested;
- total formal claims;
- total metric/result candidates;
- cited metric/result claims;
- weak/ambiguous metric/result candidates;
- invalid locator rejection count;
- cited result locator validity ratio;
- table/caption result count;
- result claims per paper;
- number of result claims carrying metric, value, method, dataset, and task fields.

Hard gates:

- cited result locator validity ratio must be 1.0 on test fixtures;
- invalid PDF block locators must not become cited claims;
- parser artifacts must not appear as evidence;
- generated result metadata must not be committed as source material.

## 19. Manual Acceptance

Use a small subset of `docs/papers` rather than the whole corpus by default.

Suggested acceptance:

```powershell
.\.venv\Scripts\python.exe -m llmwiki corpus import <tmp-corpus> --root . --parser auto
.\.venv\Scripts\python.exe -m llmwiki corpus status --root .
.\.venv\Scripts\python.exe -m llmwiki review <run-id> --root .
```

Inspect:

- `staging/<run-id>/claims.jsonl`;
- `staging/<run-id>/metric-results.jsonl`;
- `staging/<run-id>/triage.md`;
- generated source page after apply, if V4.3 implementation updates page rendering;
- catalog-backed outputs after apply.

Acceptance checks:

1. Abstract-derived headline results have valid page/block locators.
2. Experiment/table-derived results cite the result table or result statement block.
3. Caption-derived results cite caption blocks, not image artifact paths.
4. Ambiguous table values produce warnings instead of fake cited claims.
5. Result records reference real formal claim ids.
6. Weak candidates remain visible and are not silently upgraded.
7. Running clean after acceptance removes generated staging/source/wiki/state outputs according to existing cleanup rules.

## 20. Open Questions

1. Should V4.3 persist structured result metadata into a catalog table immediately, or should V4.4 introduce durable query storage for timelines?
2. Should source pages show a "Reported Results" section in V4.3, or should this wait until metric timeline output exists?
3. Should V4.3 support Markdown/text papers with `line:N` result claims, or should acceptance focus only on PDF sources?
4. How much table structure must MinerU preserve before table-derived result claims are allowed?
5. Should metric aliases be inferred locally from papers, curated manually, or deferred until V4.4?
6. Should qualitative comparisons without numeric values become structured result claims or remain ordinary claims?

## 21. Success Criteria

V4.3 is successful when:

1. Research-paper ingest can propose metric/result claims from abstract, method, experiment, table, caption, and conclusion contexts.
2. Cited PDF result claims retain valid page/block locators.
3. Structured result metadata references formal claim ids and remains tied to source-backed evidence.
4. Unsupported or ambiguous results remain weak or warning-bearing.
5. Existing staging/apply safety boundaries remain intact.
6. V4.4 can build metric timeline queries from the extracted result data without redefining the ingest contract.
