# LLM Wiki

一种使用 LLM 构建个人知识库的模式。

这是一份想法文档，设计目的是让你可以复制粘贴给自己的 LLM Agent，例如 OpenAI Codex、Claude Code、OpenCode / Pi 等。它的目标是传达高层思路，具体实现细节则由你的 Agent 和你协作完成。

## 核心想法

大多数人与 LLM 和文档交互的体验都类似 RAG：你上传一组文件，LLM 在你提问时检索相关片段，然后生成答案。这种方式可行，但问题是：LLM 每次回答问题时都在从头重新发现知识，没有积累。

如果你问一个比较微妙的问题，需要综合五份文档的信息，LLM 每次都必须重新找到相关片段，再把它们拼接起来。没有任何知识被真正沉淀下来。NotebookLM、ChatGPT 文件上传功能，以及大多数 RAG 系统，基本都是这种工作方式。

这里的想法不一样。

不是在提问时只从原始文档中检索信息，而是让 LLM **逐步构建并维护一个持久化的 wiki**。这个 wiki 是一组结构化、互相链接的 Markdown 文件，位于你和原始资料之间。

当你添加一个新来源时，LLM 不只是把它索引起来，等以后检索。它会阅读这个来源，提取关键信息，并把这些信息整合进已有的 wiki 中：

- 更新实体页面；
- 修订主题总结；
- 标记新数据与旧说法之间的矛盾；
- 强化或挑战正在形成的综合判断。

这些知识会被编译一次，然后持续保持更新，而不是每次查询时重新推导。

关键区别在于：**wiki 是一个持久的、会不断复利增长的知识产物。**

交叉引用已经在那里。矛盾已经被标记。综合分析已经反映了你读过的所有内容。你每添加一个新来源、每提出一个新问题，这个 wiki 都会变得更丰富。

你几乎不需要自己写 wiki。LLM 会负责编写和维护所有内容。你负责的是：

- 选择资料来源；
- 引导探索方向；
- 提出正确的问题。

LLM 负责所有繁琐工作：

- 总结；
- 交叉引用；
- 分类归档；
- 维护记录；
- 让知识库长期保持有用。

在实践中，我会把 LLM Agent 打开在一边，把 Obsidian 打开在另一边。LLM 根据我们的对话修改内容，我则实时浏览结果：

- 跟随链接；
- 查看图谱视图；
- 阅读更新后的页面。

Obsidian 是 IDE；LLM 是程序员；wiki 是代码库。

这个模式可以用于很多不同场景。比如：

- **个人管理**：跟踪自己的目标、健康、心理状态、自我提升；整理日记、文章、播客笔记，并逐渐构建一个关于自己的结构化图景。
- **研究**：在数周或数月内深入研究一个主题；阅读论文、文章、报告，并逐步建立一个带有演进观点的综合性 wiki。
- **读书**：每读一章就归档一章，建立人物、主题、情节线以及它们之间关系的页面。读完之后，你会得到一个丰富的伴读 wiki。可以想象类似 Tolkien Gateway 这样的粉丝 wiki：由社区志愿者多年维护，包含数千个互相关联的人物、地点、事件、语言页面。你也可以在个人阅读过程中构建类似东西，只是交叉引用和维护工作都由 LLM 来完成。
- **商业 / 团队**：由 LLM 维护的内部 wiki，输入来源可以是 Slack 讨论、会议记录、项目文档、客户通话等。也可以加入人工审核流程。因为 LLM 会做团队里没人愿意做的维护工作，所以 wiki 能够持续保持更新。
- **竞品分析、尽职调查、旅行规划、课程笔记、兴趣深挖**：任何需要长期积累知识，并希望这些知识被组织起来而不是散落各处的场景，都适合这种模式。

## 架构

这个系统有三层：

**原始资料层**：你精心收集的源文档集合。包括文章、论文、图片、数据文件等。这些资料是不可变的。LLM 可以读取它们，但永远不修改它们。这是你的事实来源。

**wiki 层**：由 LLM 生成的一组 Markdown 文件。包括总结、实体页面、概念页面、对比分析、总览、综合判断等。这一层完全由 LLM 负责。它会创建页面，在新资料加入时更新页面，维护交叉引用，并保持整体一致性。你阅读它，LLM 编写它。

**schema 层**：一个说明文档，例如 Claude Code 使用的 `CLAUDE.md`，或者 Codex 使用的 `AGENTS.md`。它告诉 LLM：

- wiki 的结构是什么；
- 使用哪些约定；
- 在摄取资料、回答问题或维护 wiki 时应该遵循什么流程。

这是关键配置文件。它会让 LLM 变成一个有纪律的 wiki 维护者，而不是一个普通聊天机器人。随着你逐渐摸索出适合自己领域的方法，你和 LLM 会一起不断改进这个 schema。

## 操作流程

### Ingest：摄取资料

你把一个新的资料放进原始资料集合中，然后告诉 LLM 处理它。

一个典型流程可能是：

1. LLM 阅读资料；
2. 和你讨论关键收获；
3. 在 wiki 中写一个总结页面；
4. 更新索引；
5. 更新 wiki 中相关的实体页面和概念页面；
6. 在日志中追加一条记录。

单个资料可能会影响 10 到 15 个 wiki 页面。

我个人更喜欢一次摄取一个资料，并保持参与。我会阅读总结、检查更新，并指导 LLM 应该强调什么。但你也可以批量摄取很多资料，减少监督。具体采用哪种工作流取决于你的风格，并且应该把这种工作流写进 schema，方便未来会话继续沿用。

### Query：查询

你可以基于 wiki 提问。

LLM 会搜索相关页面，阅读它们，然后生成带引用的综合回答。

回答可以根据问题采用不同形式：

- Markdown 页面；
- 对比表格；
- Marp 幻灯片；
- matplotlib 图表；
- canvas 等。

一个重要观点是：**好的回答也可以被重新归档进 wiki，成为新的页面。**

你提出的一个对比、一次分析、一个新发现的联系，都是有价值的，不应该消失在聊天记录里。这样，你的探索也会像摄取资料一样，在知识库中持续复利增长。

### Lint：健康检查

你可以定期让 LLM 对 wiki 做健康检查。

检查内容包括：

- 页面之间是否存在矛盾；
- 是否有旧说法已经被新资料取代；
- 是否有孤立页面，没有入站链接；
- 是否有重要概念被频繁提到，却没有自己的页面；
- 是否缺少交叉引用；
- 是否存在可以通过网络搜索补充的数据空白。

LLM 很擅长提出新的研究问题，以及建议你寻找哪些新资料。这样可以在 wiki 不断增长时保持其健康状态。

## 索引与日志

有两个特殊文件可以帮助 LLM 和你在 wiki 变大之后继续顺畅导航。它们作用不同。

### index.md

`index.md` 是面向内容的。

它是 wiki 中所有内容的目录。每个页面都会列出：

- 页面链接；
- 一句话总结；
- 可选的元数据，例如日期或来源数量。

它可以按照类别组织，比如实体、概念、来源等。

LLM 会在每次摄取资料时更新它。当回答问题时，LLM 会先阅读 index，找到相关页面，然后再深入阅读具体页面。

在中等规模下，例如大约 100 个资料来源、几百个页面，这种方式效果出奇地好，而且不需要基于 embedding 的 RAG 基础设施。

### log.md

`log.md` 是按时间顺序排列的。

它是一个只追加、不修改的记录文件，用来记录发生了什么以及什么时候发生：

- 摄取了哪些资料；
- 提出了哪些查询；
- 做了哪些 lint 检查。

一个实用技巧是：如果每条记录都用一致的前缀开头，例如：

```markdown
## [2026-04-02] ingest | Article Title
```

那么这个日志就可以用简单的 Unix 工具解析。比如：

```bash
grep "^## \[" log.md | tail -5
```

这样可以查看最近 5 条记录。

日志能提供 wiki 演化的时间线，也能帮助 LLM 理解最近做过什么。

## 可选：CLI 工具

在某个阶段，你可能会想构建一些小工具，帮助 LLM 更高效地操作 wiki。

最明显的工具是 wiki 页面搜索引擎。

在小规模时，index 文件已经够用。但当 wiki 变大后，你会想要更正式的搜索能力。

[qmd](https://github.com/tobi/qmd) 是一个不错的选择。它是一个本地 Markdown 搜索引擎，支持混合 BM25 / 向量搜索，以及 LLM 重排序，而且全部在本地设备上运行。

它同时提供：

- CLI：LLM 可以通过 shell 调用它；
- MCP server：LLM 可以把它作为原生工具使用。

你也可以自己构建更简单的工具。随着需求出现，LLM 可以帮你快速写一个朴素的搜索脚本。

## 技巧与建议

- **Obsidian Web Clipper** 是一个浏览器扩展，可以把网页文章转换成 Markdown。它非常适合快速把资料放入你的原始资料集合。
- **把图片下载到本地。** 在 Obsidian 的 Settings → Files and links 中，把 “Attachment folder path” 设置为固定目录，例如：

```text
raw/assets/
```

然后在 Settings → Hotkeys 中搜索 “Download”，找到 “Download attachments for current file”，并绑定一个快捷键，例如 `Ctrl + Shift + D`。

剪藏文章后，按下快捷键，所有图片都会下载到本地磁盘。

这是可选的，但很有用。这样 LLM 可以直接查看并引用图片，而不是依赖可能失效的 URL。

需要注意的是，LLM 不能在一次读取 Markdown 时原生理解其中的内联图片。解决方法是：让 LLM 先阅读文本，然后再单独查看部分或全部引用图片，以获得额外上下文。这个流程有点笨拙，但实际效果足够好。

- **Obsidian 的图谱视图** 是观察 wiki 结构的最佳方式。你可以看到哪些内容彼此连接、哪些页面是枢纽、哪些页面是孤岛。
- **Marp** 是一种基于 Markdown 的幻灯片格式。Obsidian 有对应插件。它适合直接从 wiki 内容生成演示文稿。
- **Dataview** 是 Obsidian 的一个插件，可以基于页面 frontmatter 执行查询。如果你的 LLM 给 wiki 页面添加 YAML frontmatter，例如标签、日期、来源数量，Dataview 就可以生成动态表格和列表。
- 这个 wiki 本质上只是一个 Markdown 文件组成的 git 仓库。因此你天然获得了版本历史、分支和协作能力。

## 为什么这个方法有效

维护知识库中真正繁琐的部分，不是阅读，也不是思考，而是文档管理工作。

比如：

- 更新交叉引用；
- 保持总结最新；
- 记录新数据什么时候与旧说法冲突；
- 在几十个页面之间维持一致性。

人类经常放弃 wiki，因为维护成本增长得比价值更快。

但 LLM 不会厌烦，不会忘记更新交叉引用，也可以在一次操作中同时修改 15 个文件。wiki 能够持续维护，是因为维护成本接近于零。

人的工作是：

- 筛选资料来源；
- 指导分析；
- 提出好问题；
- 思考这些内容到底意味着什么。

LLM 的工作是除此之外的所有事情。

这个想法在精神上与 Vannevar Bush 于 1945 年提出的 Memex 有关。Memex 是一个个人化、经过策划的知识存储系统，文档之间通过关联路径连接。

Bush 的愿景其实比今天的 Web 更接近这里描述的模式：它是私人的、主动策划的，而且文档之间的连接和文档本身一样有价值。

他当时没能解决的问题是：谁来做维护？

现在，LLM 可以处理这件事。

## 注

这份文档刻意保持抽象。它描述的是一种思路，而不是某个具体实现。

具体的目录结构、schema 约定、页面格式、工具链，都取决于你的领域、你的偏好，以及你选择的 LLM。

上面提到的所有内容都是可选且模块化的。你可以选择有用的部分，忽略不适合你的部分。

例如：

- 你的资料可能全是文本，所以完全不需要图片处理；
- 你的 wiki 可能足够小，index 文件就够用了，不需要搜索引擎；
- 你可能不关心幻灯片，只想要 Markdown 页面；
- 你可能想要完全不同的输出格式。

正确使用这份文档的方式是：把它交给你的 LLM Agent，然后和它一起实例化一个适合你需求的版本。

这份文档唯一的任务，就是传达这种模式。剩下的部分，你的 LLM 可以自己推导出来。







# 我的思考：

最终项目运行路线：

```
资料导入
→ 文档解析 / MinerU
→ normalized sources
（LLM 处理生成 wiki，是全自动，只留下一个接口 add）
→ LLMWiki ingest
→ 抽取 claims
→ 建 source / concept / entity 页面
→ 建 catalog / links / relationships

用户提问
→ retrieve/query 从 wiki + catalog 检索证据
→ LLM 基于证据回答
→ 好的问题结果再写回 wiki（这一步询问用户） → 建立 synthesis 页面

定期 Lint（显式指令）
```

synthesis 可以理解成“综合回答页”或“研究结论页”。

它不是原始资料页，也不是概念页。它更像后续阶段里，当用户问了一个问题后，系统从 wiki + catalog 检索证据，然后让 LLM 基于证据生成一份可保存的综合结果，例如：

```
用户问：苹果和橙子的营养差异是什么？ -> retrieve 找到相关 claims / sources / relationships -> LLM 基于证据回答 -> 系统问：是否把这个回答写回 wiki？ -> 如果用户同意，生成 wiki/syntheses/xxx.md
```



## V2 已有能力

目前这个项目已经是一个“本地资料 -> 结构化 wiki -> 可检索证据”的原型系统。

**已有能力**

1. 工作区初始化和健康检查 
   `llmwiki init` 可以创建工作区结构、配置文件、wiki/index/log 和 SQLite catalog。`llmwiki doctor` 可以检查 workspace、schema、依赖、index/log 是否完整。

2. 资料导入和标准化 
   `llmwiki add <source>` 现在能导入 Markdown、本地文本/PDF、网页快照类 source。它会把原始文件放进 `sources/raw/`，把可处理文本写到 `sources/normalized/`，并在 catalog 里登记 source。它也会按 sha256 去重。 
   但重点是：当前 `add` 只做导入和 normalize，还不会自动 ingest/apply。

3. LLM/规则提取到 staging 
   `llmwiki ingest <source-id>` 会读取 normalized source，生成 staging run：`claims.jsonl`、`triage.md`、`patches/*.json`、`run.json`，有 LLM proposal 时还会写 `llm-proposal.json`。 
   当前代码有 LLM ingest 路径，也保留了 heuristic fallback，这是后续 V2.1 要收紧的地方。

4. 人工审阅入口 
   `llmwiki review <run-id>`、`--detail`、`--patches` 可以查看 claims、patch、重复候选、冲突候选、弱引用 claim 等。现在它是人工流程的一部分，后续 spec 里会降级成 internal/debug。

5. 安全 apply 
   `llmwiki apply <run-id>` 是唯一正式写入 `wiki/` 和 `state/catalog.sqlite` 的路径。它会验证 patch 目标必须在 `wiki/` 下、不能改 `wiki/log.md`、必须有 frontmatter、必需章节、claim id、有效 citation，并在出错时回滚 wiki/index/log/catalog。

6. Wiki/catalog 生成 
   apply 后会生成或更新 `wiki/sources/`、`wiki/concepts/`、必要时 `wiki/entities/`，同时更新 `wiki/index.md`、追加 `wiki/log.md`，并把 claims、pages、aliases、links、relationships 写入 SQLite catalog。

7. 检索接口 
   `llmwiki retrieve` 可以从本地 catalog/wiki 返回带 citation 的 evidence context，支持 JSON 或 prompt 格式。这个是后续接 RAG/agent/query 的基础接口。

8. 简单 query 
   `llmwiki query` 目前能基于已编译 wiki 做上下文查询，但还不是完整“LLM 基于证据回答并询问是否写回 wiki”的产品级 ask 流程。

9. LLM 配置和连通性测试 
   `llmwiki llm-test` 可以调用配置好的真实 LLM provider。API key 现在按我们之前的改法走本地 ignored 配置文件，不应该提交。

10. 维护能力 
      `llmwiki lint` 可以检查 wiki 健康，但按最新决策，它是独立维护动作，不是默认 `add` 流程的一部分。

**当前最大缺口**
现在完整流程还是：

```text
add -> ingest -> review -> apply -> retrieve/query
```



## 20260527-13:25 V2.1 

目标：把 llmwiki add 做成唯一的正常资料导入入口，让用户丢一个文件或 URL 后，系统自动完成“导入到生成 wiki”的整条链路。

完成的是这样的一个任务：

```
（LLM 处理生成 wiki，是全自动，只留下一个接口 add）LLM 只生成 claims 和候选 patch，正式写入仍必须走 staging 验证和 apply_run。
→ LLMWiki ingest
→ 抽取 claims
→ 建 source / concept / entity 页面
→ 建 catalog / links / relationships
```

本规格有意为以下能力做准备，但不在当前阶段实现：

- ingest 阶段检索现有 wiki 上下文
- 多 source 概念/实体合并
- 查询时基于证据的回答
- 将回答回写到 `wiki/syntheses/`
- MinerU parser 集成
- 更强的搜索基础设施

## 20260527-17:00 V2.2 **Evidence Answer + Writeback**

