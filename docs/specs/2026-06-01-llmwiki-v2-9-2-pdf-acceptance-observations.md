# LLMWiki V2.9.2 PDF Acceptance Observations

Date: 2026-06-01

Workspace: `.tmp/papers-v292-acceptance` (temporary, not committed)

Dataset: 20 local text PDFs under `docs/papers/`

## Summary

- PDF add/apply: 20/20 completed.
- First pass add/apply: 18/20 completed.
- Retry after transient LLM JSON formatting failures: 2/2 completed.
- PDF sources in catalog: 20.
- Applied ingest runs: 20.
- PDF claims: 3358.
- Embedding rebuild: completed, 3421 chunks, 768 dimensions.
- Retrieval eval dataset `tests/evals/retrieval_v2_9_1_pdf_foundation.jsonl`: 4/4 passed.

## PDF Quality Eval

`llmwiki eval pdf-quality --root .tmp/papers-v292-acceptance --json`

- schema_version: `eval.pdf_quality.v2.9.2`
- pdf_source_count: 20
- title_pass_rate: 1.0
- sidecar_completeness: 1.0
- block_locator_validity: 1.0
- content_block_ratio: 0.9002389997372525
- parser_created_duplicate_alias_count: 0
- title_quality_issue_count: 0
- invalid_sidecar_schema_count: 0
- high_parser_warning_source_count: 0
- low_content_block_ratio_source_count: 0

## Retrieval Eval

`llmwiki eval retrieval --root .tmp/papers-v292-acceptance --dataset tests/evals/retrieval_v2_9_1_pdf_foundation.jsonl`

- cases: 4
- passed: 4
- failed: 0
- hit@5: 1.00
- recall@5: 0.79
- precision@5: 0.70
- mrr: 1.00
- evidence contract metrics: all 1.00

## Lint Observation

`llmwiki lint --root .tmp/papers-v292-acceptance` returned one non-PDF-parser issue:

- duplicate alias: 1
- shared concept/entity alias: 3
- pdf parser issues: 0

The duplicate alias is a source/entity identity collision around `GTA1: GUI Test-time Scaling Agent`; it is not a parser-created alias. This should inform a later identity-resolution refinement, not block the V2.9.2 parser-quality acceptance.

## Transient LLM Formatting Observation

Two PDFs failed on the first add pass with `Expecting ',' delimiter` from LLM JSON parsing:

- `2503.15661.pdf`
- `2506.16042.pdf`

Manual diagnostic reruns of chunk and consolidation prompts for both sources returned parseable JSON, and re-running `llmwiki add` completed successfully. This appears to be transient LLM formatting variability rather than a deterministic parser failure. A future robustness improvement could add one repair retry around chunk/consolidation JSON parsing.

## Generated Files

The temporary workspace, generated source sidecars, catalog, vector cache, staging, wiki output, and copied local API key were not committed.
