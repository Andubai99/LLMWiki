# LLM Wiki

## Retrieval Layer v1（检索层）

`llmwiki retrieve` 是外部 RAG 系统、Agent 和 LLM prompt 调用 LLMWiki 的稳定证据接口。它从本地 SQLite catalog 检索 source-backed claims，并返回 citation、page path、relationship type、score 和 warning。这个命令不会调用外部 LLM API。

面向工具的 JSON 输出：

```bash
llmwiki retrieve "RAG 为什么需要引用锚点？" --root . --json
```

面向 LLM 的 prompt 输出：

```bash
llmwiki retrieve "RAG 为什么需要引用锚点？" --root . --format prompt
```

常用过滤参数：

```bash
llmwiki retrieve "retrieval citation anchors" --root . --json --limit 5
llmwiki retrieve "retrieval citation anchors" --root . --json --source-id src_xxx
llmwiki retrieve "retrieval citation anchors" --root . --json --page-type concept
llmwiki retrieve "retrieval citation anchors" --root . --json --confidence cited
```

Python API：

```python
from pathlib import Path
from llmwiki.retrieval import retrieve_context

context = retrieve_context(Path("."), "RAG 为什么需要引用锚点？", limit=8)
```

JSON schema 会保持稳定，便于外部程序直接解析：

```json
{
  "question": "...",
  "contexts": [
    {
      "claim_id": "...",
      "source_id": "...",
      "citation_locator": "line:5;section:...;paragraph:1",
      "claim_text": "...",
      "page_path": "wiki/sources/src_xxx.md",
      "relationship_type": "supports",
      "score": 0.0
    }
  ],
  "relationships": [],
  "warnings": []
}
```

作为 RAG/Agent evidence layer，LLMWiki 应该在生成前被调用。调用方把返回的 evidence 交给模型，并要求回答中的关键结论引用 `source_id + citation_locator`。如果 `warnings` 提示证据不足、weak/uncited claim 或 `contradicts` relationship，模型应暴露这种不确定性，而不是编造答案。

当前检索限制：SQLite FTS/BM25 仍是词法检索，中文分词能力基础；alias expansion 是规则化实现；本阶段没有 vector store、reranker 或真实 LLM 调用。

## LLM Provider v1

LLM Provider 层用于让 LLMWiki 调用真实 LLM。当前默认启用 DeepSeek OpenAI-compatible API，主配置来自 `config/config.toml` 的 `[llm]`：

```toml
[llm]
enabled = true
provider = "openai"
model = "deepseek-v4-pro"
base_url = "https://api.deepseek.com"
api_key_file = "config/api-keys.toml"
timeout_seconds = 60
```

API Key 必须放在本地专用配置文件 `config/api-keys.toml` 中。这个文件已被 `.gitignore` 忽略，不能提交到仓库、代码、README、测试文件或日志。仓库只提交示例文件 `config/api-keys.example.toml`：

```powershell
Copy-Item config\api-keys.example.toml config\api-keys.toml
notepad config\api-keys.toml
```

`config/api-keys.toml` 格式如下：

```toml
[llm]
api_key = "你的真实 DeepSeek API Key"
```

设置后可以测试 provider：

```powershell
llmwiki llm-test --root .
```

`llmwiki llm-test --root .` 会读取 `[llm]` 配置并真实调用 DeepSeek API，输出 provider、model、base_url、`real_call=true` 和返回内容摘要，但不会输出 API Key。可临时覆盖模型、base URL 或超时：

```powershell
llmwiki llm-test --root . --model deepseek-v4-pro --base-url https://api.deepseek.com --timeout 60
```

代码层统一接口是 `provider.complete(messages, schema=None)`，其中 `messages` 使用 OpenAI Chat Completions 风格。provider 默认请求 `thinking = {type = "disabled"}`，避免普通抽取任务进入长推理路径；当传入 `schema` 时会请求 `response_format = {"type": "json_object"}`，但不声称强制执行完整 JSON Schema。

本阶段只建立真实 LLM 调用层。LLM 输出不得直接修改正式 wiki 页面；任何知识修改仍必须走 `ingest` 生成 staging、人工 `review`、再 `apply` 的流程。当前没有 mock provider，也没有 no-network 测试路径。

## LLM Ingest Proposal v1

`llmwiki ingest <source-id> --root .` 现在会在 `[llm].enabled = true` 时默认调用真实 DeepSeek API，让 LLM 参与 claim 抽取、source summary、concept/entity proposal、duplicate/conflict candidates 生成。LLM 的输出仍然只能写入 `staging/<run-id>/`：

```text
staging/<run-id>/
  claims.jsonl
  triage.md
  llm-proposal.json
  run.json
  patches/
```

`run.json` 会记录 `proposal_engine=llm`、provider 和 model；`triage.md` 会包含 `## LLM Proposal` 审阅信息。`ingest` 不会写正式 `wiki/`，也不会修改 `sources/raw/` 或 `sources/normalized/`。只有 `llmwiki apply <run-id> --root .` 通过安全校验后，候选 patch 才能落入正式 wiki 和 SQLite catalog。

LLM claims 必须带有效 source locator。没有合法 `line:N` 的 claim 会被标记为 weak/uncited，不能进入正式 patch 结论。需要运行旧的规则化 ingest 时，可以在工作区 `config/config.toml` 中设置：

```toml
[llm]
enabled = false
```

LLM Wiki 是一个本地优先的个人研究库：用 Python CLI 管理资料导入、claim 抽取、staging 审阅、Markdown wiki 落盘和 SQLite 索引。它的定位是 source-backed knowledge compiler，而不是自由笔记文件夹。

核心原则是：`sources/raw/` 下的原始资料不可变；`ingest` 只能在 `staging/<run-id>/` 里提出候选 claims 和 wiki patch；只有 `llmwiki apply` 才能把审阅后的内容写入 `wiki/` 并同步 `state/catalog.sqlite`。

## 目录结构

- `config/config.toml`：工作区主配置。
- `config/api-keys.example.toml`：API key 配置示例，可提交。
- `config/api-keys.toml`：本地 API key 配置，已被 `.gitignore` 忽略，不应提交。
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

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

后续本项目的开发、测试和运行都应先激活 `.venv`，再执行 `llmwiki`、`pytest`、`doctor`、`lint` 或其他项目命令。`.[dev]` 会安装运行依赖和测试依赖；如果只运行 CLI，可以使用 `python -m pip install -e .`。

第一版只使用小型依赖集合。`pypdf` 用于文本 PDF 抽取；`pytest` 是开发/测试依赖；扫描版 PDF OCR 不支持。

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
- 默认通过 OpenAI-compatible provider 调用 DeepSeek 真实 API。
- claim-first staging，并为重要 claim 保留引用。
- weak/uncited claim 可以进入 triage，但不能直接成为正式结论。
- 生成 source summary、concept 和 entity Markdown 页面。
- 用 SQLite 索引 source、claim、page、link 和 relationship。

## 不支持内容 (not supported)

- 向量数据库。
- MCP server 集成。
- Web UI 或 Obsidian 插件。
- 云同步。
- 团队权限或多人审阅流程。
- 扫描 PDF OCR。
- 自动裁决资料之间的冲突。
- LLM 直接绕过 staging/review/apply 修改正式 wiki 页面。
