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

V3 UI dashboard 线已经冻结并进入删除目标。后续论文主线不再新增、扩展或维护 UI dashboard 功能；用户交互出口应收束到 CLI、gold/eval 报告，以及后续 metric-graph-aware Ask/Synthesis。

### V4: PDF And Research Corpus Ingestion

围绕 `docs/papers` 中的 20 篇 CUA 论文，解决批量导入队列、长任务状态、失败续跑、MinerU 验收闭环、表格/图/公式 evidence foundation、论文级 page type / knowledge structure。

### V5: Research Metric Graph And Evidence-Grounded Ask/Synthesis

当前项目主线固定为：给定一批同领域论文，系统持续抽取实验指标结果，维护可追溯 research metric graph，并支持用户围绕指标、benchmark、方法和可比较性进行证据约束问答与综合。后续开发优先围绕 metric result extraction、evidence coverage audit、research metric graph、incremental update、gold set evaluation、graph-aware ask 和 evidence-grounded synthesis 推进。

在 V3/V4/V5 的具体 spec/plan 没有明确要求前，不要临时加入大范围架构改造。

## 3. Operating Rules

- Production Python package code lives under `src/llmwiki/`. Do not add new runtime modules under a root-level `llmwiki/` directory.
- Tests live under `tests/`; committed documentation/specs/plans live under `docs/`.
- New implementation plans must be saved under `docs/plans/`; new specs must be saved under `docs/specs/`. Do not create new plan/spec files under `docs/superpowers/`.
- Real acceptance observations must be written under `docs/observations/`. This directory is local, gitignored, and must not be committed; committed specs/plans may reference expected observation filenames there.
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

- UI dashboard is deprecated. Do not add new UI dashboard specs, tests, routes, controls, or acceptance work. Existing UI code may be removed by a dedicated deletion plan once CLI/Ask/Synthesis paths remain intact.
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
- V4.3 real acceptance must use the configured real LLM provider on a declared `docs/papers/` subset followed by the full 20-paper corpus, and must record only sanitized local observations under `docs/observations/`.
- V4.4 `llmwiki metric list` and `llmwiki metric timeline` are frozen CLI-first, read-only metric evolution queries over durable `metric_results`.
- Do not extend the Timeline line unless a future corpus actually needs year-based metric evolution; research metric graph is now the primary organization surface.
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
- V4.5.1 is a narrow MinerU result extraction quality repair over the same fixed 5-paper subset. It may improve parser status diagnostics, PDF result-focused chunk construction, metric result candidate validation, and result-evidence quality counters, but it must not add UI, catalog migrations, metric aliases, unit conversion, timeline ranking, automatic repairs, or wiki writeback.
- V4.5.1 strict acceptance must use `--parser mineru`, `mineru_backend = "pipeline"`, `mineru_method = "auto"`, and for the English 5-paper subset `mineru_extra_args = ["-l", "en"]`; accidental auto fallback must remain visible through parser metadata and `llmwiki eval result-evidence`.
- V4.5.1 result-focused chunks may group table/caption/nearby heading/result-text blocks into one bounded evidence window. The primary `citation_locator` remains one real block, and valid auxiliary blocks must be preserved in `evidence_block_ids`, `evidence_pages`, and `evidence_block_roles`.
- Placeholder metric values such as `See table`, `not reported`, and `N/A` must not become final cited durable `metric_results` when the same evidence bundle exposes a concrete value.
- Preserve `.tmp/paper-v451-mineru-repair-acceptance` after V4.5.1 acceptance unless the user explicitly approves cleanup.
- V4.6-min `llmwiki eval corpus-results` is CLI-first and read-only. It summarizes V4.2 inventory, V4.3 durable `metric_results`, V4.4 timeline readiness, and V4.5 result-evidence quality into `corpus_results_eval.v4.6`.
- V4.6-min uses `corpus_results_paper.v4.6`, `corpus_results_metric.v4.6`, and `corpus_results_warning.v4.6`; it is an acceptance/reporting surface, not a new evidence source.
- `llmwiki eval corpus-results` must not call LLM providers, embedding providers, MinerU, parser execution, add/import, ingest, apply, ask, synthesis, lint, clean, other eval commands, or raw PDF chunk retrieval.
- `llmwiki eval corpus-results` must not write `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/corpus-batches/`, `state/embeddings/`, `state/ui-jobs/`, or `.tmp/`.
- V4.6-min full acceptance uses strict MinerU over the full 20-paper `docs/papers/` corpus and preserves `.tmp/paper-v46-corpus-acceptance` unless the user explicitly approves cleanup.
- V4.7 `llmwiki metric canonicalize` is CLI-first and read-only. It reports conservative metric canonicalization, value repair suggestions, comparability groups, and upgraded timeline readiness over existing durable `metric_results`.
- V4.7 uses `metric_canonicalization_report.v4.7`, `canonical_metric.v4.7`, `metric_result_value_repair.v4.7`, `metric_comparability_group.v4.7`, `metric_timeline_readiness.v4.7`, and `metric_canonicalization_warning.v4.7`; it is not an evidence source and must not create, merge, delete, overwrite, or durably repair result rows.
- `llmwiki metric canonicalize` must not call LLM providers, embedding providers, MinerU, parser execution, add/import, ingest, apply, ask, synthesis, lint, clean, CLI eval recursion, or raw PDF chunk retrieval.
- `llmwiki metric canonicalize` must not write `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/corpus-batches/`, `state/embeddings/`, `state/ui-jobs/`, or `.tmp/`.
- V4.7 must not automatically merge vague labels such as `score`, `Avg`, or `Overall`; it should mark them as `ambiguous_label` or `context_dependent`.
- V4.7 acceptance should reuse preserved workspaces such as `.tmp/paper-v46-corpus-acceptance`; do not rerun full MinerU+LLM for canonicalization or timeline readiness reports.
- V4.8 `llmwiki metric repair-plan`, `llmwiki metric repair-status`, and `llmwiki metric repair-mark` are deprecated CLI-first metric repair review commands over existing V4.7 diagnostics.
- Do not continue V4.8 manual repair review as a core direction. Future work should prefer LLM-assisted metric normalization, evidence validation, and gold/eval feedback over human repair workflow expansion.
- V4.8 uses `metric_repair_plan.v4.8`, `metric_repair_proposal.v4.8`, `metric_repair_review_decision.v4.8`, `metric_repair_projection.v4.8`, `metric_repair_warning.v4.8`, and `metric_repair_run.v4.8`; proposals and decisions are review metadata, not evidence.
- Default `llmwiki metric repair-plan` and `llmwiki metric repair-status` must be read-only. `repair-plan --stage` and `repair-mark` may write only `staging/<repair-run-id>/` review artifacts.
- V4.8 must not update `metric_results`, mutate `state/catalog.sqlite`, change `llmwiki metric timeline`, create wiki pages, create source artifacts, or provide durable repair/apply.
- V4.8 must not call LLM providers, embedding providers, MinerU, parser execution, add/import, ingest, apply, ask, synthesis, lint, clean, CLI eval recursion, or raw PDF chunk retrieval.
- V4.8 acceptance should reuse `.tmp/paper-v46-corpus-acceptance`; do not rerun full MinerU+LLM for repair review proposal generation.
- V4.9 `llmwiki metric normalize`, `llmwiki metric normalize-status`, and `llmwiki metric timeline-synthesis` are CLI-first LLM metric normalization and timeline preview commands over existing catalog-backed `metric_results`.
- V4.9 uses `metric_normalization_run.v4.9`, `metric_evidence_bundle.v4.9`, `metric_normalization_decision.v4.9`, `metric_timeline_group.v4.9`, `metric_timeline_point.v4.9`, `metric_timeline_synthesis.v4.9`, and `metric_normalization_warning.v4.9`; decisions and timeline previews are derived metadata, not formal evidence.
- `llmwiki metric normalize --dry-run`, `normalize-status`, and `timeline-synthesis` must be read-only and must not call LLM providers or write workspace files.
- A real `llmwiki metric normalize` run may call the configured LLM provider and may write only `staging/<normalization-run-id>/` artifacts; it must not write `state/catalog.sqlite`, `wiki/`, `sources/`, `state/corpus-batches/`, `state/embeddings/`, or `state/ui-jobs/`.
- V4.9 must not rerun MinerU, parser execution, corpus import, ingest, apply, ask, synthesis writeback, lint, clean, or raw PDF chunk retrieval.
- V4.9 must not update durable `metric_results`, change `llmwiki metric timeline`, create durable overlays, or write wiki pages.
- V4.9 LLM prompts must use bounded evidence bundles only and must not save raw prompt, raw LLM response, API key, parser logs, parser artifacts, or unsupported evidence refs.
- V4.9 acceptance should reuse `.tmp/paper-v46-corpus-acceptance`; do not rerun full MinerU+LLM ingest for metric normalization and timeline synthesis.
- V5.0 Research Relationship Graph shifts the main research-intelligence surface from year-based timelines to source-backed cross-paper relationships.
- V5.0 is not a global scholarly knowledge graph. It is a local-first relationship graph compiler for a user-provided paper corpus.
- V5.0 commands include `llmwiki research graph`, `llmwiki research graph-status`, and `llmwiki research synthesize`.
- V5.0 uses schemas `research_relationship_run.v5.0`, `research_relationship_bundle.v5.0`, `research_relationship_edge.v5.0`, `research_graph.v5.0`, `research_synthesis.v5.0`, and `research_relationship_warning.v5.0`.
- Every accepted V5.0 relationship edge must preserve real evidence refs such as `claim_id`, `result_id`, `source_id`, `paper_id`, and `citation_locator`; the LLM must not invent relationship ids, evidence ids, source ids, paper ids, page paths, or locators.
- V5.0 relationship types may include `same_task`, `same_benchmark`, `same_metric`, `compares_against`, `improves_over`, `extends_method`, `uses_component`, `addresses_limitation`, `supports`, `contradicts_or_tensions`, `not_comparable`, and `background_related`.
- `not_comparable` is a first-class V5.0 output, not a failure; the system should preserve why papers or results cannot be fairly compared.
- V5.0 first implementation should be CLI-first and staging-only. It must not add UI, perform catalog migration, update durable relationships, write wiki pages, call MinerU/parser/import/ingest/apply, or perform external scholarly metadata lookup.
- `llmwiki research graph --dry-run`, `research graph-status`, and `research synthesize` must be read-only and must not call LLM providers or write workspace files. A real `research graph` run may call the configured LLM provider and may write only `staging/<relationship-run-id>/` artifacts.
- V5.0 acceptance should reuse `.tmp/paper-v46-corpus-acceptance` and V4.9 normalization staging artifacts where possible; full MinerU+LLM corpus re-ingest is not justified for first implementation.

## 11.6 Expensive Acceptance Policy

- MinerU+LLM full-corpus acceptance is expensive and must not be treated as routine validation.
- Default to reusing preserved acceptance workspaces such as `.tmp/paper-v46-corpus-acceptance` for read-only analysis, CLI reports, metric canonicalization, timeline readiness checks, and other post-processing work.
- Do not rerun MinerU+LLM imports when a task only changes read-only reporting, catalog queries, metric grouping, value normalization over existing rows, timeline readiness scoring, docs, tests, or formatting.
- Rerun MinerU+LLM only when the task changes ingest, PDF chunking, parser/block handling, LLM extraction prompts, metric result candidate validation, source import semantics, or apply-time metric persistence.
- When a rerun is necessary, use staged acceptance levels instead of jumping directly to the full corpus:
  - L0: unit tests and schema tests.
  - L1: read existing catalog/eval outputs.
  - L2: run new eval/report commands against preserved `.tmp` acceptance workspaces.
  - L3: rerun a targeted 1-3 paper MinerU+LLM subset.
  - L4: rerun the fixed 5-paper smoke corpus.
  - L5: rerun the full 20-paper corpus only for phase closure or when lower levels cannot answer the risk.
- Every future V4/V5 spec and implementation plan must include an `Acceptance Reuse` section stating whether existing acceptance workspaces can be reused, what the minimum rerun subset is, and what condition would justify L5 full-corpus rerun.
- Prefer `llmwiki corpus retry <batch-id> --failed-only` for transient failures; do not rerun already-applied items unless the changed code path requires re-ingesting successful sources.
- Preserve expensive acceptance outputs by default when the user intends to inspect results. Do not run clean commands that remove `.tmp/paper-v46-corpus-acceptance` or similar preserved workspaces unless the user explicitly approves cleanup.

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
