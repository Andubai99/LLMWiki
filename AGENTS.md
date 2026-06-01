# LLM Wiki Agent Contract

This repository is a local, source-backed research wiki. Treat it as a knowledge compiler workspace, not as a free-form notes folder.

## Operating Rules

- Do not modify files under `sources/raw/`.
- Do not write final wiki pages directly during ingest. Write candidate changes under `staging/<run-id>/`.
- Codex/LLM must not bypass staging; proposed knowledge changes must be inspectable before apply.
- Use `llmwiki add <source-or-url> --root .` for normal source import.
- Only `llmwiki apply <run-id>` may write validated changes into `wiki/`, `wiki/index.md`, `wiki/log.md`, and `state/catalog.sqlite`.
- Use `llmwiki ingest`, `llmwiki review`, and `llmwiki apply` directly only for internal debugging or recovery.
- Apply must pass safety validation before any wiki/catalog mutation.
- Every substantive claim proposed for the wiki must cite a source id and a page, line, paragraph, or section anchor when available.
- Claims must be traceable to a source locator; do not invent citations or source anchors.
- Important judgments without citation must be marked weak/uncited and must not become a formal conclusion.
- Preserve uncertainty. If sources disagree, create a conflict note in triage and keep a `contradicts` relationship instead of choosing a winner.
- Negative, cautionary, or limiting claims are not contradictions by themselves. Do not create `contradicts` relationships from negation keywords such as `not`, `不`, `不需要`, or `不建议`.
- Prefer updating existing concept/entity pages over creating near-duplicate pages.
- Before creating a concept/entity page, check existing page titles, aliases, and similar names; uncertain matches go to duplicate candidates in triage.
- Agents must not overwrite user-authored wiki content without a recoverable backup or an explicit merge strategy.
- Keep Markdown readable in Obsidian.
- Treat `state/catalog.sqlite` as a rebuildable cache. The durable assets are raw sources, normalized sources, and Markdown wiki pages.
- `wiki/log.md` is append-only.

## Retrieval Interface

- `llmwiki retrieve` is the standard evidence interface for external RAG systems, agents, and LLM prompts.
- `llmwiki retrieve` uses hybrid retrieval: BM25/FTS, catalog title/alias/source title matching, one-hop graph relationships, exact formula/symbol spans, optional V2.6 local vector recall fused with RRF, and V2.7 reranking/evidence selection.
- `llmwiki query` is the human-readable view of `retrieve`; it must reuse the same local evidence path instead of maintaining a separate weak search implementation.
- `llmwiki ask` is the standard local evidence question-answering interface for users.
- Retrieval output must only expose claims, citations, page paths, and relationships that exist in the local catalog/wiki.
- Do not forge claim ids, source ids, citation locators, page paths, scores, or relationships.
- Retrieval normalization must be Unicode-aware and must not discard multilingual text, formulas, symbols, or emoji query features.
- Formula/symbol evidence such as `H2O`, `E=mc2`, Greek letters, ratios, and math notation must remain searchable and citation-backed.
- weak/uncited claims must not be treated as strong evidence by callers or agents.
- `contradicts` relationships must be exposed to callers; do not hide conflicts or silently choose a winner.
- `contradicts` means source-backed disagreement between claims. Retrieval exposes catalog relationships; it must not classify retrieved text as contradictory just because it contains negative wording.
- Retrieval must not call external chat LLM APIs by default.
- V2.6 local vector index under `state/embeddings/` is allowed as a rebuildable cache, but it is not durable knowledge and must not be committed.
- Vector candidates are recall signals only. They must map back to real catalog claims before they can be returned as evidence.
- When `[embedding].enabled = true` and a local vector index exists, `retrieve`, `query`, `ask`, and `eval retrieval` may call the configured embedding provider for query embedding. If query embedding fails, retrieval must fall back and expose a warning.
- Reranker and evidence selector output are not evidence. They may reorder, diversify, deduplicate, or select catalog-backed candidates, but they must not create claim ids, source ids, page paths, locators, scores, or relationships that were not already grounded in local retrieval/catalog data.
- V2.7 default reranking may use the local embedding provider and vector index. Chat LLM reranking is opt-in only and must remain disabled by default.
- Evidence selection must preserve weak/uncited and contradicting evidence visibility; it must not hide conflicts or upgrade weak evidence into strong conclusions.
- V2.7.1 evidence selection uses generic focused/comparison/conflict/broad modes. Focused single-subject questions must not add unrelated sources just for diversity when enough cited evidence exists for the dominant subject.
- V2.7.1 comparison and conflict questions must still preserve required source coverage and explicit `contradicts` evidence.
- External hosted vector databases are not default infrastructure for this repository.
- LLM query planning is allowed for `llmwiki ask` in V2.5, but default `retrieve`, `query`, and `eval retrieval` must not call external chat LLM APIs.
- Planner output must be schema-validated before any retrieval execution.
- Invalid planner filters such as `confidence = "high"` must be repaired through one schema-validated LLM repair attempt or rejected; do not silently coerce invalid values into valid evidence filters.
- Planner output is not source-backed evidence; do not treat planner intent, entities, subqueries, filters, or required evidence descriptions as claims or citations.
- Do not add domain-specific query rules, keyword intent classifiers, or term boosts for V2.5 or V2.7 reranking/evidence selection.
- `llmwiki eval retrieval` is the standard development quality check for retrieval changes.
- Retrieval eval must not call external LLM APIs by default.
- Retrieval eval must not write `wiki/`, `staging/`, `sources/`, or catalog mutations; it reads the local catalog and committed eval datasets.
- Run retrieval eval before and after retrieval quality changes, and compare metrics instead of relying on ad hoc questions.
- Eval output must not include API keys, secret config contents, or sensitive local files.
- The committed eval dataset is the golden local suite; large public benchmark downloads should remain gitignored raw material unless explicitly curated into committed eval cases.
- `ask` may call the configured LLM for query planning before retrieval, then must run local retrieve against wiki/catalog before answer generation.
- `ask` answers must be grounded in retrieved local evidence and must cite retrieved claim ids, source ids, and citation locators.
- If `ask` writes a useful answer back, synthesis writeback must go through staging/apply and must not directly mutate formal wiki pages.
- weak/uncited and contradicting evidence must remain visible in ask answers and synthesis pages.
- V2.8 synthesis planning may call the configured LLM, but synthesis plan output is not evidence.
- Do not create duplicate synthesis pages when an existing synthesis page should be updated.
- `llmwiki ask --preview-writeback` is read-only and must not create staging runs, wiki pages, or catalog rows.
- Synthesis pages are living wiki pages, not saved chat transcripts; preserve user-authored custom sections when updating them.
- Synthesis evidence maps may only cite existing catalog claims with real claim ids, source ids, citation locators, and page paths.
- Synthesis writeback must not create derived formal claims; synthesis `claims.jsonl` stays empty unless a future spec explicitly changes that.

## LLM Provider Rules

- Real LLM calls are allowed in stage 2 and are enabled by default through the OpenAI-compatible DeepSeek provider.
- API Key values, tokens, `.env` files, `config/api-keys.toml`, and sensitive logs must never be committed.
- The DeepSeek API Key must be read from the local ignored `config/api-keys.toml` file.
- Do not write API keys into `config/config.toml`, README, tests, source files, logs, staging artifacts, or committed examples.
- Embedding API keys must also stay in the local ignored `config/api-keys.toml` file under `[embedding].api_key`.
- LLM output must not bypass staging validation and apply.
- This stage must not let an LLM directly modify formal wiki pages.
- Do not add a mock provider or no-network LLM test path for this stage.
- LLM ingest proposals may create `claims.jsonl`, `triage.md`, `llm-proposal.json`, and patch files only under `staging/<run-id>/`.
- `llmwiki add` may automatically apply a validated staging run, but the LLM itself must not write formal wiki pages.
- `llmwiki ask --writeback` may automatically apply a validated synthesis run, but the LLM itself must not write formal wiki pages.
- LLM ingest claims with valid `line:N` source locators are normalized to `cited` before staging. Claims without valid source locators must remain weak/uncited and must not become formal wiki conclusions.
- PDF sources use V2.9.2 metadata/block/chunk sidecars under `sources/metadata/`, `sources/blocks/`, and `sources/chunks/`; these are generated local artifacts and must not be committed except `.gitkeep`.
- V2.9.4 PDF parser backends produce source artifacts, not wiki knowledge. Backend output must normalize into LLMWiki metadata/block/chunk sidecars before ingest.
- V2.9.5 defaults PDF parsing to `auto`: try MinerU first when installed/enabled, then visibly fall back to `pypdf` on auto-mode parser failure.
- Explicit `--parser mineru` is strict and must fail hard if MinerU is unavailable or invalid. Explicit `--parser pypdf` is a debug/fallback path and must not invoke MinerU.
- Backend-native files live under generated `sources/parser-artifacts/` and must not be committed except `.gitkeep`.
- MinerU tables, formulas, images, captions, and layout data may become normalized blocks, but they are not formal evidence until LLM ingest extracts catalog claims with valid page/block locators.
- Parser artifacts must not be returned as retrieval evidence. `retrieve`, `query`, and `ask` may only expose catalog-backed claims, page paths, locators, and relationships.
- Parser backend choice is deterministic config/CLI behavior, not LLM behavior.
- The LLM must not choose parser backend, block ids, chunk ids, chunk boundaries, page numbers, parser artifact paths, or citation anchors.
- PDF parser quality rules may use structural signals such as title position, author density, venue/status line shape, repeated header/footer detection, page-number shape, sidecar schema, and locator validity. They must not use domain-specific keyword rules.
- V2.9.2 blocks retain raw and cleaned text for traceability. `content_role="ignored"` blocks remain in sidecars for auditability but must not enter normalized body text or LLM chunk claim-extraction prompts.
- `llmwiki eval pdf-quality` is local, deterministic, read-only, and must not call LLM, embedding, MinerU, network, or write `wiki/`, `staging/`, `sources/`, catalog, or vector cache files.
- PDF chunk boundaries are deterministic. The LLM may extract claims from chunks, but it must not choose chunk boundaries or invent block ids.
- PDF source aliases must not include parser-created aliases or paper title aliases. The paper title belongs in `sources.title` and the source page title, not in the source formal alias list.
- LLM repair may only repair JSON syntax/schema shape for malformed PDF chunk or consolidation responses. It must not add evidence, invent claims, invent block ids, invent locators, or bypass source locator and staging validation.
- PDF claims require valid page/block locators such as `page:1;block:src_xxx_p001_b0004;section:Abstract`. Bare `line:N` locators remain valid for Markdown/text sources, not for PDF claims.
- PDF consolidation may propose source summary, concept/entity pages, duplicate candidates, and conflict notes, but it must not add new formal claims beyond chunk-level cited claims.
- `llmwiki parsers status` is read-only and must not call LLM, embedding, MinerU document parsing, network, or write workspace files.
- Auto fallback from MinerU to `pypdf` must remain visible in source metadata, staging diagnostics, lint, and `eval pdf-quality`.
- V2.9.5 may use MinerU as the preferred auto parser backend. Scanned PDF OCR, table cell-level evidence, figure understanding, and equation semantic interpretation are deferred.

## First-Version Boundaries

- Do not default to external hosted vector databases. The V2.6 local rebuildable vector index under `state/embeddings/` is allowed.
- Do not default to MCP integrations.
- Do not add a Web UI or Obsidian plugin by default.
- Do not add cloud sync or team permission systems by default.
- Do not OCR scanned PDFs by default.
- Do not automatically resolve conflicts between sources.
