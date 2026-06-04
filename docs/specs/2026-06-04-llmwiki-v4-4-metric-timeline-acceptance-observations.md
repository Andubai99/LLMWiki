# LLMWiki V4.4 Metric Timeline Acceptance Observations

Date: 2026-06-04

Scope: real LLM acceptance for V4.4 metric timeline over a V4.3-generated 20-paper corpus. The workspace was temporary under `.tmp/` and is not committed. Local `config/api-keys.toml` was copied only into the temporary workspace config directory and is not committed.

## Implementation Under Test

- Spec: `docs/specs/2026-06-04-llmwiki-v4-4-metric-timeline-design.md`
- Plan: `docs/plans/2026-06-04-llmwiki-v4-4-metric-timeline.md`
- Metric list schema: `metric_list.v4.4`
- Timeline schema: `metric_timeline.v4.4`
- Timeline item schema: `metric_timeline_item.v4.4`
- Durable result surface: `state/catalog.sqlite metric_results`

## Acceptance Workspace

Workspace: `.tmp/paper-v44-acceptance`

Input: all 20 local PDFs under `docs/papers/`.

Commands:

```powershell
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v44-acceptance
.\.venv\Scripts\python.exe -m llmwiki corpus import <absolute docs\papers path> --root .tmp\paper-v44-acceptance --recursive --parser auto
.\.venv\Scripts\python.exe -m llmwiki corpus retry batch_20260604T064436Z0000_dd42aa6e --root .tmp\paper-v44-acceptance
.\.venv\Scripts\python.exe -m llmwiki metric list --root .tmp\paper-v44-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric timeline "success rate" --root .tmp\paper-v44-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric timeline "success rate" --root .tmp\paper-v44-acceptance
.\.venv\Scripts\python.exe -m llmwiki metric timeline "__llmwiki_absent_metric_v44__" --root .tmp\paper-v44-acceptance --json
```

## Corpus Import Result

Batch: `batch_20260604T064436Z0000_dd42aa6e`

Initial import result:

- corpus items: 20
- applied: 19
- failed: 1
- failed source: `docs/papers/2508.15144.pdf`
- failure stage: `ingest`
- sanitized failure reason: `Remote end closed connection without response`

Retry result:

- batch status: `completed`
- corpus items: 20
- applied: 20
- failed/skipped/interrupted: 0
- retried item attempts: 2 for `docs/papers/2508.15144.pdf`

This was treated as a transient real LLM provider/network failure. The same batch recovered through `corpus retry`; no V4.4 timeline logic change was required.

## Catalog Metrics

- sources: 20
- PDF sources: 20
- formal claims: 2775
- durable `metric_results` rows: 237
- durable rows joined to `claims` and `sources`: 237

## Metric List

`llmwiki metric list --json` returned:

- metric count: 83

Top metric groups:

| metric | rows | sources | papers | year range |
| --- | ---: | ---: | ---: | --- |
| success rate | 69 | 15 | 15 | 2021-2026 |
| accuracy | 33 | 6 | 6 | 2021-2025 |
| score | 14 | 4 | 4 | 2021-2025 |
| performance | 7 | 4 | 4 | 2025-2026 |
| average steps | 6 | 2 | 2 | 2025-2026 |

Selected metric query for timeline acceptance: `success rate`.

## Timeline Result

`llmwiki metric timeline "success rate" --json` returned:

- timeline rows: 69
- warning count: 1
- source diversity: 15
- paper diversity: 15
- rows with `result_id`, `claim_id`, `source_id`, and `citation_locator`: 69
- rows with missing year: 0
- rows with missing normalized value: 12
- duplicate-looking warning count: 0

The human output rendered a compact table with columns:

```text
Year | Paper | Method | Dataset | Task | Metric | Value | Baseline | Claim | Locator
```

The returned warning was an ambiguity warning for metric display variants that normalize to the same key.

## Empty Result Behavior

Command:

```powershell
.\.venv\Scripts\python.exe -m llmwiki metric timeline "__llmwiki_absent_metric_v44__" --root .tmp\paper-v44-acceptance --json
```

Result:

- item count: 0
- warning code: `no_catalog_backed_result`
- exit code: 0

The command returned an empty timeline with a warning and did not invent narrative.

## Conclusion

V4.4 acceptance passed the core metric timeline contract:

- full 20-paper corpus import completed after retrying one transient provider/network failure;
- durable `metric_results` rows joined to formal claims and sources;
- `metric list` exposed available metrics for query selection;
- `metric timeline` returned source-backed rows with stable IDs and locators;
- human and JSON timeline outputs were both usable;
- absent metric behavior returned `no_catalog_backed_result` without narrative invention;
- no raw prompts, raw LLM responses, parser logs, parser artifacts, generated workspace files, generated catalog, or API keys are committed.
