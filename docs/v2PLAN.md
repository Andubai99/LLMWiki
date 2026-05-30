项目运行路线：

```
资料导入
→ 文档解析 / MinerU
→ normalized sources
→ LLMWiki ingest
→ 抽取 claims
→ 建 source / concept / entity / synthesis 页面
→ 建 catalog / links / relationships
→ 用户提问
→ retrieve/query 从 wiki + catalog 检索证据
→ LLM 基于证据回答
→ 好的问题结果再写回 wiki（这一步询问用户）
```

> [!IMPORTANT]
>
> 应该先把之前项目中由用户review、apply的流程都取消，只留下一个接口就是add，然后全部由LLM和编排好的智能体workflow进行wiki生成。最终项目的数据流是：资料导入->文档解析->LLM处理（ingest等，直到生成wiki），等这些流程结束，用户可以提问->retrieve/query 从 wiki + catalog 检索证据 -> LLM基于证据回答 -> 主动询问用户是否将问题结果写回wiki。



**阶段 1：Ingest-Time 上下文检索**

目标：新资料导入时，不只读新 source，还要先查已有 wiki。

新增能力：

```
new source claims -> retrieve related existing claims/pages -> LLM 判断该更新哪些 concept/entity -> 生成 page update plan -> staging patches
```

具体要做：

- 给 ingest 增加“检索已有 wiki 上下文”的步骤。
- 检索对象包括：
  - 相关 concept pages
  - entity pages
  - existing claims
  - aliases
  - contradicts/supports relationships
- 生成一个中间文件，比如：
  - staging/<run-id>/context.json
  - staging/<run-id>/update-plan.json

验收标准：

- 第二篇相关资料导入时，不再盲目创建新 concept。
- review 能显示：“本次将更新已有页面 X，而不是创建 Y”。
- duplicate candidate 数量下降。

------

**阶段 2：Concept / Entity 增量合并**

目标：让 wiki 真正“长出来”，而不是每篇资料生成孤立页面。

当前 concept 页更像“单 source summary”。下一步要变成“多 source 聚合页”。

具体要做：

- 让 concept 页支持多来源：
  - source_count > 1
  - 多个 source links
  - 多批 claim ids
- LLM 读取旧 concept 页 + 新 claims，生成 merge patch。
- 合并时区分：
  - 新增事实
  - 已有事实的补充
  - 冲突事实
  - 不确定事实
  - 需要进一步研究的问题
- entity 页也用同样机制维护别名、关系、支持来源。

验收标准：

- 两篇都讲“草莓”的资料导入后，只保留一个 wiki/concepts/草莓.md。
- 页面里能看到两个 source 的 claims。
- 冲突不被抹平，而是进入 Open Questions 或 conflict 区域。

------

**阶段 3：Query-Time Answer + Synthesis**

目标：用户提问时，不只是 retrieve 证据，而是生成可沉淀的综合页。

新增命令可以是：

```
llmwiki answer "问题" --root . llmwiki synthesize "问题" --root .
```

两者区别：

- answer：直接回答，带 citations。
- synthesize：把回答写成 wiki/syntheses/*.md 的候选 patch。

生成的 synthesis 页应包含：

- Question / Topic
- Short Answer
- Evidence
- Analysis
- Uncertainties
- Related Pages
- Claim citations

验收标准：

- 用户问“这五种水果保存方式有什么区别？”
- 系统检索已有 wiki/catalog
- 生成一个可 apply 的 synthesis 页面
- 页面引用具体 source id + locator

这一步会让“问答结果反哺 wiki”。

------

**阶段 4：LLM Maintenance / Lint**

目标：从规则 lint 升级到 LLM 维护建议。

当前 lint 是规则式检查。后续增加：

```
llmwiki maintain --root .
```

它做：

- 找重复概念页
- 找缺少 concept/entity 的重要主题
- 找 stale claims
- 找需要补 source 的薄弱页面
- 找潜在 synthesis 机会
- 找断裂的关系网络

输出仍然进入 staging：

```
staging/<run-id>/maintenance-plan.md staging/<run-id>/patches/
```

验收标准：

- maintain 能提出“这些页面应合并”
- 能提出“这个概念被多次提到但没有页面”
- 能提出“这些 claims 可能冲突，需要人工或后续 source 解决”

------

**阶段 5：MinerU / 附件解析入口**

目标：把 PDF、扫描件、图片、表格等复杂资料转成高质量 normalized source。

建议这一步放在知识网络能力之后做。

新增能力：

```
llmwiki add paper.pdf --parser mineru
```

或：

```
llmwiki import-folder docs/papers --parser mineru
```

重点不是“能转 Markdown”，而是保留 locator：

- page number
- section
- paragraph
- table id
- figure id
- image path
- caption

目录可以扩展：

```
sources/raw/ sources/normalized/ sources/assets/
```

验收标准：

- PDF 第 12 页某段文字能成为 claim locator。
- 图片/表格能被引用到 source page。
- LLM claim 能回溯到 PDF 页码或表格编号。

------

**阶段 6：检索增强**

目标：当资料变多后，提高 retrieve/query 的召回质量。

先保持当前 SQLite FTS/BM25。等资料量上来后再考虑：

- 中文分词增强
- hybrid search
- qmd
- local embedding
- reranker
- vector DB

这不是第一优先级。只有当现有检索明显找不到相关内容时再做。

验收标准：

- 同一个问题能同时命中 source claim、concept page、synthesis page。
- 返回结果能解释为什么匹配。
- contradictory evidence 会一起暴露。

------

**阶段 7：批处理与工作流自动化**

目标：提高日常使用效率。

可做：

```
llmwiki ingest-all --root . llmwiki apply-all --root . llmwiki watch sources/inbox llmwiki pipeline docs/tests
```

也可以做简单 inbox 约定：

```
inbox/ processed/ sources/raw/ sources/normalized/ wiki/
```

这一步不是 UI，而是让 CLI 工作流更顺。

验收标准：

- 丢一批资料进去，系统按顺序处理。
- 每个 run 有状态。
- 失败时能继续，不污染已成功结果。

------

**推荐顺序**

我建议严格按这个顺序：

```
0. 提交当前 V1 baseline 1. ingest 时检索已有 wiki 上下文 2. concept/entity 增量合并 3. query-to-synthesis 4. LLM maintenance 5. MinerU 附件解析 6. 检索增强 7. 批处理/自动化
```

最重要的前三步是：

```
已有 wiki 上下文检索 -> 多来源页面合并 -> 问答结果沉淀成 synthesis
```

做完这三步，项目就会从“资料整理器”变成真正的“会累积的 LLM Wiki”。