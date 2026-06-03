# LLMWiki V3.3 Ask And Synthesis UI Design

## 1. Background

V3.1 introduced a local dashboard for workspace status. V3.2 added Source Library and single-source job visibility, so a user can submit one source path or URL from the UI and see the add job state.

The next usability gap is the research loop itself. Today users still need CLI commands for:

```bash
llmwiki ask "question" --root . --json
llmwiki ask "question" --root . --preview-writeback
llmwiki ask "question" --root . --writeback
```

V3.3 should bring that loop into the local UI without changing the underlying evidence contract:

```text
Question
-> LLM query planning
-> local retrieve
-> grounded answer
-> optional synthesis preview
-> optional synthesis writeback through staging/apply
```

The goal is not to make a chat app. The goal is a source-backed research workbench where answer text, citations, retrieved evidence, warnings, planning diagnostics, and synthesis writeback decisions are visible and auditable.

## 2. Goals

V3.3 must provide:

- an Ask panel in `llmwiki ui --root .`;
- an asynchronous ask job using the existing V3.2 UI job infrastructure;
- answer display with status, answer text, analysis, warnings, uncertainties, conflicts, and citations;
- retrieved evidence display for every cited and selected context;
- query planning diagnostics: intent, entities/concepts when present, subqueries, filters, and retrieved context count;
- synthesis preview action for an answered ask job;
- synthesis writeback action that applies through existing staging/apply only;
- visible synthesis plan details before writeback;
- sanitized failure display for planner, retrieval, answer LLM, invalid citations, synthesis planning, and synthesis apply errors;
- local action-token protection for mutating ask/writeback routes.

The user goal is:

> A user can ask a question from the UI, inspect exactly what evidence was used, preview a synthesis page update, and approve writeback without using the CLI.

## 3. Non-Goals

V3.3 does not implement:

- multi-turn chat memory;
- streaming answer tokens;
- batch ask;
- source upload;
- batch import;
- claim browser beyond the evidence attached to an ask result;
- full wiki page editor;
- custom prompt editor;
- new retrieval, reranker, planner, or synthesis algorithms;
- new PDF parsing capability;
- relationship classifier;
- autonomous wiki maintenance;
- cloud sync or multi-user authentication.

V3.3 should not start V4 batch import or V5 maintenance behavior.

## 4. Recommended Architecture

Extend the V3.2 local UI service:

```text
Browser UI
-> Local UI API
-> UI job service
-> answer_question(...)
-> optional plan_synthesis_writeback(...)
-> optional create_synthesis_run(...)
-> staging/apply/catalog/wiki
```

V3.3 should add new UI-domain modules rather than crowding existing server code:

```text
src/llmwiki/ui/
  ask_actions.py
  ask_models.py
```

Existing files extended:

```text
src/llmwiki/ui/jobs.py
src/llmwiki/ui/api.py
src/llmwiki/ui/server.py
src/llmwiki/ui/models.py
src/llmwiki/ui/static/index.html
src/llmwiki/ui/static/app.js
src/llmwiki/ui/static/styles.css
```

The UI service should call stable Python APIs:

```python
answer_question(root, question, AskOptions(...))
plan_synthesis_writeback(root, ask_result, SynthesisPlanningOptions(...))
create_synthesis_run(root, ask_result, plan, planning_options=...)
```

It must not duplicate query planning, retrieval, citation validation, synthesis validation, staging, or apply logic in the UI layer.

## 5. Job Model Extension

V3.3 should extend `state/ui-jobs/<job-id>.json` with additional job types:

- `add_source` from V3.2;
- `ask_question`;
- `synthesis_preview`;
- `synthesis_writeback`.

No new SQLite table is required.

The same generated local state directory remains:

```text
state/ui-jobs/
```

All job payloads must remain bounded and sanitized. They must not contain raw prompts, raw LLM responses, API key values, full parser logs, or arbitrary file contents.

### Ask Job

Ask job example:

```json
{
  "schema_version": "ui_job.v3.3",
  "job_id": "job_20260602_123456_ab12cd34",
  "job_type": "ask_question",
  "status": "pending",
  "stage": "queued",
  "question": "What does OSWorld evaluate?",
  "ask_options": {
    "limit": 8,
    "source_id": null,
    "page_type": null,
    "confidence": null
  },
  "result": {},
  "failure_stage": "",
  "failure_reason": ""
}
```

Allowed final statuses:

- `answered`;
- `planned_insufficient_evidence`;
- `planning_failed`;
- `planning_invalid`;
- `llm_failed`;
- `invalid_citations`;
- `failed`;
- `interrupted`.

For UI consistency, the persisted `status` may remain one of the generic job statuses (`applied`, `failed`, etc.) while `result.answer_status` stores the ask-specific status. The implementation plan should choose one representation and keep the API stable. Recommended: keep `UiJob.status` generic and store `answer_status` in `result`.

## 6. Ask Action Flow

### Submit Ask

User enters:

- question;
- optional limit;
- optional source filter;
- optional page type filter;
- optional confidence filter.

V3.3 should keep options minimal in the first UI:

- `question` text area;
- `limit` numeric input, default `8`;
- optional collapsed filters.

POST creates an `ask_question` job and returns immediately:

```text
POST /api/ask
```

The worker calls:

```python
answer_question(root, question, AskOptions(...))
```

The result is persisted as a bounded JSON payload derived from `AskResult.to_dict()` plus V3.3 display fields:

- answer;
- analysis;
- citations;
- warnings;
- uncertainties;
- conflicts;
- planning summary;
- contexts;
- relationships;
- suggested title;
- error/status.

### Display Ask Result

The UI should render:

- status banner;
- answer;
- analysis;
- citations table;
- evidence cards/table;
- warnings and uncertainties;
- conflicts;
- planning diagnostics;
- synthesis actions when eligible.

The UI should make it clear when the system is conservative because evidence is missing or weak. A `planned_insufficient_evidence` status is a valid outcome, not a UI error.

## 7. Evidence Display

V3.3 should show evidence directly attached to the ask result, not run a separate retrieval implementation.

Each evidence item should display:

- claim id;
- source id;
- source title if available;
- citation locator;
- page path;
- page type;
- confidence status;
- relationship type when present;
- rerank score / selection reason when available;
- claim text.

Citation rows should link to corresponding evidence rows inside the page. If safe local path links are implemented, they may point to the wiki page path, but V3.3 does not need OS-level file opening.

Rules:

- planner output is not evidence;
- synthesis plan output is not evidence;
- parser diagnostics are not evidence;
- answer citations must match retrieved contexts already validated by `answer_question`;
- weak/uncited and contradicting evidence must remain visible.

## 8. Planning Diagnostics Display

The planning panel should be collapsible.

It may show:

- planner status;
- intent;
- entities;
- concepts;
- subqueries;
- filters;
- required evidence descriptions;
- retrieved context count;
- planned retrieval diagnostics.

It must not imply that planner entities or concepts are catalog claims. The UI label should use language like:

```text
Query planning diagnostics
```

not:

```text
Evidence
```

If planning fails or is invalid, the UI should show the sanitized planner error and not offer synthesis writeback.

## 9. Synthesis Preview Flow

V3.3 should expose synthesis preview as a separate action after an ask job reaches `answered`.

```text
POST /api/ask/<ask-job-id>/synthesis/preview
```

This action creates a `synthesis_preview` job or stores a preview result linked to the ask job. Recommended first version: create a separate job so long LLM synthesis planning does not block the HTTP request.

The worker reconstructs or loads the persisted ask result and calls:

```python
plan_synthesis_writeback(root, ask_result, SynthesisPlanningOptions(writeback_mode=...))
```

Preview result should include:

- action: `create`, `update`, or `needs_review`;
- target page id;
- target path;
- title;
- evidence claim ids;
- relationship proposals;
- warnings/limits/open questions;
- rendered preview text from `format_synthesis_preview(plan)`;
- validation status.

Preview must not create staging runs, apply patches, write wiki pages, or mutate catalog.

## 10. Synthesis Writeback Flow

After preview, UI may offer an explicit apply button if the preview action is `create` or `update`.

```text
POST /api/ask/<ask-job-id>/synthesis/writeback
```

Request:

```json
{
  "preview_job_id": "job_...",
  "writeback_mode": "auto"
}
```

Allowed writeback modes:

- `auto`;
- `create`;
- `update`.

The worker calls:

```python
create_synthesis_run(root, ask_result, plan, planning_options=...)
```

`create_synthesis_run` already stages and applies through the existing safety path. UI code must not write synthesis pages directly.

Writeback result should display:

- writeback status;
- run id;
- pages;
- action;
- synthesis plan summary;
- failure stage/reason if failed.

If `plan.action == "needs_review"`, writeback must not apply and the UI should show a review-needed state.

## 11. API Surface

Existing V3.2 APIs remain:

```text
GET  /api/session
GET  /api/status
GET  /api/sources
GET  /api/runs
GET  /api/pages
GET  /api/jobs
GET  /api/jobs/<job-id>
POST /api/sources/add
```

New V3.3 APIs:

```text
POST /api/ask
GET  /api/ask/jobs
GET  /api/ask/jobs/<job-id>
POST /api/ask/<job-id>/synthesis/preview
POST /api/ask/<job-id>/synthesis/writeback
```

All responses use:

```json
{
  "schema_version": "ui.v3.3"
}
```

All mutating POST routes require:

```text
X-LLMWiki-UI-Token: <token>
```

No permissive CORS headers should be added.

## 12. UI Screens

V3.3 can remain a single-page dashboard with additional sections. It does not need routing.

### Ask Panel

Controls:

- question textarea;
- limit input;
- optional filters toggle;
- Ask button.

The panel should be dense and work-focused, not a marketing hero or chat-themed landing page.

### Active Research Job Strip

Shows:

- active ask/synthesis job id;
- stage;
- status;
- elapsed time when available;
- sanitized failure reason.

### Answer Panel

Shows:

- answer status;
- answer text;
- analysis;
- warnings;
- uncertainties;
- conflicts.

### Citations And Evidence

Use tables/cards with stable dimensions and no nested cards.

Recommended sections:

- Citations;
- Retrieved Evidence;
- Relationships;
- Query Planning Diagnostics.

### Synthesis Panel

Shown only when an answer is eligible.

States:

- no answered ask selected;
- preview available;
- preview running;
- preview result available;
- writeback running;
- writeback applied;
- needs review;
- failed.

Actions:

- Preview synthesis;
- Apply writeback.

V3.3 should not auto-apply synthesis immediately after ask.

## 13. Read/Write Boundary

V3.3 changes the UI boundary again:

- GET endpoints stay read-only;
- POST `/api/ask` may call LLM through `answer_question`;
- POST synthesis preview may call LLM synthesis planner;
- POST synthesis writeback may create staging runs and apply through `create_synthesis_run`;
- UI code must not directly mutate formal wiki/catalog data;
- synthesis writeback must still go through staging/apply and catalog validation.

The UI should distinguish these three categories:

1. read-only status and browsing;
2. LLM/retrieval jobs that produce UI job results only;
3. writeback jobs that intentionally mutate through existing validated pipeline.

## 14. Safety And Secret Handling

V3.3 must not expose:

- API keys;
- `config/api-keys.toml` content;
- raw prompts;
- raw LLM responses;
- full stack traces;
- full parser logs;
- arbitrary file contents.

Ask and synthesis failures must be sanitized.

Persisted UI job results should be bounded. If result payloads are too large, store a compact version:

- answer fields;
- citation/evidence summaries;
- planning summary;
- synthesis plan summary.

Do not persist raw provider response text.

## 15. Error Handling

Ask failures:

- planning failed;
- planning invalid;
- planned insufficient evidence;
- retrieval failed;
- LLM failed;
- invalid citations;
- provider unavailable;
- missing API key.

Synthesis failures:

- answer status not eligible;
- no cited evidence;
- planning failed;
- plan validation failed;
- needs review;
- apply failed.

All failure responses should include:

- job id;
- stage;
- sanitized reason;
- related run id if one exists;
- whether user can retry from UI.

V3.3 does not need retry implementation. It may display that retry is deferred.

## 16. Testing Strategy

Suggested test files:

- `tests/test_ui_ask_actions.py`;
- `tests/test_ui_ask_api.py`;
- `tests/test_ui_synthesis_actions.py`;
- `tests/test_ui_synthesis_api.py`;
- `tests/test_ui_static.py`;
- `tests/test_ui_readonly.py`;
- `tests/test_ui_mutation_boundary.py`;
- `tests/test_ui_cli.py`.

Required coverage:

- ask request validation;
- `POST /api/ask` requires token;
- valid ask request creates ask job;
- ask worker calls `answer_question` exactly once;
- answered result stores citations and contexts;
- planned insufficient evidence is displayed as non-error result;
- LLM/provider failure is sanitized;
- invalid citation status is visible;
- synthesis preview requires answered ask result;
- preview does not mutate staging/wiki/catalog;
- writeback calls `create_synthesis_run`;
- writeback result includes run id and pages;
- `needs_review` prevents writeback;
- all GET routes remain read-only;
- no UI response leaks secrets;
- static JS calls new ask/synthesis endpoints;
- existing V3.2 source add tests continue passing.

Tests should monkeypatch LLM/provider-facing APIs. V3.3 tests must not require real DeepSeek, embedding provider, MinerU, or network.

## 17. Acceptance Criteria

V3.3 is complete when:

- user can open `llmwiki ui --root .`;
- user can ask a question from the UI;
- UI shows pending/running/final ask status;
- answered ask shows citations and retrieved evidence;
- query planning diagnostics are visible but not treated as evidence;
- insufficient evidence is clearly shown;
- synthesis preview can be generated from an answered ask;
- preview does not write wiki/catalog/staging;
- writeback only happens after explicit user action;
- writeback uses existing staging/apply path and returns run id/page path;
- writeback failures are visible and sanitized;
- GET endpoints remain read-only;
- action-token protection applies to ask/preview/writeback POSTs;
- existing add/retrieve/ask/synthesis tests continue passing;
- generated `.test-workspaces`, `.pytest_cache`, `.tmp`, UI jobs, and source/wiki/staging/state caches are cleaned after verification.

## 18. Deferred To Later Versions

Deferred to V3.4:

- full claim browser;
- source page inspector;
- relationship graph UI;
- arbitrary retrieved-context inspector independent of ask.

Deferred to V3.5:

- UI-triggered lint/eval/pdf-quality execution;
- quality dashboards;
- persistent quality check history.

Deferred to V4:

- batch ask over source sets;
- paper corpus import queue;
- long-running progress callbacks across parser/chunks/LLM/apply;
- table/figure/formula evidence upgrades.

Deferred to V5:

- autonomous maintenance planner;
- relationship classifier;
- source-backed conflict detection;
- synthesis maintenance queue.

## 19. Implementation Notes

V3.3 should be implemented in small commits:

1. ask action models and validation;
2. ask job worker and persisted result shape;
3. ask HTTP API endpoints;
4. answer/evidence/planning UI;
5. synthesis preview action and API;
6. synthesis writeback action and API;
7. synthesis preview/writeback UI;
8. safety/read-write boundary tests;
9. docs and final verification.

Do not implement V3.4 evidence browser or V4 batch import in the same implementation plan.

