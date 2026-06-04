# LLMWiki V2.8 Synthesis Quality Implementation Plan

**Goal:** Upgrade `ask --writeback` from one-answer-one-page persistence into maintainable synthesis pages that can be planned, previewed, created, updated, and validated through staging/apply.

**Architecture:** Add a synthesis planning layer that proposes create/update/needs_review using bounded local context, a synthesis page model that parses and renders durable V2.8 pages, then route CLI writeback through plan -> staging -> apply. Synthesis remains grounded in existing catalog claims and does not create derived formal claims.

**Tech Stack:** Python standard library, SQLite catalog, existing LLM provider abstraction, existing staging/apply workflow, pytest.

---

## Summary

V2.8 将 `ask --writeback` 从“一问一页的问答保存”升级为可维护的 synthesis 知识页写回流程：先生成并验证 synthesis plan，再决定 create/update/needs_review，最后仍通过 staging/apply 写入 `wiki/syntheses/*.md` 和 catalog。核心原则不变：synthesis 不是 source，不创建新的 formal claims，所有 evidence 必须来自已有 catalog claim。

## Implementation Tasks

- [ ] Task 1: Planner 失败测试。
- [ ] Task 2: 实现 synthesis planner。
- [ ] Task 3: Page model 失败测试。
- [ ] Task 4: 实现 page parser/renderer。
- [ ] Task 5: 接入 staging/apply。
- [ ] Task 6: CLI preview 和 writeback mode。
- [ ] Task 7: 重复问题 update 验收测试。
- [ ] Task 8: Failure rollback 和 secret safety。
- [ ] Task 9: 文档与契约。
- [ ] Task 10: 最终验证与真实验收。

## Detailed Requirements

- 新增 `llmwiki/synthesis_planner.py`，定义 `SynthesisPlan`、`SynthesisEvidenceItem`、`SynthesisRelationship`、`SynthesisCandidate`、`SynthesisPlanningOptions`、`SynthesisPlanningError`。
- 新增 `llmwiki/synthesis_pages.py`，定义 `SynthesisPageModel`，支持 V2.2 synthesis 迁移和 V2.8 section model。
- 修改 `llmwiki/synthesis.py`，让 `create_synthesis_run(root, ask_result, plan=None)` 使用 V2.8 plan 构建 staging patch，并写 `synthesis-plan.json`。
- 修改 `llmwiki/cli.py`，为 `ask` 增加 `--preview-writeback` 和 `--writeback-mode {auto,create,update}`。
- 修改 `llmwiki/apply.py`，让 synthesis patch 校验使用 V2.8 required sections。
- 测试必须覆盖 planner validation、page parsing/rendering、preview read-only、create/update/needs_review、安全回滚、secret safety、重复 focused 问题更新同页、comparison 问题单独成页。

## Verification

- `.\.venv\Scripts\python.exe -m pytest tests/test_synthesis_planner.py tests/test_synthesis_pages.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests/test_ask_workflow.py tests/test_query_lint_doctor.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_retrieval_eval.py -q`
- `.\.venv\Scripts\python.exe -m pytest -q`
- `.\.venv\Scripts\python.exe -m llmwiki --help`

## Assumptions

- V2.8 不新增数据库表。
- V2.8 不创建 derived formal claims；`claims.jsonl` 保持为空。
- 多个可信 update target 时返回 `needs_review`，不自动合并既有 synthesis 页面。
- 非交互、无 `--writeback`、无 `--preview-writeback` 时不做 synthesis planning。
- 不加入领域规则。
