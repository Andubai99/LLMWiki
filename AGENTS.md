# LLM Wiki Agent Contract

This repository is a local, source-backed research wiki. Treat it as a knowledge compiler workspace, not as a free-form notes folder.

## Operating Rules

- Do not modify files under `sources/raw/`.
- Do not write final wiki pages directly during ingest. Write candidate changes under `staging/<run-id>/`.
- Only `llmwiki apply <run-id>` may write reviewed changes into `wiki/`, `wiki/index.md`, `wiki/log.md`, and `state/catalog.sqlite`.
- Every substantive claim proposed for the wiki must cite a source id and a page, line, paragraph, or section anchor when available.
- Important judgments without citation must be marked weak/uncited and must not become a formal conclusion.
- Preserve uncertainty. If sources disagree, create a conflict note in triage instead of choosing a winner.
- Prefer updating existing concept/entity pages over creating near-duplicate pages.
- Before creating a concept/entity page, check existing page titles, aliases, and similar names; uncertain matches go to duplicate candidates in triage.
- Keep Markdown readable in Obsidian.
- Treat `state/catalog.sqlite` as a rebuildable cache. The durable assets are raw sources, normalized sources, and Markdown wiki pages.
- `wiki/log.md` is append-only.

## First-Version Boundaries

- Do not default to external LLM API calls.
- Do not default to vector databases.
- Do not default to MCP integrations.
- Do not add a Web UI or Obsidian plugin by default.
- Do not add cloud sync or team permission systems by default.
- Do not OCR scanned PDFs by default.
- Do not automatically resolve conflicts between sources.
