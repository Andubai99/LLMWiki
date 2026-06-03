# LLMWiki V4.2 Paper Identity And Corpus Inventory Implementation Plan

## Summary

实现 `docs/specs/2026-06-03-llmwiki-v4-2-paper-identity-corpus-inventory-design.md`：新增 CLI-first 的只读 `llmwiki corpus inventory`，从现有 catalog、PDF metadata sidecars、normalized source 和 V4.1 batch state 汇总论文身份清单。V4.2 不做 catalog migration、不调用 LLM/embedding/parser、不新增 UI、不做 metric/result extraction。

方法采用 **spec-driven + contract-first + risk-based TDD**。

## Key Changes

- 新增命令：
  - `llmwiki corpus inventory --root .`
  - `llmwiki corpus inventory --root . --json`
- 新增只读 inventory 模型与逻辑，放在 `src/llmwiki/corpus/identity.py` 和 `src/llmwiki/corpus/inventory.py`。
- 固定 schema：
  - inventory response: `corpus_inventory.v4.2`
  - paper item: `paper_identity.v4.2`
- 第一版不新增 catalog 表，`paper_id = source_id`。
- Inventory JSON 输出固定为：
  - top-level: `schema_version/root/generated_at/paper_count/warning_count/papers/duplicates/batch_items/warnings`
  - paper fields 包含 `source_id/paper_id/source_type/title/authors/year/doi/arxiv_id/sha256/raw_path/normalized_path/metadata_path/page_path/applied_run_id/parser_backend/identity_status/warnings/duplicate_warnings`
  - 缺失字符串用 `""`，缺失 `year` 用 `null`，缺失 dict/list 用 `{}` / `[]`
- Deterministic identity rules：
  - arXiv：从 filename、URL、metadata/normalized bounded text 检测 `2404.07972`、`2404.07972v2`、`arXiv:...`、`arxiv.org/abs/...`
  - year：优先显式年份，其次 arXiv 年份；不从任意两位数字猜测
  - DOI：保守识别 `10.<registrant>/<suffix>` 和 `doi.org/...`，去除尾随标点；多候选给 warning
  - authors/venue/status：只使用现有 metadata 或 block-derived sidecar，不做作者消歧
- Duplicate warnings：
  - `exact`: same SHA-256，主要用于 batch/context
  - `high`: same DOI 或 same arXiv id
  - `medium`: normalized title + first author + year
  - `low`: normalized title only
  - 只报警，不 merge/delete/overwrite
- Batch context：
  - `papers` 只列 catalog-backed sources
  - `batch_items` 单独列 V4.1 generated batch items，包括 pending/failed/skipped/already_imported 状态；不得覆盖 catalog identity

## Implementation Tasks

1. 保存 plan 并提交：
   - 新增 `docs/plans/2026-06-03-llmwiki-v4-2-paper-identity-corpus-inventory.md`
   - 提交：`docs: 添加 V4.2 论文身份与语料清单执行计划`
2. 先写失败测试：
   - 新增 `tests/test_corpus_identity.py`
   - 新增 `tests/test_corpus_inventory.py`
   - 更新 `tests/test_corpus_cli.py`
   - 如 README/AGENTS 更新，扩展 `tests/test_regression_samples.py`
   - 覆盖 parser helpers、JSON schema、human output、duplicate warning、malformed sidecar、batch context、read-only boundary
3. 实现 identity 与 inventory：
   - `identity.py`：dataclasses/constants、DOI/arXiv/year parser、title normalization、metadata loading、paper identity builder
   - `inventory.py`：只读查询 catalog sources/pages/ingest_runs，安全读取 `sources/metadata` 和 bounded normalized text，附加 batch context，计算 duplicate warnings
   - 所有 sidecar/path read 必须 workspace bounded；不要信任 metadata 里的任意路径
   - 提交：`feat: 新增论文身份与语料清单模型`
4. 接入 CLI 和 formatting：
   - `cli.py` 增加 `corpus inventory`
   - `formatting.py` 增加 JSON payload 和 human table 输出
   - human 输出显示 paper count、warning count、source_id/year/title/arxiv_id/status，并列出 warnings
   - `--json` 输出稳定 schema，不打印 raw parser logs、raw prompts、secret
   - 提交：`feat: 接入语料清单 CLI`
5. 固定安全边界和文档契约：
   - `corpus inventory` 测试 monkeypatch 禁止调用 LLM、embedding、MinerU/parser、add/ingest/apply、ask/synthesis、lint/eval/clean
   - 确认 inventory 不写 `wiki/`、`sources/`、`staging/`、`state/catalog.sqlite`、`state/corpus-batches/`、`state/embeddings/`
   - README/AGENTS 增加 V4.2 只读 inventory 边界和命令示例
   - 提交：`docs: 更新 V4.2 论文身份清单契约`

## Test Plan

- 单元：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_identity.py -q`
- Inventory/CLI：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_inventory.py tests\test_corpus_cli.py -q`
- 文档/边界：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- 相关回归：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_state.py tests\test_corpus_discovery.py tests\test_corpus_runner.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_add_source.py tests\test_pdf_blocks.py -q`
- 最终验证：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_identity.py tests\test_corpus_inventory.py tests\test_corpus_cli.py tests\test_corpus_state.py tests\test_corpus_discovery.py tests\test_corpus_runner.py tests\test_regression_samples.py -q`
  - `.\.venv\Scripts\python.exe -m llmwiki clean --root .`
  - `git status --short --ignored` 确认没有 tracked/staged generated inventory state、缓存、密钥或 paper 原料

## Manual Acceptance

- 小规模 workspace：
  - 导入或使用已有 1-2 个 source
  - `.\.venv\Scripts\python.exe -m llmwiki corpus inventory --root .`
  - `.\.venv\Scripts\python.exe -m llmwiki corpus inventory --root . --json`
- 检查：
  - 每个 catalog source 有稳定 `source_id` / `paper_id`
  - `docs/papers` 风格文件名能产生 arXiv id 和 year
  - malformed/missing metadata 产生 warning，不崩溃
  - duplicate DOI/arXiv/title 能产生 warning
  - inventory 不创建或修改 `wiki/`、`sources/`、`staging/`、`state/catalog.sqlite`、`state/corpus-batches/`

## Assumptions And Defaults

- 第一版不做 catalog migration，不新增 `paper_identities` 表。
- `paper_id` 默认等于 `source_id`。
- `corpus inventory` 默认列出 catalog-backed sources；batch-only 项放入 top-level `batch_items`。
- 第一版只实现 `--json`，不实现 `--source-type`、`--batch-id`、`--missing-only` 等过滤参数。
- DOI/arXiv/year extraction 只用本地可审计文本；不联网、不调用 LLM、不调用 parser。
- Metadata and parser diagnostics are not formal evidence.
- V4.2 不引入 `page_type="paper"`；source pages 继续作为 paper-facing pages，V4.5 再评估 page type。
