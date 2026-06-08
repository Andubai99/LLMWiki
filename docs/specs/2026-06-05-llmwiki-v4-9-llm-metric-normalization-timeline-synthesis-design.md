# LLMWiki V4.9 LLM Metric Normalization And Timeline Synthesis Design

Date: 2026-06-05

## 1. 摘要

V4.9 引入一个 CLI-first 的 LLM 指标归一化与时间线综合流程，让系统自动处理 V4.7/V4.8 暴露出来的指标名、数据集名、任务名、年份和可比性问题。

核心目标不是让用户逐条审查 644 条修复建议，而是让 LLM 基于证据包自动判断：

- 这个指标结果应归属哪个标准指标；
- 这个数据集/任务写法是否和其他写法等价；
- 表格里没有直接写年份时，是否可以用论文年份作为时间线年份；
- 一个结果是本文主结果、消融结果、诊断结果，还是从其他论文转述的 baseline；
- 哪些结果可以组成一条可审计的指标演进时间线；
- 哪些判断仍然不安全，必须保留为低置信度或冲突项。

V4.9 可以调用配置好的 LLM provider，但不重新运行 MinerU、PDF parser、corpus import、ingest 或 apply。它读取既有 catalog-backed `metric_results`、formal claims、paper inventory、bounded source context、V4.7 canonicalization report 和 V4.8 repair proposals，生成一个 staging-only 的归一化与时间线综合运行。

第一版不修改 `state/catalog.sqlite`，不更新 durable `metric_results`，不写 wiki 页面。它输出可审计的自动整理结果，供后续 V4.10 或 V5 决定是否引入 durable overlay 或正式 apply。

## 2. 动机

V4.8 在 `.tmp/paper-v46-corpus-acceptance` 上得到：

- durable `metric_results`: 414；
- canonical metric count: 68；
- comparability group count: 193；
- repair proposal count: 644；
- reported year repair proposals: 384；
- metric alias review proposals: 197；
- dataset alias review proposals: 33；
- task alias review proposals: 19；
- projected strict-ready groups: 5。

这说明当前系统已经能从论文中抽出大量指标结果，但还没有真正完成“科研知识库”的关键一步：把不同论文中的结果理解为可以比较的指标演进。

V4.8 的保守规则适合作为安全底线，但如果主要依赖人工审查，项目亮点会不足。V4.9 应该把 LLM 用在更高价值的位置：不是重新抽取原始 PDF，而是在已有 evidence foundation 上做论文级和语料级的自动归一化判断。

典型问题：

- 表格只写“成功率 34%”，同一格没有年份，但论文标题、摘要、实验章节和 source metadata 已经能说明这是 2025 年论文报告的结果。
- `success rate`、`task success rate`、`SR`、`Avg. SR` 可能指同一指标，但需要结合表格标题、列名、dataset、task 和单位判断。
- `ScreenSpot-Pro` 和 `ScreenSpot Pro` 大概率是同一数据集，但 `OSWorld`、`OSWorld-Human`、`OSWorld-Verified` 可能是不同评测设置。
- 表格中的 baseline 可能是旧方法结果。它出现在 2025 年论文中，不代表该 baseline 本身是 2025 年提出的结果。

V4.9 要让 LLM 把这些上下文放在一起处理，并输出结构化、可审计、可回退的判断。

## 3. 范围

V4.9 实现：

- LLM-based metric normalization run；
- evidence bundle 构造；
- 论文级年份推断和 result role 判断；
- metric/dataset/task 自动归一化；
- comparability group 自动重组；
- timeline year 推断；
- timeline preview 和简短综合说明；
- staging-only artifacts；
- JSON 和 human output；
- 低置信度、冲突、证据不足的自动降级。

V4.9 不实现：

- UI；
- catalog migration；
- durable repair apply；
- 直接更新 `metric_results`；
- 直接更新 `claims`；
- 直接写 wiki 页面；
- 重新运行 MinerU；
- 重新运行 parser；
- 重新运行 corpus import / ingest / apply；
- 重新抽取 PDF metric results；
- 自动生成 leaderboard；
- 趋势因果判断；
- source-backed conflict classifier；
- 长篇 synthesis wiki writeback。

## 4. 命令契约

### 4.1 LLM 归一化

默认运行会调用 LLM，并写入 staging run：

```powershell
llmwiki metric normalize --root .
llmwiki metric normalize --root . --json
```

可选参数：

```powershell
--metric <text>
--dataset <text>
--task <text>
--source-id <id>
--paper-id <id>
--limit <n>
--offset <n>
--max-groups <n>
--max-results-per-group <n>
--reuse-run <normalization-run-id>
--dry-run
```

默认：

- `limit=200`；
- 最大 `limit=1000`；
- `offset>=0`；
- `max-groups` 为空时处理所有候选 group；
- `max-results-per-group=40`；
- `--dry-run` 只构造候选分组和 token/cost estimate，不调用 LLM，不写 staging。

退出行为：

- exit `0`：归一化运行成功，即使存在低置信度或冲突项；
- exit `1`：参数错误、catalog 缺失、schema 不兼容、LLM provider 不可用、证据包构造失败；
- 空语料 exit `0`，输出 `no_metric_results` warning。

### 4.2 状态查看

```powershell
llmwiki metric normalize-status <normalization-run-id> --root .
llmwiki metric normalize-status <normalization-run-id> --root . --json
```

状态查看只读，不调用 LLM，不写文件。

### 4.3 时间线综合预览

```powershell
llmwiki metric timeline-synthesis <normalization-run-id> --root .
llmwiki metric timeline-synthesis <normalization-run-id> --root . --json
llmwiki metric timeline-synthesis <normalization-run-id> --root . --metric <canonical-metric-id>
```

第一版 `timeline-synthesis` 默认读取 `metric normalize` 已经生成的 timeline preview，不再次调用 LLM。若未来需要二次 narrative synthesis，必须显式增加参数和测试边界。

## 5. Schema 版本

```text
metric_normalization_run.v4.9
metric_evidence_bundle.v4.9
metric_normalization_decision.v4.9
metric_timeline_group.v4.9
metric_timeline_point.v4.9
metric_timeline_synthesis.v4.9
metric_normalization_warning.v4.9
```

V4.9 必须保留原始审计字段：

- `result_id`;
- `claim_id`;
- `source_id`;
- `paper_id`;
- `citation_locator`;
- `metric_name`;
- `method`;
- `dataset`;
- `task`;
- `metric_value`;
- `metric_raw_value`;
- `metric_unit`;
- `metric_direction`;
- `baseline`;
- `confidence_status`;
- parser backend fields。

归一化字段只能作为 derived metadata，不替换原始 durable row。

## 6. Staging Artifacts

`metric normalize` 写入：

```text
staging/<normalization-run-id>/run.json
staging/<normalization-run-id>/evidence-bundles.jsonl
staging/<normalization-run-id>/llm-normalization-decisions.jsonl
staging/<normalization-run-id>/timeline-groups.jsonl
staging/<normalization-run-id>/timeline-points.jsonl
staging/<normalization-run-id>/timeline-synthesis.json
staging/<normalization-run-id>/warnings.jsonl
staging/<normalization-run-id>/triage.md
```

禁止写入：

- `state/catalog.sqlite`;
- `wiki/`;
- `sources/`;
- `state/corpus-batches/`;
- `state/embeddings/`;
- `state/ui-jobs/`;
- parser artifacts；
- raw prompt；
- raw LLM response；
- API key；
- parser log。

## 7. 证据包设计

V4.9 的 LLM 输入单位不是单个表格单元，而是 bounded evidence bundle。

每个 evidence bundle 可包含：

- paper identity：标题、作者、年份、DOI、arXiv id；
- source id / paper id；
- result rows；
- formal claim text；
- citation locator；
- table block；
- caption block；
- nearby heading；
- nearby result text；
- abstract 摘要片段；
- method / experiment / result section heading；
- same-paper related result rows；
- cross-paper candidate rows from same V4.7/V4.8 group；
- V4.8 repair proposals related to the same result/group。

证据包约束：

- 所有 source context 必须来自 catalog-backed source sidecars 或 normalized text；
- 每段 context 必须有 page/block/line locator；
- 不读取 raw PDF；
- 不读取 parser native artifact；
- 不暴露 parser log；
- 每个 bundle 有 token 上限；
- 超限时按优先级保留 table/caption/result text/formal claim/paper identity，截断低优先级上下文。

## 8. LLM 输出字段

每条 `metric_normalization_decision.v4.9` 至少包含：

```json
{
  "schema_version": "metric_normalization_decision.v4.9",
  "decision_id": "mnd_xxx",
  "result_ids": ["res_xxx"],
  "claim_ids": ["clm_xxx"],
  "source_ids": ["src_xxx"],
  "paper_ids": ["src_xxx"],
  "canonical_metric_id": "met_xxx",
  "canonical_metric_name": "success rate",
  "canonical_dataset_id": "dat_xxx",
  "canonical_dataset_name": "OSWorld",
  "canonical_task_id": "task_xxx",
  "canonical_task_name": "computer use",
  "result_role": "main_result",
  "paper_year": 2025,
  "result_reported_year": null,
  "timeline_year": 2025,
  "timeline_year_basis": "paper_identity_for_main_result",
  "comparable": true,
  "decision_status": "auto_accepted",
  "confidence": "high",
  "rationale": "short bounded explanation",
  "evidence_refs": [
    {
      "result_id": "res_xxx",
      "claim_id": "clm_xxx",
      "source_id": "src_xxx",
      "citation_locator": "page:6;block:src_xxx_p006_b0001"
    }
  ],
  "warnings": []
}
```

允许的 `decision_status`：

- `auto_accepted`;
- `needs_review`;
- `blocked`;
- `conflict`;
- `insufficient_evidence`。

允许的 `confidence`：

- `high`;
- `medium`;
- `low`。

允许的 `result_role`：

- `main_result`;
- `baseline`;
- `prior_work`;
- `ablation`;
- `diagnostic`;
- `dataset_stat`;
- `method_description`;
- `unclear`。

## 9. 年份处理规则

V4.9 必须区分三个年份：

| 字段 | 含义 |
| --- | --- |
| `paper_year` | 论文身份年份 |
| `result_reported_year` | 结果上下文中显式提到的年份 |
| `timeline_year` | 用于指标演进排序的年份 |

默认判断：

- 如果结果是 `main_result` 或本文实验结果，且没有冲突证据，`timeline_year` 可以使用 `paper_year`。
- 如果结果是 `ablation` 且属于本文方法，`timeline_year` 可以使用 `paper_year`，但 timeline synthesis 应标记为 ablation。
- 如果结果是 `baseline` 或 `prior_work`，只有上下文明确给出 baseline 年份或对应 source 年份时，才能使用该年份。
- 如果 baseline 只是在当前论文表格中出现，不能简单用当前论文年份伪装成 baseline 的年份。
- 如果上下文有多个冲突年份，decision 必须为 `conflict` 或 `needs_review`。
- 如果没有任何可靠年份，decision 必须为 `insufficient_evidence`。

## 10. 指标、数据集、任务归一化规则

LLM 可以自动合并：

- 大小写差异；
- 标点差异；
- 空格和连字符差异；
- 明确同义缩写，例如上下文说明 `SR` 是 `success rate`；
- 同一表格中列名和 caption 明确说明的等价写法；
- 同一论文内反复出现且定义一致的写法。

LLM 不应自动合并：

- 只凭字面相似但上下文不同的标签；
- benchmark split 不同的 dataset；
- version 不同的 dataset；
- task scope 不同的任务；
- `score`、`Avg`、`Overall`、`performance` 这类缺少定义的泛化标签；
- 单位或 value scale 不兼容的指标；
- 趋势方向不一致且无法解释的指标。

对不安全项，LLM 必须输出 `needs_review`、`blocked`、`conflict` 或 `insufficient_evidence`，不能强行合并。

## 11. 时间线综合

每个 `metric_timeline_group.v4.9` 表示一条候选指标演进路线。

group key 至少由以下 derived fields 组成：

- canonical metric；
- canonical dataset；
- canonical task；
- metric unit；
- value scale；
- metric direction；
- result role filter。

每个 `metric_timeline_point.v4.9` 至少包含：

- timeline year；
- metric value；
- method；
- paper title；
- source id；
- claim id；
- result id；
- citation locator；
- role；
- confidence；
- decision id。

`metric_timeline_synthesis.v4.9` 可以包含简短中文说明：

- 这个指标在什么任务/数据集上比较；
- 涉及哪些论文；
- 从早到晚的结果变化；
- 哪些点是主结果；
- 哪些点是 baseline 或 ablation；
- 哪些点不应直接比较；
- 主要不确定性。

综合说明必须引用 timeline point 的 result/claim/source/citation，不得创造新证据。

## 12. LLM Prompt 边界

Prompt 必须明确告诉 LLM：

- 只能使用 evidence bundle 中的信息；
- 不得补充外部知识；
- 不得发明 source id、claim id、result id、locator、年份、指标值；
- 不得把 parser diagnostics 当作 evidence；
- 不得把不确定判断写成确定结论；
- 对低置信度判断必须降级；
- 输出必须是 schema-valid JSON；
- rationale 必须简短，不保存 raw chain-of-thought。

系统可以保存 sanitized rationale，但不得保存 raw prompt 或 raw LLM response 到 committed docs。

## 13. 质量门槛

V4.9 acceptance 复用 `.tmp/paper-v46-corpus-acceptance`，不重跑 MinerU，不重跑 corpus import。

基线：

- V4.8 projected strict-ready groups: 5；
- V4.8 repair proposals: 644；
- V4.7/V4.8 仍有大量 year/alias blockers。

V4.9 目标：

- LLM normalization run 成功完成；
- parser backend distribution 保持不变；
- catalog mutation count = 0；
- generated timeline groups 数量高于 V4.8 projected strict-ready groups；
- 至少 70% 缺失 `reported_year` 的 main-result rows 能得到 `timeline_year`；
- high-confidence auto accepted decisions 占比可记录；
- conflict / needs_review / insufficient_evidence 项可记录；
- 每个 auto accepted timeline point 都有 result id、claim id、source id、citation locator；
- timeline synthesis 不出现无引用结论；
- secret/raw prompt/raw response 不进入 committed observation。

第一版建议目标：

- `auto_accepted_timeline_group_count >= 8`；
- `timeline_point_count >= 30`；
- `unsupported_evidence_ref_count = 0`；
- `catalog_write_count = 0`。

这些目标可以在真实验收后根据观察记录调整。

## 14. 安全边界

允许：

- 读取 `state/catalog.sqlite`；
- 读取 formal claims/sources/pages/relationships；
- 读取 durable `metric_results`；
- 读取 generated sidecars 中的 bounded source context；
- 读取 V4.2 inventory；
- 读取 V4.7 canonicalization output 或动态重建；
- 读取 V4.8 staged repair proposals；
- 调用配置好的 LLM provider；
- 写入 `staging/<normalization-run-id>/`。

禁止：

- 调用 MinerU；
- 调用 PDF parser；
- 调用 corpus import；
- 调用 ingest；
- 调用 apply；
- 调用 ask；
- 调用 synthesis writeback；
- 写 `state/catalog.sqlite`；
- 写 `wiki/`；
- 写 `sources/`；
- 写 `state/corpus-batches/`；
- 写 `state/embeddings/`；
- 写 `state/ui-jobs/`；
- 读取或提交 API key；
- 提交 `.tmp` 验收 workspace。

## 15. 测试计划

建议新增：

- `tests/test_metric_llm_normalization_model.py`
- `tests/test_metric_llm_normalization_bundles.py`
- `tests/test_metric_llm_normalization_prompt.py`
- `tests/test_metric_llm_normalization_cli.py`
- `tests/test_metric_llm_normalization_staging.py`
- `tests/test_metric_llm_normalization_readonly.py`
- `tests/test_metric_timeline_synthesis.py`

测试覆盖：

- evidence bundle 构造；
- token/context bounding；
- main result vs baseline 判断；
- paper year -> timeline year 的安全规则；
- conflicting year 降级；
- metric/dataset/task 自动归一化；
- vague label blocking；
- timeline group 输出；
- timeline synthesis 引用完整性；
- staging artifacts；
- `--dry-run` 不调用 LLM、不写 staging；
- status 命令只读；
- no catalog/wiki/source mutation；
- secret sanitizer；
- malformed LLM JSON repair 不得发明 evidence。

真实验收：

```powershell
.\.venv\Scripts\python.exe -m llmwiki metric normalize --root .tmp\paper-v46-corpus-acceptance --dry-run --json
.\.venv\Scripts\python.exe -m llmwiki metric normalize --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric normalize-status <normalization-run-id> --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric timeline-synthesis <normalization-run-id> --root .tmp\paper-v46-corpus-acceptance --json
```

记录：

```text
docs/observations/2026-06-05-llmwiki-v4-9-llm-metric-normalization-timeline-synthesis-observations.md
```

记录内容：

- LLM model/provider name，但不记录 key；
- processed group count；
- evidence bundle count；
- auto accepted decision count；
- needs review count；
- blocked count；
- conflict count；
- insufficient evidence count；
- timeline group count；
- timeline point count；
- main result point count；
- baseline point count；
- paper-year inferred timeline point count；
- explicit-year timeline point count；
- unsupported evidence ref count；
- catalog mutation check；
- top generated timeline examples；
- 失败样例和后续修复建议。

## 16. 后续阶段

V4.9 之后可以选择：

1. V4.10 Metric Normalization Overlay Apply
   - 把高置信度 accepted decisions 保存为 durable overlay，而不是直接改原始 `metric_results`。

2. V4.10 Timeline Wiki Preview
   - 把 timeline synthesis 生成可预览的 wiki 草稿，继续走 staging/apply。

3. V5 Research Intelligence
   - 在已有时间线基础上做 source-backed conflict detection、method evolution、benchmark coverage gap 和 living synthesis。

## 17. 开放问题

1. LLM 自动归一化结果是否允许默认 `auto_accepted`，还是必须有 confidence threshold？
2. future durable overlay 应该写入 catalog 新表，还是 generated state cache？
3. timeline synthesis 是否应该生成中文、英文，还是跟随 workspace 配置？
4. 是否需要 curated alias seed file 帮助 LLM 稳定合并常见 benchmark 名称？
5. 是否允许用户把某些低风险规则设为自动接受？
6. 是否应把 baseline/prior work 结果放入同一 timeline，还是单独显示为 reference baseline？
