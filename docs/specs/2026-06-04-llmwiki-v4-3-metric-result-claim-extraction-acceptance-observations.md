# LLMWiki V4.3 Metric Result Claim Extraction Acceptance Observations

Date: 2026-06-04

Scope: real LLM acceptance for V4.3 metric/result claim extraction. Workspaces were temporary under `.tmp/` and are not committed. Local `config/api-keys.toml` was copied only into temporary workspace config directories and is not committed.

## Implementation Under Test

- Spec: `docs/specs/2026-06-03-llmwiki-v4-3-metric-result-claim-extraction-design.md`
- Plan: `docs/plans/2026-06-04-llmwiki-v4-3-metric-result-claim-extraction.md`
- Schema: `metric_result_claim.v4.3`
- Review artifact: `staging/<run-id>/metric-results.jsonl`
- Durable catalog table: `state/catalog.sqlite metric_results`

## Subset Acceptance

Workspace: `.tmp/paper-v43-subset`

Selected the three smallest PDFs under `docs/papers/`:

- `2506.16042.pdf`
- `2508.03923.pdf`
- `2406.08184.pdf`

Commands:

```powershell
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v43-subset
.\.venv\Scripts\python.exe -m llmwiki corpus import input-papers --root .tmp\paper-v43-subset --recursive --parser auto
.\.venv\Scripts\python.exe -m llmwiki corpus inventory --root .tmp\paper-v43-subset --json
.\.venv\Scripts\python.exe -m llmwiki lint --root .tmp\paper-v43-subset
```

Results:

- corpus items: 3
- applied: 3
- failed/skipped/interrupted: 0
- formal claims: 291
- staging metric result candidates: 40
- staging cited metric results: 40
- staging weak/unsupported metric results: 0
- staging invalid result locator count: 0
- staging table/caption result count: 4
- durable `metric_results` rows: 40
- durable rows joined to `claims` and `sources`: 40
- durable invalid locator rows: 0
- durable weak rows: 0
- rows with non-empty method: 32
- rows with non-empty dataset: 28
- rows with non-empty task: 31
- rows with non-empty metric name: 40
- rows with non-empty normalized metric value: 23
- rows with non-empty baseline: 17

Observed non-blocking diagnostics:

- One subset paper produced no durable result rows: `src_0ef840403ea0`.
- `llmwiki lint` reported 3 issues, all in existing PDF parser/identity diagnostics:
  - `pdf auto fallback missing attempt diagnostics: 3`
  - `pdf paper identity overlaps: 1`
- Lint reported no PDF claims missing page/block locators and no PDF claims with invalid block locators.

## Full 20-Paper Acceptance

Workspace: `.tmp/paper-v43-acceptance`

Input: all 20 local PDFs under `docs/papers/`.

Commands:

```powershell
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v43-acceptance
.\.venv\Scripts\python.exe -m llmwiki corpus import <absolute docs\papers path> --root .tmp\paper-v43-acceptance --recursive --parser auto
.\.venv\Scripts\python.exe -m llmwiki corpus inventory --root .tmp\paper-v43-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki lint --root .tmp\paper-v43-acceptance
```

Results:

- corpus items: 20
- applied: 20
- failed/skipped/interrupted: 0
- inventory paper count: 20
- inventory warning count: 7
- formal claims: 2740
- staging metric result candidates: 194
- staging cited metric results: 194
- staging weak/unsupported metric results: 0
- staging invalid result locator count: 0
- staging table/caption result count: 19
- durable `metric_results` rows: 194
- durable rows joined to `claims` and `sources`: 194
- durable invalid locator rows: 0
- durable weak rows: 0
- rows with non-empty method: 149
- rows with non-empty dataset: 161
- rows with non-empty task: 146
- rows with non-empty metric name: 194
- rows with non-empty normalized metric value: 130
- rows with non-empty baseline: 81

Durable result rows per paper were non-zero for 18 of 20 papers. The two papers with no durable metric result rows were:

- `src_0ef840403ea0`
- `src_98d4d9b8088c`

Observed non-blocking diagnostics:

- `llmwiki lint` reported 22 issues:
  - duplicate alias: 2
  - shared concept/entity alias: 2
  - pdf parser issues: 20
  - pdf extraction warnings: 2
  - pdf auto fallback missing attempt diagnostics: 20
  - pdf paper identity overlaps: 2
  - pdf llm json repairs observed: 1
- Lint reported:
  - pdf claims missing page/block locator: 0
  - pdf claims with invalid block locator: 0
  - unresolved potential contradictions: 0

These lint diagnostics are parser/identity quality observations and do not indicate V4.3 metric result locator failure.

## Notes

- An initial subset command tried passing three PDF paths directly to `corpus import`; the current CLI accepts one path plus optional list-file/directory input. The acceptance was rerun through a temporary input directory.
- A temporary PowerShell `Set-Content` list-file attempt produced a UTF-8 BOM path issue. This was an acceptance command issue, not a V4.3 extraction failure.
- No raw prompts, raw LLM responses, parser logs, parser artifact contents, generated workspace files, generated catalog, or API keys are committed.

## Conclusion

V4.3 acceptance passed the core result extraction contract:

- real LLM corpus import succeeded on the 3-paper subset and full 20-paper corpus;
- applied PDF sources produced formal claims with valid page/block locators;
- `metric-results.jsonl` was produced in staging;
- applied cited result records were persisted to `metric_results`;
- durable result rows joined to real `claims` and `sources`;
- durable invalid result locator count was 0;
- durable weak result row count was 0.
