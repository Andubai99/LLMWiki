# LLMWiki V3.1 Local UI And Workspace Dashboard Design

## 1. Background

V2 has made LLMWiki usable as a local source-backed knowledge compiler, but normal operation is still CLI-heavy. Users must inspect `staging/`, sidecar files, generated wiki pages, and SQLite-derived state manually to understand what happened.

The V3-V5 roadmap sets V3 as the product-shell phase. V3.1 is the first UI slice. Its job is not to add new knowledge-generation behavior. Its job is to make the existing workspace state visible through a local dashboard.

V3.1 should answer basic operational questions:

- Is this workspace initialized and healthy?
- Which sources, runs, pages, and catalog objects exist?
- Are parser, LLM, embedding, and vector settings configured?
- Are there recent failures or warnings?
- Where can I open relevant local files?

## 2. Goals

V3.1 must provide:

- a local web UI entry point;
- a local API/service layer wrapping existing `src/llmwiki` modules;
- workspace selection by root path;
- read-only workspace status;
- source, run, wiki page, catalog, parser, LLM, embedding, and vector status summaries;
- sanitized display of configuration readiness without exposing secrets;
- links or paths for opening safe local artifacts;
- a foundation that V3.2 source add/job visibility and V3.3 ask/synthesis UI can extend.

V3.1 should be useful even before V3.2 exists: a user can open the UI and understand whether the workspace is ready and what data is already present.

## 3. Non-Goals

V3.1 does not implement:

- adding sources from the UI;
- batch import;
- long-running job scheduling;
- `ask` UI;
- synthesis preview/writeback UI;
- claim browser;
- relationship graph UI;
- new PDF parsing capability;
- MinerU behavior changes;
- new catalog schema;
- automatic wiki maintenance;
- cloud sync;
- multi-user permissions;
- Obsidian plugin support.

V3.1 is intentionally read-only except for starting/stopping the local app process itself.

## 4. Recommended Stack

Use a local browser UI backed by a Python service.

Recommended V3.1 stack:

- Backend: Python local HTTP service under `src/llmwiki/ui/`.
- UI: static HTML/CSS/vanilla JavaScript served by the Python service.
- CLI entry: `llmwiki ui --root .` starts the local server and prints the local URL.
- Default host: `127.0.0.1`.
- Default port: `8765`, with automatic fallback to another available local port if occupied.

Rationale:

- It avoids introducing Node/Vite/React before the first product-shell slice is proven.
- It keeps the implementation close to the existing Python package and local workspace model.
- It is enough for dashboard tables, status cards, and JSON-backed views.
- Future V3 sub-phases can replace the frontend with React/Vite if needed without changing the service contract.

The service should use existing Python APIs directly where stable APIs exist. It should not shell out to CLI commands for basic status reads.

## 5. Architecture

```text
Browser
-> Local UI static assets
-> Local Python UI service
-> Existing llmwiki domain modules
-> Workspace files + state/catalog.sqlite
```

New package:

```text
src/llmwiki/ui/
  __init__.py
  server.py
  api.py
  models.py
  static/
    index.html
    app.js
    styles.css
```

The package boundary should be:

- `server.py`: local HTTP server lifecycle and routing.
- `api.py`: read-only workspace status functions.
- `models.py`: stable response models and sanitization helpers.
- `static/`: first-pass dashboard UI.

The UI service must call into existing domain packages:

- `llmwiki.workspace`
- `llmwiki.db`
- `llmwiki.ingestion`
- `llmwiki.pdf`
- `llmwiki.retrieval`
- `llmwiki.vector`
- `llmwiki.maintenance.clean` only for status in V3.1, not for mutation.

## 6. CLI Contract

Add:

```bash
llmwiki ui --root .
```

Optional flags:

```bash
llmwiki ui --root . --host 127.0.0.1 --port 8765
llmwiki ui --root . --no-open
```

Behavior:

- starts a local read-only web server;
- prints the local URL;
- opens the browser by default when possible;
- `--no-open` only prints the URL;
- does not run LLM, embedding, MinerU, parser, lint, eval, add, ingest, apply, or clean;
- does not create, update, or delete wiki/catalog/source/staging files.

The command can remain foreground-only in V3.1. Background daemon management is not required.

## 7. API Surface

V3.1 should expose a small local JSON API.

### `GET /api/status`

Returns:

- schema version;
- workspace root;
- initialized status;
- required directory status;
- catalog existence;
- catalog table counts;
- source/page/run counts;
- latest run summaries;
- parser config status;
- LLM config status;
- embedding config status;
- vector index status;
- warnings.

No secret values are returned.

### `GET /api/sources`

Returns source summaries from catalog and source sidecars when available:

- `source_id`;
- title;
- kind;
- locator or local path summary;
- duplicate status when known;
- latest run id/status;
- parser backend;
- fallback status;
- sidecar completeness summary.

V3.1 may return an empty list if no catalog exists.

### `GET /api/runs`

Returns recent ingest/synthesis run summaries:

- `run_id`;
- source id;
- status;
- run type;
- trigger;
- created/applied/failed timestamps when available;
- failed stage;
- sanitized failure reason;
- patch count;
- claim count.

The API must not dump full prompts, raw malformed LLM output, raw parser logs, or secret config paths.

### `GET /api/pages`

Returns wiki page summaries:

- page id;
- title;
- page type;
- path;
- source id when applicable;
- claim count when known.

### `GET /api/config`

Returns readiness only:

- LLM provider configured: yes/no;
- LLM model name;
- LLM key present: yes/no;
- embedding provider configured: yes/no;
- embedding model name;
- embedding key present: yes/no;
- PDF parser default/fallback backend;
- MinerU command availability summary.

API keys, full local secret file contents, and raw env values must never be returned.

## 8. UI Screens

V3.1 first UI should have one dashboard page with simple sections.

### Header

Shows:

- product name;
- workspace root;
- initialized status;
- refresh button.

### Status Cards

Shows:

- sources count;
- claims count;
- wiki pages count;
- latest run status;
- parser backend status;
- LLM key readiness;
- embedding/vector status.

### Source Summary

Table columns:

- source id;
- title;
- kind;
- latest run status;
- parser backend/fallback;
- sidecar status.

### Recent Runs

Table columns:

- run id;
- source id;
- status;
- stage;
- claims;
- patches;
- sanitized warning/error.

### Wiki Summary

Grouped counts for:

- sources;
- concepts;
- entities;
- syntheses.

### Quality Summary

V3.1 should show known read-only status if cheap to compute. It should not run lint or eval automatically.

Allowed:

- display whether `state/catalog.sqlite` exists;
- display parser status from local config/probe;
- display vector index status from local files.

Not allowed:

- automatically running `llmwiki lint`;
- automatically running `llmwiki eval retrieval`;
- automatically running `llmwiki eval pdf-quality`;
- automatically invoking MinerU.

## 9. Workspace Status Model

The dashboard should treat workspace state as one of:

- `not_initialized`: required skeleton missing;
- `initialized_empty`: skeleton exists, catalog absent or empty;
- `ready`: catalog and skeleton available;
- `degraded`: workspace exists but has missing sidecars, failed runs, stale vector index, or parser warnings;
- `error`: status could not be read safely.

This status is for UI guidance only. It must not mutate workspace files.

## 10. Safety And Security

V3.1 must preserve these boundaries:

- UI server binds to `127.0.0.1` by default.
- UI APIs are local-only in V3.1.
- No API keys or secret config values are displayed.
- `config/api-keys.toml` content is never returned.
- Parser logs are truncated and sanitized.
- Full LLM prompts and raw model outputs are not displayed.
- Generated knowledge is not written by V3.1 dashboard endpoints.
- The UI must distinguish evidence/catalog data from parser diagnostics.
- Parser artifacts must not be displayed as evidence.

If a path is displayed, it should be a local relative path under the workspace where possible. The UI must not recursively expose arbitrary filesystem listings.

## 11. Error Handling

API errors should return structured JSON:

```json
{
  "status": "error",
  "error_type": "workspace_not_found",
  "message": "Workspace root is not initialized.",
  "warnings": []
}
```

Rules:

- errors must be sanitized;
- missing catalog is not fatal for `/api/status`;
- malformed sidecars should create warnings, not crash the whole dashboard;
- unreadable local files should show a bounded diagnostic;
- no stack traces in normal UI responses.

## 12. Data Sources

V3.1 can read:

- `config/config.toml`;
- presence of `config/api-keys.toml`, without content;
- `state/catalog.sqlite`;
- `staging/*/run.json`;
- `staging/*/llm-proposal.json`, only bounded metadata fields;
- `sources/metadata/*.json`;
- `sources/blocks/*.jsonl`, only counts and schema/quality summary;
- `sources/chunks/*.jsonl`, only counts and schema/quality summary;
- `wiki/*.template.md`;
- generated wiki page paths and catalog page rows.

V3.1 must not read entire raw PDFs into UI responses.

## 13. Testing Strategy

Tests should cover:

- UI service can start on an available localhost port.
- `/api/status` works for an initialized empty workspace.
- `/api/status` works for a workspace with seeded catalog rows.
- `/api/config` reports key presence without leaking key values.
- `/api/sources`, `/api/runs`, and `/api/pages` return stable JSON shapes.
- malformed sidecars produce warnings, not crashes.
- UI read endpoints do not call LLM, embedding provider, MinerU, parser execution, add, ingest, apply, lint, eval, or clean.
- dashboard static files are served.
- `llmwiki ui --root . --no-open` prints a URL and does not mutate workspace.

Suggested test files:

- `tests/test_ui_api.py`
- `tests/test_ui_cli.py`
- `tests/test_ui_static.py`

## 14. Acceptance Criteria

V3.1 is complete when:

- `llmwiki ui --root . --no-open` starts a local UI service and prints a URL;
- opening the URL shows a dashboard page;
- the dashboard shows workspace readiness, catalog counts, source summaries, recent run summaries, page summaries, parser status, LLM readiness, embedding/vector readiness, and warnings;
- API responses do not leak secrets;
- read-only dashboard/API routes do not mutate workspace files;
- UI works for both empty initialized workspaces and workspaces with existing catalog data;
- full project tests pass;
- generated caches are cleaned after verification.

## 15. Open Decisions Deferred To V3.2+

These are intentionally deferred:

- whether to replace vanilla JS with React/Vite;
- whether to persist UI job state in SQLite or JSONL;
- whether to expose file-open actions as clickable desktop integrations;
- whether to keep an in-app server daemon;
- how to model batch import progress;
- how much of staging details should be exposed to non-technical users.

## 16. Implementation Notes

V3.1 should be implemented in small commits:

1. UI API status models.
2. Local server and static dashboard.
3. CLI `ui` command.
4. Config/status sanitization.
5. Tests and docs.

Do not begin V3.2 source add/job visibility until V3.1 dashboard is stable and reviewed.
