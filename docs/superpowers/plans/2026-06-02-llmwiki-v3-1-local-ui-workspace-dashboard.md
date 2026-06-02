# LLMWiki V3.1 Local UI And Workspace Dashboard Implementation Plan

## Summary

目标是实现 `llmwiki ui --root .`：启动一个绑定 `127.0.0.1` 的本地只读 Web dashboard，用 Python service 直接读取 workspace、catalog、staging、sidecars 和配置状态。V3.1 不执行 add/ingest/apply/ask/lint/eval/MinerU/embedding provider，不写 wiki/catalog/source/staging/state。

计划文件目标路径：`docs/superpowers/plans/2026-06-02-llmwiki-v3-1-local-ui-workspace-dashboard.md`。

## Key Changes

- 新增 `src/llmwiki/ui/`：
  - `models.py`：响应 dataclass、`to_dict()`、secret/path sanitization。
  - `api.py`：只读 API 聚合函数：workspace status、sources、runs、pages、config。
  - `server.py`：stdlib `ThreadingHTTPServer` 路由 `/`、static assets、`/api/*`。
  - `static/index.html`、`static/app.js`、`static/styles.css`：单页 dashboard。
- 修改 `src/llmwiki/cli.py`：
  - `COMMANDS` 增加 `ui`。
  - 新增 `cmd_ui`。
  - `llmwiki ui --root . --host 127.0.0.1 --port 8765 --no-open`。
- API schema：
  - `/api/status`
  - `/api/sources`
  - `/api/runs`
  - `/api/pages`
  - `/api/config`
  - 所有响应包含 `schema_version = "ui.v3.1"`。
- 安全边界：
  - 不返回 API key、`config/api-keys.toml` 内容、raw prompt、raw LLM response、完整 parser logs。
  - 不自动运行 LLM、embedding、MinerU、parser、lint、eval、add、ingest、apply、clean。
  - dashboard/API 默认只读。

## Implementation Tasks

### Task 1: 保存执行计划

- 新建 `docs/superpowers/plans/2026-06-02-llmwiki-v3-1-local-ui-workspace-dashboard.md`，内容使用本 plan。
- 运行 `git status --short`，确认只新增计划文件。
- 提交：`docs: 保存 V3.1 UI dashboard 执行计划`。

### Task 2: UI API models 与 sanitization

- 新建 `tests/test_ui_api.py`，先写失败测试：
  - `sanitize_ui_error("sk-abc config/api-keys.toml")` 不包含 `sk-` 和 `config/api-keys.toml`。
  - response dataclass `to_dict()` 输出稳定 dict。
  - relative workspace paths 只显示 workspace 内相对路径，workspace 外路径显示为 `[outside-workspace]`。
- 新建 `src/llmwiki/ui/models.py`：
  - `UiWarning(level, message, category="general")`
  - `WorkspaceStatusResponse`
  - `SourceSummary`
  - `RunSummary`
  - `PageSummary`
  - `ConfigStatusResponse`
  - `sanitize_ui_text(text, max_chars=500)`
  - `workspace_relative_path(root, path)`
- 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_api.py -q`
- 提交：`feat: 增加 UI API 响应模型`

### Task 3: 只读 workspace status API

- 扩展 `tests/test_ui_api.py`：
  - initialized empty workspace 返回 `status="initialized_empty"`。
  - missing skeleton 返回 `status="not_initialized"`。
  - catalog 存在且有 rows 返回 `status="ready"`。
  - missing catalog 对 `/api/status` 不是 fatal。
  - monkeypatch `create_provider`、embedding provider、MinerU runner、`add_and_process_source`、`apply_run`、`lint_workspace`，若被调用测试失败。
- 新建 `src/llmwiki/ui/api.py`：
  - `get_workspace_status(root) -> WorkspaceStatusResponse`
  - 使用 `check_workspace`、`catalog_path`、SQLite read-only queries、`schema_status`。
  - 统计 `sources/claims/pages/relationships/ingest_runs` counts；不存在表时 warnings。
- 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_api.py -q`
- 提交：`feat: 增加只读 workspace dashboard API`

### Task 4: sources/runs/pages/config API

- 扩展 `tests/test_ui_api.py`：
  - `/sources` 风格函数返回 source id/title/type/latest run/parser sidecar summary。
  - `/runs` 返回 recent staging/catalog run summary，failure reason 脱敏截断。
  - `/pages` 返回 page id/title/type/path/claim count。
  - `/config` 只返回 key presence，不返回 key value。
  - malformed sidecar 产生 warning，不 crash。
- 在 `src/llmwiki/ui/api.py` 实现：
  - `list_sources(root, limit=100)`
  - `list_runs(root, limit=50)`
  - `list_pages(root, limit=200)`
  - `get_config_status(root)`
- `get_config_status` 使用：
  - `load_llm_config`
  - `load_embedding_config`
  - `load_pdf_parser_config`
  - `probe_mineru_status`
  - `vector_index_status`
  - 只检查 `config/api-keys.toml` 是否存在及 section key 是否非空，不返回内容。
- 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_api.py -q`
- 提交：`feat: 增加 UI source run page config API`

### Task 5: Local HTTP server

- 新建 `tests/test_ui_server.py`。
- 覆盖：
  - server 可绑定空闲 localhost port。
  - `GET /api/status` 返回 JSON。
  - `GET /api/unknown` 返回 404 JSON。
  - `GET /` 返回 HTML。
  - `GET /static/app.js` 返回 JS。
  - API error 不包含 stack trace。
- 新建 `src/llmwiki/ui/server.py`：
  - `UiServerConfig(root, host="127.0.0.1", port=8765)`
  - `find_available_port(host, preferred_port)`
  - `create_ui_server(config) -> ThreadingHTTPServer`
  - `serve_ui(root, host, port, open_browser=True)`
  - 路由只支持 `GET`。
- 静态目录读取限制在 `src/llmwiki/ui/static/` 内；禁止路径穿越。
- 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_server.py tests/test_ui_api.py -q`
- 提交：`feat: 增加本地 UI HTTP server`

### Task 6: Dashboard static UI

- 新建 `tests/test_ui_static.py`。
- 覆盖：
  - `index.html` 引用 `app.js` 和 `styles.css`。
  - 页面包含 dashboard root 容器。
  - JS 请求 `/api/status`、`/api/sources`、`/api/runs`、`/api/pages`、`/api/config`。
  - 静态文件不包含 `config/api-keys.toml`、`sk-`。
- 新建：
  - `src/llmwiki/ui/static/index.html`
  - `src/llmwiki/ui/static/app.js`
  - `src/llmwiki/ui/static/styles.css`
- UI 内容：
  - header：workspace root、status、refresh。
  - cards：sources、claims、pages、latest run、parser、LLM、embedding/vector。
  - tables：sources、recent runs、wiki pages。
  - warnings panel。
  - no hero/marketing page；第一屏就是 dashboard。
- 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_static.py tests/test_ui_server.py -q`
- 提交：`feat: 增加 V3.1 dashboard 静态界面`

### Task 7: CLI `llmwiki ui`

- 新建 `tests/test_ui_cli.py`。
- 覆盖：
  - `build_parser()` 包含 `ui`。
  - `llmwiki ui --root . --no-open` 调用 `serve_ui(..., open_browser=False)`。
  - `--host`、`--port` 参数传递正确。
  - CLI 不调用 add/ingest/apply/lint/eval/MinerU/LLM/embedding provider。
  - `python -m llmwiki --help` 显示 `ui  Start the local dashboard UI.`。
- 修改 `src/llmwiki/cli.py`：
  - `COMMANDS` 加 `ui`。
  - `cmd_ui(args)` 调 `serve_ui(Path(args.root).resolve(), args.host, args.port, open_browser=not args.no_open)`。
  - parser 增加 `ui` 子命令。
- 运行：
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_cli.py tests/test_scaffold.py -q`
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki --help`
- 提交：`feat: 增加 llmwiki ui 命令`

### Task 8: Read-only mutation guard

- 扩展 `tests/test_ui_api.py` 或新增 `tests/test_ui_readonly.py`。
- 记录 API 调用前后这些路径的 fingerprints：
  - `state/catalog.sqlite`
  - `wiki/index.md`
  - `wiki/log.md`
  - `staging/`
  - `sources/`
- 调用 UI API functions 和 HTTP `/api/*`。
- 断言 fingerprints 不变。
- monkeypatch 禁止：
  - `llmwiki.ingestion.pipeline.add_and_process_source`
  - `llmwiki.ingestion.ingest.ingest_source`
  - `llmwiki.ingestion.apply.apply_run`
  - `llmwiki.lint.lint_workspace`
  - `llmwiki.retrieval.eval.evaluate_retrieval`
  - `llmwiki.pdf.quality.evaluate_pdf_quality`
  - `llmwiki.pdf.mineru_runner.run_mineru_command`
  - `llmwiki.llm.create_provider`
  - `llmwiki.vector.embeddings.create_embedding_provider`
- 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_readonly.py tests/test_ui_api.py tests/test_ui_server.py -q`
- 提交：`test: 固定 UI dashboard 只读边界`

### Task 9: README / AGENTS 更新

- 修改 `README.md`：
  - 增加 `llmwiki ui --root .`。
  - 说明 V3.1 dashboard 是只读 workspace/status UI。
  - 说明不会显示 API key，不运行 add/ask/lint/eval。
- 修改 `AGENTS.md`：
  - UI API 默认只读。
  - UI 不得绕过 staging/apply。
  - UI/status endpoint 不得调用 LLM、embedding provider、MinerU parser execution。
  - UI cache/test artifacts 跑后清理。
- 更新 `tests/test_regression_samples.py` 文档断言。
- 运行：`.\.venv\Scripts\python.exe -m pytest tests/test_regression_samples.py -q`
- 提交：`docs: 更新 V3.1 UI dashboard 说明`

### Task 10: Final verification and cleanup

- 分组验证：
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_api.py tests/test_ui_server.py tests/test_ui_static.py tests/test_ui_cli.py tests/test_ui_readonly.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_scaffold.py tests/test_regression_samples.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_add_pipeline.py tests/test_ask_workflow.py tests/test_retrieval.py -q`
- 全量验证：
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki --help`
- Manual smoke：
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki ui --root . --no-open --port 8765`
  - 另一个 shell 或测试 helper 访问 `http://127.0.0.1:8765/api/status`。
- 清理：
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m llmwiki clean --scope all --root .`
- 确认 `git status --short --ignored` 不包含 `.test-workspaces`、`.pytest_cache`、`.tmp`、generated source/wiki/staging/state/vector files、`config/api-keys.toml`。
- 如有遗漏，最终提交：`feat: 完成 V3.1 本地 UI dashboard`

## Test Scenarios

- Empty initialized workspace dashboard works.
- Existing catalog workspace dashboard works.
- Missing catalog is warning, not fatal.
- Malformed sidecar is warning, not fatal.
- Config API reports key presence but never key value.
- Parser/MinerU/embedding status checks are read-only and do not run real work.
- Static dashboard renders and calls the five API endpoints.
- `llmwiki ui --root . --no-open` starts server without opening browser.
- All UI API routes are read-only and do not mutate workspace files.
- Existing add/retrieve/ask/synthesis tests continue passing.

## Assumptions And Defaults

- Use stdlib HTTP server, static HTML/CSS/vanilla JS; no Node/Vite/React in V3.1.
- Server binds to `127.0.0.1` by default.
- Default port is `8765`; if occupied, server picks another available port and prints it.
- `--no-open` disables browser opening; default may call `webbrowser.open(url)`.
- V3.1 does not add source import UI, ask UI, synthesis UI, batch queue, or job persistence.
- V3.1 does not introduce new database tables.
- UI endpoints return JSON only and never expose secrets.
- Parser artifacts and diagnostics are shown only as diagnostics, not evidence.
