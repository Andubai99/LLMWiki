# LLMWiki V3.2 Source Library And Job Visibility Design

## 1. Background

V3.1 已经实现本地只读 dashboard：用户可以打开 `llmwiki ui --root .`，查看 workspace 状态、sources、runs、pages、config readiness 和 warnings。

但 V3.1 仍不能从 UI 操作系统。用户如果要导入资料，仍必须回到 CLI 执行：

```bash
llmwiki add <source> --root .
```

V3.2 的目标是把 UI 从“只读状态面板”推进到第一个受控操作面：用户可以在 Source Library 中提交一个 source 导入请求，并看到该导入任务的 pending、running、applied、failed 状态。V3.2 不解决批量导入和论文规模化处理；它只为 V4 的 batch queue 建立最小、可审计、可扩展的 job visibility 基础。

## 2. Goals

V3.2 must provide:

- Source Library 页面增强；
- UI add source form；
- 单 source 导入 job；
- job 状态可视化；
- job 与 existing `add_and_process_source` pipeline 的安全接线；
- sanitized parser/LLM/apply failure display；
- latest job / latest run 与 source summary 的关联；
- UI API 中清晰区分 read-only GET 和 mutating POST；
- 一个可以被 V4 batch queue 扩展的本地 job state model。

V3.2 的用户目标是：

> 用户可以在本地 UI 中输入一个 PDF/Markdown/text/URL source，点击 Add，看到任务运行状态，并在失败时看到脱敏、可行动的错误原因。

## 3. Non-Goals

V3.2 does not implement:

- batch import；
- folder import；
- drag-and-drop upload；
- browser native file picker integration；
- pause/resume/cancel；
- concurrent job execution；
- retry queue；
- ask UI；
- synthesis UI；
- claim/evidence browser；
- new PDF parser features；
- table/figure/formula evidence upgrades；
- new catalog schema；
- new page types；
- cloud sync；
- multi-user permissions。

V3.2 may expose a single-source add action, but it must not become an ad hoc batch runner.

## 4. Scope Decision

V3.2 should support source input as a text field:

```text
docs/papers/2404.07972.pdf
F:\LLMWiki\docs\papers\2404.07972.pdf
https://example.com/source.html
```

This is intentionally simpler than a browser file upload. A local browser usually cannot safely provide full local file paths through a standard file picker, and implementing upload/copy semantics would complicate raw source ownership. V3.2 keeps the same source identity model as CLI: the UI asks the local service to run the existing `add` pipeline against a source path or URL.

V4 may add folder selection, batch import, source sets, and durable import queues.

## 5. Recommended Architecture

Extend the V3.1 local UI service:

```text
Browser UI
-> Local UI API
-> UI job service
-> existing add_and_process_source(...)
-> staging/apply/catalog/wiki
```

New package additions:

```text
src/llmwiki/ui/
  jobs.py
  actions.py
```

Existing files extended:

```text
src/llmwiki/ui/api.py
src/llmwiki/ui/server.py
src/llmwiki/ui/models.py
src/llmwiki/ui/static/index.html
src/llmwiki/ui/static/app.js
src/llmwiki/ui/static/styles.css
```

Suggested responsibilities:

- `jobs.py`: job dataclasses, persisted job state, job store, status transitions.
- `actions.py`: action layer that validates requests and starts source-add jobs.
- `api.py`: read-only aggregations plus job listing/status helpers.
- `server.py`: GET and POST routes, action-token enforcement, HTTP JSON envelope.
- static UI: add source form, job list, source list refresh.

V3.2 should not shell out to the CLI for add. It should call the existing Python API:

```python
add_and_process_source(root, source_input, parser_backend=None, parser_output_dir=None)
```

The existing pipeline remains the only path that writes generated knowledge. UI must not write wiki pages, catalog rows, claims, or patches directly.

## 6. Job State Model

V3.2 should introduce a small local job state directory:

```text
state/ui-jobs/
  <job-id>.json
```

This is generated local state and must be gitignored.

No SQLite schema change is needed in V3.2.

### Job Fields

Each job JSON uses:

```json
{
  "schema_version": "ui_job.v3.2",
  "job_id": "job_20260602_123456_ab12cd34",
  "job_type": "add_source",
  "status": "pending",
  "source_input": "docs/papers/2404.07972.pdf",
  "source_kind": "local_path",
  "requested_parser": null,
  "created_at": "2026-06-02T12:34:56+08:00",
  "started_at": null,
  "finished_at": null,
  "source_id": "",
  "run_id": "",
  "stage": "queued",
  "result": {},
  "failure_stage": "",
  "failure_reason": "",
  "warnings": []
}
```

Allowed status values:

- `pending`
- `running`
- `applied`
- `failed`
- `interrupted`

`applied` means the existing `add_and_process_source` pipeline returned success and apply completed. It does not mean the UI wrote wiki/catalog directly.

If the UI server starts and finds jobs marked `running` from a previous process, it should mark them `interrupted` with a warning:

```text
Previous UI process exited before this job reported completion.
```

This avoids pretending that stale jobs are still running.

## 7. Execution Model

V3.2 should use a single in-process worker thread for UI jobs.

Rules:

- only one add job runs at a time；
- additional jobs may stay `pending` or be rejected with `job_queue_busy`；
- implementation should choose one behavior and document it in API responses；
- recommended first version: allow a small FIFO queue but execute sequentially；
- no parallel `add_and_process_source` calls；
- no cancellation in V3.2。

Sequential execution is important because `add/apply` mutates shared workspace state. V4 can later replace this with a richer persistent queue.

## 8. Action Security

V3.1 was read-only. V3.2 introduces mutating POST routes, so it must add a basic local action-token boundary.

Recommended model:

- server generates a random action token on startup；
- `GET /api/session` returns non-secret session metadata and action token for the local UI；
- POST routes require header:

```text
X-LLMWiki-UI-Token: <token>
```

- no permissive CORS headers are added；
- POST requests without the token return `403`。

This is not a full multi-user auth system. It is a local CSRF guard for a browser UI bound to `127.0.0.1`.

## 9. API Surface

V3.2 keeps all V3.1 APIs:

```text
GET /api/status
GET /api/sources
GET /api/runs
GET /api/pages
GET /api/config
```

New APIs:

```text
GET  /api/session
GET  /api/jobs
GET  /api/jobs/<job-id>
POST /api/sources/add
```

All responses use:

```json
{
  "schema_version": "ui.v3.2"
}
```

### `GET /api/session`

Returns:

- schema version；
- workspace root；
- UI server version；
- action token；
- supported actions。

The action token is only for local UI POSTs. It is not an API key and must not be written to workspace files.

### `GET /api/jobs`

Returns recent UI jobs:

- job id；
- type；
- status；
- source input summary；
- source id；
- run id；
- stage；
- timestamps；
- sanitized failure reason；
- warnings。

### `GET /api/jobs/<job-id>`

Returns full bounded job details, excluding raw prompts, raw LLM outputs, parser logs, API keys, and arbitrary file contents.

### `POST /api/sources/add`

Request:

```json
{
  "source": "docs/papers/2404.07972.pdf",
  "parser": null
}
```

Allowed `parser` values:

- `null` or `""`: use workspace default；
- `"auto"`；
- `"pypdf"`；
- `"mineru"`。

V3.2 should not expose `parser_output_dir` in the normal UI. Precomputed parser output remains a debug CLI surface.

Response:

```json
{
  "schema_version": "ui.v3.2",
  "job": {
    "job_id": "job_...",
    "status": "pending"
  }
}
```

Validation:

- empty source is rejected；
- control characters are rejected；
- `config/api-keys.toml` is rejected；
- directories are rejected in V3.2；
- unsupported parser value is rejected；
- source path errors are returned as sanitized job failure or immediate validation error；
- URLs are allowed only for `http://` and `https://` if existing CLI source import supports them。

## 10. UI Changes

V3.2 should turn the V3.1 dashboard into a Source Library page.

### Add Source Panel

Fields:

- source path or URL；
- parser mode: default / auto / pypdf / mineru strict；
- submit button；
- validation message。

Text should be operational, not instructional marketing. Example:

```text
Source path or URL
Parser
Add source
```

### Job Strip

Shows current active job:

- source；
- status；
- stage；
- elapsed time；
- failure reason if failed；
- latest warning。

### Jobs Table

Columns:

- job id；
- source；
- status；
- stage；
- run id；
- created/finished；
- failure。

### Source Table Enhancements

Source list should show:

- source id；
- title；
- source type；
- latest job status；
- latest run status；
- parser backend；
- fallback；
- sidecar completeness。

### Refresh Behavior

The UI should poll while there are pending/running jobs.

Recommended:

- normal refresh interval: manual refresh only；
- when active job exists: poll `/api/jobs` every 2 seconds；
- after job completes: refresh `/api/status`, `/api/sources`, `/api/runs`, `/api/pages`。

## 11. Failure Handling

All failures must be visible and sanitized.

Failure examples:

- source path not found；
- URL fetch failure；
- MinerU unavailable in explicit `mineru` mode；
- parser failed and auto fallback also failed；
- LLM ingest malformed output after repair failure；
- apply safety validation failed；
- catalog write failed。

The job should record:

- `failure_stage`；
- `failure_reason`；
- `warnings`；
- related `run_id` if a staging run exists。

Do not expose:

- API key values；
- `config/api-keys.toml` contents；
- raw LLM prompts；
- raw LLM responses；
- full parser stdout/stderr；
- full stack traces。

The UI may show a suggested debug command, but it must be bounded and non-secret:

```bash
llmwiki review <run-id> --root . --detail
```

## 12. Source Identity And Duplicates

V3.2 should not create a new duplicate-detection system. It should surface existing source status and existing catalog/source uniqueness behavior.

If `add_and_process_source` reports already imported / duplicate / unchanged source behavior, the UI job should record that as a successful or no-op result according to the pipeline's existing semantics.

The UI should display:

- source id when known；
- latest run id when known；
- duplicate/no-op warning if available。

## 13. Read/Write Boundary

V3.2 changes the UI boundary:

- GET endpoints remain read-only。
- POST `/api/sources/add` is explicitly mutating。
- The only mutation allowed by V3.2 is creating/updating UI job state and invoking the existing source add pipeline.
- The add pipeline may write `sources/`, `staging/`, `wiki/`, `state/catalog.sqlite`, and `wiki/log.md` through existing validation/apply code.
- UI code must not directly mutate formal wiki/catalog data.

Tests must verify that GET routes still do not mutate workspace files.

Tests must also verify that POST routes call only the approved action path.

## 14. Testing Strategy

Suggested test files:

- `tests/test_ui_jobs.py`
- `tests/test_ui_actions.py`
- `tests/test_ui_server_actions.py`
- `tests/test_ui_static.py`
- `tests/test_ui_readonly.py`
- `tests/test_ui_cli.py`

Required coverage:

- job JSON roundtrip；
- old/malformed job files become warnings, not crashes；
- server startup marks stale running jobs as interrupted；
- POST without action token returns 403；
- POST with token creates an add job；
- worker calls `add_and_process_source` exactly once per job；
- worker records success source id/run id；
- worker records sanitized failure；
- only one job runs at a time；
- GET endpoints remain read-only；
- UI static JS calls `/api/session`, `/api/jobs`, and `/api/sources/add`；
- static files contain no secret markers；
- CLI help remains stable。

Integration tests can monkeypatch `add_and_process_source` to avoid real LLM calls. V3.2 tests must not depend on real DeepSeek, embedding provider, MinerU, or network.

## 15. Acceptance Criteria

V3.2 is complete when:

- user can open `llmwiki ui --root .`；
- UI displays source library and job list；
- user can submit a single source path or URL from UI；
- a job is created and visible as pending/running/applied/failed；
- successful add uses the existing pipeline and produces normal source/run/catalog/wiki outputs；
- failed add shows sanitized error details；
- API keys and secret config are not exposed；
- GET endpoints stay read-only；
- POST action requires local UI token；
- concurrent source add jobs do not run in parallel；
- all existing add/retrieve/ask/parser tests continue passing；
- generated `.test-workspaces`, `.pytest_cache`, `.tmp`, and source/wiki/staging/state caches are cleaned after verification。

## 16. Deferred To Later V3/V4

Deferred to V3.3:

- ask UI；
- cited answer display；
- query plan diagnostics；
- synthesis preview/writeback UI。

Deferred to V3.4:

- claim browser；
- evidence inspector；
- relationship view。

Deferred to V3.5:

- UI-triggered lint/eval/pdf-quality execution and result dashboards。

Deferred to V4:

- batch import；
- folder import；
- pause/resume/cancel；
- durable long-running queue；
- retry/skip for corpus processing；
- corpus-level PDF parser acceptance；
- paper-level page types and research structures。

## 17. Open Decisions For Implementation Plan

The implementation plan should choose exact defaults for:

- whether the worker accepts a FIFO queue or rejects new jobs while one is active；
- max retained job files；
- whether job ids use timestamp/hash or UUID；
- how to derive stage updates from `add_and_process_source` if it does not expose progress callbacks；
- whether `POST /api/sources/add` returns immediately after enqueue or waits for validation-only completion；
- whether UI should expose parser selection in a collapsed advanced section or simple select。

Recommended defaults:

- use FIFO queue with one active worker；
- retain latest 200 job files；
- use timestamp plus short random suffix for job ids；
- stage starts as `queued`, then `running`, then final status；
- return immediately after enqueue；
- expose parser select with default option first。

## 18. Implementation Notes

V3.2 should be implemented in small commits:

1. job model and persistence；
2. action-token and POST routing；
3. source add action and worker；
4. UI job/add-source components；
5. docs and safety tests。

Do not implement V3.3 ask UI in the same plan.
