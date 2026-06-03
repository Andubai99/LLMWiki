# LLMWiki V3.4 Evidence And Wiki Browser Design

## 1. Background

V3.1 introduced the local workspace dashboard. V3.2 added source submission and UI job visibility. V3.3 added the Ask/Synthesis research loop, including cited answers, retrieved evidence attached to ask jobs, synthesis preview, and synthesis writeback through the existing staging/apply path.

The next usability gap is inspection. A user can now ask a question and see citations, but there is still no dedicated UI path for answering:

- What catalog claim does this citation point to?
- Which source and wiki page does this claim come from?
- Is this claim cited, weak, or uncited?
- Does this claim participate in a `supports` or `contradicts` relationship?
- Is a synthesis page text source-backed, or is it narrative synthesis text?
- What can be inspected safely without opening raw staging files, sidecars, or SQLite manually?

V3.4 should add a read-only Evidence and Wiki Browser around the existing catalog/wiki outputs. It should make source-backed evidence inspectable without changing retrieval, ask, synthesis, parser, or apply behavior.

## 2. Goals

V3.4 must provide:

- a read-only evidence browser in `llmwiki ui --root .`;
- a read-only wiki browser for source, concept, entity, synthesis, and index pages;
- source detail view with source metadata summary, latest run/job summary, source page link, sidecar availability, and source claims;
- page detail view with catalog page metadata, aliases, safe wiki markdown content, linked pages, related sources, and related evidence;
- claim detail view with claim text, claim id, source id, confidence status, citation locator, page path, relationships, and bounded citation context;
- citation-to-claim navigation from V3.3 Ask result citations and retrieved evidence rows;
- clear visual distinction between catalog-backed formal claims and synthesis/page markdown text;
- filters for page type, source id, confidence status, relationship type, and simple catalog text search;
- deterministic, local, read-only GET APIs for the new browser views;
- sanitized warnings for missing catalog rows, missing wiki files, malformed sidecars, unsupported locators, and broken links.

The user goal is:

> A user can click from an answer citation into the exact catalog claim, inspect its source/page/locator, browse related wiki pages, and distinguish source-backed evidence from narrative synthesis text without reading SQLite, staging files, or raw sidecars manually.

## 3. Non-Goals

V3.4 does not implement:

- wiki page editing;
- claim editing;
- source re-ingest;
- retry/cancel UI jobs;
- batch import;
- folder import;
- lint or eval execution;
- quality dashboards;
- new retrieval, reranker, evidence selector, planner, or synthesis algorithms;
- semantic search through embeddings;
- LLM-based evidence explanation;
- relationship classification;
- conflict confirmation workflows;
- autonomous wiki maintenance;
- parser backend changes;
- PDF table/figure/formula understanding upgrades;
- opening arbitrary local files from the browser;
- Obsidian plugin integration;
- cloud sync or multi-user permissions.

V3.4 is a read-only browser. It should not start V4 corpus ingestion or V5 maintenance behavior.

## 4. Scope Decision

V3.4 should browse persisted catalog/wiki state, not run retrieval.

The browser search may use:

- catalog SQL;
- local SQLite FTS over `claims_fts`;
- direct bounded reads of catalog-referenced wiki markdown files;
- direct bounded reads of generated source sidecars such as `sources/metadata/`, `sources/blocks/`, and `sources/chunks/`.

The browser search must not call:

- chat LLM providers;
- embedding providers;
- `retrieve`;
- ask planning;
- reranking;
- MinerU document parsing;
- add/ingest/apply;
- lint/eval/clean;
- parser artifact readers that expose backend-native files.

This avoids surprising provider calls from GET requests and keeps browse results distinct from answer-time retrieval results.

## 5. Recommended Architecture

Extend the existing V3.3 local UI service with read-only browser models and API helpers:

```text
Browser UI
-> Local UI GET API
-> catalog sqlite + wiki markdown + bounded source sidecars
-> read-only Evidence/Wiki Browser
```

Recommended additions:

```text
src/llmwiki/ui/
  browser_api.py
  browser_models.py
```

Existing files extended:

```text
src/llmwiki/ui/api.py
src/llmwiki/ui/server.py
src/llmwiki/ui/models.py
src/llmwiki/ui/static/index.html
src/llmwiki/ui/static/app.js
src/llmwiki/ui/static/styles.css
tests/test_ui_browser_api.py
tests/test_ui_server.py
tests/test_ui_static.py
tests/test_ui_readonly.py
```

The implementation plan may choose to place helpers in existing `api.py` / `models.py` if the code remains small, but the browser-specific logic should stay separate from ask/synthesis action code.

## 6. Data Model

V3.4 should not require a catalog schema migration.

It should read the existing tables:

```text
sources(source_id, title, source_type, raw_path, normalized_path, sha256, url, imported_at, status)
claims(claim_id, source_id, claim_text, citation_locator, confidence_status, created_at)
pages(page_id, path, page_type, title, aliases, updated_at)
links(from_page, to_page, link_type)
relationships(subject_id, object_id, relationship_type, evidence_claim_id, source_id)
ingest_runs(run_id, source_id, status, created_at, applied_at)
```

V3.4 may read `claims_fts` for simple catalog text search when available, with deterministic fallback to bounded `LIKE` queries when FTS is missing or malformed.

## 7. API Surface

Existing V3.3 APIs remain:

```text
GET  /api/session
GET  /api/status
GET  /api/sources
GET  /api/runs
GET  /api/pages
GET  /api/jobs
GET  /api/jobs/<job-id>
GET  /api/ask/jobs
GET  /api/ask/jobs/<job-id>
POST /api/sources/add
POST /api/ask
POST /api/ask/<job-id>/synthesis/preview
POST /api/ask/<job-id>/synthesis/writeback
```

New V3.4 read-only APIs:

```text
GET /api/sources/<source-id>
GET /api/pages/<page-id>
GET /api/evidence/claims
GET /api/evidence/claims/<claim-id>
GET /api/evidence/relationships
```

All new endpoints are GET-only and do not require the UI action token because they are read-only. They still must sanitize output and reject unsafe ids/paths.

All responses use:

```json
{
  "schema_version": "ui.v3.4"
}
```

Existing wire values should remain raw where they are audit fields:

- `source_id`;
- `claim_id`;
- `page_id`;
- `run_id`;
- `job_id`;
- `citation_locator`;
- `page_type`;
- `confidence_status`;
- `relationship_type`;
- job `status`;
- run `status`;
- parser backend values.

UI labels may be localized, but machine/audit values must not be translated.

## 8. Source Detail Endpoint

```text
GET /api/sources/<source-id>
```

Response should include:

- source catalog row;
- latest ingest run summary;
- latest UI job summary when available;
- source wiki page summary when available;
- source claim count by confidence status;
- source claims, paginated or bounded;
- linked pages from `links`;
- relationships where `source_id` matches;
- sidecar availability summary;
- sanitized metadata summary.

Allowed metadata summary fields should be explicit and bounded, for example:

- `parser_backend`;
- `parser_backend_fallback_from`;
- `page_count`;
- `block_count`;
- `chunk_count`;
- `metadata_path`;
- `blocks_path`;
- `chunks_path`.

Rules:

- do not expose raw PDF bytes;
- do not expose full parser logs;
- do not expose backend-native parser artifacts;
- do not expose API keys, prompts, or raw LLM responses;
- if a catalog path points outside the workspace, return `[outside-workspace]` and a warning.

## 9. Page Detail Endpoint

```text
GET /api/pages/<page-id>
```

Response should include:

- page catalog row;
- aliases parsed from the catalog `aliases` JSON field;
- safe workspace-relative wiki path;
- bounded wiki markdown content when the page file exists under `wiki/`;
- outgoing and incoming links;
- related source ids;
- related claims;
- relationships involving this page id;
- warnings for missing files, malformed aliases, broken links, or unsafe paths.

Page content is display text, not formal evidence. The UI must label it accordingly.

Recommended display distinction:

```text
Page Markdown
This is the current wiki page text. It may include synthesis narrative and user-authored prose.

Catalog-Backed Claims
These rows come from the catalog claims table and include source locators.
```

For page types:

- `source`: related claims are claims whose `source_id` is the source page id or source id inferred from the page path.
- `concept` / `entity`: related claims are claims connected through `links` and relationships when present.
- `synthesis`: related evidence comes from catalog relationships and evidence claim ids. Do not treat synthesis markdown paragraphs as formal claims.
- `index`: show page markdown and links, but no special evidence inference is required.

## 10. Claim List Endpoint

```text
GET /api/evidence/claims?query=&source_id=&page_id=&page_type=&confidence=&relationship_type=&limit=&offset=
```

Supported filters:

- `query`: simple catalog text search over claim text and citation locator;
- `source_id`;
- `page_id`;
- `page_type`;
- `confidence`: raw values such as `cited` or `weak`;
- `relationship_type`: raw values such as `supports` or `contradicts`;
- `limit`;
- `offset`.

Rules:

- default `limit` should be modest, for example 50;
- maximum `limit` should be bounded, for example 200;
- no provider calls;
- no embedding vector calls;
- no chat LLM reranking;
- do not hide weak/uncited claims;
- do not hide `contradicts` relationships;
- sort deterministically, for example by `created_at desc, claim_id`.

Each claim row should include:

- `claim_id`;
- `claim_text`;
- `source_id`;
- source title when available;
- `citation_locator`;
- `confidence_status`;
- inferred page summary when available;
- relationship type summary;
- created timestamp.

## 11. Claim Detail Endpoint

```text
GET /api/evidence/claims/<claim-id>
```

Response should include:

- full claim row;
- source summary;
- source page summary;
- citation locator;
- confidence status;
- relationships where the claim is `evidence_claim_id`, `subject_id`, or `object_id`;
- candidate wiki pages connected to the claim through source/page links;
- bounded citation context when resolvable;
- locator resolution status.

Locator resolution should be conservative:

- Markdown/text `line:N` locators may read a bounded snippet from the catalog `normalized_path` if it resolves inside the workspace.
- PDF `page:N;block:<block-id>` locators may read a bounded matching block from `sources/blocks/<source-id>.jsonl`.
- Unsupported locators should display the raw locator plus `unsupported_locator`, not fabricate context.
- Missing sidecars should produce warnings, not errors.
- Parser diagnostics and parser artifact paths are not evidence and must not be displayed as citation context.

The detail view must never invent or repair locators.

## 12. Relationship Endpoint

```text
GET /api/evidence/relationships?source_id=&page_id=&claim_id=&relationship_type=&limit=&offset=
```

Response should include raw catalog relationship rows plus optional resolved titles for known source/page/claim ids.

Relationship rows remain audit data. The UI may label them, but raw values must remain visible:

- `subject_id`;
- `object_id`;
- `relationship_type`;
- `evidence_claim_id`;
- `source_id`.

`contradicts` relationships must stay visible and should not be softened into a generic warning.

## 13. UI Screens

V3.4 can stay within the existing single-page dashboard. It does not need a multi-route frontend framework.

Recommended UI structure:

- Evidence Browser tab/section;
- Wiki Browser tab/section;
- detail drawer or side-by-side detail panel;
- links from Ask citations/evidence rows into claim detail;
- links from source rows into source detail;
- links from wiki page rows into page detail.

### Evidence Browser

Controls:

- query input;
- source filter;
- page type filter;
- confidence filter;
- relationship filter;
- clear filters button.

Results:

- claims table;
- compact relationship badges;
- raw ids visible in monospace;
- detail action for each claim.

### Wiki Browser

Controls:

- page type segmented control or select;
- query input over page title/path;
- source/concept/entity/synthesis filters.

Results:

- page list grouped or filterable by page type;
- page detail panel with markdown preview;
- linked pages;
- catalog-backed claim section;
- synthesis evidence section when applicable.

### Citation Navigation

V3.3 citations and retrieved evidence rows should become clickable within the UI:

```text
Ask citation -> claim detail -> source detail/page detail -> related claims/relationships
```

This navigation must use catalog ids, not free-form file paths.

## 14. Read-Only Boundary

V3.4 does not add any mutating POST route.

New GET endpoints may read:

- workspace skeleton;
- `state/catalog.sqlite`;
- `state/ui-jobs/`;
- `staging/<run-id>/run.json` summaries;
- catalog-referenced wiki markdown files under `wiki/`;
- source metadata/block/chunk sidecars under `sources/metadata/`, `sources/blocks/`, and `sources/chunks/`.

New GET endpoints must not:

- write files;
- mutate catalog;
- create UI jobs;
- call LLM providers;
- call embedding providers;
- run MinerU or any parser backend;
- call add/ingest/apply;
- call ask;
- call synthesis planning/writeback;
- call lint/eval/clean;
- expose raw prompts;
- expose raw LLM responses;
- expose full parser logs;
- expose backend-native parser artifacts;
- expose API key paths or values.

## 15. Safety And Sanitization

V3.4 should add explicit safety checks:

- ids are treated as ids, not filesystem paths;
- page markdown is read only from catalog rows and only if the resolved path is under `wiki/`;
- normalized snippets are read only from catalog rows and only if the resolved path is under `sources/normalized/`;
- PDF block snippets are read only from `sources/blocks/<source-id>.jsonl`;
- response text is bounded;
- JSONL sidecar reads are bounded by line count and byte count;
- malformed JSON/JSONL returns warnings instead of crashing;
- secret patterns are sanitized through the existing UI sanitizer;
- no CORS expansion is introduced.

Recommended bounds for the implementation plan to decide:

- page markdown max characters: 120,000;
- claim text max characters: existing sanitizer defaults unless table layout needs tighter bounds;
- locator context max characters: 4,000;
- JSONL sidecar scan max bytes: 5 MB per request;
- max claim list limit: 200.

## 16. Error Model

New endpoints should return normal HTTP error codes with sanitized messages:

- `400 invalid_request` for invalid ids, invalid limit/offset, or unsupported filter values;
- `404 not_found` for missing catalog source/page/claim ids;
- `409 catalog_unavailable` when the workspace has no usable catalog;
- `500 internal_error` only for unexpected server errors after sanitization.

Missing sidecars, missing wiki markdown files, unsupported locators, and broken links should generally be warnings inside a `200` response when the primary catalog row exists.

## 17. Testing Strategy

The implementation plan should use contract-first, risk-based TDD.

Recommended tests:

- `tests/test_ui_browser_api.py`
  - source detail returns source row, latest run, sidecar summary, and claims;
  - page detail returns page row, aliases, bounded markdown, links, and related evidence;
  - claim list filters by query/source/confidence/relationship;
  - claim detail resolves Markdown `line:N` snippets;
  - claim detail resolves PDF `page:N;block:<id>` snippets from blocks sidecar;
  - unsupported locators return warnings without fabricated context;
  - malformed sidecars warn without crashing;
  - path traversal and outside-workspace paths are rejected or redacted.

- `tests/test_ui_server.py`
  - new GET routes are reachable;
  - missing ids return `404`;
  - invalid filters return `400`;
  - new routes do not require action token because they are read-only;
  - no new mutating route is exposed.

- `tests/test_ui_readonly.py`
  - new GET routes do not call LLM providers, embedding providers, MinerU parsing, add/ingest/apply, ask, synthesis, lint, eval, or clean;
  - new GET routes do not write `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/embeddings/`, or `state/ui-jobs/`.

- `tests/test_ui_static.py`
  - static UI contains Evidence Browser and Wiki Browser controls;
  - V3.3 Ask citations/evidence rows still exist;
  - secret marker checks remain.

Existing tests that should still pass:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_ui_static.py tests\test_ui_server.py tests\test_ui_api.py tests\test_ui_ask_api.py tests\test_ui_synthesis_api.py
.\.venv\Scripts\python.exe -m pytest tests\test_ui_readonly.py tests\test_ui_mutation_boundary.py
```

## 18. Manual Acceptance

Manual V3.4 acceptance should use a workspace with at least:

- one Markdown/text source with `line:N` citations;
- one PDF source with `page:N;block:<block-id>` citations;
- one concept or entity page;
- one synthesis page produced by V3.3 writeback;
- at least one weak/uncited claim if available;
- at least one `contradicts` relationship if available.

Acceptance steps:

1. Start `llmwiki ui --root . --no-open`.
2. Open the dashboard in a browser.
3. Open Evidence Browser and filter claims by source, confidence, and relationship type.
4. Open a claim detail and confirm raw claim/source/page/locator ids are visible.
5. Confirm Markdown `line:N` citation context is shown when available.
6. Confirm PDF `page:N;block:<id>` citation context is shown when available.
7. Open Wiki Browser and inspect source, concept/entity, synthesis, and index pages.
8. Confirm page markdown is labeled as page text, not formal evidence.
9. Confirm catalog-backed claims are shown separately from synthesis narrative text.
10. Ask a question, click a citation, and confirm it navigates to the matching claim detail.
11. Confirm unsupported/missing locators produce warnings rather than fabricated context.
12. Confirm no generated files are created by browsing.

## 19. Success Criteria

V3.4 is successful when:

- users can inspect evidence and wiki pages without leaving the UI;
- every claim detail preserves source id, claim id, citation locator, confidence status, and relationship audit values;
- source-backed claims are visibly separate from synthesis/page markdown text;
- citation links from Ask results lead to claim details;
- GET browsing does not call providers or write workspace state;
- missing or malformed sidecars degrade with warnings;
- no parser artifacts, secrets, raw prompts, or raw LLM responses are exposed.

## 20. Open Decisions For The Implementation Plan

The V3.4 implementation plan should decide:

- whether to bump every UI response to `ui.v3.4` or use `ui.v3.4` only for new browser endpoints;
- whether claim search should use FTS first with `LIKE` fallback or only bounded `LIKE` for the first implementation;
- exact pagination defaults and maximum limits;
- whether page detail should render markdown as plain text or a constrained markdown preview;
- whether detail panels are implemented as tabs, drawers, or a fixed split layout;
- exact Chinese labels for Evidence Browser, Wiki Browser, Claim Detail, Source Detail, and Page Detail;
- whether V3.4 should include a small relationship table in the main UI or only in detail views.

Do not proceed from this spec directly into code changes without a separate implementation plan under `docs/plans/`.
