# LLMWiki V4.8 Metric Repair Review Workflow Observations

Date: 2026-06-05

Scope: V4.8 acceptance reused the preserved V4.6 strict MinerU workspace `.tmp/paper-v46-corpus-acceptance`. No MinerU, parser, LLM, import, ingest, apply, clean, catalog mutation, or wiki writeback was run. The only intentional acceptance write was a V4.8 repair review staging run under the preserved `.tmp` workspace.

## Commands

```powershell
.\.venv\Scripts\python.exe -m llmwiki metric repair-plan --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric repair-plan --root .tmp\paper-v46-corpus-acceptance
.\.venv\Scripts\python.exe -m llmwiki metric repair-plan --root .tmp\paper-v46-corpus-acceptance --stage --json
.\.venv\Scripts\python.exe -m llmwiki metric repair-status run_metric_repair_20260605130651_8d69489b --root .tmp\paper-v46-corpus-acceptance --json
```

Staged run retained for inspection:

```text
.tmp/paper-v46-corpus-acceptance/staging/run_metric_repair_20260605130651_8d69489b/
```

## Summary

JSON schema: `metric_repair_plan.v4.8`

| Metric | Value |
| --- | ---: |
| durable result rows read | 414 |
| canonical metric count | 68 |
| comparability group count | 193 |
| proposal count | 644 |
| projected strict-ready groups | 5 |
| projected ready-after-value-repair groups | 0 |
| decision count | 0 |
| warning count | 400 |

Proposal counts by type:

| Proposal type | Count |
| --- | ---: |
| `reported_year_from_paper_identity` | 384 |
| `metric_value_from_v47_suggestion` | 6 |
| `metric_alias_review` | 197 |
| `dataset_alias_review` | 33 |
| `task_alias_review` | 19 |
| `blocked_vague_label` | 5 |

Proposal counts by status:

| Status | Count |
| --- | ---: |
| `proposed` | 639 |
| `blocked` | 5 |

Proposal counts by risk:

| Risk | Count |
| --- | ---: |
| `low` | 394 |
| `medium` | 159 |
| `high` | 91 |

## Staging Verification

`repair-plan --stage` created a staging-only review run with:

- `run.json`
- `metric-repair-plan.json`
- `metric-repair-proposals.jsonl`
- `metric-repair-decisions.jsonl`
- `triage.md`

`repair-status` read the staged plan and reported the same 644 unpaged proposals. No decision rows were appended during acceptance, so accepted/rejected counts remain zero.

## Notable Proposal Examples

Value repair proposals came directly from V4.7 suggestions:

| Result id | Suggested value | Unit | Risk |
| --- | ---: | --- | --- |
| `res_clm_src_983159c8e074_llm_080_001` | 50 | % | low |
| `res_clm_src_983159c8e074_llm_080_002` | 50 | % | low |
| `res_clm_src_983159c8e074_llm_091_001` | 50 | % | low |
| `res_clm_src_6ec95bbb5a13_llm_064_001` | 9 |  | medium |
| `res_clm_src_983159c8e074_llm_106_001` | 90 | % | medium |
| `res_clm_src_983159c8e074_llm_079_001` | 34 | % | medium |

Blocked vague labels:

- `overall_score`
- `score`
- `overall`
- `avg`
- `performance`

Example metric alias reviews include:

- `success_rate` vs `task_success_rate`
- `accuracy` vs `grounding_accuracy`
- `average_accuracy` vs `average_grounding_accuracy`
- `avg_sr` vs `avg_sr_average_success_rate`

These are intentionally review proposals, not accepted aliases.

## Interpretation

V4.8 successfully turns V4.7 diagnostics into inspectable repair proposals and preserves a staging-only review workflow.

The large number of year repair proposals means many result rows lack `reported_year` even when paper identity can supply a year. However, only 5 projected groups become strict-ready because most year proposals affect single-paper groups or groups that still have comparability blockers. This is useful: V4.8 separates "repairable field" from "timeline readiness impact."

The next stage should not automatically apply these repairs. Before durable mutation, the project needs a separate apply/overlay spec that decides how accepted proposals are represented and how `llmwiki metric timeline` consumes them.
