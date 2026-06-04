# LLMWiki V4 Research Corpus And Metric Evolution Design

## 1. Summary

V4 should move LLMWiki from a single-source research wiki compiler toward a research corpus knowledge base for several papers in the same field.

The primary product goal is not a new UI. The primary goal is:

```text
research papers
-> source parsing
-> source-backed claims
-> paper/method/dataset/metric/result structure
-> relationships
-> wiki pages and catalog
-> metric evolution queries
```

In this phase, retrieval and embeddings are supporting mechanisms for wiki-native evidence recall and maintenance targeting. They are not the product model. LLMWiki should not regress into a raw-document RAG system that rediscovers knowledge from PDF chunks on every question.

V4 should use `docs/papers` as the first acceptance corpus and should make metric/result evolution over a set of related papers a first-class workflow.

## 2. Motivation

The original LLM Wiki vision is that the wiki is a persistent, compounding artifact. When a source is added, the system should integrate it into the existing knowledge base instead of only indexing it for query-time retrieval.

The current project already has:

- source import and normalization;
- PDF metadata/block/chunk sidecars;
- LLM ingest through staging/apply;
- claim-level catalog rows with source locators;
- source/concept/entity/synthesis Markdown pages;
- retrieval, ask, synthesis writeback, and local eval tools.

The next bottleneck is that multiple papers in the same field still do not reliably compile into a research-aware structure. A user should be able to add several papers and then ask questions such as:

- Which papers report this metric?
- How did this metric evolve over time?
- Which methods improved over which baselines?
- Which datasets or benchmarks were used for the reported results?
- Which claims are source-backed, weak, conflicting, or stale?

V4 should make those questions answerable from wiki/catalog structure, with retrieval used to find and rank evidence rather than to replace the wiki.

## 3. Product Direction

### 3.1 Core User Story

A user has several papers in one research area. They add the papers to LLMWiki. LLMWiki parses each paper, extracts source-backed claims, identifies paper-level entities and metric/result statements, updates the wiki through staging/apply, and lets the user ask:

```text
How has <metric> changed across these papers?
```

The answer should be grounded in catalog claims and locators. A typical output can be a timeline table plus a short synthesis:

```text
Metric: accuracy
Dataset: CUA

Year | Paper | Method | Value | Claim | Locator
2022 | ...   | ...    | 78.4  | ...   | page:...
2024 | ...   | ...    | 82.1  | ...   | page:...
2026 | ...   | ...    | 84.0  | ...   | page:...
```

This workflow is more important for V4 than adding another UI surface.

### 3.2 Relationship To RAG

V4 should explicitly separate wiki-native retrieval from raw-document RAG.

Preferred query path:

```text
question
-> query planning
-> catalog/wiki retrieval
-> relationship expansion
-> evidence selection
-> answer or metric timeline
```

Fallback path:

```text
question
-> source/normalized search
-> candidate evidence found outside formal claims
-> report a wiki coverage gap
-> propose ingest or maintenance work
```

Embeddings remain optional semantic recall signals. They may help find semantically related catalog-backed claims, page titles, aliases, and metric variants. They must not become durable knowledge and must not be returned as evidence unless mapped back to real catalog claims, source ids, page paths, and locators.

`wiki/index.md`, wiki links, catalog tables, and relationships remain the primary navigation structure. Embeddings are a recall helper for ambiguity and incomplete links.

## 4. Scope

V4 includes:

- corpus-level import for a folder or selected paper list;
- durable batch state for per-paper processing status;
- paper identity and paper-level wiki/catalog structure;
- metric/result claim extraction from research papers;
- source-backed relationships between papers, methods, datasets, metrics, and results;
- CLI-first metric timeline queries;
- PDF evidence quality improvements required for metrics, tables, captions, and formulas;
- corpus acceptance metrics and regression fixtures.

V4 does not include:

- a new UI redesign;
- autonomous whole-wiki maintenance without user review;
- final literature review generation without staging/apply;
- scanned PDF OCR by default;
- table cell-level semantic understanding beyond what is required for source-backed result extraction;
- cloud sync;
- team permissions;
- external hosted vector databases by default.

## 5. Concepts And Knowledge Model

### 5.1 Required Concepts

V4 should introduce a research-paper-aware knowledge model. The implementation plan may choose whether these are new `page_type` values, typed concept/entity pages, or catalog fields, but the user-facing model must distinguish them clearly:

- `paper`: a source paper with stable identity, title, authors, venue/year when available, and source id.
- `method`: a named method, model, algorithm, architecture, or intervention.
- `dataset`: a dataset, benchmark, corpus, or evaluation suite.
- `task`: the evaluated task or problem setting.
- `metric`: a named measurement such as accuracy, F1, latency, error rate, BLEU, win rate, or domain-specific score.
- `result`: a reported metric value under a specific method/dataset/task/setting.
- `limitation`: a source-backed statement about constraints, failure cases, or open problems.
- `synthesis`: a maintained narrative page that summarizes current understanding without becoming a source of formal claims.

### 5.2 Result Claim Shape

Metric/result claims should be structured enough to support timeline and comparison queries.

A candidate result claim should carry:

```text
claim_id
source_id
paper_id
claim_text
citation_locator
confidence_status
method
dataset
task
metric_name
metric_value
metric_unit
metric_direction
baseline
comparison_value
setting
reported_year
page_path
```

Only fields supported by the source should be populated. Missing fields should remain empty or weak, not invented.

`metric_value` should be normalized when deterministic and preserved as source text when normalization is ambiguous. The raw source expression should remain available through `claim_text` and locator context.

### 5.3 Relationships

V4 should support source-backed relationships needed for corpus navigation and metric evolution:

- `reports_metric`: paper or method reports a metric/result.
- `evaluates_on`: paper or method evaluates on a dataset/benchmark/task.
- `uses_method`: paper uses a method.
- `extends`: paper or method extends another paper or method.
- `compares_against`: paper or method compares against another method/baseline.
- `improves_over`: result or method improves over a baseline result or method.
- `has_limitation`: paper or method has a source-backed limitation.
- `contradicts`: source-backed disagreement between claims.

Each relationship must include or point to evidence claim ids where possible. Relationship output is not evidence by itself unless it is backed by catalog claims and locators.

V4 should not create `contradicts` relationships from negation keywords alone.

## 6. V4 Sub-Phases

### 6.1 V4.1 Corpus Import Queue

Add a CLI-first corpus import surface:

```powershell
llmwiki corpus import docs/papers --root .
llmwiki corpus status --root .
llmwiki corpus retry <batch-id> --root .
llmwiki corpus skip <batch-id> <source-id-or-path> --root .
```

The exact command names can be refined in the implementation plan, but V4 needs a first-class batch model.

Requirements:

- process files sequentially by default;
- persist batch state under generated state;
- store per-paper status, run id, parser backend, start/end times, and sanitized failure reason;
- avoid duplicate imports;
- allow retry of failed sources without reprocessing successful sources;
- prevent concurrent wiki/catalog corruption;
- never commit batch state or generated paper artifacts.

Acceptance:

- a folder of papers can be imported through one command;
- one failed paper does not fail or roll back the entire corpus;
- already imported papers are skipped or marked up to date;
- batch state can explain what happened without exposing secrets.

### 6.2 V4.2 Paper Identity And Corpus Inventory

Before metric extraction, every paper needs stable identity.

Requirements:

- derive source id from existing import rules;
- store paper title as source/page metadata, not as a formal alias unless explicitly supported;
- capture authors, venue, year, DOI/arXiv id when available;
- create or update a paper-facing source page;
- expose a corpus inventory command.

Candidate command:

```powershell
llmwiki corpus inventory --root . --json
```

Acceptance:

- each imported paper has a stable source id and paper identity summary;
- duplicate detection can warn about likely duplicate papers;
- paper title retrieval works through catalog title/page metadata;
- no paper identity field is invented without source support.

### 6.3 V4.3 Metric And Result Claim Extraction

Extend ingest so that research papers produce structured metric/result candidates.

Requirements:

- detect metric/result statements in abstracts, method sections, experiment sections, tables, captions, and conclusion sections;
- preserve page/block locators for PDF claims;
- normalize obvious numeric values while preserving source wording;
- distinguish main results from background or related-work results when possible;
- mark ambiguous or unsupported result claims as weak;
- keep all candidate claims under staging until apply.

Acceptance:

- result claims can be listed and filtered by metric, dataset, method, paper, and task;
- result claims keep valid source locators;
- unsupported metric values do not become cited claims;
- table-derived claims cite table/caption/page/block context when available.

### 6.4 V4.4 Metric Timeline CLI

Add a CLI-first metric timeline workflow:

```powershell
llmwiki metric timeline "<metric>" --root .
llmwiki metric timeline "<metric>" --dataset "<dataset>" --root .
llmwiki metric timeline "<metric>" --task "<task>" --json --root .
```

Requirements:

- retrieve metric/result claims from catalog;
- use title, aliases, lexical retrieval, and optional embedding recall to handle metric name variants;
- group by dataset/task/setting when specified;
- sort by paper year or source date when available;
- show method, metric value, paper/source id, claim id, and citation locator;
- expose warnings for missing year, ambiguous metric, duplicate result, or weak evidence.

Acceptance:

- a user can ask how a metric evolved across the imported corpus;
- the timeline is based on catalog-backed result claims, not raw PDF chunks;
- every row has a source-backed claim or is clearly marked weak/unsupported;
- JSON output is stable enough for tests and later UI use.

### 6.5 V4.5 PDF Evidence Quality For Research Results

Improve PDF parsing only where it directly supports source-backed research evidence.

Requirements:

- preserve table-like text sufficiently for metric/result extraction;
- preserve figure/table captions;
- preserve formulas and symbols in normalized blocks;
- keep appendix and reference sections identifiable when possible;
- expose parser backend attempts and fallback reasons as diagnostics, not evidence;
- ensure parser artifacts are never returned as retrieval evidence.

Acceptance:

- table text can produce cited result claims with page/block locators;
- formulas and symbols remain searchable;
- captions can be retrieved and cited;
- `eval pdf-quality` reports relevant structured block coverage;
- unsupported parser outputs produce warnings instead of fabricated context.

### 6.6 V4.6 Corpus Acceptance Evaluation

V4 needs acceptance metrics tied to the corpus workflow.

Required metrics:

- corpus import completion rate;
- per-paper import success/failure status;
- retry success rate;
- PDF sidecar completeness;
- parser backend distribution;
- metric/result claim count per paper;
- cited result claim ratio;
- result locator validity;
- metric timeline row count and source diversity;
- duplicate paper/method/metric page rate;
- weak/uncited result visibility;
- parser artifact leakage rate.

Acceptance:

- eval commands can run without LLM calls unless an explicit LLM-dependent eval is introduced by a later spec;
- acceptance reports do not write wiki/catalog/source/staging mutations;
- generated eval outputs remain ignored unless explicitly curated.

## 7. Query And Maintenance Behavior

### 7.1 User Questions

For ordinary user questions, `ask` should continue to use:

```text
LLM query planning
-> local retrieve_context
-> grounded answer generation
```

V4 should improve what `retrieve_context` can find by enriching catalog structure, not by bypassing the wiki.

### 7.2 Metric Evolution Questions

Metric evolution questions should prefer the metric timeline path over free-form answer generation.

Examples:

- "How has accuracy changed across these CUA papers?"
- "Which paper first improved F1 over the previous method?"
- "What metrics have been reported for this benchmark?"

The system should first collect structured metric/result claims, then let the LLM explain the timeline if a narrative answer is requested.

### 7.3 Wiki Coverage Gaps

If retrieval finds related source text but no formal catalog claim, the system should report a coverage gap:

```text
No catalog-backed metric claim found.
Candidate source context exists in normalized source text.
Suggested action: run ingest or maintenance to compile this into the wiki.
```

Raw source search may help discover missing knowledge, but raw chunks must not be silently promoted into formal answers.

## 8. Safety And Evidence Boundaries

V4 must preserve these invariants:

- raw sources remain immutable;
- generated knowledge changes go through staging/apply;
- formal claims require source ids and locators;
- PDF claims require page/block locators when available;
- weak/uncited claims remain visible and cannot become strong conclusions;
- parser diagnostics and parser artifacts are not evidence;
- vector chunks are recall signals only;
- synthesis text is not formal evidence;
- LLM planner output is not evidence;
- relationship classifier output must be validated against catalog-backed claims;
- no API key, secret config, raw prompt, raw LLM response, or full parser log is committed or exposed in generated public artifacts.

## 9. Data And Storage

The implementation plan should decide whether V4 needs a catalog migration. The spec does not require a particular schema, but V4 behavior needs durable representation for:

- paper identity;
- result claim fields;
- metric aliases;
- paper/method/dataset/metric/result relationships;
- corpus batch state;
- corpus acceptance summaries.

Generated state should remain under ignored directories such as `state/`. Formal wiki outputs should remain under `wiki/` and should be written only through apply.

If new committed eval fixtures are added, they must live under `tests/` or `docs/` and must not include large raw PDFs or API secrets.

## 10. Test Strategy

The implementation plan should use spec-driven, contract-first, risk-based TDD.

Suggested test groups:

- batch command contract tests;
- corpus state serialization tests;
- paper identity parsing tests;
- result claim normalization tests;
- metric timeline API/CLI tests;
- relationship validation tests;
- PDF sidecar and locator validity tests;
- no-write and no-secret boundary tests;
- regression fixtures for a small curated paper subset;
- eval tests for metric timeline outputs.

Manual acceptance should use a small subset of `docs/papers` first, then the full corpus.

## 11. Manual Acceptance

V4 manual acceptance should verify:

1. A folder of papers can be queued for import.
2. Per-paper status is visible from CLI.
3. A failed paper can be retried without reprocessing successful papers.
4. Imported papers have stable paper identity pages.
5. Metric/result claims are visible in catalog-backed outputs.
6. Metric timeline returns source-backed rows with claim ids and locators.
7. Weak or ambiguous metric claims remain visible.
8. Parser fallback diagnostics are visible but not treated as evidence.
9. Generated batch/eval artifacts are cleaned or ignored.
10. `git status --short --ignored` does not show generated artifacts as staged or tracked.

## 12. Success Criteria

V4 is successful when:

- several same-domain papers can be imported as a corpus;
- each paper has stable identity and source-backed wiki representation;
- metric/result claims can be extracted, validated, and applied;
- metric evolution queries produce timeline outputs with claim ids and locators;
- retrieval helps find relevant wiki evidence without replacing the wiki;
- raw source search is treated as coverage-gap discovery, not formal evidence;
- parser/table/caption/formula handling is good enough to support cited result extraction;
- generated artifacts remain bounded, ignored, and cleanable;
- no write path bypasses staging/apply.

## 13. Open Decisions For The Implementation Plan

- Should paper/method/dataset/metric/result become new `page_type` values or typed concept/entity pages?
- Does V4 require a catalog schema migration for structured result fields?
- Should corpus batch state use JSONL files, SQLite tables, or both?
- What is the smallest paper subset for deterministic tests without committing large PDFs?
- How should metric aliases be curated and audited?
- Should metric timeline be implemented as a new CLI group or as an extension of `query/retrieve`?
- Which PDF parser backend should be the default for V4 acceptance on this machine?
- Which generated corpus artifacts should `llmwiki clean --scope generated` remove?
