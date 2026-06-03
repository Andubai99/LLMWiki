# LLMWiki V3.4 Evidence And Wiki Browser Implementation Plan

## Summary

Implement `docs/specs/2026-06-03-llmwiki-v3-4-evidence-wiki-browser-design.md`: add a read-only Evidence/Wiki Browser to the Chinese `llmwiki ui` so users can navigate from Ask citations to claim details, inspect source/page/locator/confidence/relationships, and distinguish catalog-backed claims from page or synthesis markdown text.

Method: spec-driven + contract-first + risk-based TDD. Write failing tests for the deterministic API/read-only boundaries first, implement backend browser APIs, then connect the static frontend.

## Key Changes

- Bump UI response schema to `ui.v3.4`; keep UI job schema at `ui_job.v3.3`.
- Add read-only GET APIs:
  - `GET /api/sources/<source-id>`
  - `GET /api/pages/<page-id>`
  - `GET /api/evidence/claims`
  - `GET /api/evidence/claims/<claim-id>`
  - `GET /api/evidence/relationships`
- Add browser-specific models in `src/llmwiki/ui/browser_models.py`.
- Add browser-specific read-only catalog/wiki/sidecar logic in `src/llmwiki/ui/browser_api.py`.
- Use bounded SQL `LIKE` for claim search; no FTS query parsing in the first implementation.
- Keep default `limit=50`, max `limit=200`, and require `offset >= 0`.
- Render page markdown as escaped/plain text in a `<pre>`; do not add a markdown renderer.
- Resolve only:
  - Markdown/text `line:N` snippets from catalog `normalized_path` under `sources/normalized/`.
  - PDF `page:N;block:<block-id>` snippets from `sources/blocks/<source-id>.jsonl`.
- Treat unsupported locators, missing sidecars, and malformed sidecars as warnings. Never fabricate context.
- Add frontend sections:
  - `证据浏览`: query/source/page type/confidence/relationship filters plus claims table.
  - `Wiki 浏览`: page type/query filters plus page list.
  - shared detail panel for `声明详情` / `资料源详情` / `页面详情`.
- Make V3.3 citation/evidence claim ids clickable so they load claim detail.
- Do not add an independent relationship table page; show raw relationship rows in detail views and compact relationship summaries in claim list.
- Preserve raw audit values: `source_id`, `claim_id`, `page_id`, `citation_locator`, `confidence_status`, `relationship_type`, job/run status, and parser backend values.

## Implementation Tasks

### Task 1: Save Plan

- Create this file at `docs/plans/2026-06-03-llmwiki-v3-4-evidence-wiki-browser.md`.
- Run `git status --short`; expect only this plan file.
- Commit: `保存 V3.4 证据与 Wiki 浏览执行计划`.

### Task 2: Backend Browser Models And API

- Create `tests/test_ui_browser_api.py` with failing tests for:
  - source detail returns source row, latest run, latest job when present, sidecar summary, metadata summary, claim counts, and claims;
  - page detail returns page row, parsed aliases, bounded markdown, links, related claims, and relationships;
  - claim list filters by query, source, page type, confidence, and relationship;
  - relationship list filters by source, page, claim, and relationship type;
  - claim detail preserves raw audit values and resolves Markdown `line:N` context;
  - claim detail resolves PDF `page:N;block:<id>` context from blocks sidecar;
  - unsupported locator returns warning without fabricated context;
  - missing or malformed sidecars warn without crashing;
  - outside-workspace paths are redacted or rejected.
- Implement `browser_models.py` response dataclasses.
- Implement `browser_api.py` helpers and read-only query functions.
- Update `UI_SCHEMA_VERSION = "ui.v3.4"` and existing UI API tests.
- Run `.\.venv\Scripts\python.exe -m pytest tests\test_ui_browser_api.py tests\test_ui_api.py -q`.
- Commit: `新增 V3.4 证据浏览后端 API`.

### Task 3: HTTP GET Routes

- Extend `tests/test_ui_server.py` for new GET routes:
  - reachable without `X-LLMWiki-UI-Token`;
  - missing source/page/claim returns `404`;
  - invalid filter/limit/offset returns `400`;
  - missing or invalid catalog returns `409 catalog_unavailable`;
  - no new V3.4 POST route exists.
- Modify `server.py` only in GET routing and error serialization.
- Do not change existing POST token behavior.
- Run `.\.venv\Scripts\python.exe -m pytest tests\test_ui_server.py tests\test_ui_api.py tests\test_ui_browser_api.py -q`.
- Commit: `接入 V3.4 只读浏览 HTTP 路由`.

### Task 4: Static Evidence/Wiki Browser UI

- Extend `tests/test_ui_static.py` for:
  - `证据浏览`, `Wiki 浏览`, `声明详情`, `资料源详情`, `页面详情`;
  - new endpoint strings in `app.js`;
  - claim detail loading helpers;
  - clickable citation/evidence claim ids;
  - existing Ask/Synthesis/Source Library ids remain;
  - secret marker checks remain.
- Modify `index.html`, `app.js`, and `styles.css`.
- Use `escapeHtml` or `textContent` for all dynamic content.
- Render detail markdown/context as escaped/plain text only.
- Keep the app single-page and work-focused.
- Run `.\.venv\Scripts\python.exe -m pytest tests\test_ui_static.py tests\test_ui_browser_api.py -q`.
- Commit: `新增 V3.4 证据与 Wiki 浏览界面`.

### Task 5: Read-Only Boundary And Safety

- Extend `tests/test_ui_readonly.py`:
  - new GET routes do not call LLM providers, embedding providers, MinerU parsing, add/ingest/apply, ask, synthesis, lint, eval, or clean;
  - new GET routes do not write `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/embeddings/`, or `state/ui-jobs/`.
- Extend `tests/test_ui_mutation_boundary.py`:
  - V3.4 adds no new POST route;
  - all existing mutating routes still require token.
- Preserve sanitizer coverage for `config/api-keys.toml`, `api_key=...`, and `sk-...`.
- Run `.\.venv\Scripts\python.exe -m pytest tests\test_ui_readonly.py tests\test_ui_mutation_boundary.py -q`.
- Commit: `固定 V3.4 UI 只读浏览边界`.

### Task 6: Documentation And Contract

- Update `README.md` with V3.4 Evidence/Wiki Browser behavior and read-only boundaries.
- Update `AGENTS.md` with V3.4 GET routes and evidence/page-text distinction.
- Update `tests/test_regression_samples.py` accordingly.
- Run `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`.
- Commit: `更新 V3.4 证据浏览文档契约`.

### Task 7: Verification And Cleanup

- Run:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_ui_static.py tests\test_ui_server.py tests\test_ui_api.py tests\test_ui_browser_api.py tests\test_ui_readonly.py tests\test_ui_mutation_boundary.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_ui_ask_api.py tests\test_ui_synthesis_api.py tests\test_ui_server_actions.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Run `.\.venv\Scripts\python.exe -m llmwiki clean --root .`.
- Run `git status --short --ignored` and confirm generated files, caches, local API keys, and acceptance outputs are not staged.
- Commit any remaining feature-scope changes if needed.

## Test Scenarios

- Empty or missing catalog returns safe unavailable responses.
- Source detail is read-only and bounded.
- Page detail distinguishes markdown text from catalog-backed evidence.
- Claim list supports deterministic filters and pagination.
- Claim detail preserves claim/source/page/locator/confidence/relationship audit values.
- Markdown `line:N` context resolves only from safe normalized source paths.
- PDF block context resolves only from safe blocks sidecars.
- Unsupported or malformed locators warn instead of inventing context.
- Ask citation claim ids navigate to claim detail.
- `contradicts` relationships remain visible.
- GET routes do not call providers or mutate workspace state.
- Existing V3.3 ask/synthesis and V3.2 source add routes still pass.

## Assumptions And Defaults

- No catalog schema migration.
- No React/Vite/Markdown renderer/i18n framework.
- No FTS in the first implementation; use bounded `LIKE`.
- `ui.v3.4` applies to all UI responses; `ui_job.v3.3` remains unchanged.
- V3.4 adds no POST route and creates no UI jobs.
- Page markdown is display text, not formal evidence.
- Synthesis markdown paragraphs are not claims.
- Only catalog claims and catalog relationships count as evidence.
- Commit by feature/function: plan, backend API, HTTP routes, frontend UI, read-only boundary, docs/contract.
