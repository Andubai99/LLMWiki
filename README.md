# LLM Wiki

LLM Wiki is a local-first personal research library: Python CLI, Markdown wiki, SQLite index, and a staging review workflow. It is meant to act as a source-backed knowledge compiler, not a free-form notes folder.

Raw sources stay immutable under `sources/raw/`. Ingest creates candidate claims and wiki page patches under `staging/<run-id>/`; only `llmwiki apply` writes final wiki pages and synchronizes `state/catalog.sqlite`.

## Directory Layout

- `sources/raw/`: original Markdown, text PDF, text, and web snapshots.
- `sources/normalized/`: normalized Markdown with line/page anchors.
- `state/catalog.sqlite`: rebuildable source, claim, alias, page, link, relationship, and ingest run index.
- `wiki/index.md`: entry index.
- `wiki/log.md`: append-only apply log.
- `wiki/sources/`: source summaries.
- `wiki/concepts/`: concept pages.
- `wiki/entities/`: entity pages.
- `wiki/syntheses/`: synthesis pages.
- `staging/<run-id>/`: `triage.md`, `claims.jsonl`, and `patches/`.
- `llmwiki/`: CLI implementation.
- `tests/`: automated tests and regression fixtures.

## Install

Use Python 3.10 or newer. From the repository root:

```bash
python -m pip install -e .
```

The first version uses a small dependency set. `pypdf` is used for text PDF extraction; scanned PDF OCR is not supported.

## CLI Usage

```bash
llmwiki init --root .
```

Creates the workspace directories, default config, agent contract, wiki index/log, and SQLite schema.

```bash
llmwiki add tests/fixtures/minimal_source.md --root .
```

Copies the source into `sources/raw/`, writes normalized Markdown with line anchors into `sources/normalized/`, computes SHA-256, and deduplicates repeated imports by hash.

```bash
llmwiki ingest <source-id> --root .
```

Extracts cited claims first, performs simple identity/conflict checks, and writes only to `staging/<run-id>/`.

```bash
llmwiki review <run-id> --root .
```

Prints candidate patch count, duplicate candidates, conflict candidates, citation coverage, and patch paths. It does not modify `wiki/`.

```bash
llmwiki apply <run-id> --root .
```

Validates staged patch safety, writes Markdown pages under `wiki/`, refreshes `wiki/index.md`, appends `wiki/log.md`, and synchronizes SQLite claims/pages/links/relationships/runs.

```bash
llmwiki query "retrieval citation anchors" --root .
```

Searches the SQLite claim store using FTS/BM25 when available, falls back to simple text search, and prints retrieval context with `source_id` and citation locators. It does not call an external LLM API.

```bash
llmwiki lint --root .
```

Checks broken links, orphan pages, duplicate aliases, uncited claims, source hash drift, missing citation status, and contradiction indicators.

```bash
llmwiki doctor --root .
```

Checks Python, workspace directories, config, database schema, and wiki index/log.

## Obsidian And Git

Open the repository root or `wiki/` folder in Obsidian to browse pages. Keep the repository under Git so raw sources, normalized sources, staging reviews, and applied Markdown history remain auditable.

## Supported

- Markdown and plain text source import.
- Web snapshot import for reachable `http`/`https` URLs.
- Text PDF import through `pypdf`.
- Claim-first staging with citations.
- Source summary, concept, and entity Markdown pages.
- SQLite source/claim/page/link/relationship indexing.

## Not Supported

- External LLM API calls by default.
- Vector databases.
- MCP server integration.
- Web UI or Obsidian plugin.
- Cloud sync.
- Team permissions or multi-user review.
- Scanned PDF OCR.
- Automatic conflict adjudication.
