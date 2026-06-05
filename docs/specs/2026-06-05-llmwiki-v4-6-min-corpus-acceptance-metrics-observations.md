# LLMWiki V4.6-min Corpus Acceptance Metrics Observations

Date: 2026-06-05

## Summary

V4.6-min `llmwiki eval corpus-results` was verified on:

- Smoke workspace: `.tmp/paper-v451-mineru-repair-acceptance`
- Full acceptance workspace: `.tmp/paper-v46-corpus-acceptance`

Both workspaces were preserved for follow-up inspection. No clean command was run against these acceptance workspaces.

## Commands

Smoke:

```powershell
.\.venv\Scripts\python.exe -m llmwiki eval corpus-results --root .tmp\paper-v451-mineru-repair-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki eval corpus-results --root .tmp\paper-v451-mineru-repair-acceptance
```

Full acceptance:

```powershell
.\.venv\Scripts\python.exe -m llmwiki parsers status --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki corpus import .tmp\paper-v46-corpus-acceptance\docs\papers --root .tmp\paper-v46-corpus-acceptance --recursive --parser mineru --json
.\.venv\Scripts\python.exe -m llmwiki corpus retry batch_20260605T071209Z0000_1e2879d0 --root .tmp\paper-v46-corpus-acceptance --failed-only --json
.\.venv\Scripts\python.exe -m llmwiki eval corpus-results --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki eval corpus-results --root .tmp\paper-v46-corpus-acceptance
```

Strict MinerU config:

- `mineru_command = "F:/LLMWiki/.venv/Scripts/mineru.exe"`
- `mineru_backend = "pipeline"`
- `mineru_method = "auto"`
- `mineru_extra_args = ["-l", "en"]`
- `parser_backend_result_counts = {"mineru": 414}`
- `parser_fallback_result_count = 0`

## Smoke Result

The 5-paper smoke workspace produced:

- sources/papers: 5 / 5
- batch applied: 5 / 5
- formal claims: 85
- durable metric results: 91
- joined/context available: 91 / 91
- parser fallback rows: 0
- table/caption/result-text result counts: 51 / 1 / 86
- unique table/caption evidence blocks: 22 / 1
- missing method/dataset/task/value: 0 / 0 / 0 / 19
- metric list count: 34
- timeline candidates: 4
- warnings/errors: 19 / 0

## Full 20-paper Result

Initial corpus import completed with transient failures:

- batch id: `batch_20260605T071209Z0000_1e2879d0`
- initial result: 16 applied, 4 failed
- failure shape: remote connection close or LLM chunk failure during ingest
- recovery: `corpus retry --failed-only` successfully applied all 4 failed items
- final batch result: 20 applied, 0 failed, 0 interrupted

Final `eval corpus-results` summary:

- sources/papers: 20 / 20
- batch applied: 20 / 20
- formal claims: 378
- durable metric results: 414
- joined results: 414 / 414
- resolvable locators: 414 / 414
- context available: 414 / 414
- parser backend distribution: `{"mineru": 414}`
- parser fallback rows: 0
- table/caption/result-text result counts: 337 / 17 / 321
- unique table/caption evidence blocks: 90 / 5
- missing normalized value: 63
- missing method/dataset/task: 0 / 0 / 0
- missing baseline: 320
- metric list count: 68
- timeline candidate count: 11
- missing year count: 0
- warnings/errors: 63 / 0

Quality gates:

- pass: catalog_available
- pass: corpus_sources_present
- pass: all_batch_items_applied
- pass: no_parser_fallback_results
- pass: metric_results_present
- pass: all_results_joined
- pass: all_locators_resolvable
- pass: context_available
- pass: no_result_errors
- warn: core_fields_usable, because 63 rows still miss normalized metric value
- pass: table_evidence_present
- pass: timeline_candidates_present

Top timeline-ready metrics:

- `success rate`: 101 rows, 13 papers, ready
- `accuracy`: 47 rows, 7 papers, ready
- `Average Accuracy`: 38 rows, 3 papers, ready
- `score`: 32 rows, 3 papers, ready
- `Avg`: 15 rows, 5 papers, ready
- `Overall Average`: 12 rows, 2 papers, ready
- `performance`: 11 rows, 5 papers, ready
- `Overall`: 8 rows, 2 papers, ready

## Notes

- `corpus-results` did not call parser, LLM, embedding, import, ingest, apply, ask, synthesis, lint, clean, or other eval commands during report generation.
- The full acceptance workspace contains generated source/wiki/staging/state/parser artifacts and local copied API key config; it is intentionally preserved and must not be committed.
- `formal_claim_count` can be lower than `metric_result_count` because one formal claim may produce multiple structured metric result rows.
