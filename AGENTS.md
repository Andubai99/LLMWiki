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
- External hosted vector databases are not default infrastructure for this repository.
- LLM query planning is allowed for `llmwiki ask` in V2.5, but default `retrieve`, `query`, and `eval retrieval` must not call external chat LLM APIs.
- Planner output must be schema-validated before any retrieval execution.
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
- Claims without valid source locators must remain weak/uncited and must not become formal wiki conclusions.

## First-Version Boundaries

- Do not default to external hosted vector databases. The V2.6 local rebuildable vector index under `state/embeddings/` is allowed.
- Do not default to MCP integrations.
- Do not add a Web UI or Obsidian plugin by default.
- Do not add cloud sync or team permission systems by default.
- Do not OCR scanned PDFs by default.
- Do not automatically resolve conflicts between sources.
