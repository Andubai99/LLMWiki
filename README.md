# LLM Wiki

LLM Wiki is a local-first framework for building a source-backed personal research wiki with LLM agents.

The first milestone is a Python CLI scaffold plus a Markdown workspace:

- immutable raw sources
- normalized source text with citation anchors
- staged LLM-proposed wiki changes
- review/apply workflow
- Markdown wiki as the durable human-readable artifact
- SQLite as an index and audit cache, not the source of truth

See [docs/CAPABILITY_STRUCTURE.md](docs/CAPABILITY_STRUCTURE.md) for the current capability map.

