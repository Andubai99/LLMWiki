# LLMWiki V2.9.6 MinerU Hardening Acceptance Observations

Date: 2026-06-02

Workspace: `.tmp/papers-v296-mineru-hardening`

## Commands

- `llmwiki parsers status --root .tmp\papers-v296-mineru-hardening --json`
- `llmwiki add docs\papers\2506.16042.pdf --root .tmp\papers-v296-mineru-hardening`
- `llmwiki add docs\papers\2508.03923.pdf --root .tmp\papers-v296-mineru-hardening`
- `llmwiki add docs\papers\2406.08184.pdf --root .tmp\papers-v296-mineru-hardening`
- `llmwiki lint --root .tmp\papers-v296-mineru-hardening`
- `llmwiki eval pdf-quality --root .tmp\papers-v296-mineru-hardening --json`
- `llmwiki eval retrieval --root .tmp\papers-v296-mineru-hardening --dataset tests\evals\retrieval_v2_9_1_pdf_foundation.jsonl`
- `llmwiki add docs\papers\2404.07972.pdf --root .tmp\papers-v296-mineru-hardening --parser mineru`

## Results

- Parser status found MinerU through `repo_venv`: `F:\LLMWiki\.venv\Scripts\mineru.exe`.
- All three normal `add` runs succeeded through auto fallback to `pypdf`.
- `lint` passed with `pdf parser issues: 0`.
- `eval pdf-quality` reported:
  - `pdf_source_count: 3`
  - `parser_backend_distribution: {"pypdf": 3}`
  - `auto_fallback_count: 3`
  - `mineru_command_source_distribution: {"repo_venv": 3}`
  - `mineru_attempt_count: 3`
  - `mineru_attempt_failure_count: 3`
  - `mineru_attempt_missing_content_list_count: 3`
  - `auto_fallback_with_attempt_diagnostics_count: 3`
  - `auto_fallback_missing_attempt_diagnostics_count: 0`
  - `block_locator_validity: 1.0`
- PDF retrieval eval passed all cases: `Passed: 4`, `Failed: 0`.
- Explicit `--parser mineru` on an unimported PDF failed hard at import with a safe reason:
  - `MinerU command exited with code 1; MinerU content-list output was not found`

## Observations

- V2.9.6 hardening works as intended: auto fallback remains successful and records failed MinerU attempts plus successful pypdf attempts.
- The current local MinerU invocation is discoverable but does not produce a content-list path that the adapter can use.
- Next parser work should inspect the actual MinerU CLI mode/output layout or adjust `mineru_method` / `mineru_backend` config defaults before expecting MinerU-backed sources in real acceptance.
- No API keys, parser logs, parser artifacts, generated wiki pages, catalog, embeddings, or `.tmp` workspace files should be committed.
