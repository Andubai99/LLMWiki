# LLM Wiki Agent Contract

This repository is a local, source-backed research wiki. Treat it as a knowledge compiler workspace, not as a free-form notes folder.

## Operating Rules

- Do not modify files under `sources/raw/`.
- Do not write final wiki pages directly during ingest. Write candidate changes under `staging/<run-id>/`.
- Codex/LLM must not bypass staging; proposed knowledge changes must be reviewable before apply.
- Only `llmwiki apply <run-id>` may write reviewed changes into `wiki/`, `wiki/index.md`, `wiki/log.md`, and `state/catalog.sqlite`.
- Apply must pass safety validation before any wiki/catalog mutation.
- Every substantive claim proposed for the wiki must cite a source id and a page, line, paragraph, or section anchor when available.
- Claims must be traceable to a source locator; do not invent citations or source anchors.
- Important judgments without citation must be marked weak/uncited and must not become a formal conclusion.
- Preserve uncertainty. If sources disagree, create a conflict note in triage and keep a contradicts relationship instead of choosing a winner.
- Prefer updating existing concept/entity pages over creating near-duplicate pages.
- Before creating a concept/entity page, check existing page titles, aliases, and similar names; uncertain matches go to duplicate candidates in triage.
- Agents must not overwrite user-authored wiki content without a recoverable backup or an explicit merge strategy.
- Keep Markdown readable in Obsidian.
- Treat `state/catalog.sqlite` as a rebuildable cache. The durable assets are raw sources, normalized sources, and Markdown wiki pages.
- `wiki/log.md` is append-only.

## Retrieval Interface

- `llmwiki retrieve` is the standard evidence interface for external RAG systems, agents, and LLM prompts.
- Retrieval output must only expose claims, citations, page paths, and relationships that exist in the local catalog/wiki.
- Do not forge claim ids, source ids, citation locators, page paths, scores, or relationships.
- weak/uncited claims must not be treated as strong evidence by callers or agents.
- `contradicts` relationships must be exposed to callers; do not hide conflicts or silently choose a winner.
- Retrieval must not call external LLM APIs by default.

## LLM Provider Rules

- Real LLM calls are allowed in stage 2 and are enabled by default through the OpenAI-compatible DeepSeek provider.
- API Key values, tokens, `.env` files, `config/api-keys.toml`, and sensitive logs must never be committed.
- The DeepSeek API Key must be read from the local ignored `config/api-keys.toml` file.
- Do not write API keys into `config/config.toml`, README, tests, source files, logs, staging artifacts, or committed examples.
- LLM output must not bypass staging, review, and apply.
- This stage must not let an LLM directly modify formal wiki pages.
- Do not add a mock provider or no-network LLM test path for this stage.
- LLM ingest proposals may create `claims.jsonl`, `triage.md`, `llm-proposal.json`, and patch files only under `staging/<run-id>/`.
- Claims without valid source locators must remain weak/uncited and must not become formal wiki conclusions.

## First-Version Boundaries

- Do not default to vector databases.
- Do not default to MCP integrations.
- Do not add a Web UI or Obsidian plugin by default.
- Do not add cloud sync or team permission systems by default.
- Do not OCR scanned PDFs by default.
- Do not automatically resolve conflicts between sources.
