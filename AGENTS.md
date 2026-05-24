# LLM Wiki Agent Contract

This repository is a local, source-backed research wiki. Treat it as a knowledge compiler workspace, not as a free-form notes folder.

## Operating Rules

- Do not modify files under `sources/raw/`.
- Do not write final wiki pages directly during ingest. Write candidate changes under `staging/<run-id>/`.
- Every substantive claim proposed for the wiki must cite a source id and a page, line, or paragraph anchor when available.
- Preserve uncertainty. If sources disagree, create a conflict note in triage instead of choosing a winner.
- Prefer updating existing concept/entity pages over creating near-duplicate pages.
- Keep Markdown readable in Obsidian.
- Treat `state/catalog.sqlite` as a rebuildable cache. The durable assets are raw sources, normalized sources, and Markdown wiki pages.

## Current Capability Stage

The current project stage is scaffold-only. CLI commands exist as interfaces, but ingest, review, apply, query, and lint behavior still need implementation.

