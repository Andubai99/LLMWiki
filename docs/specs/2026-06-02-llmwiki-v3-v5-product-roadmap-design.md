# LLMWiki V3-V5 Product Roadmap

## 1. Background

V2 has established the core source-backed knowledge compiler:

- `llmwiki add` can import one source, run LLM ingest, stage candidate knowledge, validate, and apply it into wiki/catalog.
- `retrieve` / `query` provide local citation-backed evidence retrieval.
- `ask` uses LLM query planning, local retrieval, grounded answer generation, and optional synthesis writeback.
- PDF import has metadata/block/chunk sidecars, chunked LLM ingest, parser backend diagnostics, and MinerU/pypdf backend boundaries.
- The repository already contains a real target corpus: 20 CUA-domain papers under `docs/papers`.

The current bottleneck is no longer whether a single document can produce useful LLM output. Single-document RAG-like behavior is broadly proven. The next bottleneck is operational and product-level:

- user interaction is still CLI-heavy;
- batch and long-running workflows are not first-class;
- PDF rich parsing is still incomplete for research papers;
- wiki self-maintenance and research relationship intelligence are not mature;
- real paper-scale workflows need visible progress, diagnostics, review, and recovery.

This spec defines the strategic direction for V3, V4, and V5. It is intentionally a roadmap spec, not an implementation plan. Each major phase should receive its own detailed spec and implementation plan before code changes.

## 2. Strategic Direction

LLMWiki should evolve from a command-line research wiki compiler into a local-first research knowledge workspace.

The long-term product shape is:

```text
Source Library
-> Parser / Ingest Job Queue
-> Staging / Evidence / Quality Review
-> Wiki + Catalog + Graph
-> Ask / Retrieve / Synthesis
-> Maintenance / Conflict / Relationship Intelligence
```

Obsidian can remain a strong Markdown browsing surface, but LLMWiki needs its own product UI for operations that Obsidian does not solve:

- import status;
- parser diagnostics;
- LLM run progress;
- failed job recovery;
- claim/evidence inspection;
- synthesis preview;
- evaluation dashboards;
- wiki maintenance queues.

## 3. Phase Summary

### V3: User Interaction And Product Shell

V3 makes the system usable as a product.

Primary goal: provide a local UI around the existing source-backed pipeline so users can operate the system without reading raw CLI/staging files.

V3 should not attempt to solve the hardest PDF parsing or research-relationship problems. It should expose the existing pipeline clearly and make failures actionable.

### V4: PDF And Research Corpus Ingestion

V4 makes the system reliable for real paper corpora.

Primary goal: import and process `docs/papers`-style research PDFs at corpus scale, with batch queues, long-running status, robust MinerU integration, table/figure/formula evidence foundations, and paper-specific knowledge structures.

V4 should turn the 20 CUA papers into the standard local acceptance corpus.

### V5: Wiki Self-Maintenance And Research Intelligence

V5 makes the wiki maintain itself as a research artifact.

Primary goal: when new papers are added or users ask important questions, the system should propose maintenance updates to existing pages, detect source-backed disagreements, classify meaningful research relationships, and evolve synthesis pages rather than accumulating disconnected summaries.

V5 should build on stable PDF evidence and corpus-scale ingestion from V4.

## 4. V3: User Interaction And Product Shell

### 4.1 Goals

V3 must provide a local UI for:

- viewing the source library;
- adding one or more sources;
- seeing import/parser/LLM/apply progress;
- inspecting failed jobs and safe error diagnostics;
- browsing generated wiki pages and catalog evidence;
- asking questions and seeing cited answers;
- previewing synthesis writeback before apply;
- viewing lint/eval/pdf-quality status;
- opening relevant files in Obsidian or the local filesystem.

The UI should make existing capabilities visible without weakening the source-backed contract.

### 4.2 Recommended Architecture

Use a local product shell:

```text
Local Web UI
-> Local API / service layer
-> Existing llmwiki modules
-> Workspace files + catalog.sqlite
```

The service layer should wrap existing Python functions instead of shelling out for every operation where a stable Python API exists. CLI can remain the automation and debug surface.

The first V3 implementation should prefer a local browser UI over an Obsidian plugin because:

- it can show job state, diagnostics, JSON, citations, and previews more naturally;
- it does not depend on Obsidian plugin APIs;
- it can still link to Markdown pages that users browse in Obsidian.

### 4.3 V3 Sub-Phases

#### V3.1 Local App Shell

Add a local app entry point and basic API surface:

- start local server;
- select workspace root;
- read workspace status;
- list sources, runs, wiki pages, and catalog counts;
- display parser/LLM/embedding config status without secrets.

Acceptance:

- user can open a local UI and see whether the workspace is ready;
- no API keys or secret config values are displayed;
- UI does not mutate wiki/catalog unless a command explicitly does so.

#### V3.2 Source Library And Job Visibility

Add source-centric views:

- source list;
- add source form;
- per-source status;
- latest run status;
- parser backend, fallback, sidecar completeness;
- links to raw/normalized/metadata/block/chunk artifacts where safe.

V3 may initially run imports sequentially using existing `add` behavior. It does not need full production batch scheduling yet, but it should model jobs in a way that V4 can extend.

Acceptance:

- user can add a single PDF from the UI;
- user can see whether it is pending, running, applied, failed, or already imported;
- failed parser/LLM/apply errors are visible and sanitized.

#### V3.3 Ask And Synthesis UI

Add the user-facing research loop:

- ask a question;
- show answer, citations, warnings, and retrieved evidence;
- show query plan and subqueries in a collapsible diagnostic view;
- preview synthesis writeback;
- approve writeback through staging/apply;
- open resulting synthesis page.

Acceptance:

- `ask` UI can answer from existing catalog evidence;
- citation list links back to source/page/locator context;
- `--preview-writeback` behavior is represented as an explicit preview state;
- writeback never bypasses staging/apply.

#### V3.4 Evidence And Wiki Browser

Add inspection tools:

- claim browser;
- source page view;
- concept/entity/synthesis page list;
- relationship view;
- retrieved-context inspector;
- weak/uncited and contradicts visibility.

Acceptance:

- user can inspect why an answer cited a claim;
- user can distinguish source-backed claims from synthesis text;
- parser artifacts and diagnostics are not presented as evidence.

#### V3.5 Quality Dashboard

Expose existing quality commands:

- `lint`;
- `doctor`;
- `eval retrieval`;
- `eval pdf-quality`;
- parser status;
- embedding status.

Acceptance:

- user can run or view quality checks from UI;
- results are shown with actionable categories;
- read-only checks remain read-only and do not call LLM/MinerU parsing.

### 4.4 V3 Non-Goals

V3 does not implement:

- full batch import engine;
- new PDF parsing capability;
- table cell-level evidence;
- figure understanding;
- equation semantic interpretation;
- new paper page types;
- relationship classifier;
- automatic wiki maintenance planning;
- multi-user permissions;
- cloud sync.

### 4.5 V3 Success Criteria

V3 is successful when a user can operate the existing single-source pipeline, ask questions, inspect evidence, approve synthesis writeback, and understand failures through a local UI without reading raw staging files manually.

## 5. V4: PDF And Research Corpus Ingestion

### 5.1 Goals

V4 must make LLMWiki reliable for the 20 CUA papers in `docs/papers`.

It must solve:

- batch import queue;
- long-running task status;
- failure resume/retry;
- MinerU command/output acceptance;
- parser diagnostics at corpus scale;
- table/formula/figure/caption evidence foundations;
- paper-specific knowledge structure.

### 5.2 V4 Sub-Phases

#### V4.1 Batch Import Queue

Add a first-class batch import model:

- add files, folders, or selected source lists;
- persist job state;
- process sources sequentially by default;
- support pause/resume/retry/skip;
- avoid duplicate imports;
- keep per-source logs and sanitized errors.

Acceptance:

- user can import all 20 `docs/papers/*.pdf` through one batch action;
- a failed paper does not lose the whole batch;
- already applied sources are skipped or marked up to date;
- no concurrent catalog/wiki corruption is possible.

#### V4.2 Long-Running Task Status

Track progress across parser, chunking, LLM calls, staging, apply, embeddings, and eval.

Acceptance:

- user can see which stage each paper is in;
- PDF chunk progress is visible;
- LLM usage and repair counts are summarized safely;
- failed stages include actionable debug commands or UI links.

#### V4.3 MinerU Acceptance Closure

Resolve the current MinerU gap: local MinerU is discoverable, but real runs have fallen back because no usable content-list output was found.

V4 should:

- validate actual MinerU CLI modes and output layouts;
- configure method/backend defaults that produce supported outputs;
- update the adapter for real MinerU content-list variants;
- keep pypdf fallback visible;
- build acceptance tests from several real CUA PDFs.

Acceptance:

- at least a representative subset of `docs/papers` imports through MinerU without fallback;
- fallback cases explain why MinerU failed;
- `eval pdf-quality` reports backend distribution and structured block counts accurately.

#### V4.4 Rich PDF Evidence Blocks

Extend normalized blocks for:

- table-like content;
- figure captions;
- image captions;
- formulas/equations;
- appendix/reference sections.

V4 should not claim to semantically understand every table or figure, but it should preserve enough structure for citation-backed extraction.

Acceptance:

- table text can become cited claims with page/block locators;
- formula text can be searched and cited;
- figure/caption text can be searched and cited;
- parser artifacts are still not evidence by themselves.

#### V4.5 Paper-Level Knowledge Structure

Introduce research-paper-specific page and graph concepts only after PDF evidence is stable.

Candidate page types or structured concepts:

- paper;
- method;
- benchmark;
- dataset;
- metric;
- result;
- task;
- limitation.

This may require either new `page_type` values or a typed concept/entity convention. The detailed V4 spec must choose one.

Acceptance:

- each paper has a clear paper identity;
- methods and benchmarks can be represented without collapsing into generic concepts;
- claims about metrics/results remain source-backed;
- retrieval can answer paper comparison questions with citations.

### 5.3 V4 Non-Goals

V4 does not implement:

- autonomous synthesis maintenance across the whole wiki;
- full conflict classification;
- automatic literature review generation without user approval;
- cloud storage;
- multi-user workflows.

### 5.4 V4 Success Criteria

V4 is successful when the 20 CUA papers can be imported as a corpus with visible progress, reliable recovery, high PDF sidecar quality, searchable table/formula/caption evidence, and research-paper-aware wiki structure.

## 6. V5: Wiki Self-Maintenance And Research Intelligence

### 6.1 Goals

V5 should make the wiki actively maintain itself as a research knowledge base.

It must improve:

- automatic update proposals for existing pages;
- stale claim detection;
- duplicate page consolidation proposals;
- relationship classification;
- source-backed disagreement detection;
- synthesis evolution;
- research gap and open-question tracking.

### 6.2 V5 Sub-Phases

#### V5.1 Maintenance Planner

Add a planner that reviews new evidence against existing wiki pages and proposes maintenance actions:

- update source summary;
- update concept/entity/paper/method pages;
- update synthesis pages;
- create new page;
- merge or mark duplicates;
- flag stale or unsupported claims.

Acceptance:

- after importing a new paper, system can list which existing pages should be updated;
- proposals go through staging/review/apply;
- no automatic destructive overwrite.

#### V5.2 Research Relationship Classifier

Classify paper-domain relationships from source-backed evidence:

- introduces;
- extends;
- evaluates;
- uses benchmark;
- compares against;
- reports result;
- improves over;
- contradicts;
- refines;
- shares limitation;
- supports.

Classifier output must be validated against catalog claims and locators. It cannot create relationships from unsupported prose.

Acceptance:

- relationships include evidence claim ids;
- unsupported relationships are rejected or marked for review;
- retrieval exposes relationships without treating them as unverified claims.

#### V5.3 Conflict And Change Detection

Detect real source-backed disagreement, not negation keywords.

Examples:

- two papers report incompatible results for the same benchmark/metric;
- one paper claims a limitation remains open while another claims to solve it;
- newer evaluation contradicts earlier reported capability;
- benchmark definitions or task scopes differ in ways that affect comparison.

Acceptance:

- conflict candidates include both sides, source ids, claim ids, locators, and a comparison explanation;
- uncertain conflicts are staged as review candidates, not applied as formal `contradicts`;
- confirmed conflicts become catalog relationships and remain visible in retrieve/ask/synthesis.

#### V5.4 Living Synthesis Maintenance

Upgrade synthesis pages from answer writebacks into maintained research narratives:

- update survey pages when new papers arrive;
- preserve revision history;
- separate current consensus, evidence map, conflicts, limitations, and open questions;
- link synthesis pages to paper/method/benchmark pages.

Acceptance:

- adding a new relevant paper proposes updates to existing synthesis pages;
- stale synthesis claims are visible;
- user can approve or reject maintenance patches.

#### V5.5 Maintenance Evaluation

Add eval suites for wiki maintenance:

- page update precision;
- duplicate detection quality;
- relationship classification precision/recall;
- conflict detection precision/recall;
- synthesis update quality;
- evidence contract validity.

Acceptance:

- relationship and conflict work is measured against curated CUA cases;
- regression failures are visible before changing classifiers.

### 6.3 V5 Non-Goals

V5 does not:

- auto-resolve conflicts by choosing a winner;
- silently rewrite user-authored wiki pages;
- treat model opinions as evidence;
- bypass staging/apply;
- require external hosted vector databases by default.

### 6.4 V5 Success Criteria

V5 is successful when LLMWiki can ingest a new CUA paper, identify which existing wiki objects it affects, propose source-backed relationship/conflict updates, update relevant synthesis pages through reviewable patches, and preserve uncertainty instead of flattening disagreements.

## 7. Cross-Cutting Requirements

All future phases must preserve these project contracts:

- raw sources remain immutable;
- generated knowledge changes go through staging/apply;
- parser artifacts are diagnostics, not evidence;
- citations must point to real source locators;
- weak/uncited claims remain visible and cannot become strong conclusions;
- `retrieve/query/eval retrieval/eval pdf-quality/parsers status` do not call chat LLMs;
- API keys and secret config values are never committed or displayed;
- generated source/wiki/staging/state/vector artifacts remain ignored unless explicitly curated;
- no domain-specific keyword hacks for retrieval, relationship classification, or evidence selection;
- real CUA papers under `docs/papers` become the main acceptance corpus for V4 and V5.

## 8. Evaluation Strategy

### V3 Metrics

- user can complete add/ask/writeback from UI;
- failure reason clarity;
- number of CLI-only steps remaining for normal use;
- evidence inspection usability;
- no secret leakage in UI/API responses.

### V4 Metrics

- 20-paper batch completion rate;
- per-paper failure recovery rate;
- MinerU success/fallback distribution;
- sidecar completeness;
- block locator validity;
- table/formula/caption retrieval coverage;
- non-introduction claim coverage;
- parser-created alias/title issue count.

### V5 Metrics

- relationship precision and recall on curated CUA cases;
- conflict candidate precision;
- duplicate page reduction;
- stale claim detection quality;
- synthesis update acceptance rate;
- evidence contract validity for maintenance patches.

## 9. Recommended Next Specs

The next detailed spec should be:

```text
V3.1 Local UI And Workspace Dashboard
```

It should define:

- local server/API architecture;
- UI framework choice;
- workspace selection and status model;
- source/run/page list APIs;
- read-only safety boundaries;
- first dashboard screens;
- how UI will coexist with CLI and Obsidian.

After V3.1, write separate specs for:

1. V3.2 Source Library And Job Visibility.
2. V3.3 Ask And Synthesis UI.
3. V4.1 Batch Import Queue.
4. V4.3 MinerU Acceptance Closure.
5. V5.1 Maintenance Planner.

Do not jump directly from this roadmap into a large all-in-one implementation plan. V3, V4, and V5 should be decomposed into small, reviewable specs and feature commits.

## 10. Open Decisions For V3.1

These should be decided in the next spec:

- UI stack: local web app, desktop wrapper, or Obsidian plugin.
- Backend shape: direct Python service, FastAPI, or CLI wrapper.
- Whether job state is stored in SQLite, JSONL, or a new local state file.
- Whether the UI should create a branch/worktree per large import batch.
- How much of `staging/` should be exposed directly to users.

Recommended default:

- local web app;
- Python service wrapping existing modules;
- small persisted job table/state file;
- no cloud;
- no multi-user permissions;
- Obsidian remains the Markdown reading environment, not the operations UI.
