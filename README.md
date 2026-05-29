# LLM Wiki

## Retrieval Layer v2.6（混合本地检索 + 向量召回）

`llmwiki retrieve` 是外部 RAG 系统、Agent 和 LLM prompt 调用 LLMWiki 的稳定证据接口。它从本地 SQLite catalog 检索 source-backed claims，并返回 citation、page path、relationship type、score、retrieval reasons 和 warning。这个命令使用确定性的混合本地检索，不会调用外部 LLM API。

V2.4 的本地检索信号包括 SQLite FTS/BM25、catalog title/alias/source title、one-hop graph relationship、exact formula/symbol span，并用 RRF 做融合排序。V2.6 在此基础上增加本地可重建 vector index：当 `[embedding].enabled = true` 且 `state/embeddings/` 已存在时，`retrieve` 会调用 embedding provider 生成 query vector，把 vector candidates 作为另一个召回信号参与 RRF。vector 只能帮助召回候选，最终返回的 evidence 仍必须映射回 catalog 中真实存在的 `claim_id`、`source_id`、`citation_locator` 和 `page_path`。

如果 vector index 缺失、过期、维度不匹配或 query embedding 调用失败，`retrieve` 会回退到 BM25/catalog/exact/graph 检索，并在 diagnostics/warnings 中暴露原因。它会做 Unicode-aware normalization，尽量保留中文、多语种、公式、符号和 emoji 查询特征。

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
  "schema_version": "retrieval.v2.6",
  "contexts": [
    {
      "rank": 1,
      "claim_id": "...",
      "source_id": "...",
      "citation_locator": "line:5;section:...;paragraph:1",
      "claim_text": "...",
      "page_path": "wiki/sources/src_xxx.md",
      "page_type": "source",
      "relationship_type": "supports",
      "confidence_status": "cited",
      "score": 0.0,
      "retrieval_reasons": ["bm25:term=rag"]
    }
  ],
  "relationships": [],
  "warnings": [],
  "diagnostics": {
    "query_terms": [],
    "candidate_count": 0,
    "returned_count": 0,
    "failure_stage": null,
    "query_features": {},
    "retrievers": {
      "vector": {
        "enabled": true,
        "index_present": false,
        "query_embedded": false,
        "candidate_count": 0,
        "provider": "dashscope_multimodal",
        "model": "tongyi-embedding-vision-flash-2026-03-06",
        "dimension": 768,
        "failure_stage": "missing_index"
      }
    },
    "fusion": {}
  }
}
```

作为 RAG/Agent evidence layer，LLMWiki 应该在生成前被调用。调用方把返回的 evidence 交给模型，并要求回答中的关键结论引用 `source_id + citation_locator`。如果 `warnings` 提示证据不足、weak/uncited claim 或 `contradicts` relationship，模型应暴露这种不确定性，而不是编造答案。

`contradicts` 表示 source-backed claims 之间存在真实 disagreement。否定句、提醒句、限制句本身不是矛盾，例如“不建议多吃”“不需要提前清洗”这类 claim 会作为普通 evidence 保留，不会因为包含否定词自动变成 `contradicts` relationship。`retrieve` 只暴露 catalog 中已有的 relationships，不负责从文本关键词判断矛盾。

当前检索限制：V2.6 有本地 JSONL vector index，但没有外部 hosted vector DB、reranker 或 vector-only answer generation。`retrieve`、`query`、`eval retrieval` 不调用 chat LLM；在 embedding 启用且本地 index 存在时，它们可能调用 embedding provider 做 query embedding。LLM query planning 只接入 `ask`。`query` 是 `retrieve` 的人类可读输出，不另起一套弱检索。

## Retrieval Evaluation v2.3+（检索评测）

`llmwiki eval retrieval` 是开发和质量检查命令，用 committed JSONL 数据集评测当前检索层的召回、排序、证据契约和失败阶段。它默认不调用 LLM，不写 `wiki/`、`staging/`、`sources/` 或 catalog，只读取本地 workspace。

```bash
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_3.jsonl
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_3.jsonl --json
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_4_fruits.jsonl
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_6_semantic_fruits.jsonl
```

评测输出包含 `hit@5`、`recall@5`、`precision@5`、`MRR`，以及 LLMWiki 特有的 `claim_id_validity`、`source_id_validity`、`citation_locator_presence`、`page_path_validity`、`relationship_validity` 和 `contradiction_exposure_rate`。

V2.3 建立了测量层；V2.4 在此基础上替换为混合本地检索；V2.6 增加 vector diagnostics 和语义检索回归数据。后续修改检索、query planning、vector search 或 reranker 前后，都应该运行该 eval 命令并比较结果。

## LLM Provider v1

LLM Provider 层用于让 LLMWiki 调用真实 LLM。当前默认启用 DeepSeek OpenAI-compatible API，主配置来自 `config/config.toml` 的 `[llm]`：

```toml
[llm]
enabled = true
provider = "openai"
model = "deepseek-v4-flash"
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

[embedding]
api_key = "你的真实 DashScope Embedding API Key"
```

设置后可以测试 provider：

```powershell
llmwiki llm-test --root .
```

`llmwiki llm-test --root .` 会读取 `[llm]` 配置并真实调用 DeepSeek API，输出 provider、model、base_url、`real_call=true` 和返回内容摘要，但不会输出 API Key。可临时覆盖模型、base URL 或超时：

```powershell
llmwiki llm-test --root . --model deepseek-v4-flash --base-url https://api.deepseek.com --timeout 60
```

代码层统一接口是 `provider.complete(messages, schema=None)`，其中 `messages` 使用 OpenAI Chat Completions 风格。provider 默认请求 `thinking = {type = "disabled"}`，避免普通抽取任务进入长推理路径；当传入 `schema` 时会请求 `response_format = {"type": "json_object"}`，但不声称强制执行完整 JSON Schema。

本阶段只建立真实 LLM 调用层。LLM 输出不得直接修改正式 wiki 页面；正常导入由 `llmwiki add` 自动生成 staging、执行安全验证、再通过 `apply` 写入 wiki/catalog。当前没有 mock provider，也没有 no-network 测试路径。

## Embeddings + Vector Store v2.6

V2.6 增加独立的 `[embedding]` 配置和 DashScope multimodal embedding provider。默认模型是 `tongyi-embedding-vision-flash-2026-03-06`，使用 DashScope 原生 multimodal endpoint，不使用 OpenAI-compatible `/embeddings` endpoint。

```toml
[embedding]
enabled = true
provider = "dashscope_multimodal"
model = "tongyi-embedding-vision-flash-2026-03-06"
endpoint_url = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
api_key_file = "config/api-keys.toml"
dimension = 768
timeout_seconds = 60
```

embedding key 只放在本地忽略文件 `config/api-keys.toml` 的 `[embedding].api_key`。不要写入 `config/config.toml`、README、测试、日志或 staging artifact。

```bash
llmwiki embeddings test --root . --text "草莓应该怎么保存？"
llmwiki embeddings rebuild --root . --batch-size 16
llmwiki embeddings status --root .
```

`embeddings rebuild` 会从 catalog 构建 claim/page/source title chunks，调用 embedding provider，并把可重建缓存写到 `state/embeddings/manifest.json`、`chunks.jsonl`、`vectors.jsonl`。这些文件不是 durable knowledge，已被 `.gitignore` 忽略，可以随时删除后重建。

vector retrieval 是召回信号，不是证据来源。向量相似度命中的 chunk 必须先映射回 catalog 中真实 claim，才能进入 `retrieve/query/ask` 返回结果；answer citation 仍然只能引用 retrieved claim ids、source ids 和 locators。

## LLM Ingest Proposal v1

`llmwiki add <source> --root .` 现在是正常资料导入入口。它会导入并 normalize source，然后调用真实 DeepSeek API，让 LLM 参与 claim 抽取、source summary、concept/entity proposal、duplicate/conflict candidates 生成。LLM 的输出仍然只能先写入 `staging/<run-id>/`：

```text
staging/<run-id>/
  claims.jsonl
  triage.md
  llm-proposal.json
  run.json
  patches/
```

`run.json` 会记录 `proposal_engine=llm`、provider、model 和 `trigger=add`；`triage.md` 会包含 `## LLM Proposal` 调试信息。`add` 不会让 LLM 直接写正式 `wiki/`，也不会在 ingest 阶段修改 `sources/raw/` 或 `sources/normalized/`。只有内部 `apply` 安全校验通过后，候选 patch 才能落入正式 wiki 和 SQLite catalog。

LLM claims 必须带有效 source locator。没有合法 `line:N` 的 claim 会被标记为 weak/uncited，不能进入正式 patch 结论。内部/调试场景仍可直接运行 `llmwiki ingest <source-id> --root .`。需要运行旧的规则化 ingest 时，可以在工作区 `config/config.toml` 中设置：

V2.5.1 禁用自动关键词/否定词矛盾检测。LLM 或人工提出的 conflict candidate 会保留在 triage/open questions 中，只有能够被验证为真实 source-backed claim disagreement 的内容才应成为正式 `contradicts` relationship。

```toml
[llm]
enabled = false
```

## Ask + Query Planning + Synthesis Writeback v2.5

`llmwiki ask` 是正常问答入口。V2.5 中，它先调用配置好的 LLM 生成结构化 query plan，再把 plan 里的 subqueries 交给本地 `retrieve_context` 从 `wiki/` 和 `state/catalog.sqlite` 检索 evidence，最后只基于 retrieved evidence 调用 LLM 生成 grounded answer。答案必须引用 retrieved claim id、source id 和 citation locator；如果证据不足、存在 weak/uncited evidence 或 `contradicts` relationship，输出必须暴露这种不确定性。

```bash
llmwiki ask "RAG 为什么需要引用锚点？" --root .
```

默认情况下，`ask` 只输出答案，不写 wiki。用户确认答案值得保存时，可以显式写回：

```bash
llmwiki ask "RAG 为什么需要引用锚点？" --root . --writeback
```

写回会创建 `staging/<run-id>/`，生成 synthesis patch，并通过 `apply` 安全校验后写入 `wiki/syntheses/*.md`、刷新 `wiki/index.md`、追加 `wiki/log.md`、同步 catalog。LLM 不能直接写正式 wiki 页面。

Planner output 不是 evidence。它只能提供 intent、entities、concepts、subqueries、filters 和 required evidence 描述；claim id、source id、citation locator、page path、relationship 和 score 仍只能来自本地 catalog 检索结果。V2.5 不通过领域关键词规则或 term boost 来修补检索。

机器可读输出：

```bash
llmwiki ask "RAG 为什么需要引用锚点？" --root . --json
```

`retrieve` 仍然是外部系统使用的稳定 evidence API；`query` 是同一 evidence API 的人类可读输出，不调用 LLM。`eval retrieval` 也保持本地确定性。

LLM Wiki 是一个本地优先的个人研究库：用 Python CLI 管理资料导入、claim 抽取、staging 审阅、Markdown wiki 落盘和 SQLite 索引。它的定位是 source-backed knowledge compiler，而不是自由笔记文件夹。

核心原则是：`sources/raw/` 下的原始资料不可变；LLM ingest 只能在 `staging/<run-id>/` 里提出候选 claims 和 wiki patch；只有内部 `apply` 安全校验通过后，内容才能写入 `wiki/` 并同步 `state/catalog.sqlite`。

## 目录结构

- `config/config.toml`：工作区主配置。
- `config/api-keys.example.toml`：API key 配置示例，可提交。
- `config/api-keys.toml`：本地 API key 配置，已被 `.gitignore` 忽略，不应提交。
- `sources/raw/`：原始 Markdown、文本 PDF、纯文本和网页快照。
- `sources/normalized/`：带行号、页码或段落锚点的规范化 Markdown。
- `state/catalog.sqlite`：可重建的索引和审计缓存，保存 source、claim、alias、page、link、relationship、ingest run。
- `state/embeddings/`：V2.6 本地可重建 vector index 缓存，不提交。
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

正常导入入口。该命令会把资料复制到 `sources/raw/`，在 `sources/normalized/` 生成带引用锚点的规范化 Markdown，调用 LLM 生成 staging proposal，自动验证并 apply 到 `wiki/` 和 `state/catalog.sqlite`。成功输出会包含 source id、run id、proposal engine、claims、patches、写入页面和 warnings。

重复导入已完成 apply 的同一 source 时，`add` 会直接提示 wiki 已是最新，不创建重复 run 或重复页面。

```bash
llmwiki ask "retrieval citation anchors" --root .
```

正常问答入口。该命令只从本地 wiki/catalog 检索 evidence，再调用 LLM 生成带 citations 的 answer；默认不写回 wiki。

```bash
llmwiki ask "retrieval citation anchors" --root . --writeback
```

把用户认可的问题结果写回为 synthesis 页面。写回仍然必须经过 `staging/<run-id>/` 和内部 apply 安全校验。

### Advanced/debug commands

```bash
llmwiki ingest <source-id> --root .
```

内部/调试命令。先抽取带引用的 claims，再执行简单的 identity/conflict 检查，只写入 `staging/<run-id>/`，不会修改正式 `wiki/`。

```bash
llmwiki review <run-id> --root .
```

advanced/debug review/apply v2 中，`review` 是只读检查命令：展示 run_id、source_id、状态、创建时间、claim 数、patch 数、citation 覆盖率、triage 摘要、claims 表、patch 表、新增/更新页面、duplicate candidates、conflict candidates 和 weak/uncited claims。它只读取 `staging/` 和 SQLite，不会修改 `wiki/`、`wiki/index.md`、`wiki/log.md` 或 `state/catalog.sqlite`。

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

内部/调试命令。校验 staged patch 安全性，写入 `wiki/` 下的 Markdown 页面，刷新 `wiki/index.md`，追加 `wiki/log.md`，并同步 SQLite 中的 claims、pages、links、relationships 和 runs。当前实现允许 `staged` 或 `reviewed` 状态进入 apply；正常用户不需要手动运行它。apply 成功后，SQLite 和 staging manifest 中的 run 状态会变为 `applied`。

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

复用 `retrieve` 的混合本地检索结果，输出带 `claim_id`、`source_id`、citation locator、page path、relationship type 和 score 的 retrieval context。该命令是确定性的本地上下文命令，不调用外部 LLM API。

```bash
llmwiki embeddings status --root .
llmwiki embeddings test --root . --text "草莓应该怎么保存？"
llmwiki embeddings rebuild --root . --batch-size 16
```

V2.6 embedding 维护命令。`status` 只读本地配置和 `state/embeddings/`，不调用 provider；`test` 真实调用 embedding provider 一次；`rebuild` 从 catalog 重新生成本地 vector index。输出不会打印 API key。

```bash
llmwiki lint --root .
```

检查断链、孤页、重复 alias、无引用 claim、source hash drift 和缺 citation 状态。

lint 是独立维护动作，不属于 `add` 的默认流程。用户可以显式要求 LLM 运行 `llmwiki lint --root .`，或手动运行。lint 会报告已经记录的 `contradicts` relationships；这些记录是审计信息，不会自动让 lint 失败。V2.5.1 不再用 `not`、`不`、`不需要`、`不建议` 这类词面规则推断未处理矛盾。

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
- `llmwiki add` 自动完成单个资料的导入、LLM ingest、staging 验证和 apply。
- `llmwiki ask` 使用 LLM query planning 生成 subqueries，再基于本地 evidence 调用 LLM 生成带 citation 的回答。
- `llmwiki ask --writeback` 通过 staging/apply 生成 synthesis 页面。
- `llmwiki eval retrieval` 用本地 committed eval 数据集检查 retrieval 质量和 evidence contract。
- `llmwiki embeddings test/rebuild/status` 管理本地可重建 vector index。
- `llmwiki retrieve` / `llmwiki query` 使用混合检索，覆盖 BM25、catalog title/alias、graph relationship、formula/symbol exact match 和可选 vector recall。
- claim-first staging，并为重要 claim 保留引用。
- weak/uncited claim 可以进入 triage，但不能直接成为正式结论。
- 生成 source summary、concept 和 entity Markdown 页面。
- 用 SQLite 索引 source、claim、page、link 和 relationship。

## 不支持内容 (not supported)

- 外部托管向量数据库或团队级 vector DB 服务。
- MCP server 集成。
- Web UI 或 Obsidian 插件。
- 云同步。
- 团队权限或多人审阅流程。
- 扫描 PDF OCR。
- 自动裁决资料之间的冲突。
- LLM 直接绕过 staging/apply 修改正式 wiki 页面。
