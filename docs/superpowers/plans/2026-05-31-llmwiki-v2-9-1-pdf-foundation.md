# LLMWiki V2.9.1 PDF Foundation Implementation Plan

## Summary

Replace the current PDF path, `PDF -> pypdf flat text -> first 16k chars -> LLM ingest`, with a source-backed foundation:

`PDF -> metadata + blocks + chunks -> full-document chunked LLM ingest -> page/block citation-backed claims`

The normal user entry remains:

```powershell
python -m llmwiki add <pdf> --root .
```

V2.9.1 does not add UI, MinerU, OCR, structured table extraction, figure extraction, formula object extraction, new SQLite tables, or a new `page_type="paper"`.

## Default Decisions

- `sources/metadata/`, `sources/blocks/`, and `sources/chunks/` are generated source artifacts. Their contents are gitignored; `.gitkeep` files preserve the directory skeleton.
- PDF parsing uses the existing `pypdf` dependency.
- Chunk boundaries are deterministic and are not chosen by the LLM.
- Chunk token estimates use `ceil(len(text) / 4)`, with target `4500` tokens and hard max `6000` tokens.
- V2.9.1 performs exact duplicate claim dedupe only. It does not do semantic claim merging because that risks losing locators.
- Chunk consolidation may summarize the source and propose pages/duplicates/conflict notes, but it must not introduce new formal claims.

## Key Changes

- Add `llmwiki/pdf_blocks.py` for PDF metadata and block parsing.
- Add `llmwiki/source_chunks.py` for deterministic section-aware chunks.
- Update source import so PDF normalized Markdown is rendered from blocks, not flat page-marker text.
- Update LLM ingest so PDF sources are processed chunk by chunk and require block/page locators.
- Update lint with PDF parser quality checks.
- Update staging, source pages, review output, retrieval tests, eval data, README, AGENTS, and `.gitignore`.

## Task List

1. Add source artifact directories and PDF parser tests.
2. Render normalized Markdown from blocks and integrate PDF import sidecars.
3. Add deterministic source chunker.
4. Add block locator validation to LLM ingest.
5. Add chunked PDF LLM ingest.
6. Expose PDF parse diagnostics in staging, source pages, and review output.
7. Add lint checks for parser artifacts and block locators.
8. Add retrieval and ask regressions for PDF block locators.
9. Add V2.9.1 eval dataset and docs.
10. Run real 20-paper acceptance in a temporary workspace.
11. Run final verification and clean generated state before finishing.

## Acceptance Criteria

- PDF source titles are no longer `<!-- page:1 -->`.
- Imported PDFs produce metadata, blocks, chunks, and normalized Markdown with stable block anchors.
- PDF claims use locators containing page and block information.
- `llmwiki add <pdf>` ingests all chunks rather than truncating normalized text to 16k chars.
- Lint reports missing sidecars, parser-marker titles, missing PDF block locators, and invalid block locators.
- Retrieval and ask continue to return catalog-backed evidence only.
- The 20 local papers in `docs/papers` can be exercised in a temporary workspace without committing generated artifacts.

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pdf_blocks.py tests/test_source_chunks.py tests/test_pdf_chunked_ingest.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_llm_ingest.py tests/test_add_source.py tests/test_add_pipeline.py tests/test_ingest_review.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_ask_workflow.py tests/test_retrieval_eval.py tests/test_query_lint_doctor.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m llmwiki --help
```
