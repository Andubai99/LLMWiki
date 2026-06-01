# LLMWiki MinerU Real Acceptance Observations

Date: 2026-06-01

Scope: real local acceptance for V2.9.5 MinerU auto parser behavior using a temporary workspace at `.tmp/papers-mineru-real-acceptance`. Generated workspace artifacts, parser artifacts, catalog, wiki pages, logs, and API keys are intentionally not committed.

## Environment

- Installed MinerU into the project virtual environment with `uv pip install -U "mineru[all]" --python .\.venv\Scripts\python.exe`.
- MinerU CLI version installed by package resolution: `mineru==3.2.1`.
- The command is available as `.venv\Scripts\mineru.exe`.
- `llmwiki parsers status --root . --json` only reports MinerU available when `.venv\Scripts` is on `PATH`.
- Temporary workspace parser config:
  - `default_backend = "auto"`
  - `mineru_backend = "pipeline"`
  - `mineru_method = "txt"`
  - `fallback_backend = "pypdf"`

## PDFs Tested

Selected the three smallest PDFs under `docs/papers` to keep the real parser and LLM ingest run bounded:

| PDF | Source ID | Parser Backend | Claims | Result |
| --- | --- | --- | ---: | --- |
| `2506.16042.pdf` | `src_ee48a997c1d5` | `pypdf` fallback from MinerU | 141 | applied |
| `2508.03923.pdf` | `src_7870174c6207` | `mineru` | 113 | applied |
| `2406.08184.pdf` | `src_0ef840403ea0` | `mineru` | 79 | applied |

All three completed `llmwiki add <pdf> --root <tmp>` and reached apply.

## Quality Checks

`llmwiki eval pdf-quality --root .tmp\papers-mineru-real-acceptance --json` reported:

- `pdf_source_count`: 3
- `title_pass_rate`: 1.0
- `sidecar_completeness`: 1.0
- `block_locator_validity`: 1.0
- `parser_backend_distribution`: `{"pypdf": 1, "mineru": 2}`
- `mineru_source_count`: 2
- `pypdf_source_count`: 1
- `auto_fallback_count`: 1
- `structured_block_count`: 24
- `table_like_block_count`: 14
- `equation_like_block_count`: 2
- `image_or_caption_block_count`: 8
- `block_locator_validity_by_backend`: `{"pypdf": 1.0, "mineru": 1.0}`

`llmwiki lint --root .tmp\papers-mineru-real-acceptance` returned `Lint OK`.

`llmwiki eval retrieval --root .tmp\papers-mineru-real-acceptance --dataset tests\evals\retrieval_v2_9_1_pdf_foundation.jsonl` returned:

- cases: 4
- passed: 4
- failed: 0
- `claim_id_validity`: 1.0
- `source_id_validity`: 1.0
- `citation_locator_presence`: 1.0
- `page_path_validity`: 1.0

`llmwiki ask "What does MobileAgentBench evaluate?" --root .tmp\papers-mineru-real-acceptance --no-writeback --json` returned `status="answered"` and cited only catalog-backed claims with page/block locators.

## Observed Issues

1. MinerU installed in `.venv` is not discovered unless `.venv\Scripts` is on `PATH`.
   - The project default `mineru_command = "mineru"` works in an activated shell.
   - In non-activated shells, `parsers status` reports `mineru_available=false` even though `.venv\Scripts\mineru.exe` exists.
   - Follow-up option: support resolving workspace-local `.venv\Scripts\mineru.exe`, or document setting `mineru_command` to an absolute local path in untracked/local config.

2. Auto fallback metadata loses failed MinerU command diagnostics.
   - For `src_ee48a997c1d5`, metadata recorded `parser_backend="pypdf"` and `parser_backend_fallback_from="mineru"`.
   - The fallback reason included `MinerU command exited with code 1; MinerU content-list output was not found`.
   - But metadata had `parser_command_invoked=false`, `parser_command_returncode=null`, and no stdout/stderr snippets.
   - This makes the fallback visible but not actionable enough. Follow-up should preserve sanitized failed MinerU command diagnostics on the fallback pypdf metadata.

3. MinerU `pipeline/txt` succeeded on two small PDFs and produced structured block counts, but one small PDF still failed MinerU and fell back to pypdf.
   - This is acceptable for `auto`, but it confirms fallback must remain visible and diagnosable.
   - The failed case should be useful as a regression fixture if we can extract a minimal sanitized failure condition.

4. Retrieval/ask worked without an embedding index by falling back to deterministic reranking.
   - This is not a parser failure.
   - For future semantic retrieval acceptance, run `llmwiki embeddings rebuild` before retrieval/ask comparison.

5. The LLM planner returned an empty `required_evidence` description/coverage object in the `ask` run.
   - This did not break answer grounding because citations were validated against retrieved catalog claims.
   - This is a planner quality issue, not a MinerU parser issue.

## Follow-Up Candidates

- V2.9.6 or patch: preserve MinerU command diagnostics across auto fallback.
- V2.9.6 or docs: make local `.venv\Scripts\mineru.exe` discovery/configuration explicit.
- Acceptance expansion: rerun 5-10 PDFs after command diagnostics are fixed, including one larger PDF and one table-heavy PDF.
- Retrieval acceptance: rebuild embeddings in the temp workspace before semantic PDF questions.
