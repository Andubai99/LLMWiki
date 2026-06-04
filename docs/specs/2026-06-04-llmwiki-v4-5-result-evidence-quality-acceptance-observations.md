# LLMWiki V4.5-min Result Evidence Quality Acceptance Observations

Date: 2026-06-04

Workspace preserved for follow-up inspection:

```text
.tmp/paper-v45-acceptance
```

## Scope

Acceptance used the fixed 5-paper subset required by the V4.5-min spec:

- `docs/papers/2404.07972.pdf`
- `docs/papers/2409.08264.pdf`
- `docs/papers/2501.16150.pdf`
- `docs/papers/2506.16042.pdf`
- `docs/papers/2509.15221.pdf`

The 5 PDFs were copied into `.tmp/paper-v45-acceptance/input-papers/`. The local ignored `config/api-keys.toml` was copied into the temporary workspace config directory for real LLM ingest. API keys, raw prompts, raw LLM responses, parser logs, parser artifacts, generated catalog/source/wiki/staging files, and raw eval JSON were not committed.

## Commands

First attempted command used a repo-relative input path and failed before import started:

```powershell
.\.venv\Scripts\python.exe -m llmwiki corpus import .tmp\paper-v45-acceptance\input-papers --root .tmp\paper-v45-acceptance --parser auto
```

Corrected command:

```powershell
.\.venv\Scripts\python.exe -m llmwiki corpus import input-papers --root .tmp\paper-v45-acceptance --parser auto
```

Eval commands:

```powershell
.\.venv\Scripts\python.exe -m llmwiki eval result-evidence --root .tmp\paper-v45-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki eval result-evidence --root .tmp\paper-v45-acceptance
```

## Import Result

- Batch id: `batch_20260604T085346Z0000_8dfe53b2`
- Imported paper count: 5
- Applied: 5
- Already imported: 0
- Failed: 0
- Skipped: 0
- Interrupted: 0

Applied source titles recorded by the catalog:

- `src_d4c6e20dd594`: `Autonomous agents that accomplish complex computer tasks with minimal human`
- `src_fbd0821e7262`: `WINDOWS AGENTARENA : EVALUATING MULTI-MODAL OS A GENTS AT SCALE`
- `src_9a21aa2f6def`: `AI agents operate by perceiving their environment and selecting actions to achieve predefined goals (Mnih et al.`
- `src_ee48a997c1d5`: `OSWorld-Human: Benchmarking the Efficiency of Computer-Use Agents`
- `src_6ec95bbb5a13`: `ScaleCUA: Scaling Open-Source Computer Use Agents with Cross-Platform Data`

## V4.5 Eval Metrics

- Formal claim count: 864
- Durable `metric_results` row count: 73
- Eval item count: 73
- Rows preserving `result_id/claim_id/source_id/citation_locator`: 73
- Joined result count: 73
- Resolvable locator count: 73
- Context available count: 73
- PDF result count: 73
- Markdown/text result count: 0
- Table/caption context count: 0
- Parser diagnostic source count: 5
- Parser fallback rows: 73
- Error count: 0
- Warning count: 174
- Info count: 51

Field completeness diagnostics:

- Missing normalized metric value: 28
- Missing method: 26
- Missing dataset: 29
- Missing task: 18
- Missing baseline: 51

Top diagnostic codes:

- `parser_fallback_observed`: 73
- `missing_baseline`: 51
- `missing_dataset`: 29
- `missing_metric_value`: 28
- `missing_method`: 26
- `missing_task`: 18

## Notes

V4.5-min met its evidence-closure goal on this subset: every durable result row joined back to formal claims/sources, every locator resolved, and every row had available bounded context.

The main observed quality gap is not locator closure; it is extraction completeness. Many rows lack normalized values or method/dataset/task/baseline fields. All result rows carried `parser_fallback_observed`, and there were no table/caption-context rows in this run, which suggests the 5-paper acceptance was handled through fallback parser text blocks rather than table/caption-rich MinerU blocks.

Per user instruction, `.tmp/paper-v45-acceptance` was preserved after acceptance for follow-up inspection.
