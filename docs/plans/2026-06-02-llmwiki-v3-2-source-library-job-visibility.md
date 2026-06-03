# LLMWiki V3.2 Source Library And Job Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use TDD: write failing tests first, verify failure, implement, verify pass, then commit. Split commits by feature/function.

**Goal:** Extend the V3.1 read-only dashboard into a Source Library UI that can enqueue one source import job and show pending/running/applied/failed/interrupted status.

**Architecture:** Add a small `state/ui-jobs/` JSON job store, a FIFO in-process worker, a source-add action layer, and V3.2 HTTP routes on top of the existing UI server. The worker calls the existing `add_and_process_source(...)` pipeline; UI code never writes formal wiki/catalog knowledge directly.

**Tech Stack:** Python stdlib HTTP server, dataclasses, JSON files, existing `llmwiki` pipeline APIs, vanilla HTML/CSS/JS, pytest monkeypatch tests.

---

## Summary

目标是把 V3.1 只读 dashboard 扩展为 V3.2 Source Library + Job Visibility：用户可以在本地 UI 中提交单个 source path/URL，系统创建 `add_source` UI job，用一个本地 FIFO worker 顺序调用现有 `add_and_process_source(...)`，并在 UI/API 中展示 pending/running/applied/failed/interrupted 状态。

V3.2 不做批量导入、Ask UI、synthesis UI、claim browser、新 PDF 能力或新数据库表。所有 formal knowledge 写入仍必须通过现有 add/ingest/staging/apply pipeline；UI 不能直接写 wiki/catalog。

关键默认决策：

- Job state 存在 `state/ui-jobs/<job-id>.json`。
- Job schema 为 `ui_job.v3.2`，API schema 升到 `ui.v3.2`。
- 单 worker FIFO queue；不并发执行 `add_and_process_source`。
- Job id 使用 timestamp + short random suffix。
- 保留最近 200 个 job 文件。
- `POST /api/sources/add` 校验后立即 enqueue 返回。
- parser 选择用简单 select：default / auto / pypdf / mineru。
- `GET` endpoint 保持只读；只有 `POST /api/sources/add` 是 mutating。
- POST 需要 server 启动时生成的 `X-LLMWiki-UI-Token`。

## Implementation Tasks

### Task 1: Save Implementation Plan

- [ ] 新建 `docs/plans/2026-06-02-llmwiki-v3-2-source-library-job-visibility.md`，内容使用本 plan。
- [ ] 运行 `git status --short`，预期只新增 plan 文件。
- [ ] 提交：`git add docs/plans/2026-06-02-llmwiki-v3-2-source-library-job-visibility.md && git commit -m "docs: 保存 V3.2 执行计划"`

### Task 2: UI Job Model And Persistence

- [ ] 新建 `tests/test_ui_jobs.py`，先写失败测试：
  - `UiJob.to_dict()` 输出稳定字段，`schema_version="ui_job.v3.2"`。
  - `create_add_source_job(root, "docs/papers/a.pdf", parser="auto")` 生成 `pending/queued` job。
  - job 文件写入 `state/ui-jobs/<job-id>.json`。
  - `load_jobs(root)` 按 `created_at` 倒序返回。
  - malformed job JSON 变成 warning，不 crash。
  - `mark_stale_running_jobs_interrupted(root)` 把旧 `running` job 改成 `interrupted`。
  - `prune_jobs(root, keep=200)` 只保留最近 200 个 job。
  - output 不包含 `sk-` 或 `config/api-keys.toml`。
- [ ] 新建 `src/llmwiki/ui/jobs.py`：
  - `UI_JOB_SCHEMA_VERSION = "ui_job.v3.2"`
  - `UiJob`
  - `UiJobStore`
  - `create_add_source_job(...)`
  - `load_jobs(...)`
  - `save_job(...)`
  - `update_job(...)`
  - `mark_stale_running_jobs_interrupted(...)`
  - `prune_jobs(...)`
- [ ] 修改 `.gitignore` 增加 `state/ui-jobs/`。
- [ ] 修改 `src/llmwiki/workspace.py` 初始化 `state/ui-jobs` 目录。
- [ ] 修改 `src/llmwiki/maintenance/clean.py`，让 `--scope generated/all` 清理 `state/ui-jobs/*` 并保留目录。
- [ ] 运行：
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_jobs.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_regression_samples.py::test_gitignore_excludes_generated_workspace_content -q`
- [ ] 提交：`git add .gitignore src/llmwiki/workspace.py src/llmwiki/maintenance/clean.py src/llmwiki/ui/jobs.py tests/test_ui_jobs.py tests/test_regression_samples.py && git commit -m "feat: 增加 UI job 持久化模型"`

### Task 3: Source Add Action Validation

- [ ] 新建 `tests/test_ui_actions.py`，先写失败测试：
  - empty source 返回 validation error。
  - source 包含控制字符返回 validation error。
  - `config/api-keys.toml` 被拒绝。
  - directory source 在 V3.2 被拒绝。
  - parser 只允许 `None/""/auto/pypdf/mineru`。
  - `http://` 和 `https://` URL 被接受。
  - local file path 被接受。
  - validation error 脱敏，不包含 secret。
- [ ] 新建 `src/llmwiki/ui/actions.py`：
  - `UiActionError`
  - `AddSourceRequest`
  - `validate_add_source_request(root, payload)`
  - `enqueue_add_source_job(root, payload, job_manager)`
- [ ] 行为：
  - payload 必须是 JSON object。
  - `source` trim 后非空。
  - relative path 按 workspace root 解释；absolute path 允许，但只作为 locator 传给 existing pipeline。
  - directory path 立即拒绝。
  - 不读取 raw PDF 内容，不运行 parser/LLM。
- [ ] 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_actions.py tests/test_ui_jobs.py -q`
- [ ] 提交：`git add src/llmwiki/ui/actions.py tests/test_ui_actions.py && git commit -m "feat: 增加 UI add source action 校验"`

### Task 4: Job Worker And Pipeline Bridge

- [ ] 扩展 `tests/test_ui_actions.py` 或新增 `tests/test_ui_job_worker.py`：
  - worker 调用 `add_and_process_source(root, source, parser_backend=parser_or_none)` exactly once。
  - success 后 job 为 `applied`，记录 `source_id/run_id/result`。
  - duplicate/already_applied 结果仍记录为成功状态，result 中保留 pipeline status。
  - `AddPipelineError(stage="ingest", reason="sk-secret config/api-keys.toml")` 后 job 为 `failed`，failure reason 脱敏。
  - unexpected exception 后 job 为 `failed`，不含 traceback/secret。
  - 同一时刻只执行一个 job；第二个 pending 等前一个完成。
  - job result 不保存 raw prompt/raw LLM response/full parser logs。
- [ ] 在 `src/llmwiki/ui/jobs.py` 实现：
  - `UiJobManager`
  - `start()`
  - `stop()`
  - `enqueue(job)`
  - `run_pending_once()` 测试入口
  - FIFO queue + worker thread
- [ ] 在 `src/llmwiki/ui/actions.py` 接入 worker：`run_add_source_job(root, job)`。
- [ ] 实现 stage：queued -> running -> applied/failed；没有 pipeline callback 前不伪造细粒度 parser/LLM/apply progress。
- [ ] 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_actions.py tests/test_ui_jobs.py -q`
- [ ] 提交：`git add src/llmwiki/ui/actions.py src/llmwiki/ui/jobs.py tests/test_ui_actions.py tests/test_ui_jobs.py && git commit -m "feat: 增加 UI source add job worker"`

### Task 5: UI API Job Endpoints

- [ ] 扩展 `tests/test_ui_api.py`：
  - `list_ui_jobs(root)` 返回 job summaries。
  - `get_ui_job(root, job_id)` 返回单个 bounded job。
  - malformed job file 进入 warnings。
  - existing `/api/sources` source summary 增加 `latest_job_id/latest_job_status`。
  - API schema 从 `ui.v3.1` 升到 `ui.v3.2`。
- [ ] 修改 `src/llmwiki/ui/models.py`：
  - `UI_SCHEMA_VERSION = "ui.v3.2"`
  - 新增 `JobSummary`
  - `SourceSummary` 增加 `latest_job_id/latest_job_status`
- [ ] 修改 `src/llmwiki/ui/api.py`：
  - `list_ui_jobs(root, limit=100)`
  - `get_ui_job(root, job_id)`
  - `latest_job_by_source_input(...)` 或按 `source_id` 关联 latest job。
- [ ] 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_api.py tests/test_ui_jobs.py -q`
- [ ] 提交：`git add src/llmwiki/ui/models.py src/llmwiki/ui/api.py tests/test_ui_api.py && git commit -m "feat: 增加 UI job 查询 API"`

### Task 6: HTTP Session Token And POST Routes

- [ ] 新建 `tests/test_ui_server_actions.py`，先写失败测试：
  - `GET /api/session` 返回 `schema_version="ui.v3.2"`、action token、supported actions。
  - `GET /api/jobs` 返回 JSON。
  - `GET /api/jobs/<job-id>` 返回 JSON 或 404。
  - `POST /api/sources/add` 无 token 返回 403。
  - wrong token 返回 403。
  - valid token + valid payload enqueue job。
  - invalid JSON 返回 400 JSON。
  - route 不加 permissive CORS header。
  - POST failure response 不含 stack trace、`sk-`、`config/api-keys.toml`。
- [ ] 修改 `src/llmwiki/ui/server.py`：
  - `UiServerConfig` 增加 `action_token: str | None = None`
  - `create_ui_server` 生成 token 和 `UiJobManager`
  - `do_POST`
  - `read_json_body(handler, max_bytes=65536)`
  - `require_action_token(handler, token)`
  - `write_api` 支持 `/api/session`、`/api/jobs`、`/api/jobs/<id>`
  - `write_post_api` 支持 `/api/sources/add`
  - server shutdown 时 stop worker。
- [ ] 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_server_actions.py tests/test_ui_server.py tests/test_ui_api.py -q`
- [ ] 提交：`git add src/llmwiki/ui/server.py tests/test_ui_server_actions.py tests/test_ui_server.py && git commit -m "feat: 增加 UI job HTTP API"`

### Task 7: Static Source Library UI

- [ ] 扩展 `tests/test_ui_static.py`：
  - `index.html` 包含 add source form。
  - `app.js` 请求 `/api/session`、`/api/jobs`、`/api/sources/add`。
  - `app.js` 发送 `X-LLMWiki-UI-Token`。
  - parser select 包含 default/auto/pypdf/mineru。
  - UI 有 jobs table 和 active job strip。
  - static files 不含 `sk-`、`config/api-keys.toml`。
- [ ] 修改：
  - `src/llmwiki/ui/static/index.html`
  - `src/llmwiki/ui/static/app.js`
  - `src/llmwiki/ui/static/styles.css`
- [ ] UI 行为：
  - 页面第一屏仍是 dashboard/source library，不做 marketing hero。
  - Add source 表单提交后立即显示 job。
  - pending/running job 存在时每 2 秒轮询 `/api/jobs`。
  - job 完成后刷新 status/sources/runs/pages。
  - errors 显示在 warnings panel，必须 escape HTML。
- [ ] 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_static.py tests/test_ui_server_actions.py -q`
- [ ] 提交：`git add src/llmwiki/ui/static/index.html src/llmwiki/ui/static/app.js src/llmwiki/ui/static/styles.css tests/test_ui_static.py && git commit -m "feat: 增加 Source Library job UI"`

### Task 8: Read-Only And Mutating Boundary Tests

- [ ] 扩展 `tests/test_ui_readonly.py`：
  - 所有 GET routes，包括 `/api/session`、`/api/jobs`、`/api/jobs/<id>`，不改变 `wiki/`、`sources/`、`staging/`、`state/catalog.sqlite`。
  - GET routes 不调用 `add_and_process_source`、LLM provider、embedding provider、MinerU command、lint/eval。
- [ ] 新增 `tests/test_ui_mutation_boundary.py`：
  - `POST /api/sources/add` 只允许创建 `state/ui-jobs` job file 并调用 job manager。
  - worker mutation 只通过 monkeypatched `add_and_process_source`。
  - UI server/action layer 不直接调用 `apply_run`、`ingest_source`、`import_source`。
- [ ] 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_readonly.py tests/test_ui_mutation_boundary.py -q`
- [ ] 提交：`git add tests/test_ui_readonly.py tests/test_ui_mutation_boundary.py && git commit -m "test: 固定 V3.2 UI 读写边界"`

### Task 9: CLI And Server Lifecycle Regression

- [ ] 扩展 `tests/test_ui_cli.py`：
  - `llmwiki ui --root . --no-open` starts server with job manager。
  - CLI help still shows `ui  Start the local dashboard UI.`
  - UI command does not directly call add/ingest/apply/lint/eval/LLM/embedding/MinerU before POST。
- [ ] 如需要，为 `serve_ui` 增加 graceful stop 测试 hook，但不要改变用户 CLI 行为。
- [ ] 运行：
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_cli.py tests/test_scaffold.py -q`
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki --help`
- [ ] 提交：`git add src/llmwiki/ui/server.py tests/test_ui_cli.py tests/test_scaffold.py && git commit -m "test: 固定 V3.2 UI CLI 生命周期"`

### Task 10: Docs And Agent Contract

- [ ] 修改 `README.md`：
  - V3.2 Source Library 说明。
  - `llmwiki ui --root .` 可从 UI 添加单个 source。
  - job state 位于 `state/ui-jobs/`，是 generated local state。
  - `POST /api/sources/add` 是唯一 V3.2 mutating UI endpoint。
  - 批量导入仍 deferred to V4。
- [ ] 修改 `AGENTS.md`：
  - GET endpoints remain read-only。
  - POST `/api/sources/add` may invoke existing add pipeline only。
  - UI job state is generated cache and must be cleaned after tests/acceptance。
  - UI must not directly write formal wiki/catalog data。
  - UI must not add batch queue or Ask UI outside later specs。
- [ ] 修改 `tests/test_regression_samples.py` 文档断言：
  - 包含 `state/ui-jobs/`
  - 包含 `POST /api/sources/add`
  - 包含 `V3.2 Source Library`
- [ ] 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_regression_samples.py -q`
- [ ] 提交：`git add README.md AGENTS.md tests/test_regression_samples.py && git commit -m "docs: 更新 V3.2 source library 说明"`

### Task 11: Verification And Manual Smoke

- [ ] 分组验证：
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_jobs.py tests/test_ui_actions.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_api.py tests/test_ui_server.py tests/test_ui_server_actions.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_static.py tests/test_ui_readonly.py tests/test_ui_mutation_boundary.py tests/test_ui_cli.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_add_pipeline.py tests/test_ask_workflow.py tests/test_retrieval.py -q`
- [ ] 全量验证：
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki --help`
- [ ] Manual smoke：
  - start server in a short test helper；
  - call `/api/session`；
  - POST `/api/sources/add` with a monkeypatched or minimal safe test source only in a temp workspace；
  - verify `/api/jobs` shows job status。
- [ ] 清理：
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki clean --scope all --root .`
  - confirm `git status --short --ignored` does not include `.test-workspaces`、`.pytest_cache`、`.tmp`、generated source/wiki/staging/state/vector files、`state/ui-jobs/` contents、`config/api-keys.toml`。
- [ ] 如有遗漏提交：`git commit -m "feat: 完成 V3.2 source library job visibility"`

## Test Scenarios

- Empty initialized workspace can open UI and show empty jobs.
- UI can enqueue a single source add job with valid token.
- Missing/invalid token is rejected with 403.
- Invalid source input is rejected before worker runs.
- Worker records success from `add_and_process_source`.
- Worker records sanitized failure from `AddPipelineError`.
- Stale running jobs become interrupted on server startup.
- Multiple jobs are executed sequentially, never concurrently.
- GET endpoints remain read-only and do not call provider/runtime work.
- POST add path is the only mutating UI endpoint.
- Static dashboard polls jobs while pending/running.
- Existing CLI/add/retrieve/ask/parser tests continue passing.
- No tests require real DeepSeek, embedding provider, MinerU, or network.

## Assumptions And Defaults

- V3.2 uses stdlib HTTP server and vanilla JS; no Node/Vite/React.
- `state/ui-jobs/` is generated local state, ignored by git and cleaned by `llmwiki clean --scope generated/all`.
- No SQLite schema change.
- No source upload semantics; user enters a path or URL string.
- No batch/folder import in V3.2.
- No cancellation/retry/pause/resume.
- No fine-grained parser/LLM/apply progress until pipeline exposes callbacks.
- `POST /api/sources/add` returns immediately after enqueue.
- Server action token is generated per process and not persisted.
- Existing pipeline remains the only code path allowed to write formal wiki/catalog knowledge.
