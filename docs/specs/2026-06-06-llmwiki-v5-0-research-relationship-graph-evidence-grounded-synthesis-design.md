# LLMWiki V5.0 Research Relationship Graph And Evidence-Grounded Synthesis Design

Date: 2026-06-06

## 1. 摘要

V5.0 将 LLMWiki 的主轴从“按年份画指标时间线”调整为“跨论文研究关系图谱”。这是因为当前 CUA 语料中的论文大多集中在同一年，强行做按年份演进图会削弱项目价值。更合理的目标是让系统自动识别同领域论文之间的研究关系：哪些论文研究同一任务、使用同一 benchmark、报告可比较指标、复用或扩展方法、比较同一 baseline、解决前人限制，或者存在结果张力。

The core output is source-backed cross-paper relationships, not a loose topic cluster or an ungrounded graph.

V5.0 不是要做一个通用大规模学术知识图谱。In short, V5.0 is not a global scholarly knowledge graph. 它的定位是：

> local-first, source-backed research relationship graph compiler for a user-provided paper corpus.

也就是说，用户投入 5-50 篇同领域论文后，LLMWiki 不只生成单篇 wiki 页面，而是把已有 claims、metric results、paper identity、bounded context 和 V4.9 normalization decisions 编译成一个可审计的研究关系网络。每条关系边必须能回到真实 `claim_id`、`result_id`、`source_id`、`paper_id` 和 `citation_locator`。LLM 可以判断关系，但不能发明证据。

第一版以 CLI-first、staging-only 为主，不新增 UI，不写 durable catalog，不直接修改 wiki 页面。V5.0 的输出是可审查的 relationship graph 和 evidence-grounded synthesis preview，为后续 V5 durable relationship apply、graph browser 或 wiki maintenance planner 打基础。

## 2. 动机

V4.3-V4.9 已经让系统具备了论文级指标抽取、结果证据检查、指标归一化和 timeline preview 能力。但实际验收暴露出一个核心问题：如果语料里的论文几乎都在同一年，年份并不是最有信息量的组织维度。

科研阅读中真正有价值的问题通常是关系型的：

- 哪些论文解决同一个任务？
- 哪些论文使用同一 benchmark 或 dataset？
- 哪些方法可以在同一 metric 上比较？
- 哪些论文把某个方法作为 baseline？
- 哪些论文声称改进了某个组件或路线？
- 哪些论文解决了其他论文提出的 limitation？
- 哪些结果看似相关但由于 dataset split、metric definition、setting 或 result role 不同而不可比较？
- 哪些结论之间存在 source-backed tension 或 contradiction？

这些问题不是普通 RAG 的强项。普通 RAG 可以找到相关片段，但不会长期维护一个可查询、可审计、可更新的研究关系结构。V5.0 的目标是把这些跨论文关系提升为一等对象。

## 3. 与通用知识图谱工作的区别

V5.0 不能声称“首次构建科研知识图谱”。已有工作已经覆盖大规模 academic KG、scientific information extraction、GraphRAG 和 paper relation classification。LLMWiki 的差异化应放在以下边界上：

- 小语料深度，而不是全网规模。
- 用户本地语料，而不是中心化公共 KG。
- 每条关系边都 source-backed，而不是只存实体三元组。
- 关系边能回到 page/block/line locator，而不是只给 citation sentence。
- 输出是 wiki/compiler workflow 的一部分，而不是一次性抽取结果。
- 重点判断可比较性、不可比较性、baseline 角色和 limitation 关系，而不是只抽 task/dataset/method 三元组。

V5.0 的评价重点也不应是“实体数量”或“边数量”，而应是：

- edge evidence coverage；
- fabricated reference count；
- cross-paper relationship usefulness；
- not-comparable 判断是否能避免错误比较；
- synthesis 是否能引用具体 edge evidence。

## 4. 范围

V5.0 实现：

- research relationship evidence bundle 构造；
- LLM-based relationship extraction and validation；
- research relationship graph staging artifacts；
- evidence-grounded cross-paper synthesis preview；
- relationship graph status and summary；
- JSON 和 human-readable CLI output；
- acceptance reuse over preserved V4.6/V4.9 workspaces；
- 明确的 safety/read-only/write-boundary 测试契约。

V5.0 不实现：

- UI graph browser；
- durable catalog migration；
- durable relationship apply；
- wiki writeback；
- global scholarly KG integration；
- external scholarly metadata lookup；
- citation network crawling；
- new PDF parsing；
- new MinerU ingest；
- metric extraction prompt changes；
- automatic conflict resolution；
- automatic leaderboard generation；
- graph layout visualization；
- multi-user collaboration。

## 5. 命令契约

新增 `research` 命令组。

### 5.1 Relationship graph dry-run

```powershell
llmwiki research graph --root . --dry-run
llmwiki research graph --root . --dry-run --json
```

`--dry-run` 只构造候选 bundle 和成本估算，不调用 LLM，不写 staging。

### 5.2 Relationship graph run

```powershell
llmwiki research graph --root .
llmwiki research graph --root . --json
```

可选参数：

```powershell
--topic <text>
--source-id <id>
--paper-id <id>
--relationship-type <type>
--metric <text>
--dataset <text>
--task <text>
--limit <n>
--offset <n>
--max-bundles <n>
--max-results-per-bundle <n>
--reuse-normalization-run <normalization-run-id>
```

默认策略：

- `limit=200`
- 最大 `limit=1000`
- `offset>=0`
- `max-bundles` 为空时处理候选分页范围内所有 bundles
- `max-results-per-bundle=40`
- real run 可以调用配置好的 LLM provider
- real run 只写 `staging/<relationship-run-id>/`

### 5.3 Relationship graph status

```powershell
llmwiki research graph-status <relationship-run-id> --root .
llmwiki research graph-status <relationship-run-id> --root . --json
```

`graph-status` 只读，不调用 LLM，不写文件。

### 5.4 Evidence-grounded synthesis preview

```powershell
llmwiki research synthesize <relationship-run-id> --root .
llmwiki research synthesize <relationship-run-id> --root . --json
llmwiki research synthesize <relationship-run-id> --root . --topic "GUI grounding"
```

第一版 `research synthesize` 默认只读取 relationship graph run 中已生成的 edges 和 evidence refs，生成 cross-paper synthesis preview。若实现需要二次 LLM synthesis，必须显式记录 provider/model，并且仍只能写入同一个 relationship staging run。Synthesis output 不是 formal evidence，不得新增 claim 或 relationship edge。

## 6. Schema 版本

V5.0 固定以下 schema：

```text
research_relationship_run.v5.0
research_relationship_bundle.v5.0
research_relationship_edge.v5.0
research_graph.v5.0
research_synthesis.v5.0
research_relationship_warning.v5.0
```

## 7. Staging artifacts

`llmwiki research graph` 写入：

```text
staging/<relationship-run-id>/run.json
staging/<relationship-run-id>/relationship-bundles.jsonl
staging/<relationship-run-id>/relationship-edges.jsonl
staging/<relationship-run-id>/research-graph.json
staging/<relationship-run-id>/research-synthesis.json
staging/<relationship-run-id>/warnings.jsonl
staging/<relationship-run-id>/triage.md
```

禁止写入：

- `state/catalog.sqlite`
- `wiki/`
- `sources/`
- `state/corpus-batches/`
- `state/embeddings/`
- `state/ui-jobs/`
- parser artifacts
- raw prompt
- raw LLM response
- API key
- parser log

## 8. Relationship bundle 设计

V5.0 的 LLM 输入单位是 bounded relationship bundle。它不直接读取 raw PDF，也不读取 parser-native artifact。它只能使用已有可审计数据：

- paper identity from V4.2 inventory；
- formal claims；
- durable `metric_results`；
- V4.7 canonicalization reports；
- V4.8 repair proposals；
- V4.9 normalization decisions and timeline points；
- source page paths；
- bounded PDF block context；
- bounded Markdown/text line context；
- existing catalog relationships；
- source-backed citation locators。

Bundle 类型：

- `same_benchmark_bundle`
- `same_metric_bundle`
- `baseline_comparison_bundle`
- `method_component_bundle`
- `limitation_bundle`
- `tension_bundle`
- `not_comparable_bundle`
- `topic_cluster_bundle`

每个 context item 必须保留：

- `source_id`
- `paper_id`
- `claim_id` when available
- `result_id` when available
- `citation_locator`
- `page_path`
- `context_preview`

## 9. Relationship edge 模型

每条 `research_relationship_edge.v5.0` 至少包含：

```json
{
  "schema_version": "research_relationship_edge.v5.0",
  "relationship_id": "rr_edge_xxx",
  "relationship_type": "same_benchmark",
  "subject": {
    "entity_type": "paper",
    "entity_id": "src_xxx",
    "label": "Paper A"
  },
  "object": {
    "entity_type": "benchmark",
    "entity_id": "bench_xxx",
    "label": "OSWorld"
  },
  "source_ids": ["src_xxx"],
  "paper_ids": ["src_xxx"],
  "claim_ids": ["clm_xxx"],
  "result_ids": ["res_xxx"],
  "citation_locators": ["page:6;block:src_xxx_p006_b0002"],
  "evidence_refs": [
    {
      "claim_id": "clm_xxx",
      "result_id": "res_xxx",
      "source_id": "src_xxx",
      "paper_id": "src_xxx",
      "citation_locator": "page:6;block:src_xxx_p006_b0002"
    }
  ],
  "confidence": "high",
  "decision_status": "auto_accepted",
  "comparability_status": "comparable",
  "rationale": "short bounded explanation",
  "warnings": []
}
```

Allowed `relationship_type` values:

- `same_task`
- `same_benchmark`
- `same_metric`
- `compares_against`
- `improves_over`
- `extends_method`
- `uses_component`
- `addresses_limitation`
- `supports`
- `contradicts_or_tensions`
- `not_comparable`
- `background_related`

Allowed `entity_type` values:

- `paper`
- `method`
- `benchmark`
- `dataset`
- `task`
- `metric`
- `result`
- `claim`
- `component`
- `limitation`
- `concept`

Allowed `decision_status` values:

- `auto_accepted`
- `needs_review`
- `blocked`
- `conflict`
- `insufficient_evidence`

Allowed `confidence` values:

- `high`
- `medium`
- `low`

Allowed `comparability_status` values:

- `comparable`
- `partially_comparable`
- `not_comparable`
- `not_applicable`
- `unknown`

## 10. 关系判断规则

### 10.1 可自动接受的关系

LLM 可以自动接受：

- 同一个明确 benchmark/dataset 的大小写、标点、空格变体；
- 同一个 formal claim 或 metric result 明确报告的 task/metric/result；
- 表格中明确写出的 method-vs-baseline 比较；
- 论文明确声称使用、扩展或替换某组件；
- limitation section 明确声明要解决的问题；
- V4.9 已高置信归一化的 same metric/dataset/task group。

### 10.2 必须降级的关系

以下情况必须输出 `needs_review`、`blocked`、`conflict` 或 `insufficient_evidence`：

- 只凭论文标题相似推断方法继承；
- 只凭 citation 出现推断 improves_over；
- dataset split/version 不同但 LLM 想合并；
- metric unit/value scale 不同但 LLM 想合并；
- baseline 出现在当前论文表格中，但没有证据说明它属于当前论文提出的方法；
- contradiction 只来自否定词或弱语义相似；
- evidence refs 缺失、伪造或无法回到输入 bundle。

### 10.3 Not-comparable 是一等输出

`not_comparable` 不是失败项。它是 V5.0 的关键价值之一。系统应明确记录为什么两个结果不能比较，例如：

- benchmark split 不同；
- metric definition 不同；
- result role 不同；
- setting 不同；
- value scale 不同；
- one result is main result, another is ablation or prior-work baseline。

## 11. Evidence-grounded synthesis 规则

Research synthesis 必须从 accepted or medium-confidence relationship edges 生成。每个 synthesis bullet 或段落必须引用至少一个 edge evidence ref。

Synthesis 可以回答：

- 当前语料围绕哪些研究问题形成集群；
- 哪些 benchmark 是共同比较中心；
- 哪些方法或组件被多个论文复用；
- 哪些结果可以比较；
- 哪些结果不能比较；
- 哪些 limitations 被后续论文明确处理；
- 哪些结论存在 tension。

Synthesis 不得：

- 创建新的 formal claim；
- 创建新的 durable relationship；
- 直接写 wiki；
- 隐藏 `not_comparable` 和 `contradicts_or_tensions`；
- 将低置信边表述成确定结论；
- 使用没有 edge evidence ref 的概括性断言。

## 12. 安全边界

- LLM 不得发明 `claim_id`、`result_id`、`source_id`、`paper_id`、`citation_locator`。
- LLM 不得把 parser diagnostics、parser logs、parser artifacts 当作 evidence。
- Relationship edge 只有在 evidence refs 全部存在于输入 bundle 且能回到 catalog-backed data 时才能进入 graph。
- JSON repair 只能修复 schema 形状，不得新增 evidence。
- `research graph --dry-run`、`graph-status` 和默认只读 `synthesize` 不得调用 MinerU、parser、corpus import、ingest、apply、ask、synthesis writeback、clean。
- Real `research graph` 可调用 LLM provider，但不得调用 MinerU/parser/import/ingest/apply。
- 所有 real run 写入必须限制在 `staging/<relationship-run-id>/`。

## 13. Acceptance Reuse

V5.0 默认复用已有验收工作区：

- `.tmp/paper-v46-corpus-acceptance`
- 可选复用 V4.9 normalize run，例如 `run_metric_normalize_20260605141915_d6d6d379`

V5.0 不需要重跑 full MinerU+LLM ingest。默认验收层级：

- L0: unit/schema tests；
- L1: dry-run over existing catalog；
- L2: bounded relationship graph smoke over preserved `.tmp/paper-v46-corpus-acceptance`；
- L3: rerun only a targeted 1-3 paper ingest if relationship evidence bundle construction exposes stale source artifacts；
- L4: rerun fixed 5-paper smoke only if ingest/chunk/metric extraction changes are introduced by a later spec；
- L5: rerun full 20-paper corpus only for phase closure or if lower levels cannot answer relationship extraction risk。

Because V5.0 only consumes existing evidence, L5 full-corpus rerun is not justified for the first implementation.

## 14. Quality Gates

V5.0 acceptance should record:

- paper count used；
- formal claim count available；
- metric result count available；
- relationship bundle count；
- relationship edge count；
- edge count by relationship type；
- accepted / needs_review / blocked / conflict / insufficient_evidence counts；
- edge evidence coverage；
- fabricated reference count；
- unresolved locator count；
- cross-paper edge count；
- not-comparable edge count；
- synthesis paragraph count；
- synthesis evidence ref coverage；
- LLM provider/model and token count for real smoke；
- whether any forbidden path was written。

Minimum quality gates:

- fabricated reference count must be 0；
- every accepted edge must have at least one evidence ref；
- every synthesis paragraph must cite at least one accepted or medium-confidence edge；
- dry-run must be read-only；
- status/synthesis read-only mode must not call LLM；
- real graph run must write only staging artifacts。

## 15. Open Questions

- Should accepted V5.0 edges later become durable catalog relationships, or should they remain a derived overlay?
- Should `not_comparable` edges be shown in retrieval results, or only in graph/synthesis views?
- Should relationship synthesis eventually write `wiki/syntheses/` pages through staging/apply?
- Should method/component entities get dedicated wiki pages, or stay as graph labels until V5.1?
- Should future UI expose a graph browser, a relationship table, or both?

## 16. Suggested Next Implementation Phase

V5.0 implementation should start with a narrow CLI-first graph run:

1. Build relationship bundles from existing catalog + V4.9 staging artifacts.
2. Add strict schema tests for edge refs and no fabricated ids.
3. Add `research graph --dry-run`.
4. Add bounded LLM graph run over 5-10 bundles.
5. Add read-only `graph-status`.
6. Add `research synthesize` preview from generated edges.
7. Reuse `.tmp/paper-v46-corpus-acceptance` for acceptance, with no MinerU+LLM ingest rerun.
