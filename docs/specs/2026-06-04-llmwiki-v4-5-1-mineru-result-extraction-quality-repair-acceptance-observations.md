# LLMWiki V4.5.1 MinerU Result Extraction Quality Repair Acceptance Observations

Date: 2026-06-04

## Workspace

- Final workspace kept for inspection: `.tmp/paper-v451-mineru-repair-acceptance`
- Intermediate comparison workspaces kept:
  - `.tmp/paper-v45-acceptance`
  - `.tmp/paper-v45-mineru-acceptance`
  - `.tmp/paper-v451-mineru-repair-acceptance-initial`
  - `.tmp/paper-v451-mineru-repair-acceptance-field-filter-before-caption`
- API key file was copied only into ignored `.tmp` workspace config and is not included here.
- Raw prompts, raw LLM responses, parser logs, parser artifacts, generated sources, staging, wiki, and catalog files are not included in this observation.

## Commands

```powershell
.\.venv\Scripts\python.exe -m llmwiki init --root .tmp\paper-v451-mineru-repair-acceptance
.\.venv\Scripts\python.exe -m llmwiki parsers status --root .tmp\paper-v451-mineru-repair-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki corpus import docs\papers --root .tmp\paper-v451-mineru-repair-acceptance --recursive --parser mineru --json
.\.venv\Scripts\python.exe -m llmwiki eval result-evidence --root .tmp\paper-v451-mineru-repair-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric list --root .tmp\paper-v451-mineru-repair-acceptance --json
```

Strict MinerU config used in the final workspace:

```toml
[pdf_parser]
mineru_enabled = true
mineru_command = "F:/LLMWiki/.venv/Scripts/mineru.exe"
mineru_backend = "pipeline"
mineru_method = "auto"
mineru_extra_args = ["-l", "en"]
```

`parsers status` confirmed `mineru_command_source=configured_path`, `mineru_backend=pipeline`, `mineru_method=auto`, `mineru_extra_args=["-l", "en"]`, and `mineru_available=true`.

## Final Result

- Imported paper count: 5
- Corpus batch status: `completed`
- Applied item count: 5
- Failed item count: 0
- Formal claim count: 1777
- Durable `metric_results` row count: 91
- Metric list count: 34
- Parser backend result counts: `{"mineru": 91}`
- Parser fallback result count: 0
- Parser diagnostic source count: 0
- Joined result count: 91
- Resolvable locator count: 91
- Context available count: 91
- Error count: 0

Per-source durable result rows:

| Paper | Rows |
| --- | ---: |
| SCALECUA: SCALING OPEN-SOURCE COMPUTER USE AGENTS WITH CROSS-PLATFORM DATA | 42 |
| OSWORLD: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments | 18 |
| WINDOWSAGENTARENA: EVALUATING MULTI-MODAL OS AGENTS AT SCALE | 16 |
| OSWORLD-HUMAN: BENCHMARKING THE EFFICIENCY OF COMPUTER-USE AGENTS | 12 |
| A Comprehensive Survey of Agents for Computer Use: Foundations, Challenges, and Future Directions | 3 |

## Quality Comparison

| Metric | pypdf/fallback V4.5-min | strict MinerU baseline | V4.5.1 initial | V4.5.1 final |
| --- | ---: | ---: | ---: | ---: |
| metric_results | 73 | 53 | 92 | 91 |
| parser fallback rows | 73 | 0 | 0 | 0 |
| table result count | 0 | 12 | 42 | 51 |
| caption result count | 0 | 0 | 3 | 1 |
| result-text context count | 69 | 41 | 82 | 86 |
| missing value count | 28 | 21 | 42 | 19 |
| missing method count | 26 | 15 | 29 | 0 |
| missing dataset count | 29 | 9 | 28 | 0 |
| missing task count | 18 | 8 | 26 | 0 |
| warning count | 174 | 53 | 125 | 19 |
| error count | 0 | 0 | 0 | 0 |

Unique referenced evidence blocks in final V4.5.1:

- Unique table blocks referenced: 22
- Unique caption blocks referenced: 1
- Evidence role mentions: `paragraph=156`, `section_heading=48`, `table=77`, `caption=1`

Top metric groups from `llmwiki metric list`:

| Metric | Rows | Sources | Papers |
| --- | ---: | ---: | ---: |
| accuracy | 22 | 2 | 2 |
| success rate | 12 | 3 | 3 |
| Median completion time | 9 | 2 | 2 |
| Average score | 8 | 1 | 1 |
| performance | 4 | 2 | 2 |

## Acceptance Assessment

Passed:

- Strict MinerU imported 5/5 papers with no fallback.
- Durable `metric_results` exceeded both the V4.5.1 target of 70 and the pypdf/fallback baseline of 73.
- Table-backed result coverage improved from 12 to 51 rows.
- Caption-backed result coverage became non-zero.
- All durable rows joined to formal claims and sources.
- All durable rows had resolvable locators and available context.
- Missing method/dataset/task counts are 0.
- Missing normalized value count improved below the strict MinerU baseline.
- `error_count` is 0.

Remaining issues:

- Caption support is still thin: only one unique caption block is referenced. Many MinerU table blocks already contain their table caption text inline, but separate caption-block pairing remains a future quality target.
- `missing_baseline_count` remains high at 67. This is expected for rows without explicit baseline/comparison in the bounded evidence, but V4.6 should report it separately from hard extraction quality gates.
- The survey paper contributes only 3 durable result rows after tightening core-field requirements. This is acceptable for V4.5.1 because broad survey/taxonomy counts are no longer promoted to durable `metric_results`, but V4.6 may need a separate survey-statistics extraction category if those become useful.
