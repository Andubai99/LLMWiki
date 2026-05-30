# LLMWiki Version Capabilities

本文档汇总项目迄今为止已经实现或纳入当前代码契约的主要版本能力。它只描述现有能力，不把后续规划误写成已完成能力。

## 当前总体能力

LLMWiki 当前是一个本地、source-backed 的研究 wiki 编译器。核心数据流是：

```text
资料导入
-> 文档 normalize
-> LLM ingest / claim 抽取
-> staging
-> apply
-> wiki + catalog
-> retrieve/query/ask
-> 可选 synthesis writeback
```

当前正常入口主要是：

```bash
llmwiki add <source> --root .
llmwiki retrieve "问题" --root . --json
llmwiki query "问题" --root .
llmwiki ask "问题" --root .
llmwiki ask "问题" --root . --writeback
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_7_evidence_selection_fruits.jsonl
```

`ingest`、`review`、`apply` 仍保留为 internal/debug/recovery 命令；正常资料导入不要求用户手动 review/apply。

## V1: 基础 CLI 与 source-backed wiki 骨架

V1 建立了本项目的基础工作区和安全写入模型。

主要能力：

- `llmwiki init` 创建 workspace、目录结构、默认配置、wiki/index/log 和 SQLite catalog。
- `llmwiki add` 早期负责 source import 和 normalize。
- 原始资料进入 `sources/raw/`，normalized source 进入 `sources/normalized/`。
- catalog 使用 SQLite，包含 `sources`、`claims`、`pages`、`aliases`、`links`、`relationships`、`ingest_runs` 等表。
- `ingest` 生成 staged run，不直接写正式 wiki。
- `review` 查看 staging 内容。
- `apply` 通过安全校验后写入 `wiki/`、`wiki/index.md`、`wiki/log.md` 和 catalog。
- `query` 提供早期本地查询能力。
- `lint` 检查 wiki/catalog 健康度。
- `doctor` 检查 workspace 和运行环境。

关键边界：

- 不允许 LLM 或 ingest 直接写正式 wiki。
- 正式 wiki 写入必须经过 staging/apply。
- `sources/raw/` 被视为不可变输入。
- SQLite catalog 是可重建缓存，Markdown wiki 是主要可读成果。

## LLM Provider / LLM Ingest 基础能力

在 V2 主流程之前，项目已经具备真实 LLM 调用和 LLM ingest proposal 能力。

主要能力：

- 使用 `config/config.toml` 配置 LLM provider、model、base URL。
- API key 从本地忽略文件 `config/api-keys.toml` 读取。
- 默认走 OpenAI-compatible DeepSeek provider。
- LLM 输出用于 claim 抽取、source summary、concept/entity proposal、duplicate/conflict candidates。
- LLM proposal 写入 `staging/<run-id>/`，包括 `claims.jsonl`、`triage.md`、`llm-proposal.json` 和 patches。
- LLM 输出不能绕过 staging/apply。
- 无有效 source locator 的 claim 保持 weak/uncited，不能成为正式结论。

关键边界：

- 不提交 API key。
- 不把 API key 写入 README、测试、日志、staging 或 wiki。
- 不提供 public no-network/mock provider 路径；测试可以 monkeypatch provider。

## V2.1: Autonomous Add Pipeline

V2.1 把资料导入从多步开发流程改为用户只需一个入口。

主要能力：

- `llmwiki add <source> --root .` 成为正常资料导入入口。
- 一条命令自动完成：
  - source import
  - normalize
  - LLM ingest
  - staging run creation
  - validation
  - apply
  - wiki/catalog/index/log 更新
- 成功输出 source id、run id、proposal engine、claim count、patch count、applied pages 和 warnings。
- 重复导入已 applied source 时，不重复创建 run 或页面。
- 失败时报告 failed stage、source id、run id 和 debug command。
- `ingest/review/apply` 保留为 internal/debug 命令。

关键边界：

- 取消用户必经的人工 review/apply，但不取消 staging/apply 安全层。
- `add` 默认要求 LLM，不走 public no-LLM 路径。
- `lint` 是独立维护命令，不属于默认 `add` 流程。

## V2.2: Ask + Synthesis Writeback

V2.2 增加基于本地 evidence 的问答和可选写回。

主要能力：

- 新增 `llmwiki ask "问题" --root .`。
- `ask` 先从本地 `wiki + catalog` 检索 evidence，再调用 LLM 回答。
- 回答必须引用 retrieved claim id、source id、citation locator。
- 无 evidence 时不调用 LLM，返回 insufficient evidence。
- LLM 引用未知 claim 时判为 invalid citation，不写 wiki。
- 默认不写回；非交互环境也不自动写回。
- `--writeback` 会把有价值回答写成 synthesis 页面。
- synthesis writeback 仍走 staging/apply。
- synthesis 页面进入 `wiki/syntheses/`，并登记到 catalog `pages/links/aliases`。
- `retrieve` 保持机器 evidence API；`query` 保持本地确定性命令。

关键边界：

- synthesis 不创建新的正式 source-backed claims。
- synthesis 是基于已有 evidence 的组织和解释，不是新的事实来源。
- `ask --writeback` 不能直接修改正式 wiki。

## V2.3: Retrieval Evaluation

V2.3 建立检索质量评测层，为后续 retrieval 改造提供可比较指标。

主要能力：

- 新增 `llmwiki eval retrieval`。
- 使用 JSONL eval dataset 评测当前 `retrieve_context`。
- 支持 human 和 JSON 输出。
- 评测不调用 LLM，不写 `wiki/`、`staging/`、`sources/` 或 catalog。
- retrieval output 增加 diagnostics，例如 query terms、candidate count、returned count、failure stage。
- 初始评测指标包括：
  - `hit@k`
  - `recall@k`
  - `precision@k`
  - `MRR`
  - evidence contract metrics，例如 claim/source/page/relationship validity。
- 支持 no-evidence、relationship miss、contract violation 等 failure stage。

关键边界：

- V2.3 不改检索质量，只建立测量层。
- 后续检索改造应在修改前后跑 eval 对比。

## V2.4: Hybrid Local Retrieval

V2.4 替换早期较弱的规则式本地检索，建立 deterministic hybrid retrieval。

主要能力：

- 新增 Unicode-aware query analysis。
- `retrieve_context` 使用混合本地召回：
  - SQLite FTS/BM25
  - catalog title/alias/source title
  - exact formula/symbol spans
  - one-hop graph relationship expansion
- 使用 RRF 做 hybrid fusion。
- `query` 改为复用 `retrieve`，不再维护另一套弱检索。
- 支持中文、英文、多语种、公式、符号、emoji 等查询特征保留。
- retrieval diagnostics 展示各 retriever 的候选数量和 fusion 信息。
- 增加 V2.4 fruit eval dataset 和自然中文 ask 回归。

关键边界：

- V2.4 不调用 LLM。
- V2.4 不引入 embedding/vector store。
- 不添加水果、维生素、保存等领域专用规则。

## V2.5: LLM Query Planning

V2.5 把 LLM 引入 `ask` 的 query planning，但不让 planner 产生 evidence。

主要能力：

- `ask` 变为 planner-first：
  - LLM planner 生成结构化 query plan。
  - plan 包含 intent、entities、concepts、subqueries、filters、required evidence。
  - 每条 subquery 再交给本地 `retrieve_context`。
  - answer LLM 只能基于 retrieved local evidence 回答。
- planner JSON 经过 schema validation。
- planner 不能输出 claim id、citation locator、page path、score 等 evidence 字段。
- planned retrieval 会合并多条 subquery 的 contexts、relationships、warnings。
- answer citation 仍只能引用 retrieved contexts。
- `retrieve/query/eval retrieval` 仍不调用 chat LLM。

关键边界：

- planner output 不是 evidence。
- planner 不能伪造 source、claim、page、relationship。
- V2.5 不实现 embedding、reranking、vector DB 或 UI。

## V2.5.1: Relationship Semantics Fix

V2.5.1 修复 `contradicts` 的语义，避免把普通否定句误判为冲突。

主要能力：

- 禁用基于 `not`、`不`、`不需要`、`不建议` 等词面的自动矛盾生成。
- negative/caution/limiting claims 仍作为普通 cited claims 保存。
- LLM conflict candidates 保留在 triage/open questions 中，但不自动升级为 formal `contradicts`。
- explicit `contradicts` relationship 仍会被 `retrieve/query/ask/eval` 暴露。
- `lint` 不再从否定词推断 unresolved contradiction。

关键边界：

- V2.5.1 不实现 LLM relationship classifier。
- `contradicts` 只表示 source-backed claims 之间的真实 disagreement。

## V2.6: Embedding + Local Vector Store

V2.6 增加本地可重建 vector index，把 semantic retrieval 作为召回信号。

主要能力：

- 新增 embedding provider 配置 `[embedding]`。
- 默认 embedding provider 为 DashScope multimodal。
- 默认模型为 `tongyi-embedding-vision-flash-2026-03-06`。
- 使用 DashScope 原生 multimodal endpoint。
- 新增 `llmwiki embeddings` 命令组：
  - `embeddings test`
  - `embeddings rebuild`
  - `embeddings status`
- 本地 vector index 存在 `state/embeddings/`：
  - `manifest.json`
  - `chunks.jsonl`
  - `vectors.jsonl`
- 支持 claim、page title、source title 等 text chunks。
- `VectorRetriever` 加入 hybrid retrieval。
- 当 embedding enabled 且 index 存在时，`retrieve/query/ask/eval retrieval` 可调用 embedding provider 做 query embedding。
- vector candidate 必须映射回真实 catalog claim，才能作为 evidence 返回。
- 增加 V2.6 semantic fruit eval dataset。

关键边界：

- 不引入外部 hosted vector DB。
- vector 只是 recall signal，不是 evidence。
- index 是可重建 cache，不提交。
- V2.6 不做 MinerU、OCR、表格、图片 block embedding。

## V2.7: Reranking + Evidence Selection

V2.7 在 hybrid/vector recall 之后增加 reranking 和 evidence selection。

主要能力：

- 新增 reranker 层：
  - deterministic reranker
  - embedding reranker
  - opt-in LLM reranker 接口
- 默认使用 embedding reranker；失败时 fallback 到 deterministic reranker。
- 新增 evidence selector。
- selector 控制：
  - 多 source 覆盖
  - 每 source 最大 contexts 数
  - 重复 claim/text/locator 去重
  - weak/uncited evidence 可见性
  - explicit `contradicts` 冲突证据保留
- `retrieve_context` schema 为 `retrieval.v2.7`。
- context 增加：
  - `candidate_rank`
  - `rerank_score`
  - `selection_reason`
  - `coverage_group`
  - `redundancy_group`
  - `rerank_reasons`
- diagnostics 增加 candidate pool、reranking、selection 信息。
- `ask` 通过 planned retrieval 获得 rerank/selection 后的 selected contexts。
- retrieval eval 增加：
  - `nDCG@5`
  - `MAP@5`
  - `context_precision@5`
  - `context_recall@5`
  - `coverage@5`
  - `source_diversity@5`
  - `redundancy_rate@5`
  - `selected_conflict_exposure_rate`
  - `weak_evidence_visibility_rate`

关键边界：

- reranker/selector 不能创建 evidence。
- 默认不启用 chat LLM reranker。
- 不添加领域关键词规则或 intent classifier。

## V2.7.1: Selection, Planner Repair, Confidence Fix

V2.7.1 是修复版本，解决 V2.7 真实验收中发现的 focused 问题、多样性过度、planner repair 和 confidence 语义问题。

主要能力：

- evidence selector 增加通用 selection modes：
  - `focused`
  - `comparison`
  - `conflict`
  - `broad`
- focused 单主题问题在有足够 cited evidence 时，不再为了多样性混入无关 source。
- comparison 问题仍保留多个 source 覆盖。
- conflict 问题仍保留 explicit `contradicts` 证据和 warning。
- `retrieve_context` 支持内部 selection mode hint。
- planned retrieval 的比较型 subquery 会先 focused 检索，再合并多 source 证据。
- planner 对 invalid filter enum，例如 `confidence = "high"`，会触发一次 schema repair。
- 不静默把非法 confidence 映射成 `cited`。
- LLM ingest 对有效 locator-backed claim 归一为 `cited`。
- 无有效 locator 的 claim 保持 weak/uncited。
- `lint` 区分：
  - formal uncited claims without locator
  - uncited-with-locator inconsistency
- V2.7 fruit eval 数据集只保留真实五篇水果文档应满足的 focused/comparison cases；synthetic weak/conflict fixture 分开测试。

关键边界：

- 不新增 retriever、vector store、UI 或数据库表。
- 不改变 `retrieval.v2.7` schema 兼容性。
- 不让 `retrieve/query/eval retrieval` 默认调用 chat LLM。

## 当前尚未实现的后续方向

以下是规划方向，不属于当前已实现能力：

- V2.8 Synthesis Quality：让 synthesis 页面可更新、可去重、可长期维护，而不只是保存一次问答。
- V2.9 Rich Source Parsing：处理 MinerU、PDF、表格、公式、图片 OCR、多模态 blocks。
- 更强的 relationship classifier：用模型化方式识别真实 claim-level contradictions。
- 完整 usage/cost ledger：记录 Codex 外部 LLM/embedding 调用的 token 和成本。

