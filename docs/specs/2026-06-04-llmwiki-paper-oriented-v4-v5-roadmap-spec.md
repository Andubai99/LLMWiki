# LLMWiki Paper-Oriented V4/V5 Roadmap Spec

Date: 2026-06-04

Status: planning spec

## 1. Purpose

This spec resets the next implementation route around the paper goal:

```text
Incremental Scientific Knowledge Maintenance
```

The system should maintain source-backed scientific result claims over a growing local research corpus, then support metric timelines, claim relations, graph updates, trend updates, conflict detection, and research gap discovery.

The current implementation status is:

- V4.1 corpus import queue is implemented.
- V4.2 paper identity and corpus inventory are implemented.
- V4.3 metric/result claim extraction is still mostly design.
- V4.4 metric timeline is not implemented.
- V4.5/V4.6 result-evidence quality and corpus acceptance metrics are not complete.

The next work should not broaden the product surface. It should turn the existing evidence compiler into a paper-evaluable research substrate.

## 2. Core Thesis

LLMWiki should not be framed as raw-document RAG.

The paper-oriented thesis is:

```text
Raw papers are compiled into source-backed claims with stable locators.
Structured result metadata is attached to formal claims.
Metric timelines, relations, trends, conflicts, and gaps are derived from catalog-backed claims.
LLM output can propose claims, relations, or summaries, but cannot become evidence without catalog claims and locators.
```

This preserves the existing evidence contract while adding the missing scientific claim graph layer.

## 3. Constraints

### 3.1 Dataset

Use the existing 20 local CUA / computer-use-agent papers under:

```text
docs/papers/
```

Do not modify files under `docs/papers/`.

Do not introduce a new public dataset before the 20-paper corpus can produce structured result claims and metric timelines.

### 3.2 Real LLM Acceptance

Paper acceptance for V4.3 and later must use the configured real LLM provider.

Unit tests may cover deterministic schema, parsing, validation, and formatting code, but they are not sufficient paper evidence by themselves. The acceptance record for each phase must include real LLM runs over `docs/papers/` or a declared subset followed by the full 20-paper run.

Do not add a production mock provider or public no-network LLM path for this work.

### 3.3 Error Policy

Do not add speculative fallback designs before observing actual failures.

When a real LLM, parser, table, locator, or metric extraction failure occurs:

1. Record the concrete command, source id, source file, error message, and generated artifact paths in an acceptance observation file.
2. Fix the narrow observed blocker.
3. Re-run the smallest command that proves the blocker is fixed.

Avoid broad abstractions whose only purpose is to handle hypothetical future parser, provider, or table formats.

### 3.4 Knowledge Safety

All formal knowledge changes must still go through:

```text
ingest -> staging -> review -> apply
```

V4/V5 must not directly mutate formal `wiki/`, `state/catalog.sqlite`, or source sidecars outside existing approved write paths.

Parser artifacts, parser logs, parser backend attempts, and raw LLM responses are diagnostics, not evidence.

## 4. Route Overview

The implementation route is:

```text
V4.3 Structured Metric/Result Claims
-> V4.4 Metric Timeline
-> V4.5-min Result Evidence Quality Closure
-> V4.6-min Corpus Acceptance Metrics
-> V5.2-min Claim Relation Layer
-> V5.1-min Maintenance Planner
-> V5.3 Conflict/Change Detection
-> V5.4 Trend/Gap/Synthesis Maintenance
-> Paper evaluation package
```

This keeps the original V4/V5 intent, but the implementation order puts the relation layer before the full maintenance planner because the planner needs claim-pair relation evidence.

## 5. V4.3 Structured Metric/Result Claims

### 5.1 Goal

Extend research-paper ingest so it can extract structured metric/result records while preserving the formal claim layer as the source of truth.

Every cited result record must map to:

- a real `claim_id` in the same staging run or applied catalog;
- a real `source_id`;
- a real citation locator;
- readable `claim_text`.

### 5.2 Required Schema

Use one first-version schema:

```text
metric_result_claim.v4.3
```

Fields:

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
reported_year
is_main_result
value_normalization_status
warnings
created_at
```

Rules:

- Missing strings use `""`.
- Missing lists use `[]`.
- Missing booleans use `null`.
- Missing year uses `null`.
- `paper_id` defaults to `source_id` until a durable paper identity table exists.
- `metric_value` is normalized only when deterministic.
- `metric_raw_value` preserves the source expression.
- Unsupported metric values must not become cited result claims.

### 5.3 Storage Decision

V4.3 should use both:

```text
staging/<run-id>/metric-results.jsonl
state/catalog.sqlite metric_results table
```

`metric-results.jsonl` is the review artifact. The `metric_results` catalog table is the single durable query surface for V4.4.

Do not store structured result fields inside the existing `claims` table. Formal claims remain lightweight and evidence-focused.

### 5.4 Extraction Scope

Extract result candidates from PDF chunks when supported by source text:

- abstract headline results;
- experiment/result sections;
- table-like blocks;
- captions that explicitly state result context;
- conclusion or limitation sections when they state a result or limitation.

Do not infer missing baselines, datasets, methods, metric direction, or values.

Do not create result claims from visual interpretation of figures.

### 5.5 Acceptance

V4.3 is acceptable when the 20-paper corpus can report:

- total formal claims;
- total structured result records;
- structured result records per paper;
- cited result ratio;
- invalid result locator count;
- weak or unsupported result candidate count;
- number of records with non-empty method, dataset, task, metric name, value, and baseline.

## 6. V4.4 Metric Timeline

### 6.1 Goal

Add:

```powershell
llmwiki metric timeline "<metric>" --root .
llmwiki metric timeline "<metric>" --dataset "<dataset>" --root .
llmwiki metric timeline "<metric>" --task "<task>" --json --root .
```

The timeline must be generated from catalog-backed `metric_results` joined to formal claims, sources, pages, and paper identity metadata.

It must not call a chat LLM.

### 6.2 Query Rules

First version matching should be conservative:

- exact casefold match;
- normalized whitespace and punctuation match;
- optional dataset/task filters;
- no domain-specific metric boosts;
- no raw PDF chunk search as evidence.

If no catalog-backed result exists, return an empty timeline with a warning:

```text
No catalog-backed result claim found for this metric.
```

### 6.3 Timeline Rows

Each row must include:

```text
paper_id
source_id
source_title
reported_year
method
dataset
task
metric_name
metric_value
metric_unit
metric_raw_value
baseline
comparison_value
setting
claim_id
citation_locator
page_path
confidence_status
warnings
```

Rows sort by:

1. `reported_year` when present;
2. source import time;
3. source id.

### 6.4 Acceptance

V4.4 is acceptable when:

- timeline output is derived entirely from `metric_results` and formal claims;
- every non-warning row has `claim_id`, `source_id`, and `citation_locator`;
- JSON output is stable enough for evaluation;
- human output is readable in the CLI;
- empty-result behavior does not invent narrative.

## 7. V4.5-min Result Evidence Quality Closure

V4.5 should not become broad PDF/table understanding work.

Only improve PDF/table/caption handling when it blocks V4.3/V4.4 result evidence.

Minimum closure:

- cited result locators resolve to Markdown/text `line:N` or PDF `page:N;block:<block-id>`;
- table-like blocks can support result claims only when the normalized table text contains the metric/value context;
- captions can support result claims only for statements present in the caption;
- invalid, malformed, or ambiguous table evidence becomes a warning or weak candidate;
- parser backend fallback remains visible.

No OCR, visual chart interpretation, or general table semantic parser is required.

## 8. V4.6-min Corpus Acceptance Metrics

Add one read-only evaluation surface for result/corpus acceptance, for example:

```powershell
llmwiki eval corpus-results --root . --json
```

The exact command name can be finalized in the implementation plan, but the first version should be one command, read-only, and local.

Required metrics:

```text
corpus_source_count
pdf_source_count
applied_source_count
failed_source_count
parser_backend_distribution
result_claim_count
result_claim_count_per_paper
cited_result_ratio
weak_or_unsupported_result_count
result_locator_validity
table_or_caption_result_count
timeline_metric_count
timeline_row_count
timeline_source_diversity
duplicate_paper_warning_count
missing_year_count
```

This command must not call LLM providers, embedding providers, MinerU, parser execution, add, ingest, apply, ask, synthesis, or clean.

## 9. V5.2-min Claim Relation Layer

The original V5 relationship classifier remains valid. The minimum implementation should come before the full maintenance planner.

### 9.1 Candidate Generation

For each new structured result claim, generate a small candidate set of old claims.

Candidate retrieval should use:

- same or similar `metric_name`;
- same or similar dataset/task when present;
- same or similar method/baseline when present;
- optional vector recall mapped back to real catalog claims.

Do not compare every claim pair in the graph.

First version target:

```text
top_k <= 10 old claims per new structured result claim
```

### 9.2 Classifier Output

Use five relation labels:

```text
supports
contradicts
extends
refines
unrelated
```

Every non-`unrelated` output must include:

```text
subject_claim_id
object_claim_id
relationship_type
evidence_claim_ids
explanation
confidence
created_at
```

This likely requires a new claim-pair relationship table rather than overloading the existing page/source-oriented `relationships` table.

### 9.3 Safety

Classifier output is not evidence.

A relation can be applied only when both claim ids exist and both claims have valid source locators. Unsupported or low-confidence relations stay in staging/triage.

## 10. V5.1-min Maintenance Planner

The maintenance planner consumes new claims, metric results, and relation candidates.

Input:

```text
new source
new formal claims
new metric_results
candidate claim relations
existing metric timelines
existing synthesis/trend/gap pages when present
```

Output:

```text
ADD_RELATION
FLAG_CONFLICT
FLAG_REFINEMENT
MARK_POSSIBLY_STALE
UPDATE_TIMELINE
UPDATE_TREND
UPDATE_GAP
UPDATE_SYNTHESIS
NEEDS_REVIEW
```

First version output should be a staged maintenance plan, not automatic wiki mutation.

Do not implement autonomous destructive merges.

## 11. V5.3 Conflict And Change Detection

V5.3 should distinguish:

```text
contradiction
refinement
context-dependent difference
metric/dataset mismatch
baseline mismatch
```

The conflict object must include both sides:

```text
claim_a
claim_b
source_a
source_b
locator_a
locator_b
structured_field_comparison
explanation
confidence
```

Do not create `contradicts` from negation keywords.

## 12. V5.4 Trend, Gap, And Living Synthesis

Trends and gaps should become maintained objects only after V4.4 timelines and V5 relation candidates exist.

Trend/gap generation must cite supporting claims.

First version trend object:

```text
trend_id
title
supporting_claim_ids
opposing_claim_ids
metric_names
time_range
summary
confidence
last_updated
```

First version gap object:

```text
gap_id
title
evidence_claim_ids
gap_type
research_question
confidence
last_updated
```

The LLM may draft summaries, but trend/gap evidence must come from catalog claims and relations.

## 13. Acceptance Workflow

Each phase should end with an acceptance observation file under `docs/specs/`.

Suggested full-corpus acceptance workspace:

```powershell
llmwiki clean --root .tmp/paper-v4-acceptance --scope all --dry-run
llmwiki corpus import docs/papers --root .tmp/paper-v4-acceptance --recursive --parser auto
llmwiki corpus inventory --root .tmp/paper-v4-acceptance --json
llmwiki eval corpus-results --root .tmp/paper-v4-acceptance --json
llmwiki metric timeline "<metric-from-corpus>" --root .tmp/paper-v4-acceptance --json
```

The actual metric query should be selected from extracted corpus metric names, not hardcoded before extraction results are known.

Generated workspaces, source sidecars, staging, catalog, wiki output, vector cache, parser artifacts, and local API keys must not be committed.

## 14. Paper Readiness Milestones

### 14.1 Demo / Workshop Paper

Minimum:

- V4.3 structured result claims;
- V4.4 metric timeline;
- V4.6-min corpus acceptance metrics;
- one 20-paper real LLM acceptance observation;
- evidence contract metrics remain valid.

This supports a paper framed as:

```text
LLMWiki: A Source-backed Evidence Compiler for Auditable Research Wikis
```

### 14.2 Method Paper

Minimum:

- V4.3/V4.4/V4.6-min complete;
- V5.2-min relation classifier;
- V5.1-min maintenance planner;
- V5.3 conflict/change detection;
- small human-checked gold set over the 20-paper corpus;
- baselines and ablations.

Suggested gold set:

```text
100-200 structured result claims
200-400 claim-pair relation candidates
5-10 timeline updates
5-10 trend or gap updates
```

Baselines can wait until the system has stable outputs:

- long-context LLM;
- vector RAG;
- GraphRAG-style chunk/entity graph;
- static non-incremental claim graph.

## 15. Implementation Discipline

For each phase:

1. Write or update a focused implementation plan under `docs/plans/`.
2. Add deterministic unit tests for schema and validation.
3. Run real LLM acceptance on the 20 papers or a declared subset followed by the full corpus.
4. Record observed failures before adding fallback logic.
5. Clean generated state unless explicitly preserving an acceptance workspace.
6. Commit logically separated changes.

Do not add UI, external hosted vector databases, MCP integrations, cloud sync, team permissions, OCR, or autonomous destructive wiki maintenance as part of this route.

