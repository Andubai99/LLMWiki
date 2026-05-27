# LLMWiki V2.2：证据问答与 Synthesis 写回

## 1. 背景

V2.1 已经把 `llmwiki add <source> --root .` 变成正常的资料导入入口。现在，一份 source 可以通过一条面向用户的命令完成导入、normalize、LLM ingest、staging、验证、apply、wiki 页面创建和 catalog 更新。

下一个缺失的闭环是“使用”。当 wiki 和 catalog 已经存在后，用户应该能提出一个研究问题，得到一个基于证据的 LLM 回答，并决定这个有价值的结果是否应该变成一个持久的 synthesis 页面。

目标流程：

```text
用户提问
-> 从 wiki + catalog retrieve/query 证据
-> LLM 只能基于检索到的证据回答
-> 用户决定这个答案是否值得保存
-> synthesis 写回必须经过 staging/apply
-> 更新 wiki/syntheses/*.md 和 catalog
```

这一阶段把 LLMWiki 从“可以把资料编译成 wiki”推进到“可以基于已编译的 wiki 回答问题，并把好的答案保存回 wiki”。

## 2. 目标

V2.2 增加一个基于证据的问答 workflow：

- 增加一个正常 CLI 入口，用于生成 grounded answer：

```bash
llmwiki ask "问题" --root .
```

- 使用现有 `retrieve_context` 作为证据来源。
- 只有在检索到证据之后，才调用已配置的 LLM provider。
- 要求答案引用检索到的 claim id、source id 和 citation locator。
- 暴露证据不足、weak/uncited evidence 和 contradictions，而不是隐藏不确定性。
- 询问用户是否把答案写回为 synthesis 页面。
- 写回时创建 staging run，并通过现有安全路径 apply。
- 保留 `retrieve` 作为稳定的机器证据 API，保留 `query` 作为确定性的本地上下文命令。

## 3. 非目标

本阶段不实现：

- Web UI 或 Obsidian 插件。
- Vector database、embedding search 或 reranking。
- MinerU、OCR、表格抽取或更丰富的附件解析。
- 多轮聊天记忆。
- Web 搜索或外部实时浏览。
- 对每个答案自动写回。
- 让 LLM 直接写入 `wiki/`。
- 把 derived claims 作为一等 source claim 写入 `claims` 表。
- 团队同步、权限系统或云存储。

## 4. 命令模型

### 4.1 `ask`

主命令：

```bash
llmwiki ask "RAG 为什么需要引用锚点？" --root .
```

默认行为：

```text
retrieve evidence
-> 生成答案
-> 输出 citations 和 warnings
-> 如果运行在交互式终端中，询问是否写回
```

默认行为必须安全：

- 如果不是交互式终端，除非传入 `--writeback`，否则 `ask` 不得写回。
- 如果 evidence 为空，`ask` 默认不应调用 LLM，而应返回证据不足的答案。
- 如果 LLM 返回的 citation 不存在于检索到的 evidence 中，这个答案无效，不能写回。

常用 flags：

```bash
llmwiki ask "问题" --root . --limit 8
llmwiki ask "问题" --root . --json
llmwiki ask "问题" --root . --writeback
llmwiki ask "问题" --root . --no-writeback
llmwiki ask "问题" --root . --source-id src_xxx
llmwiki ask "问题" --root . --page-type concept
llmwiki ask "问题" --root . --confidence cited
```

`--writeback` 表示用户已经为这次命令调用批准写回。即便如此，系统仍然必须执行 staging validation 和 apply safety checks。

`--no-writeback` 会关闭交互式提示，并保持 wiki 不变。

### 4.2 `retrieve`

`retrieve` 仍然是外部 RAG 系统、agent 和测试使用的稳定 evidence interface：

```bash
llmwiki retrieve "问题" --root . --json
llmwiki retrieve "问题" --root . --format prompt
```

V2.2 可以改进 retrieve warnings 或输出字段，但只能以向后兼容方式进行。现有 JSON keys 必须保持稳定。

### 4.3 `query`

`query` 仍然是一个简单的、确定性的本地命令。它不应调用 LLM。未来它可以变成面向人的 retrieve 输出别名，但 V2.2 不应依赖 `query` 来生成答案。

## 5. 面向用户的输出

人类可读的 `ask` 输出形状应如下：

```text
Question: RAG 为什么需要引用锚点？

Answer:
RAG 需要引用锚点，因为后续回答必须能追溯到具体 source 和 locator...

Citations:
- clm_xxx src_abc line:12 wiki/concepts/rag.md
- clm_yyy src_def line:8 wiki/sources/src_def.md

Warnings:
- Contradictory evidence is present; answer keeps the conflict visible.

Writeback:
Not written. Run with --writeback or answer yes when prompted to create a synthesis page.
```

写回成功时：

```text
Writeback:
Applied synthesis run: run_answer_xxx_...
Page:
- wiki/syntheses/rag-why-citation-anchors-matter.md
```

JSON 输出应该可被机器解析，并且不能包含 secret：

```json
{
  "question": "...",
  "answer": "...",
  "status": "answered",
  "citations": [
    {
      "claim_id": "clm_xxx",
      "source_id": "src_xxx",
      "citation_locator": "line:12",
      "page_path": "wiki/concepts/example.md"
    }
  ],
  "warnings": [],
  "writeback": {
    "status": "skipped",
    "run_id": null,
    "pages": []
  }
}
```

允许的 answer statuses：

- `answered`
- `insufficient_evidence`
- `llm_failed`
- `invalid_citations`
- `writeback_failed`

## 6. 内部架构

新增聚焦模块，而不是继续扩张 `cli.py`：

```text
llmwiki/answer.py
  answer_question(root, question, options) -> AskResult
  build_answer_prompt(...)
  validate_answer_citations(...)

llmwiki/synthesis.py
  create_synthesis_run(root, AskResult) -> SynthesisRunResult
  build_synthesis_patch(...)

llmwiki/cli.py
  cmd_ask(...)
```

高层 ask pipeline：

```text
retrieve_context(root, question, filters)
-> 如果没有 cited evidence，返回 insufficient_evidence
-> 从 config/config.toml + config/api-keys.toml 创建 LLM provider
-> 要求 LLM 输出结构化 grounded answer
-> 校验所有 cited claim id 都来自 retrieved evidence
-> 输出答案
-> 如果用户确认 writeback：
     创建 staging synthesis run
     apply_run(root, run_id)
     输出已 apply 的 synthesis 页面
```

除非显式请求 writeback，否则 `answer_question` 应该是只读的。LLM answer 本身不得写文件。

## 7. Answer Contract

系统应要求 LLM 输出结构化 JSON，然后由项目代码进行校验。

预期 answer object：

```json
{
  "short_answer": "...",
  "analysis": "...",
  "citations": [
    {
      "claim_id": "clm_xxx",
      "source_id": "src_xxx",
      "citation_locator": "line:12"
    }
  ],
  "uncertainties": ["..."],
  "conflicts": ["..."],
  "suggested_title": "..."
}
```

校验规则：

- 每个被引用的 `claim_id` 必须存在于 retrieved contexts 中。
- 被引用的 `source_id` 和 `citation_locator` 必须和该 claim 的 retrieved context 匹配。
- `status=answered` 至少需要一个 cited claim。
- 如果 retrieved warnings 提到 weak/uncited evidence，答案必须包含 uncertainty 或 warnings。
- 如果 retrieved relationships 包含 `contradicts`，答案必须提到冲突，不能静默选择一方。
- 如果校验失败，不写回。

LLM 可以对 evidence 做总结和推理，但不能把没有 citation 的事实性结论当作确定事实引入。

## 8. Synthesis 写回

写回会创建一个 `synthesis` 页面。它不是新的 source import，也不应该创建假的 raw source 文件。

Staging run 形状：

```text
staging/<run-id>/
  run.json
  claims.jsonl
  triage.md
  patches/
    001-synthesis-<slug>.json
```

V2.2 中 `claims.jsonl` 可以为空。synthesis 页面应该复用 catalog 中已有的 evidence claim ids，而不是发明新的 formal claims。这可以保持 source-backed claims 和用户批准的 analysis pages 之间的边界。

`run.json` 应包含：

```json
{
  "run_id": "run_answer_xxx_...",
  "run_type": "synthesis_writeback",
  "trigger": "ask",
  "status": "staged",
  "question": "...",
  "answer_status": "answered",
  "evidence_claim_ids": ["clm_xxx"],
  "proposal_engine": "llm",
  "provider": "openai",
  "model": "deepseek-v4-pro"
}
```

因为当前 catalog 中 `ingest_runs.source_id` 是必需的兼容字段，所以 V2.2 在 `apply_run` 记录 run 时应使用一个合成 source id，例如 `synthesis:<answer-id>`。这个值不能被当作 `sources` 里的真实 source。

synthesis patch 只能写入：

```text
wiki/syntheses/<slug>.md
```

patch 应包含：

```json
{
  "source_id": "synthesis:<answer-id>"
}
```

这是 applied run record 的 catalog 兼容值，不是真实导入的 source id。

页面必须满足现有 `synthesis` page requirements：

```text
---
page_type: synthesis
title: "..."
aliases: []
source_count: N
claim_ids: ["clm_xxx", "clm_yyy"]
updated_at: "..."
---

# ...

## Question/Topic
## Short Answer
## Evidence
## Analysis
## Uncertainties
## Related Pages
```

synthesis 页面应包含：

- 原始用户问题。
- 简短答案。
- Evidence list，包含 claim id、source id、locator 和 page path。
- 基于 evidence 的分析。
- 不确定性和冲突。
- 相关 source/concept/entity 页面。

写回必须调用 `apply_run`。它不能直接写 `wiki/syntheses/*.md`、`wiki/index.md`、`wiki/log.md` 或 `state/catalog.sqlite`。

## 9. 安全与失败行为

### 无证据

如果 retrieval 没有返回 contexts：

- 返回 `status=insufficient_evidence`。
- 默认不调用 LLM。
- 不提示 writeback。
- 建议添加更多 sources。

### Weak 或 Uncited Evidence

如果 retrieval 包含 weak/uncited evidence：

- 保持 warnings 可见。
- 答案可以解释 weak evidence 暗示了什么。
- 答案不能把 weak/uncited material 作为正式结论呈现。
- 除非至少有一个 cited claim 支持 synthesis，否则应拒绝 writeback。

### Contradictions

如果 retrieved relationships 包含 `contradicts`：

- 答案必须暴露分歧。
- synthesis 页面必须在 `## Uncertainties` 中包含该分歧。
- 除非 evidence 本身支持某个结论，否则系统不能选择胜者。

### 无效 LLM 输出

如果 LLM 返回 malformed JSON、缺少 citations，或 citations 不在 retrieved evidence 中：

- 返回 `status=invalid_citations` 或 `llm_failed`。
- 不写回。
- 不泄露包含 API key 或 config secrets 的 prompt text。

### Writeback 失败

如果 synthesis staging 或 apply 失败：

- 在 CLI 输出中保留答案。
- 如果已有 staging run，标记该 run 为 failed。
- 让现有 apply rollback 恢复 wiki/index/log/catalog 状态。
- 输出 debug command：

```bash
llmwiki review <run-id> --detail --root .
```

## 10. 数据与 Catalog 行为

V2.2 应避免 schema churn，除非实现证明确实必要。

不新增表时必须满足：

- Synthesis pages 注册到 `pages`，`page_type=synthesis`。
- Synthesis page aliases 索引到 `aliases`。
- Synthesis page links 存入 `links`。
- 已有 claim ids 继续作为 synthesis pages 的 evidence anchors。
- `relationships` 可以增加从 synthesis page ids 到 evidence claim ids 或 related page ids 的 `supports` 或 `refines` 记录，只要 retrieval 仍然能暴露 contradictions。
- `ingest_runs` 可以用合成 `source_id` 兼容值记录 applied synthesis run。

V2.2 不为 synthesized conclusions 创建新的 `claims` rows。后续阶段可以加入显式 derived-claim provenance，但本阶段应保持边界清晰：

```text
claims = source-backed facts
syntheses = user-approved analysis grounded in existing claims
```

## 11. CLI Help 与文档

`llmwiki --help` 应包含：

```text
ask       Answer a question using local wiki evidence and the configured LLM.
```

README 应描述 V2.2 的正常流程：

```bash
llmwiki add docs/example.md --root .
llmwiki ask "问题" --root .
```

Advanced/debug docs 应保留：

- `retrieve`：机器 evidence。
- `query`：确定性 context。
- `review/apply`：检查失败或 staged writeback runs。
- `lint`：显式维护命令，不属于默认 ask 流程。

AGENTS.md 应更新为：

- `ask` 可以调用已配置的 LLM。
- `ask` 必须只基于 retrieved local evidence 回答。
- synthesis writeback 必须经过 staging/apply。
- weak/uncited 和 contradicting evidence 必须保持可见。

## 12. 测试

实现前先加测试：

- 无匹配 evidence 时，`ask` 返回 `insufficient_evidence`，且不调用 LLM。
- `ask` 检索 evidence、调用 monkeypatched provider、校验 citations，并输出答案。
- `ask --json` 返回稳定 JSON，且不包含 secrets。
- LLM 引用了 retrieved evidence 外部的 citations 时，返回 `invalid_citations`，且不 writeback。
- Contradictory evidence 会出现在 answer warnings 和 synthesis uncertainties 中。
- `ask --writeback` 创建 staging run，apply 一个 synthesis page，更新 `wiki/index.md`、`wiki/log.md` 和 catalog pages。
- 非交互式 `ask` 且没有 `--writeback` 时，不写 wiki files。
- Writeback apply failure 会把 run 标记为 failed，且不留下 partial wiki/catalog mutations。
- 现有 `retrieve` JSON tests 继续通过。
- `query` 仍然是确定性的，且不调用 LLM。

不要增加 production mock provider 或 no-network public path。测试可以在 test boundary monkeypatch provider construction。

## 13. 验收标准

V2.2 完成时应满足：

- `llmwiki ask "问题" --root .` 能基于本地 wiki/catalog evidence 回答。
- 答案包含可追溯到 retrieved claim ids、source ids 和 locators 的 citations。
- 当 evidence 缺失或无效时，命令拒绝把答案当事实回答。
- 命令暴露 retrieval warnings 和 contradictions。
- 用户可以通过 `--writeback` 或交互式 yes/no prompt 批准 writeback。
- Writeback 通过 staging/apply 创建合法的 `wiki/syntheses/*.md` 页面。
- Synthesis pages 出现在 `wiki/index.md` 和 catalog `pages` 中。
- API keys 和本地 config secrets 不得出现在 answer output、staging artifacts、tests、docs 或 logs 中。
- 完整 pytest 通过。

## 14. Implementation Plan 默认选择

这些选择不是产品阻塞项。implementation plan 应采用以下默认值，除非测试证明需要改变：

- 交互式确认应使用一个小的、可注入的 confirmation helper，方便测试避免 stdin。
- 当 writeback 被跳过时，不保存 answer artifacts。没有被批准的 writeback 就不产生持久副作用。
- Synthesis slug 应使用 sanitized LLM suggested title，并用 question hash 作为 fallback。
- 无效 LLM JSON 应使用更严格的 repair prompt 重试一次，然后 fail safe。
- Relationships 先从 page links 和 existing claim ids 开始。只有在测试证明有价值时，再增加更丰富的 synthesis relationships。
