# LLM Wiki

LLM Wiki 是一个本地优先、source-backed 的研究 wiki 编译器。它不是自由笔记文件夹，而是把资料导入、解析、LLM 抽取、staging 校验、Markdown wiki 生成、SQLite catalog 索引、检索问答和 synthesis 写回串起来的知识工作流。

核心原则：

- 原始资料保留在 `sources/raw/`，导入后不应被修改。
- LLM 不能直接写正式 `wiki/` 页面。
- 所有候选知识变化先进入 `staging/<run-id>/`。
- 只有通过安全校验的 `apply` 才能写入 `wiki/`、`wiki/index.md`、`wiki/log.md` 和 `state/catalog.sqlite`。
- 每条正式 claim 必须能追溯到 source locator。Markdown/text 使用 `line:N`，PDF 使用 page/block locators，例如 `page:1;block:src_xxx_p001_b0004;section:Abstract`。
- `weak/uncited` evidence 必须保留可见，但不能升级成强结论。
- `contradicts` 只表示 source-backed claims 之间的真实 disagreement。否定句、限制句、提醒句本身不是 contradiction。

## 快速开始

安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

如果只运行 CLI，可以使用：

```powershell
python -m pip install -e .
```

初始化工作区：

```bash
llmwiki init --root .
```

配置 API Key：

```powershell
Copy-Item config\api-keys.example.toml config\api-keys.toml
notepad config\api-keys.toml
```

`config/api-keys.toml` 是本地忽略文件，不要提交。示例：

```toml
[llm]
api_key = "你的 DeepSeek API Key"

[embedding]
api_key = "你的 DashScope Embedding API Key"
```

测试 LLM Provider：

```bash
llmwiki llm-test --root .
```

导入资料并生成 wiki：

```bash
llmwiki add docs/example.md --root .
llmwiki add docs/papers/example.pdf --root .
```

提问：

```bash
llmwiki ask "这个资料说明了什么？" --root .
```

预览或写回 synthesis：

```bash
llmwiki ask "这个资料说明了什么？" --root . --preview-writeback
llmwiki ask "这个资料说明了什么？" --root . --writeback
llmwiki ask "这个资料说明了什么？" --root . --writeback --writeback-mode update
```

检索 evidence：

```bash
llmwiki retrieve "retrieval citation anchors" --root . --json
llmwiki retrieve "retrieval citation anchors" --root . --format prompt
llmwiki query "retrieval citation anchors" --root .
```

维护检查：

```bash
llmwiki lint --root .
llmwiki doctor --root .
llmwiki clean --root .
llmwiki clean --root . --scope all
```

本地只读 dashboard：

```bash
llmwiki ui --root .
llmwiki ui --root . --no-open --port 8765
```

## 工作区结构

- `config/config.toml`：工作区主配置。
- `config/api-keys.example.toml`：API key 示例，可提交。
- `config/api-keys.toml`：本地 API key，已被 `.gitignore` 忽略。
- `sources/raw/`：原始 Markdown、文本 PDF、纯文本和网页快照。
- `sources/normalized/`：规范化 Markdown，包含 line/page/block anchors。
- `sources/metadata/`：PDF metadata sidecars，本地生成态，不提交。
- `sources/blocks/`：PDF block JSONL sidecars，本地生成态，不提交。
- `sources/chunks/`：PDF chunk JSONL sidecars，本地生成态，不提交。
- `sources/parser-artifacts/`：MinerU 等 parser backend 的原生产物，本地生成态，不提交。
- `staging/<run-id>/`：候选 claims、triage、patches、LLM proposal 和 run manifest。
- `state/catalog.sqlite`：可重建 catalog 缓存。
- `state/embeddings/`：可重建本地 vector index 缓存。
- `wiki/sources/`：source 摘要页。
- `wiki/concepts/`：concept 页面。
- `wiki/entities/`：entity 页面。
- `wiki/syntheses/`：synthesis 页面。
- `wiki/index.md`：wiki 索引。
- `wiki/log.md`：append-only apply 日志。
- `llmwiki/`：CLI 和核心实现。
- `tests/`：测试、fixtures 和 eval datasets。

## 正常数据流

`llmwiki add <source> --root .` 是正常资料导入入口：

1. 复制资料到 `sources/raw/`。
2. 生成 `sources/normalized/`。
3. 对 PDF 生成 metadata、blocks、chunks sidecars。
4. 调用配置好的 LLM 做 ingest。
5. 生成 `staging/<run-id>/claims.jsonl`、`triage.md`、`llm-proposal.json`、`run.json` 和 `patches/`。
6. 运行安全校验。
7. apply 到 `wiki/` 和 `state/catalog.sqlite`。

`run.json` 会记录 `proposal_engine=llm`、provider、model 和 `trigger=add`。PDF source 还会记录 `source_parse_schema`、`source_chunk_schema`、page/block/chunk counts、sidecar paths、parser backend diagnostics 和 `parser_backend_attempts`。

`llm-proposal.json` 保存 LLM Ingest Proposal 的调试信息，但不能包含 API key、完整敏感 prompt 或未脱敏日志。

## CLI 命令

### 正常命令

```bash
llmwiki init --root .
llmwiki add docs/example.md --root .
llmwiki ask "问题" --root .
llmwiki retrieve "问题" --root . --json
llmwiki query "问题" --root .
llmwiki lint --root .
llmwiki doctor --root .
llmwiki clean --root .
llmwiki ui --root .
```

`llmwiki ask` 会先调用 LLM query planning，再使用本地 retrieve 从 wiki/catalog 检索证据，最后只基于 retrieved evidence 生成 grounded answer。默认不写回 wiki。

`llmwiki retrieve` 是外部 RAG 系统、Agent 和 LLM prompt 的标准 evidence API。`llmwiki query` 是同一路径的人类可读输出，不维护另一套弱检索。

`llmwiki clean --root .` 默认只清理测试缓存和临时验收工作区；`llmwiki clean --root . --scope generated` 清理生成态 source/wiki/staging/state/vector cache；`--scope all` 同时清理两类内容。`--dry-run` 可先预览将删除的路径。该命令会保留 `.gitkeep`、`config/api-keys.toml`、`docs/papers/`、`.venv/` 和用户资料。

## V3.1 Local UI

`llmwiki ui --root .` 启动绑定 `127.0.0.1` 的本地 read-only dashboard。它直接读取 workspace skeleton、catalog、staging runs、PDF sidecars、parser 状态、LLM/embedding 配置状态和 vector index 状态，用于快速判断当前 workspace 是否 ready、有哪些 sources、最近 runs 和 wiki pages。

V3.1 UI 只提供观察面，不提供操作面。Dashboard/API 不执行 `add`、`ingest`、`apply`、`ask`、`lint`、`eval`、`clean`，不运行 LLM、embedding provider、MinerU 文档解析或 PDF parser，也不写 `wiki/`、`staging/`、`sources/`、`state/catalog.sqlite` 或 `state/embeddings/`。

UI API 包括：

```text
/api/status
/api/sources
/api/runs
/api/pages
/api/config
```

当前 UI 响应使用 `schema_version="ui.v3.4"`，并且只报告 API key 是否存在，不返回 API key 值、`config/api-keys.toml` 内容、raw prompt、raw LLM response 或完整 parser logs。

## V3.2 Source Library

V3.2 在 `llmwiki ui --root .` 中增加 Source Library。用户可以在 dashboard 中提交一个 source path 或 URL，UI 会创建 `add_source` job，并在 Jobs 表中展示 `pending`、`running`、`applied`、`failed`、`interrupted` 状态。Job state 是 generated local state，位于 `state/ui-jobs/`，schema 为 `ui_job.v3.2`。

V3.2 唯一可写 UI endpoint 是 `POST /api/sources/add`。它要求 `/api/session` 返回的本进程 `X-LLMWiki-UI-Token`，只负责校验输入、写入 UI job，并由 FIFO worker 顺序调用现有 `add_and_process_source(...)` pipeline。UI 层不得直接写正式 `wiki/` 或 `state/catalog.sqlite`；formal knowledge 仍必须通过 source import、LLM ingest、staging validation 和 apply。

V3.2 只支持单个 source path/URL。批量/目录导入、retry/cancel、claim browser 和细粒度 parser/LLM/apply progress 留给后续 V3/V4 spec。

## V3.3 Ask And Synthesis UI

V3.3 在 `llmwiki ui --root .` 中增加 Ask And Synthesis UI。用户可以在本地 dashboard 中提交问题，UI 会创建 `ask_question` job，由 FIFO worker 调用既有 `answer_question(...)`，并展示 answer、analysis、citations、retrieved evidence、warnings、uncertainties、conflicts 和 query planning diagnostics。

V3.3 新增 token-protected endpoints：

```text
POST /api/ask
GET /api/ask/jobs
GET /api/ask/jobs/<job-id>
POST /api/ask/<job-id>/synthesis/preview
POST /api/ask/<job-id>/synthesis/writeback
```

Synthesis preview 是只读的：它只调用 synthesis planner，生成 preview job，不创建 staging，不写 `wiki/`、`sources/`、`state/catalog.sqlite`。Synthesis writeback 必须由用户显式触发，并且只通过现有 `create_synthesis_run(...)` staging/apply 路径执行。Planner output 和 synthesis plan output 都不是 evidence；UI 中的 Retrieved Evidence 和 Citations 只显示 catalog-backed claims。

V3.3 job state 仍位于 `state/ui-jobs/`，schema 为 `ui_job.v3.3`。`POST /api/sources/add`、`POST /api/ask`、synthesis preview/writeback 都要求本进程 `X-LLMWiki-UI-Token`。GET endpoints 仍保持只读。

## V3.4 Evidence And Wiki Browser

V3.4 在 `llmwiki ui --root .` 中增加只读 Evidence/Wiki Browser。用户可以从 Ask citations 或 retrieved evidence 跳转到 claim detail，检查 `claim_id`、`source_id`、`page_id`、`citation_locator`、`confidence_status` 和 `relationship_type`，也可以浏览 source/concept/entity/synthesis/index 页面。

V3.4 新增 read-only GET endpoints：

```text
GET /api/sources/<source-id>
GET /api/pages/<page-id>
GET /api/evidence/claims
GET /api/evidence/claims/<claim-id>
GET /api/evidence/relationships
```

这些 GET endpoints 只读取 catalog、catalog-referenced wiki markdown、`sources/metadata/`、`sources/blocks/`、`sources/chunks/` 和 UI job summaries。它们不得调用 LLM、embedding provider、MinerU、PDF parser、retrieve、ask、synthesis、add/ingest/apply、lint/eval/clean，也不得写 `wiki/`、`sources/`、`staging/`、`state/catalog.sqlite`、`state/embeddings/` 或 `state/ui-jobs/`。

V3.4 中 page markdown 是页面文本，不是 formal evidence。只有 catalog-backed claims 和 catalog relationships 是 evidence；synthesis markdown 段落不会被升级为 claims。Markdown/text `line:N` 和 PDF `page:N;block:<block-id>` locator 可显示 bounded context；unsupported locator、missing sidecar、malformed sidecar 只产生 warning，不伪造证据。

## V4.1 Corpus Import Queue

V4.1 新增 CLI-first 的语料导入队列，用于把同领域论文或资料按顺序批量交给现有 `add_and_process_source(...)` pipeline。它只做 batch orchestration，不改变 ingest、staging、apply 语义，不新增 UI，也不做 metric/result extraction。

常用命令：

```bash
llmwiki corpus import docs/papers --root . --dry-run
llmwiki corpus import docs/papers --root . --recursive --parser auto
llmwiki corpus status --root .
llmwiki corpus status <batch-id> --root . --json
llmwiki corpus retry <batch-id> --root . --failed-only
llmwiki corpus skip <batch-id> <item-id-or-path> --root . --reason "out of scope"
```

Batch state 是 generated cache，位于 `state/corpus-batches/`：

```text
state/corpus-batches/<batch-id>/batch.json
state/corpus-batches/<batch-id>/items.jsonl
state/corpus-batches/<batch-id>/attempts.jsonl
state/corpus-batches/<batch-id>/events.jsonl
```

`corpus import --dry-run` 和 `corpus status` 是只读操作，不调用 LLM、parser、add/apply，也不写 `state/corpus-batches/`。真实 `corpus import` / `corpus retry` 只通过现有 `add_and_process_source(...)` 写正式知识；corpus layer 不直接写 `wiki/`、`staging/`、`sources/` 或 `state/catalog.sqlite`。URL batch import is out of scope；URL 仍使用单源 `llmwiki add`。

### Internal/debug 命令

```bash
llmwiki ingest <source-id> --root .
llmwiki review <run-id> --root .
llmwiki review <run-id> --detail --root .
llmwiki review <run-id> --patches --root .
llmwiki apply <run-id> --root .
```

这些命令用于内部调试和恢复。正常用户不需要手工运行 `ingest/review/apply`。

review/apply v2 状态包括 `staged`、`reviewed`、`applied`。`review` 是只读检查命令；`apply` 会做安全校验并在更新已有页面前写入 `backups`。

### Embeddings 命令

```bash
llmwiki embeddings status --root .
llmwiki embeddings test --root . --text "草莓应该怎么保存？"
llmwiki embeddings rebuild --root . --batch-size 16
```

`embeddings rebuild` 从 catalog 构建 claim/page/source title chunks，调用 embedding provider，并写入 `state/embeddings/`。这是可重建缓存，不是 durable knowledge。

### Parser 命令

```bash
llmwiki parsers status --root .
llmwiki parsers status --root . --json
```

`llmwiki parsers status` 是只读环境检查。它不会解析 PDF，不调用 LLM，不调用 embedding provider，不运行 MinerU 文档解析，也不写 workspace。

## LLM Provider

LLM Provider 读取 `config/config.toml` 的 `[llm]`：

```toml
[llm]
enabled = true
provider = "openai"
model = "deepseek-v4-flash"
base_url = "https://api.deepseek.com"
api_key_file = "config/api-keys.toml"
timeout_seconds = 60
```

`config/api-keys.toml` 中的 `[llm].api_key` 才是真实密钥位置。不要把密钥写进 `config/config.toml`、README、测试、源码、日志、staging artifact 或提交历史。

代码层统一接口是：

```python
provider.complete(messages, schema=None)
```

当传入 `schema` 时，会要求 JSON object 输出，但仍需要项目自己的 schema validation 和 repair。

## Retrieval Layer v2.7

`llmwiki retrieve` 是 RAG/Agent evidence layer。它返回本地 catalog 中真实存在的 claims、citations、page paths、relationships、scores、retrieval reasons、reranking diagnostics 和 selection diagnostics。

检索信号包括：

- SQLite FTS/BM25。
- catalog title、alias、source title matching。
- one-hop graph relationships。
- exact formula/symbol spans。
- V2.6 local vector recall。
- RRF fusion。
- V2.7 reranking。
- V2.7 evidence selection。

JSON 示例：

```json
{
  "question": "...",
  "schema_version": "retrieval.v2.7",
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
      "retrieval_reasons": ["bm25:term=rag"],
      "candidate_rank": 1,
      "rerank_score": 0.0,
      "selection_reason": "best_for_coverage",
      "coverage_group": "source:src_xxx",
      "redundancy_group": "..."
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
    "retrievers": {},
    "fusion": {},
    "reranking": {},
    "selection": {}
  }
}
```

Python API：

```python
from pathlib import Path
from llmwiki.retrieval import retrieve_context

context = retrieve_context(Path("."), "RAG 为什么需要引用锚点？", limit=8)
```

`retrieve/query/eval retrieval` 默认不调用 chat LLM。启用 embedding 且存在本地 vector index 时，它们可能调用 embedding provider 生成 query embedding；失败时会 fallback 并给出 warning。

## Retrieval Evaluation

`llmwiki eval retrieval` 是检索改造的质量检查命令：

```bash
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_3.jsonl
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_4_fruits.jsonl
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_6_semantic_fruits.jsonl
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_7_evidence_selection_fruits.jsonl
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_9_1_pdf_foundation.jsonl
```

它读本地 catalog 和 committed JSONL 数据集，不调用 LLM，不写 `wiki/`、`staging/`、`sources/` 或 catalog。

指标包括 hit@5、recall@5、precision@5、MRR、nDCG@5、MAP@5、coverage、source diversity、redundancy rate、selected conflict exposure、weak evidence visibility，以及 claim/source/page/locator/relationship validity。

## Ask + Query Planning + Synthesis

`llmwiki ask` 的流程：

```text
question
-> LLM query planner
-> local retrieve_context
-> grounded answer LLM
-> optional synthesis writeback
```

Planner output is not evidence。它只能提供 intent、entities、concepts、subqueries、filters 和 required evidence 描述。`claim_id`、`source_id`、`citation_locator`、`page_path`、relationship 和 score 只能来自本地 catalog/retrieve。

Synthesis planning output is not evidence。Evidence map 只能引用已有 catalog claims。

Synthesis pages are living wiki pages，不是聊天记录归档。V2.8 synthesis 页面包含：

- `Scope`
- `Current Answer`
- `Evidence Map`
- `Analysis`
- `Conflicts And Limits`
- `Open Questions`
- `Related Pages`
- `Revision History`

重复问题应更新已有 synthesis 页面，而不是创建近重复页面。

## PDF 解析

### V2.9.2 PDF Quality

文本 PDF 会被解析为 metadata、blocks、chunks：

- `sources/metadata/<source_id>.json`
- `sources/blocks/<source_id>.jsonl`
- `sources/chunks/<source_id>.jsonl`

PDF normalized Markdown 从 blocks 渲染，使用稳定 block anchors：

```markdown
<!-- block:src_xxx_p001_b0004; page:1; type:abstract; section:Abstract -->
```

PDF claims 必须使用 page/block locators。裸 `line:N` 对 Markdown/text 仍有效，但不能作为 PDF claim 的正式引用。

`content_role="ignored"` 的 blocks 会保留在 sidecar 里用于审计，但不会进入 normalized body 或 LLM chunk claim-extraction prompts。

```bash
llmwiki eval pdf-quality --root .
llmwiki eval pdf-quality --root . --json
```

`llmwiki eval pdf-quality` 是 deterministic、read-only、no-LLM、no-embedding、no-network、no-MinerU-execution 的质量检查。

### V2.9.3 PDF Ingest Robustness

PDF chunk ingest 和 consolidation 有一次 schema-aware JSON repair。JSON repair 只能修复 JSON syntax/shape，不能创建 evidence、block ids、locators、claims 或 citations。

Malformed LLM JSON 不会持久化。`llm-proposal.json`、`run.json`、`triage.md` 和 `review --detail` 只记录 repair counts 和脱敏 repair events。

PDF source title 是 metadata，不是 formal alias。source page 的 formal alias 只保留 `source_id`；论文标题通过 `sources.title` 和 `pages.title` 被检索。

### V2.9.4 Parser Backend And MinerU Adapter

PDF import 有 parser backend 边界。Parser backend output is not wiki knowledge。MinerU 的 tables、formulas、images、captions 和 layout data 可以被规范化为 LLMWiki blocks/chunks，但只有经过 LLM ingest 抽取、带合法 page/block locator 的 catalog claims 才是 evidence。

V2.9.4 不实现 scanned PDF OCR、table cell-level evidence、figure understanding、equation semantic interpretation、新数据库表或 `page_type="paper"`。

### V2.9.5 MinerU Auto Parser Notes

PDF parser defaults to `auto`。当 MinerU 可用且启用时，`llmwiki add <pdf> --root .` tries MinerU first；如果 MinerU 不可用或失败，auto 会 fallback 到 `pypdf` 并记录可见 warning。

显式 `--parser mineru` 是 strict，失败时不 fallback。显式 `--parser pypdf` 是 debug/fallback path，会跳过 MinerU。

### V2.9.6 MinerU Operational Hardening

`llmwiki parsers status --root . --json` 输出 `parser_status.v2.9.6`，包含 `mineru_command_source`。

命令发现顺序：

1. 显式配置的 command path。
2. PATH。
3. workspace `.venv`。
4. repo `.venv`。

它不会修改 PATH，不会自动安装 MinerU。

当 auto 先尝试 MinerU 后 fallback 到 pypdf，PDF metadata 会记录 `parser_backend_attempts`：失败的 MinerU attempt 和成功的 pypdf attempt。它们会出现在 `run.json`、`triage.md`、source pages、`llmwiki lint` 和 `llmwiki eval pdf-quality` 中，但只是 diagnostics，不是 evidence。

Parser stdout/stderr snippets 必须 bounded and secret-safe。API key、`config/api-keys.toml`、完整 parser logs 和 backend-native artifacts 都不能提交。

## Embeddings + Vector Store

V2.6 增加 `[embedding]` 配置和 DashScope multimodal embedding provider：

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

Vector retrieval 是召回信号，不是 evidence 来源。命中的 vector chunk 必须映射回真实 catalog claim，才能进入 `retrieve/query/ask` 输出。

## Obsidian 和 Git

可以用 Obsidian 打开仓库根目录或 `wiki/` 目录浏览 Markdown。建议始终使用 Git 管理仓库，这样 raw sources、normalized sources、staging review 和已 apply 的 wiki 历史都可审计。

## 支持内容

- Markdown 和纯文本资料导入。
- 可访问 HTTP/HTTPS URL 的网页快照导入。
- 文本 PDF 导入。
- PDF metadata/block/chunk sidecars。
- MinerU auto parser backend 和 pypdf fallback。
- DeepSeek OpenAI-compatible LLM Provider。
- `llmwiki add` 自动完成导入、LLM ingest、staging validation 和 apply。
- `llmwiki ask` 使用 LLM query planning + local retrieve + grounded answer。
- `llmwiki ask --writeback` 通过 staging/apply 生成 synthesis 页面。
- `llmwiki retrieve` / `llmwiki query` 混合检索和 citation-backed evidence。
- `llmwiki ui` 本地 workspace dashboard、Source Library、Ask UI 和 synthesis preview/writeback UI。
- `llmwiki eval retrieval` 本地评测检索质量。
- `llmwiki embeddings test/rebuild/status` 管理本地可重建 vector index。
- claim-first staging。
- source summary、concept、entity 和 synthesis Markdown 页面。
- SQLite catalog 索引 source、claim、page、link 和 relationship。

## 不支持内容 (not supported)

- 外部 hosted vector DB 作为默认基础设施。
- MCP server 集成。
- 批量 source import / retry / cancel 的交互式 Web UI。
- Obsidian plugin。
- 云同步。
- 团队权限系统。
- 扫描 PDF OCR。
- table cell-level evidence。
- figure understanding。
- equation semantic interpretation。
- 自动裁决来源冲突。
- LLM 绕过 staging/apply 直接修改正式 wiki。
