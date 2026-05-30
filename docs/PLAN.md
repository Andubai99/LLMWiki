# LLM Wiki 个人研究库落地方案

## Summary
第一版做成本地优先的 **Python CLI + Markdown wiki + agent 工作流**。核心不是做一个新的笔记 App，而是做一个可靠的“知识编译器”：原始资料不可变，LLM 只通过暂存区提出 wiki 修改，用户审阅后再落盘。Obsidian 负责阅读和浏览，Git 负责版本历史，Python CLI 负责解析、索引、引用、lint 和写入保护。

## Architecture
采用五层结构：

1. **Raw Sources**
   - `sources/raw/` 保存原始 PDF、Markdown、网页快照。
   - 每个 source 有稳定 `source_id`、sha256、标题、来源 URL、导入时间。
   - 原文不可被 LLM 修改。

2. **Normalized Sources**
   - `sources/normalized/` 保存从 PDF/网页转出的 Markdown。
   - 保留页码、段落号或行号，供 claim-level citation 使用。
   - PDF 第一版支持文本型 PDF；扫描 PDF 先标记为 unsupported，不做 OCR。

3. **Claim Store**
   - `state/catalog.sqlite` 保存 source、claim、alias、page、link、relationship、ingest run。
   - 每个 claim 至少包含：`claim_id`、正文、source_id、引用位置、置信状态、关联实体/概念。
   - Markdown 是人类界面，SQLite 是机器索引和审计缓存。

4. **Wiki**
   - `wiki/index.md`：入口索引。
   - `wiki/log.md`：append-only 操作日志。
   - `wiki/sources/`：单篇资料摘要。
   - `wiki/concepts/`：概念页。
   - `wiki/entities/`：人物、机构、项目、论文等实体页。
   - `wiki/syntheses/`：跨资料综合、比较、研究问题、结论页。
   - 页面 frontmatter 包含 `page_type`、`aliases`、`source_count`、`claim_ids`、`updated_at`。

5. **Staging + Review**
   - `staging/<run-id>/triage.md` 记录本次 ingest 的候选新增页、候选修改页、重复候选、冲突和证据。
   - `staging/<run-id>/patches/` 保存待应用 Markdown patch。
   - 默认不自动写 wiki；必须执行 apply 才落盘。

## Key Changes / Interfaces
提供一个 `llmwiki` Python CLI，第一版命令固定如下：

- `llmwiki init`：创建目录、`config/config.toml`、本地 `config/api-keys.toml`、初始 `AGENTS.md`、空索引和数据库。
- `llmwiki add <file-or-url>`：导入 PDF/Markdown/网页，生成 raw + normalized source，并写入 source catalog。
- `llmwiki ingest <source-id>`：生成 agent ingest context，要求 LLM 产出 claims、候选 wiki patch 和 triage。
- `llmwiki review <run-id>`：展示候选修改、冲突、重复页和引用覆盖率。
- `llmwiki apply <run-id>`：校验 patch、更新 wiki、刷新 index、追加 log。
- `llmwiki query "<question>"`：先搜 index/SQLite/BM25，再让 LLM 基于 wiki 和 claims 回答；高价值回答可保存到 `wiki/syntheses/`。
- `llmwiki lint`：检查断链、孤页、重复 alias、无引用 claim、source drift、跨页矛盾候选。
- `llmwiki doctor`：检查环境、数据库、目录、依赖和配置。

主要改进点：
- 采用 **claim-first ingestion**，先提取可引用 claim，再更新概念/实体页。
- 采用 **typed relationships**，关系至少区分 `supports`、`contradicts`、`refines`、`contains`、`similar_to`。
- 采用 **identity resolution**，新概念/实体页创建前必须查 alias 和相似标题，重复候选进入 triage。
- 采用 **staged writes**，LLM 不能直接改 wiki 正式页。
- 采用 **source-backed citations**，重要段落必须引用 `source_id + page/line/paragraph`。
- 搜索第一版用 SQLite FTS/BM25；向量检索和 MCP 作为第二阶段扩展。

## Test Plan
- 初始化测试：`llmwiki init` 后目录、配置、数据库 schema、初始 Markdown 文件都存在。
- 导入测试：Markdown、网页、文本 PDF 能生成 raw/normalized/source metadata；重复 source 通过 hash 检出。
- Ingest 测试：给定样例 source，生成 staging run，包含 claims、triage、候选 patch，不直接修改 wiki。
- Apply 测试：应用候选 patch 后 index/log/catalog 同步更新，Git diff 可读。
- Lint 测试：能发现断链、孤页、重复 alias、缺 citation、source hash drift。
- Query 测试：回答只能使用检索到的 wiki/claim/source context，并输出引用。
- 回归样例：准备 3 篇互相重叠/矛盾的小文章，用来验证实体合并、冲突保留和综合页更新。

## Assumptions
- 第一版面向个人研究库，不做团队权限、多人审批、云同步或 Web UI。
- 第一版使用 Python CLI；Obsidian 只是 Markdown 浏览器，不开发 Obsidian 插件。
- 第一版支持 Markdown、网页、文本 PDF；图片和扫描 PDF 只作为附件记录。
- 第一版由本地 agent 或 Codex/Claude 执行 LLM 写作步骤，CLI 负责约束、索引、审计和落盘保护。
- 数据库是辅助索引，不是知识源；真正可读、可迁移的知识仍保存在 Markdown 和 raw sources 中。
