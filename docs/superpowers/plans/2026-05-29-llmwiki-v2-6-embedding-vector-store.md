# LLMWiki V2.6 Embedding + Vector Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DashScope multimodal embedding provider, rebuildable local vector index, and vector retrieval signal while preserving catalog-backed evidence.

**Architecture:** Embeddings are configured separately from chat LLM settings. A rebuild command creates text chunks from catalog/wiki records and stores vectors under `state/embeddings/`; retrieval optionally embeds the query and fuses vector candidates with existing BM25/catalog/exact/graph candidates through RRF. Vector similarity never creates evidence; returned contexts still come from catalog claims.

**Tech Stack:** Python standard library, SQLite catalog, pytest, DashScope native multimodal embedding HTTP endpoint, JSONL vector storage.

---

## Tasks

- [ ] Task 0: Fix current config test drift and workspace defaults.
- [ ] Task 1: Add embedding config and DashScope multimodal provider.
- [ ] Task 2: Add chunk builder and rebuildable JSONL vector index.
- [ ] Task 3: Add `llmwiki embeddings test/rebuild/status`.
- [ ] Task 4: Integrate `VectorRetriever` into hybrid retrieval.
- [ ] Task 5: Update query/ask/eval regression and add V2.6 semantic eval cases.
- [ ] Task 6: Add real provider smoke test guarded by local key availability.
- [ ] Task 7: Update docs, AGENTS, and gitignore.
- [ ] Task 8: Run final verification, real acceptance where possible, and clean generated state.

## Verification Commands

- `.\.venv\Scripts\python.exe -m pytest tests/test_embeddings_provider.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests/test_vector_index.py tests/test_vector_retrieval.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests/test_embeddings_cli.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_retrieval_eval.py tests/test_query_lint_doctor.py tests/test_ask_workflow.py -q`
- `.\.venv\Scripts\python.exe -m pytest -q`
- `.\.venv\Scripts\python.exe -m llmwiki --help`
- `.\.venv\Scripts\python.exe -m llmwiki embeddings status --root .`
