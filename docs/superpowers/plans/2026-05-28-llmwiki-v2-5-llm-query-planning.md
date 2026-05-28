# LLMWiki V2.5 LLM Query Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Use TDD: write failing tests first, verify failure, implement, verify pass, then commit.

## Summary

目标是实现 `ask` 的 planner-first 流程：`ask` 先调用配置好的 LLM 生成结构化 query plan，再把 plan 里的 subqueries 逐条交给本地 `retrieve_context` 执行，最后只基于本地 catalog 返回的 evidence 生成回答。`retrieve`、`query`、`eval retrieval` 继续保持本地、确定性、不调用 LLM。

## Key Changes

- 新增 `llmwiki/planner.py`：负责 planner prompt、JSON schema、解析、验证、repair 和安全失败。
- 新增 `llmwiki/planned_retrieval.py`：负责执行 planner subqueries、调用本地 `retrieve_context`、合并 contexts/relationships/warnings/diagnostics。
- 修改 `llmwiki/answer.py`：`answer_question` 改为 planner-first，新增 planning diagnostics 与 planner 失败状态。
- 修改 `llmwiki/cli.py`：human/JSON ask 输出增加 planning object，同时保持旧字段兼容。
- 更新 README 和 AGENTS：明确 planner output 不是 evidence，`retrieve/query/eval` 不调用 LLM，V2.5 不加领域规则。

## Implementation Tasks

### Task 1: Planner 数据结构与失败测试

- 新建 `tests/test_planner.py`。
- monkeypatch `llmwiki.planner.create_provider`，返回确定性 JSON。
- 覆盖 valid JSON、malformed JSON repair、repair 失败、未知 catalog refs、伪造 evidence 字段、secret 不泄露。
- 先跑 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_planner.py -q`，预期模块缺失失败。
- 提交：`test: 覆盖 V2.5 查询规划验证`。

### Task 2: 实现 `planner.py`

- 创建 `llmwiki/planner.py`。
- planner prompt 只包含用户问题、ask filters、bounded catalog overview、JSON schema 和安全规则。
- 不传 raw source 全文、API key、秘密配置。
- `validate_query_plan` 固定 schema/version/subquery/filter/catalog/evidence 字段规则。
- malformed JSON 一次 repair；仍失败则返回 invalid。
- 跑 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_planner.py -q`。
- 提交：`feat: 增加 LLM 查询规划器`。

### Task 3: Planned retrieval 执行层

- 新建 `tests/test_planned_retrieval.py`。
- 覆盖多 subquery 调用本地 `retrieve_context`、claim 去重、伪造 evidence 不进入结果、filters 传递、no evidence diagnostics。
- 新建 `llmwiki/planned_retrieval.py`。
- `execute_query_plan` 逐条调用 `retrieve_context`，按 subquery 顺序和 retrieve rank 合并，不做 rerank。
- 跑 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_planned_retrieval.py tests/test_planner.py -q`。
- 提交：`feat: 增加规划检索执行层`。

### Task 4: 接入 `ask` planner-first

- 修改 `tests/test_ask_workflow.py`，让 fake provider 支持 planner call + answer call。
- 覆盖 ask JSON planning、比较问题多 subquery、answer citation 来自 planned contexts、invalid planner 不调用 answer、planned no evidence 不调用 answer、非 writeback 不写 synthesis。
- 修改 `answer_question`：调用 `plan_question`、`execute_query_plan`，用 merged retrieval 构造 answer prompt。
- 跑 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_ask_workflow.py tests/test_planned_retrieval.py tests/test_planner.py -q`。
- 提交：`feat: 将 ask 接入 LLM 查询规划`。

### Task 5: CLI 输出与兼容回归

- 修改 `format_ask_result` 和 `ask_output_dict`。
- human 输出新增 `Planning:` 段。
- JSON 输出新增 `planning.status/intent/subquery_count/retrieved_context_count/warnings`。
- 保持旧字段 `question/answer/status/citations/warnings/writeback` 可用。
- 跑 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_ask_workflow.py tests/test_query_lint_doctor.py -q`。
- 提交：`feat: 输出 ask 查询规划诊断`。

### Task 6: 确保 retrieve/query/eval 不调用 LLM

- 扩展 `tests/test_retrieval.py`、`tests/test_query_lint_doctor.py`、`tests/test_retrieval_eval.py`。
- monkeypatch planner/provider，若 `retrieve/query/eval retrieval` 调用 LLM 则失败。
- 跑 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_retrieval.py tests/test_query_lint_doctor.py tests/test_retrieval_eval.py -q`。
- 提交：`test: 固定 retrieve query eval 本地契约`。

### Task 7: 文档与 agent contract

- README 更新：`ask` 使用 LLM planner -> local retrieve -> grounded answer；`retrieve/query` 不调用 LLM；planner output is not evidence。
- AGENTS 更新：planner 必须 schema validation；planner output 不得作为 evidence；V2.5 不得添加领域规则、关键词 intent classifier、term boost。
- 跑 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_regression_samples.py -q`。
- 提交：`docs: 更新 V2.5 查询规划说明`。

### Task 8: 最终验证

- 跑 planner/planned retrieval/ask/retrieval/query/eval 分组测试。
- 跑 `.\\.venv\\Scripts\\python.exe -m pytest -q`。
- 跑 `.\\.venv\\Scripts\\python.exe -m llmwiki --help`。
- 跑 `.\\.venv\\Scripts\\python.exe -m llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_4_fruits.jsonl`。
- 如果当前 workspace 有五篇水果 catalog，跑 `ask "这五种水果里哪种更适合补充维生素 C？" --root . --no-writeback --json`。
- 删除 `.test-workspaces`。
- 确认 `git status --short` 不包含 generated wiki/source/staging/state/config secrets。

## Assumptions

- 按已提交 V2.5 spec 执行：`ask` 使用 planner-first，而不是“弱召回时才 planner”。
- 不新增 public no-network mode，不新增生产 mock provider；测试只用 monkeypatch。
- 不新增数据库表；planner 使用 catalog 只读快照。
- 不实现 embedding、vector DB、reranker、UI、MinerU、OCR。
- 不加入领域规则、关键词 intent classifier、维生素/水果/保存类 term boost。
- planner 可以看到 bounded catalog overview，但不能看到完整 raw source 或 secret config。
- `.test-workspaces` 是测试临时目录，最终验证后必须清理。
