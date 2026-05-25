# LLM Wiki

LLM Wiki 是一个本地优先的个人研究库：用 Python CLI 管理资料导入、claim 抽取、staging 审阅、Markdown wiki 落盘和 SQLite 索引。它的定位是 source-backed knowledge compiler，而不是自由笔记文件夹。

核心原则是：`sources/raw/` 下的原始资料不可变；`ingest` 只能在 `staging/<run-id>/` 里提出候选 claims 和 wiki patch；只有 `llmwiki apply` 才能把审阅后的内容写入 `wiki/` 并同步 `state/catalog.sqlite`。

## 目录结构

- `sources/raw/`：原始 Markdown、文本 PDF、纯文本和网页快照。
- `sources/normalized/`：带行号、页码或段落锚点的规范化 Markdown。
- `state/catalog.sqlite`：可重建的索引和审计缓存，保存 source、claim、alias、page、link、relationship、ingest run。
- `wiki/index.md`：wiki 入口索引。
- `wiki/log.md`：append-only apply 日志。
- `wiki/sources/`：单篇资料摘要页。
- `wiki/concepts/`：概念页。
- `wiki/entities/`：实体页。
- `wiki/syntheses/`：综合分析页。
- `staging/<run-id>/`：每次 ingest 的 `triage.md`、`claims.jsonl` 和 `patches/`。
- `llmwiki/`：CLI 和核心实现。
- `tests/`：自动化测试和回归样例。

## 安装

需要 Python 3.10 或更高版本。在仓库根目录执行：

```bash
python -m pip install -e .
```

第一版只使用小型依赖集合。`pypdf` 用于文本 PDF 抽取；扫描版 PDF OCR 不支持。

## CLI 用法

```bash
llmwiki init --root .
```

创建工作区目录、默认配置、agent contract、wiki index/log 和 SQLite schema。

```bash
llmwiki add tests/fixtures/minimal_source.md --root .
```

把资料复制到 `sources/raw/`，在 `sources/normalized/` 生成带引用锚点的规范化 Markdown，计算 SHA-256，并按 hash 去重。

```bash
llmwiki ingest <source-id> --root .
```

先抽取带引用的 claims，再执行简单的 identity/conflict 检查，只写入 `staging/<run-id>/`，不会修改正式 `wiki/`。

```bash
llmwiki review <run-id> --root .
```

review/apply v2 中，`review` 是只读审阅命令：展示 run_id、source_id、状态、创建时间、claim 数、patch 数、citation 覆盖率、triage 摘要、claims 表、patch 表、新增/更新页面、duplicate candidates、conflict candidates 和 weak/uncited claims。它只读取 `staging/` 和 SQLite，不会修改 `wiki/`、`wiki/index.md`、`wiki/log.md` 或 `state/catalog.sqlite`。

```bash
llmwiki review <run-id> --detail --root .
```

展示完整 claims、triage 细节和引用覆盖情况。

```bash
llmwiki review <run-id> --patches --root .
```

展示每个候选 Markdown patch 的完整内容，方便在 apply 前审阅页面正文。

```bash
llmwiki apply <run-id> --root .
```

校验 staged patch 安全性，写入 `wiki/` 下的 Markdown 页面，刷新 `wiki/index.md`，追加 `wiki/log.md`，并同步 SQLite 中的 claims、pages、links、relationships 和 runs。当前实现允许 `staged` 或 `reviewed` 状态进入 apply；还没有强制单独的 reviewed 命令，所以 apply 前的人工确认依赖用户运行 `review`、`review --detail` 或 `review --patches`。apply 成功后，SQLite 和 staging manifest 中的 run 状态会变为 `applied`。

apply 安全校验包括：

- 只能写入 `wiki/`，不能写入 `sources/raw/` 或 `sources/normalized/`。
- 不能删除页面，不能重写 `wiki/log.md` 历史。
- Markdown 必须有合法 frontmatter，包含 `page_type`、`title`、`aliases`、`source_count`、`claim_ids`、`updated_at`。
- `page_type` 必须是 `source`、`concept`、`entity` 或 `synthesis`。
- 页面必须包含该类型要求的章节。
- patch 引用的 `claim_ids` 必须存在于 staging claims 或数据库。
- 重要内容不能全部来自 weak/uncited claim；没有 cited claim 的 patch 会被拒绝。
- 目标页已存在时，apply 会先把旧页面写入 `staging/<run-id>/backups/`，再执行更新。第一版采用 recoverable backups，不做语义级合并。

```bash
llmwiki query "retrieval citation anchors" --root .
```

优先使用 SQLite FTS/BM25 检索 claim store，必要时回退到简单文本检索，输出带 `source_id` 和 citation locator 的 retrieval context。第一版不会调用外部 LLM API。

```bash
llmwiki lint --root .
```

检查断链、孤页、重复 alias、无引用 claim、source hash drift、缺 citation 状态和潜在矛盾。

lint 会区分已经记录的 `contradicts` relationships 和未处理的潜在矛盾。已记录冲突是审计信息，不会自动让 lint 失败；未处理的潜在矛盾仍然需要进入 triage 或 relationship。

```bash
llmwiki doctor --root .
```

检查 Python、依赖、工作区目录、配置、数据库 schema 和 wiki index/log。

## Obsidian 与 Git

可以在 Obsidian 中打开仓库根目录或 `wiki/` 目录来浏览 Markdown 页面。建议始终用 Git 管理仓库，这样 raw sources、normalized sources、staging review 和已 apply 的 Markdown 历史都可审计。

## 支持内容

- Markdown 和纯文本资料导入。
- 可访问 `http`/`https` URL 的网页快照导入。
- 通过 `pypdf` 导入文本 PDF。
- claim-first staging，并为重要 claim 保留引用。
- weak/uncited claim 可以进入 triage，但不能直接成为正式结论。
- 生成 source summary、concept 和 entity Markdown 页面。
- 用 SQLite 索引 source、claim、page、link 和 relationship。

## 不支持内容 (not supported)

- 默认调用外部 LLM API。
- 向量数据库。
- MCP server 集成。
- Web UI 或 Obsidian 插件。
- 云同步。
- 团队权限或多人审阅流程。
- 扫描 PDF OCR。
- 自动裁决资料之间的冲突。
