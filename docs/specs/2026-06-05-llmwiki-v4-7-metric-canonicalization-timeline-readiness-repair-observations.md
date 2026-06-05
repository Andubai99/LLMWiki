# LLMWiki V4.7 Metric Canonicalization And Timeline Readiness Repair Observations

Date: 2026-06-05

Scope: V4.7 read-only acceptance reused the preserved V4.6 strict MinerU workspace `.tmp/paper-v46-corpus-acceptance`. No MinerU, parser, LLM, import, ingest, apply, clean, or catalog write was run for this observation.

## Commands

```powershell
.\.venv\Scripts\python.exe -m llmwiki metric canonicalize --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric canonicalize --root .tmp\paper-v46-corpus-acceptance
```

## Summary

JSON schema: `metric_canonicalization_report.v4.7`

| Metric | Value |
| --- | ---: |
| durable result rows read | 414 |
| joined result rows | 414 |
| resolvable locators | 414 |
| context available rows | 414 |
| source count | 18 |
| paper count | 18 |
| canonical metric count | 68 |
| comparability group count | 193 |
| timeline readiness rows | 195 |
| value repair suggestions | 6 |
| parser backend result counts | `{"mineru": 414}` |
| parser fallback result count | 0 |
| result error count | 0 |
| warning count | 400 |

## Timeline Readiness

| Status | Count |
| --- | ---: |
| `strict_ready` | 0 |
| `ready_after_value_repair` | 0 |
| `discoverable_not_comparable` | 2 |
| `needs_canonical_review` | 0 |
| `needs_value_repair` | 0 |
| `needs_year_repair` | 5 |
| `not_ready_single_paper` | 188 |
| `not_ready_empty` | 0 |

The two corpus-level discoverable metrics are `success_rate` and `accuracy`. Both have enough cross-paper rows, but the rows split across dataset, task, unit, direction, or value-scale groups, so V4.7 correctly does not mark them directly comparable.

Five groups have enough cross-paper rows but need year repair before they can become timeline candidates:

- `accuracy` on `ScreenSpot-Pro` / `GUI grounding`
- `success rate` on `OSWorld` / `computer use`
- `success rate` on `WindowsAgentArena` / `computer use`
- `success rate` on `OSWorld` / `GUI automation`

## Top Canonical Metrics

| Canonical metric | Display name | Rows | Papers | Missing values |
| --- | --- | ---: | ---: | ---: |
| `success_rate` | success rate | 101 | 13 | 25 |
| `accuracy` | accuracy | 47 | 7 | 10 |
| `average_accuracy` | Average Accuracy | 38 | 3 | 0 |
| `score` | score | 32 | 3 | 3 |
| `successful_rate` | Successful Rate | 16 | 1 | 0 |
| `avg` | Avg | 15 | 5 | 0 |
| `overall_average` | Overall Average | 12 | 2 | 0 |
| `performance` | performance | 11 | 5 | 6 |
| `grounding_accuracy` | grounding accuracy | 8 | 1 | 6 |
| `overall` | Overall | 8 | 2 | 0 |

Vague labels such as `score`, `avg`, `overall`, and `performance` are intentionally not merged into richer metric aliases. They remain review targets rather than automatic canonical merges.

## Value Repair Suggestions

| Result id | Metric | Suggested value | Unit | Source | Confidence |
| --- | --- | ---: | --- | --- | --- |
| `res_clm_src_6ec95bbb5a13_llm_064_001` | Number of understanding samples | 9 |  | claim_text | medium |
| `res_clm_src_983159c8e074_llm_079_001` | success rate improvement | 34 | % | claim_text | medium |
| `res_clm_src_983159c8e074_llm_080_001` | success rate | 50 | % | metric_raw_value | high |
| `res_clm_src_983159c8e074_llm_080_002` | success rate | 50 | % | metric_raw_value | high |
| `res_clm_src_983159c8e074_llm_091_001` | success rate | 50 | % | metric_raw_value | high |
| `res_clm_src_983159c8e074_llm_106_001` | SR, SR@100 | 90 | % | context_preview | medium |

These are suggestions only. V4.7 did not write repaired values into `metric_results`, did not create new claims, and did not alter the timeline command behavior.

## Warning Profile

Top warning codes:

| Code | Count |
| --- | ---: |
| `missing_baseline` | 320 |
| `missing_metric_value` | 63 |
| `metric_variant_grouped` | 8 |
| `ambiguous_label` | 7 |
| `discoverable_not_comparable` | 2 |

## Interpretation

V4.7 makes the current bottleneck clearer: the full-corpus MinerU extraction is evidence-resolvable and parser fallback-free, but timeline readiness is blocked by comparability, year completeness, and metric naming granularity rather than by locator quality.

The next repair stage should not rerun MinerU+LLM by default. It should first decide whether year repair and metric alias curation can be represented as another read-only report or whether a durable, reviewable repair/apply workflow is needed.
