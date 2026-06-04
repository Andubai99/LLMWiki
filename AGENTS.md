# LLM Wiki Agent Contract

本文件是 Codex/LLM 在本仓库工作的行为契约。LLMWiki 是一个本地优先、source-backed 的研究 wiki 编译器，不是自由笔记文件夹。Agent 的职责是维护一个可审计的知识编译流程：source 导入、解析、LLM ingest、staging、安全校验、apply、检索、问答、synthesis 写回和质量检查。

## 1. 项目现有能力

当前项目已经具备这些核心能力：

- `llmwiki add <source-or-url> --root .` 是正常 source 导入入口。它会导入资料、解析/normalize、调用 LLM ingest、生成 staging run、通过安全校验后 apply 到 wiki/catalog。
- Markdown、文本、网页快照、文本 PDF 都可作为 source。PDF 会生成 metadata、blocks、chunks sidecars。
- PDF parser 支持 `auto` 后端：优先 MinerU，失败时可见地 fallback 到 `pypdf`。V2.9.6 会发现 configured command、PATH、workspace `.venv` 和 repo `.venv` 中的 MinerU。
- `llmwiki retrieve` 是标准 evidence API，`llmwiki query` 是同一路径的人类可读输出。
- `llmwiki ask` 是本地证据问答入口：LLM query planning -> local retrieve -> grounded answer。可选 `--preview-writeback` / `--writeback` 走 synthesis planning 和 staging/apply。
- `llmwiki embeddings` 管理本地可重建 vector index；vector 只是召回信号，不是 evidence。
- `llmwiki lint`、`doctor`、`eval retrieval`、`eval pdf-quality` 用于本地质量检查。
- `wiki/sources/`、`wiki/concepts/`、`wiki/entities/`、`wiki/syntheses/`、`wiki/index.md`、`wiki/log.md` 是正式 Markdown wiki 输出。
- `state/catalog.sqlite` 是可重建 catalog/cache，索引 sources、claims、pages、links、relationships、runs。

## 2. 后续路线

后续开发按 V3/V4/V5 推进，具体 spec 见 `docs/specs/2026-06-02-llmwiki-v3-v5-product-roadmap-design.md`。

### V3: User Interaction And Product Shell

优先做本地 UI / 产品外壳，解决用户交互差的问题。目标是让用户在 UI 中完成 source 添加、运行状态查看、失败恢复、evidence 检查、ask、synthesis preview/writeback、lint/eval 查看。V3 不应顺手实现复杂 PDF parsing 或关系分类。

### V4: PDF And Research Corpus Ingestion

围绕 `docs/papers` 中的 20 篇 CUA 论文，解决批量导入队列、长任务状态、失败续跑、MinerU 验收闭环、表格/图/公式 evidence foundation、论文级 page type / knowledge structure。

### V5: Wiki Self-Maintenance And Research Intelligence

提升 wiki 自我维护能力和真实论文场景下的关系/冲突识别能力。目标包括 maintenance planner、research relationship classifier、source-backed conflict detection、living synthesis 更新和相关评测。

在 V3/V4/V5 的具体 spec/plan 没有明确要求前，不要临时加入大范围架构改造。

## 3. Operating Rules

- Production Python package code lives under `src/llmwiki/`. Do not add new runtime modules under a root-level `llmwiki/` directory.
- Tests live under `tests/`; committed documentation/specs/plans live under `docs/`.
- New implementation plans must be saved under `docs/plans/`; new specs must be saved under `docs/specs/`. Do not create new plan/spec files under `docs/superpowers/`.
- Do not modify files under `sources/raw/`.
- Do not write final wiki pages directly during ingest. Write candidate changes under `staging/<run-id>/`.
- Codex/LLM must not bypass staging; proposed knowledge changes must be inspectable before apply.
- Only `llmwiki apply <run-id>` may write validated changes into `wiki/`, `wiki/index.md`, `wiki/log.md`, and `state/catalog.sqlite`.
- Use `llmwiki ingest`, `llmwiki review`, and `llmwiki apply` directly only for internal debugging or recovery.
- Apply must pass safety validation before any wiki/catalog mutation.
- Claims must be traceable to a source locator. Do not invent citations or source anchors.
- Every substantive claim proposed for the wiki must cite a source id and a page, line, paragraph, section, or block anchor when available.
- Important judgments without citation must be marked weak/uncited and must not become formal conclusions.
- Agents must not overwrite user-authored wiki content without a recoverable backup or an explicit merge strategy.
- Preserve uncertainty. Do not automatically resolve conflicts between sources.
- Keep Markdown readable in Obsidian.
- Treat `wiki/log.md` as append-only.

## 4. Source, Citation, And Evidence Boundaries

- A formal claim requires a source id, claim text, confidence status, and valid source locator.
- Markdown/text sources use `line:N` locators.
- PDF sources require page/block locators such as `page:1;block:src_xxx_p001_b0004;section:Abstract`.
- Bare `line:N` locators remain valid for Markdown/text sources, not for PDF claims.
- weak/uncited claims must remain visible but must not be upgraded into strong conclusions.
- Do not forge claim ids, source ids, citation locators, page paths, scores, or relationships.
- Parser diagnostics, parser logs, parser artifact paths, and `parser_backend_attempts` are audit data, not evidence.
- Parser artifacts must not be returned as retrieval evidence.

## 5. Retrieval And Ask Boundaries

- `llmwiki retrieve` is the standard evidence interface for external RAG systems, agents, and LLM prompts.
- `llmwiki query` is the human-readable view of `retrieve`; it must reuse the same local evidence path instead of maintaining a separate weak search implementation.
- `llmwiki ask` is the standard local evidence question-answering interface for users.
- Retrieval output must only expose claims, citations, page paths, and relationships that exist in the local catalog/wiki.
- Retrieval normalization must be Unicode-aware and must not discard multilingual text, formulas, symbols, or emoji query features.
- Formula/symbol evidence such as `H2O`, `E=mc2`, Greek letters, ratios, and math notation must remain searchable and citation-backed.
- `contradicts` relationships must be exposed to callers; do not hide conflicts or silently choose a winner.
- `contradicts` means source-backed disagreement between claims. Do not create `contradicts` relationships from negation keywords such as `not`, `不`, `不需要`, or `不建议`.
- Retrieval must not call external chat LLM APIs by default.
- `retrieve`, `query`, `eval retrieval`, `eval pdf-quality`, and `parsers status` are local/read-only or deterministic maintenance surfaces unless their command contract explicitly says otherwise.

## 6. Vector, Reranking, And Selection

- V2.6 local vector index under `state/embeddings/` is allowed as a rebuildable cache, but it is not durable knowledge and must not be committed.
- Vector candidates are recall signals only. They must map back to real catalog claims before they can be returned as evidence.
- When `[embedding].enabled = true` and a local vector index exists, `retrieve`, `query`, `ask`, and `eval retrieval` may call the configured embedding provider for query embedding. If query embedding fails, retrieval must fall back and expose a warning.
- Reranker and evidence selector output are not evidence. They may reorder, diversify, deduplicate, or select catalog-backed candidates, but they must not create claim ids, source ids, page paths, locators, scores, or relationships that were not already grounded in local retrieval/catalog data.
- Chat LLM reranking is opt-in only and must remain disabled by default.
- Evidence selection must preserve weak/uncited and contradicting evidence visibility; it must not hide conflicts or upgrade weak evidence into strong conclusions.
- Do not add domain-specific query rules, keyword intent classifiers, or term boosts for retrieval, reranking, or evidence selection.

## 7. Ask, Planner, And Synthesis Rules

- `ask` may call the configured LLM for query planning before retrieval, then must run local retrieve against wiki/catalog before answer generation.
- Planner output is not source-backed evidence. Do not treat planner intent, entities, subqueries, filters, or required evidence descriptions as claims or citations.
- Planner output must be schema-validated before retrieval execution.
- Invalid planner filters such as `confidence = "high"` must be repaired through one schema-validated LLM repair attempt or rejected; do not silently coerce invalid values.
- `llmwiki ask --preview-writeback` is read-only and must not create staging runs, wiki pages, or catalog rows.
- synthesis plan output is not evidence.
- Do not create duplicate synthesis pages when an existing synthesis page should be updated.
- Synthesis pages are living wiki pages, not saved chat transcripts; preserve user-authored custom sections when updating them.
- Synthesis evidence maps may only cite existing catalog claims with real claim ids, source ids, citation locators, and page paths.
- Synthesis writeback must not create derived formal claims; synthesis `claims.jsonl` stays empty unless a future spec explicitly changes that.

## 8. LLM Provider Rules

- Real LLM calls are allowed in ingest, ask planning, answer generation, synthesis planning, and PDF JSON repair where the implemented workflow requires them.
- API Key values, tokens, `.env` files, `config/api-keys.toml`, and sensitive logs must never be committed.
- The DeepSeek API Key must be read from the local ignored `config/api-keys.toml` file.
- Embedding API keys must also stay in the local ignored `config/api-keys.toml` file under `[embedding].api_key`.
- Do not write API keys into `config/config.toml`, README, tests, source files, logs, staging artifacts, committed examples, or UI responses.
- Do not add a production mock provider or public no-network LLM path unless a future spec explicitly requires it. Existing tests may monkeypatch providers.
- LLM ingest proposals may create `claims.jsonl`, `triage.md`, `llm-proposal.json`, run manifests, and patch files only under `staging/<run-id>/`.
- LLM output must not bypass staging validation and apply.
- LLM ingest claims with valid source locators are normalized to `cited` before staging. Claims without valid source locators must remain weak/uncited.
- LLM repair may only repair JSON syntax/schema shape for malformed PDF chunk or consolidation responses. It must not add evidence, invent claims, invent block ids, invent locators, or bypass source locator and staging validation.

## 9. PDF And Parser Backend Rules

- PDF parser backends produce source artifacts, not wiki knowledge.
- PDF sources use metadata/block/chunk sidecars under `sources/metadata/`, `sources/blocks/`, and `sources/chunks/`; these are generated local artifacts and must not be committed except `.gitkeep`.
- Backend-native files live under generated `sources/parser-artifacts/` and must not be committed except `.gitkeep`.
- V2.9.5 defaults PDF parsing to `auto`: try MinerU first when installed/enabled, then visibly fall back to `pypdf` on auto-mode parser failure.
- Explicit `--parser mineru` is strict and must fail hard if MinerU is unavailable or invalid.
- Explicit `--parser pypdf` is a debug/fallback path and must not invoke MinerU.
- The LLM must not choose parser backend, block ids, chunk ids, chunk boundaries, page numbers, parser artifact paths, or citation anchors.
- PDF chunk boundaries are deterministic.
- MinerU tables, formulas, images, captions, and layout data may become normalized blocks, but they are not formal evidence until LLM ingest extracts catalog claims with valid page/block locators.
- `content_role="ignored"` blocks remain in sidecars for auditability but must not enter normalized body text or LLM chunk claim-extraction prompts.
- PDF source aliases must not include parser-created aliases or paper title aliases. The paper title belongs in `sources.title` and the source page title, not in the source formal alias list.
- `llmwiki parsers status` is read-only and must not call LLM, embedding, MinerU document parsing, network, or write workspace files.
- Parser attempt diagnostics are not evidence and must never be returned by `retrieve`, `query`, or `ask`.
- Auto fallback from MinerU to `pypdf` must remain visible in source metadata, staging diagnostics, lint, and `eval pdf-quality`.

## 10. Quality And Evaluation

- `llmwiki eval retrieval` is the standard development quality check for retrieval changes.
- Retrieval eval must not call external LLM APIs by default.
- Retrieval eval must not write `wiki/`, `staging/`, `sources/`, or catalog mutations; it reads the local catalog and committed eval datasets.
- `llmwiki eval pdf-quality` is local, deterministic, read-only, and must not call LLM, embedding, MinerU, network, or write `wiki/`, `staging/`, `sources/`, catalog, or vector cache files.
- Eval output must not include API keys, secret config contents, or sensitive local files.
- Run relevant evals before and after retrieval/parser/wiki-maintenance quality changes.
- The committed eval dataset is the golden local suite; large public benchmark downloads should remain gitignored raw material unless explicitly curated into committed eval cases.

## 11. UI Dashboard Rules

- `llmwiki ui` starts a local dashboard bound to `127.0.0.1` by default.
- UI GET/status endpoints may read workspace skeleton, catalog, staging metadata, source sidecars, UI job state, parser status, config presence, and vector index status.
- UI GET/status endpoints must not call LLM providers, embedding providers, MinerU document parsing, parser execution, add/ingest/apply/ask/lint/eval/clean, or any write path.
- V3.4 UI adds these read-only browser endpoints: `GET /api/sources/<source-id>`, `GET /api/pages/<page-id>`, `GET /api/evidence/claims`, `GET /api/evidence/claims/<claim-id>`, and `GET /api/evidence/relationships`.
- V3.4 browser endpoints may read catalog rows, catalog-referenced wiki markdown, generated source metadata/block/chunk sidecars, and UI job summaries. They must not call `retrieve`, LLM providers, embedding providers, MinerU, parser execution, ask, synthesis, add/ingest/apply, lint/eval/clean, or any write path.
- In the V3.4 UI, page markdown and synthesis markdown are display text, not formal evidence. Only catalog-backed claims and catalog relationships count as evidence.
- V3.4 locator context is conservative: Markdown/text `line:N` and PDF `page:N;block:<block-id>` may show bounded context; unsupported or missing locators must warn instead of fabricating context.
- V3.3 UI allows these mutating token-protected endpoints: `POST /api/sources/add`, `POST /api/ask`, `POST /api/ask/<job-id>/synthesis/preview`, and `POST /api/ask/<job-id>/synthesis/writeback`.
- `POST /api/sources/add` must require `X-LLMWiki-UI-Token`, validate one source path/URL, write `state/ui-jobs/` job state, and then invoke only the existing `add_and_process_source(...)` pipeline through the UI worker.
- `POST /api/ask` may call `answer_question(...)` only through a queued UI worker job after token validation. It must not run ask work from GET routes or during server startup.
- UI query planning diagnostics are not evidence. Retrieved Evidence and Citations UI sections must only show catalog-backed contexts/citations returned by existing ask/retrieve code.
- `POST /api/ask/<job-id>/synthesis/preview` must be read-only: it may call synthesis planning through a queued job but must not create staging runs, wiki pages, source artifacts, or catalog rows.
- `POST /api/ask/<job-id>/synthesis/writeback` must use only `create_synthesis_run(...)`; the UI layer must not call `apply_run`, write catalog rows, or write wiki pages directly.
- Synthesis plan output is not evidence, and preview/writeback jobs must remain tied to an answered ask job.
- UI must not bypass staging/apply and must not directly mutate formal `wiki/`, `staging/`, `sources/`, `state/catalog.sqlite`, or `state/embeddings/` data outside the existing add pipeline.
- UI job state under `state/ui-jobs/` is generated cache and must be cleaned after tests/acceptance unless the user asks to keep it.
- UI responses must not expose API key values, `config/api-keys.toml` contents, raw prompts, raw LLM responses, full parser logs, or parser artifact contents.
- UI diagnostics are not evidence. Parser/status/config fields shown by the dashboard must not be returned as retrieval evidence.
- V3.4 UI supports single-source add jobs, ask/synthesis jobs, and read-only Evidence/Wiki Browser. Do not add batch/folder import, retry/cancel, chat history, fine-grained progress UI, editing, relationship confirmation, or quality dashboards without a later V3/V4/V5 spec and implementation plan.

## 11.5 Corpus Import Queue Rules

- V4.1 corpus import is CLI-first batch orchestration for local files/folders/list files. Do not add UI routes, URL batch import, concurrent workers, background daemons, or metric/result extraction without a later spec and implementation plan.
- `llmwiki corpus import` and `llmwiki corpus retry` may call only the existing `add_and_process_source(...)` pipeline for formal knowledge changes.
- The corpus layer must not directly write `wiki/`, `staging/`, `sources/`, `state/catalog.sqlite`, or `state/embeddings/`.
- `llmwiki corpus status` and `llmwiki corpus import --dry-run` are read-only: they must not call LLM providers, embedding providers, MinerU, parser execution, add/ingest/apply, ask, synthesis, lint/eval/clean, or any write path.
- Batch state under `state/corpus-batches/` is generated cache and must not be committed. It uses `corpus_batch.v4.1`, `corpus_item.v4.1`, and `corpus_attempt.v4.1`.
- Failed corpus items must not invalidate successful items. Retry must append attempts to the same batch instead of creating a replacement batch.
- Duplicate detection may use local SHA-256 and applied catalog state, but uncertain duplicates must be reported as warnings instead of being silently skipped.
- V4.2 `llmwiki corpus inventory` is read-only paper identity inventory over catalog sources, PDF metadata sidecars, normalized source text, and optional V4.1 batch state.
- `llmwiki corpus inventory` must not call LLM providers, embedding providers, MinerU, parser execution, add/ingest/apply, ask, synthesis, lint/eval/clean, or any write path.
- `llmwiki corpus inventory` must not write `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/corpus-batches/`, or `state/embeddings/`.
- V4.2 inventory uses `corpus_inventory.v4.2` and `paper_identity.v4.2`; first-version `paper_id` defaults to `source_id` and no `paper_identities` catalog table is required.
- DOI, arXiv id, year, authors, venue/status, parser backend, and duplicate warnings are metadata for inventory. They are not formal evidence and must not become claims without a later source-backed extraction spec.
- V4.2 duplicate warnings must not merge, delete, overwrite, or silently skip sources.
- V4.3 metric/result claim extraction extends research-paper ingest only; do not add UI, `llmwiki metric timeline`, metric aliases, relationship classification, or source page required sections in V4.3.
- V4.3 uses `metric_result_claim.v4.3`, writes review metadata to `staging/<run-id>/metric-results.jsonl`, and persists only cited applied records to the catalog `metric_results` table during `apply_run`.
- `claims` remain the evidence source of truth. `metric_results` rows must reference real `claim_id`, `source_id`, `paper_id`, `claim_text`, and citation locator; first-version `paper_id` defaults to `source_id`.
- Weak, ambiguous, unsupported, invalid-locator, or non-applied result candidates may appear in staging/triage but must not become durable `metric_results` rows.
- Parser artifacts, parser logs, parser backend attempts, diagnostics, raw prompts, and raw LLM responses are not evidence for metric/result claims.
- V4.3 real acceptance must use the configured real LLM provider on a declared `docs/papers/` subset followed by the full 20-paper corpus, and must record only sanitized observations under `docs/specs/`.
- V4.4 `llmwiki metric list` and `llmwiki metric timeline` are CLI-first, read-only metric evolution queries over durable `metric_results`.
- V4.4 metric timeline rows must come from `state/catalog.sqlite metric_results` joined to formal `claims` and `sources`; paper identity fields are display/sort metadata, not result evidence.
- V4.4 uses `metric_list.v4.4`, `metric_timeline.v4.4`, and `metric_timeline_item.v4.4`; every non-warning timeline row must preserve real `result_id`, `claim_id`, `source_id`, and `citation_locator`.
- `llmwiki metric list` and `llmwiki metric timeline` must not call LLM providers, embedding providers, MinerU, parser execution, add/import, ingest, apply, ask, synthesis, lint, eval, clean, or raw PDF chunk retrieval.
- `llmwiki metric list` and `llmwiki metric timeline` must not write `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/corpus-batches/`, `state/embeddings/`, `state/ui-jobs/`, or `.tmp/`.
- V4.4 does not implement UI, metric alias auto-merge, substring metric matching, unit conversion, ranking, trend/gap/synthesis, relationship classification, or wiki writeback.
- V4.5-min `llmwiki eval result-evidence` is CLI-first and read-only. It evaluates durable `metric_results` rows against formal `claims`, `sources`, source sidecars, normalized source text, and paper inventory metadata.
- V4.5-min uses `result_evidence_quality.v4.5` and `result_evidence_item.v4.5`; every item must preserve real `result_id`, `claim_id`, `source_id`, `paper_id`, and `citation_locator`.
- `llmwiki eval result-evidence` must not call LLM providers, embedding providers, MinerU, parser execution, add/import, ingest, apply, ask, synthesis, lint, clean, other eval commands, or raw PDF chunk retrieval.
- `llmwiki eval result-evidence` must not write `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/corpus-batches/`, `state/embeddings/`, `state/ui-jobs/`, or `.tmp/`.
- V4.5-min does not implement UI, extraction prompt changes, metric aliases, unit conversion, timeline ranking, automatic repairs, or wiki writeback.
- V4.5-min real acceptance uses a fixed 5-paper `docs/papers/` subset instead of the full 20-paper corpus. Preserve `.tmp/paper-v45-acceptance` after acceptance unless the user explicitly approves cleanup.

## 12. Generated Files And Cleanup

每次运行测试、验收、批量导入实验或真实 PDF acceptance 后，必须及时清理生成态和缓存，除非用户明确要求保留用于检查。

优先使用项目命令清理，而不是手写临时删除脚本：

```bash
llmwiki clean --root .
llmwiki clean --root . --scope generated
llmwiki clean --root . --scope all
```

默认 `llmwiki clean --root .` 只清理测试缓存和临时验收工作区；`--scope generated` 清理生成态 source/wiki/staging/state/vector cache；`--scope all` 同时清理两类内容。需要确认删除范围时先加 `--dry-run`。

优先清理：

- `.test-workspaces/`
- `.pytest_cache/`
- `.tmp/` 下的临时验收 workspace
- generated `sources/raw/*`、`sources/normalized/*`、`sources/metadata/*`、`sources/blocks/*`、`sources/chunks/*`，保留 `.gitkeep`
- generated `sources/parser-artifacts/*`，保留 `.gitkeep`
- generated `staging/*`
- generated `state/catalog.sqlite`
- generated `state/corpus-batches/*`
- generated `state/embeddings/*`
- generated `wiki/sources/*.md`、`wiki/concepts/*.md`、`wiki/entities/*.md`、`wiki/syntheses/*.md`
- generated `wiki/index.md` 和 `wiki/log.md`，除非当前任务明确要求保留正式输出

不要删除：

- 用户资料，例如 `docs/papers/`
- 本地密钥，例如 `config/api-keys.toml`
- `.gitkeep`
- 用户明确要求保留的验收工作区或输出

提交前必须确认 `git status --short` 不包含 `.test-workspaces`、`.pytest_cache`、`.tmp`、生成态 source/wiki/staging/state/vector files、`config/api-keys.toml` 或大型 PDF 原料。

## 13. Git And Closeout

- 按功能拆分提交，不要把无关改动塞进一个提交。
- 如果一次运行修改了仓库文件，结束前应提交，除非存在明确 blocker。
- 如果不能提交，必须说明原因，并列出仍未提交的文件。
- 每次提交前运行与改动相关的最小验证；涉及文档契约时至少运行 `tests/test_regression_samples.py`。
- 不要提交 `.test-workspaces`、`.pytest_cache`、`.tmp`、生成态 wiki/source/staging/state/vector cache 或 API key。

## 14. First-Version Boundaries

- Do not default to external hosted vector databases. The V2.6 local rebuildable vector index under `state/embeddings/` is allowed.
- Do not default to MCP integrations.
- V3.4 local Source Library, Ask/Synthesis UI, and read-only Evidence/Wiki Browser are allowed; do not add further operational UI features outside an approved V3 spec and implementation plan.
- Do not add cloud sync or team permission systems by default.
- Do not OCR scanned PDFs by default.
- Do not automatically resolve conflicts between sources.
