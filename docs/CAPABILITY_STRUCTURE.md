# LLM Wiki 项目能力结构

## 项目定位

LLM Wiki 是一个本地优先的个人研究库框架。它的核心形态是 Python CLI + Markdown wiki + agent 工作流：CLI 管文件、索引、校验和落盘保护；LLM 负责阅读、提取、总结和提出候选修改；人负责审阅、裁决冲突和决定是否合并。

本项目不是新的笔记 App，也不是通用 RAG 平台。它更接近一个 source-backed knowledge compiler：把原始资料编译成可读、可追溯、可维护的 Markdown wiki。

## 能力地图

| 能力域 | 当前状态 | V1 目标 |
| --- | --- | --- |
| Workspace | 已有目录与配置骨架 | `llmwiki init` 可生成完整工作区 |
| Source Intake | 仅有目录占位 | 支持 Markdown、网页、文本型 PDF 导入 |
| Normalization | 仅有目录占位 | 转成带行号、段落号或页码锚点的 Markdown |
| Claim Store | 仅有 `state/` 占位 | SQLite 保存 source、claim、alias、page、relationship、run |
| Staging | 仅有目录占位 | ingest 只生成候选 claims、triage、patch，不直写 wiki |
| Review / Apply | CLI 接口占位 | review 汇总风险，apply 校验后写入 wiki/index/log |
| Wiki | 已有基础目录和 index/log | 维护 sources、concepts、entities、syntheses 四类页面 |
| Lint | CLI 接口占位 | 检查断链、孤页、重复 alias、缺引用、source drift |
| Query | CLI 接口占位 | 基于 index + SQLite FTS 检索，生成带引用回答 |
| Agent Contract | 已有初始规则 | 约束 LLM 使用 staging、引用 source、保留不确定性 |

## 数据流

```text
raw source
  -> normalized source
  -> extracted claims
  -> staged triage + patches
  -> human review
  -> apply to wiki
  -> refresh index/log/catalog
  -> query/lint/synthesis
```

## 目录职责

- `sources/raw/`：不可变原始资料，LLM 不得修改。
- `sources/normalized/`：从原始资料转换出的可引用文本。
- `wiki/`：最终知识库，面向人和 agent 阅读。
- `staging/`：LLM 提出的候选修改区，默认不提交历史 run。
- `state/`：SQLite 索引与审计缓存，可重建。
- `llmwiki/`：Python CLI 与核心库代码。
- `tests/`：框架与后续行为测试。

## CLI 能力边界

第一版 CLI 暴露固定命令：

```bash
llmwiki init
llmwiki add <file-or-url>
llmwiki ingest <source-id>
llmwiki review <run-id>
llmwiki apply <run-id>
llmwiki lint
llmwiki query "<question>"
llmwiki doctor
```

当前 scaffold 只实现命令入口和 `doctor` 工作区检查。其余命令保留接口，后续按 V1 目标逐步填充。

## 写入原则

- Raw source 是事实来源，不可被自动修改。
- Wiki 是编译产物，但每个重要 claim 必须能回到 source。
- Ingest 阶段只写 staging。
- Apply 阶段才允许修改正式 wiki。
- SQLite 是辅助索引，不是长期知识源。

## 暂不包含

- Web UI 或桌面应用。
- Obsidian 插件。
- MCP server。
- 团队权限和多人审批。
- 扫描 PDF OCR。
- 图片理解。
- 自动裁决矛盾。
- 自动合并相似概念。
- 向量数据库或复杂知识图谱。
