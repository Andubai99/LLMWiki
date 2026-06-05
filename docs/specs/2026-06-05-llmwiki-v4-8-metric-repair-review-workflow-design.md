# LLMWiki V4.8 Metric Repair Review Workflow Design

Date: 2026-06-05

## 1. Summary

V4.8 adds a CLI-first metric repair review workflow over existing V4.7 canonicalization output:

```powershell
llmwiki metric repair-plan --root . --json
llmwiki metric repair-plan --root . --stage
llmwiki metric repair-status <repair-run-id> --root .
llmwiki metric repair-mark <repair-run-id> <proposal-id> --root . --status accepted --reason "reviewed"
```

The goal is to convert V4.7 diagnostics into reviewable repair proposals without rerunning MinerU+LLM and without mutating durable `metric_results` rows.

V4.8 is a review workflow, not a durable repair/apply workflow. It may write staging-only repair review artifacts when explicitly requested with `--stage` or `repair-mark`, but it must not write `state/catalog.sqlite`, wiki pages, source artifacts, corpus batch state, or embedding/UI job state.

## 2. Motivation

V4.7 acceptance reused `.tmp/paper-v46-corpus-acceptance` and found:

- 414 durable `metric_results`;
- 414 / 414 joined result rows;
- 414 / 414 resolvable locators;
- 414 / 414 context-available rows;
- parser backend distribution `{"mineru": 414}`;
- parser fallback count `0`;
- result error count `0`;
- canonical metric count `68`;
- comparability group count `193`;
- value repair suggestions `6`;
- `strict_ready = 0`;
- `discoverable_not_comparable = 2`;
- `needs_year_repair = 5`;
- `not_ready_single_paper = 188`.

This means the current bottleneck is not parser or locator quality. The bottleneck is reviewable interpretation:

- which metric aliases are safe to group;
- which dataset/task variants are lexical variants versus genuinely different evaluation settings;
- which missing years can be filled from paper identity metadata;
- which missing metric values can be accepted from deterministic V4.7 value repair suggestions;
- which vague labels such as `score`, `Avg`, `Overall`, or `performance` must stay blocked.

V4.8 should make those decisions inspectable and auditable before any future catalog mutation is designed.

## 3. Scope

V4.8 implements:

- repair proposal generation from existing V4.7 canonicalization and V4.5 result-evidence helpers;
- optional staging of repair proposals under `staging/<repair-run-id>/`;
- review status tracking for proposals;
- projected timeline readiness after accepted proposals;
- compact human output and stable JSON output.

V4.8 does not implement:

- UI;
- catalog migration;
- durable updates to `metric_results`;
- automatic repair apply;
- automatic metric alias merge;
- LLM-based repair;
- MinerU, parser, or ingest reruns;
- new extraction prompts;
- wiki writeback;
- trend synthesis;
- conflict detection;
- metric ranking or benchmark leaderboard output.

## 4. Command Contract

### 4.1 Report-Only Plan

Default `repair-plan` is read-only and writes nothing:

```powershell
llmwiki metric repair-plan --root .
llmwiki metric repair-plan --root . --json
```

Optional filters:

```powershell
--metric <text>
--dataset <text>
--task <text>
--proposal-type <type>
--limit <n>
--offset <n>
```

Default `limit=200`, maximum `limit=1000`, and `offset>=0`.

Exit behavior:

- exit `0` when proposal generation succeeds, even if proposals are blocked or require review;
- exit `1` for invalid arguments, missing catalog, incompatible schema, or unreadable bounded context required for diagnostics;
- empty corpus exits `0` with `no_catalog_backed_result` and `no_repair_proposals` warnings.

### 4.2 Staged Plan

When explicitly requested, `repair-plan --stage` writes review artifacts:

```powershell
llmwiki metric repair-plan --root . --stage
```

It writes only:

```text
staging/<repair-run-id>/run.json
staging/<repair-run-id>/metric-repair-plan.json
staging/<repair-run-id>/metric-repair-proposals.jsonl
staging/<repair-run-id>/metric-repair-decisions.jsonl
staging/<repair-run-id>/triage.md
```

The initial `metric-repair-decisions.jsonl` may be empty. Staging a plan must not mutate `state/catalog.sqlite`.

### 4.3 Review Status

Review status is read-only:

```powershell
llmwiki metric repair-status <repair-run-id> --root .
llmwiki metric repair-status <repair-run-id> --root . --json
```

It reads staged plan artifacts and summarizes:

- proposal counts by type;
- proposal counts by review status;
- potential readiness impact;
- warnings and blockers.

### 4.4 Mark Proposal

Marking a proposal writes only a decision row under the repair staging directory:

```powershell
llmwiki metric repair-mark <repair-run-id> <proposal-id> --root . --status accepted --reason "paper year matches source identity"
llmwiki metric repair-mark <repair-run-id> <proposal-id> --root . --status rejected --reason "dataset setting differs"
llmwiki metric repair-mark <repair-run-id> <proposal-id> --root . --status needs_review --reason "ambiguous metric label"
```

Allowed statuses:

- `accepted`;
- `rejected`;
- `needs_review`;
- `blocked`.

`repair-mark` must preserve append-only decision history. If a proposal is marked more than once, the latest decision controls the current status, but previous decisions remain inspectable.

### 4.5 Durable Apply

Durable apply is out of scope for V4.8.

V4.8 must not provide a command that updates `metric_results`. A future phase may add `llmwiki metric repair apply <repair-run-id>` only after a separate spec defines:

- allowed mutable fields;
- backup strategy;
- catalog transaction boundaries;
- how accepted aliases are represented;
- how `llmwiki metric timeline` consumes repairs;
- rollback behavior;
- tests proving no evidence fields are rewritten.

## 5. Schema Versions

Top-level report:

```text
metric_repair_plan.v4.8
```

Nested schemas:

```text
metric_repair_proposal.v4.8
metric_repair_review_decision.v4.8
metric_repair_projection.v4.8
metric_repair_warning.v4.8
```

Staged run manifest:

```text
metric_repair_run.v4.8
```

V4.8 must preserve original audit values:

- `result_id`;
- `claim_id`;
- `source_id`;
- `paper_id`;
- `citation_locator`;
- `metric_name`;
- `dataset`;
- `task`;
- `metric_value`;
- `metric_raw_value`;
- `metric_unit`;
- `metric_direction`;
- `reported_year`;
- `confidence_status`;
- parser backend fields.

Repair suggestions are additional proposed metadata, not replacements for stored values.

## 6. JSON Shape

Top-level repair plan:

```json
{
  "schema_version": "metric_repair_plan.v4.8",
  "root": "F:/LLMWiki/.tmp/paper-v46-corpus-acceptance",
  "generated_at": "2026-06-05T00:00:00+00:00",
  "query": {
    "metric": "",
    "dataset": "",
    "task": "",
    "proposal_type": "",
    "limit": 200,
    "offset": 0
  },
  "summary": {},
  "proposals": [],
  "projections": [],
  "warnings": []
}
```

The JSON must not include raw prompts, raw LLM responses, parser logs, parser artifact contents, API key paths, or API key values. It may include short bounded context snippets only for repair review.

## 7. Proposal Types

### 7.1 `reported_year_from_paper_identity`

Generate this proposal when:

- a result row has missing `reported_year`;
- V4.2 inventory has a non-null paper year for the same `paper_id` or `source_id`;
- no existing result row for the same paper has a conflicting explicit year;
- evidence/context does not contain a conflicting year close to the result.

Risk level:

- `low` when paper identity year is available from DOI/arXiv/title metadata and no conflict is detected;
- `medium` when the year is inferred from source title or filename;
- `high` when multiple year candidates exist.

V4.8 should propose year repair for the V4.7 `needs_year_repair` groups when safe.

### 7.2 `metric_value_from_v47_suggestion`

Generate this proposal from V4.7 value repair suggestions when:

- `metric_value` is empty;
- V4.7 repair status is `suggested`;
- repair confidence is `high` or `medium`;
- the suggestion has one numeric value and compatible unit/value scale.

Risk level:

- `low` for high-confidence `metric_raw_value` suggestions;
- `medium` for claim/context suggestions;
- `high` for low-confidence or multi-number suggestions, which should normally stay blocked.

### 7.3 `metric_alias_review`

Generate this proposal when canonicalization finds likely metric variants that are not automatically safe to merge.

Examples:

- `success rate`, `Successful Rate`, `SR`, `Avg. SR`;
- `accuracy`, `Average Accuracy`, `Overall accuracy`;
- `score`, `Avg`, `Overall`, `performance`.

Risk level:

- `medium` for lexical abbreviation candidates in the same dataset/task/unit/direction group;
- `high` for vague labels or variants that depend on table columns, benchmark sections, or paper-specific definitions.

V4.8 must not auto-accept these proposals.

### 7.4 `dataset_alias_review`

Generate this proposal when dataset labels differ by punctuation, case, spacing, or suffixes that may reflect split settings.

Examples:

- `OSWorld` vs `OSWorld full test` vs `OSWorld test_sub`;
- `ScreenSpot-Pro` vs `ScreenSpot Pro`;
- `WindowsAgentArena` vs `Windows Agent Arena`.

Risk level:

- `low` for punctuation/case/whitespace only;
- `medium` for spelling variants;
- `high` for labels that may refer to subset, split, or benchmark variant.

Labels that mention `test`, `train`, `dev`, `subset`, `full`, `mini`, `pro`, or version suffixes should not be auto-accepted.

### 7.5 `task_alias_review`

Generate this proposal when task labels are close lexical variants:

- `computer use` vs `computer-use`;
- `GUI grounding` vs `GUI Grounding`;
- `GUI automation` vs `computer use`.

Risk level:

- `low` for punctuation/case only;
- `medium` for simple word order or spelling variants;
- `high` for semantically different task names.

V4.8 must not merge task aliases automatically when the label changes task scope.

### 7.6 `blocked_vague_label`

Generate this proposal-like diagnostic when a metric label is too vague to repair safely:

- `score`;
- `Avg`;
- `Overall`;
- `performance`;
- `result`;
- `metric`;
- `value`.

These should default to review status `blocked` unless the user explicitly marks them for future curation.

## 8. Proposal Object

Each `proposals[]` item:

```json
{
  "schema_version": "metric_repair_proposal.v4.8",
  "proposal_id": "mrp_<stable_hash>",
  "proposal_type": "reported_year_from_paper_identity",
  "review_status": "proposed",
  "risk_level": "low",
  "title": "Fill missing reported_year from paper identity",
  "rationale": "Result row has no reported_year and source inventory year is 2024.",
  "deterministic_rule": "paper_identity_year_no_conflict",
  "target": {
    "result_id": "res_xxx",
    "claim_id": "clm_xxx",
    "source_id": "src_xxx",
    "paper_id": "src_xxx",
    "citation_locator": "page:3;block:src_xxx_p003_b0004"
  },
  "current": {
    "reported_year": null
  },
  "suggested": {
    "reported_year": 2024
  },
  "evidence_refs": [
    {
      "result_id": "res_xxx",
      "claim_id": "clm_xxx",
      "source_id": "src_xxx",
      "citation_locator": "page:3;block:src_xxx_p003_b0004",
      "context_preview": "bounded short snippet"
    }
  ],
  "readiness_impact": {
    "before_status": "needs_year_repair",
    "after_status_if_accepted": "strict_ready",
    "comparability_group_key": "success_rate|osworld|computer_use|%|higher_is_better|percent"
  },
  "warnings": []
}
```

`proposal_id` must be deterministic from:

- proposal type;
- target row IDs or group key;
- current values;
- suggested values.

The LLM must not choose proposal IDs.

## 9. Review Decisions

Each `metric-repair-decisions.jsonl` row:

```json
{
  "schema_version": "metric_repair_review_decision.v4.8",
  "decision_id": "mrd_<stable_hash>",
  "proposal_id": "mrp_<stable_hash>",
  "status": "accepted",
  "reason": "paper year matches inventory and no conflict found",
  "decided_at": "2026-06-05T00:00:00+00:00"
}
```

Decision rows are append-only. They are staging review metadata, not evidence.

## 10. Projection

V4.8 should show projected readiness if accepted proposals were applied later.

Each `projections[]` item:

```json
{
  "schema_version": "metric_repair_projection.v4.8",
  "comparability_group_key": "success_rate|osworld|computer_use|%|higher_is_better|percent",
  "canonical_metric_key": "success_rate",
  "current_readiness_status": "needs_year_repair",
  "projected_readiness_status": "strict_ready",
  "required_proposal_ids": ["mrp_a", "mrp_b"],
  "blocked_proposal_ids": [],
  "remaining_blockers": []
}
```

Projection is advisory only. It must not change `llmwiki metric timeline` output.

## 11. Summary Metrics

`summary` should include:

```text
metric_result_count
canonical_metric_count
comparability_group_count
proposal_count
proposal_count_unpaged
proposal_counts_by_type
proposal_counts_by_status
proposal_counts_by_risk
year_repair_proposal_count
value_repair_proposal_count
metric_alias_review_count
dataset_alias_review_count
task_alias_review_count
blocked_vague_label_count
projected_strict_ready_count
projected_ready_after_value_repair_count
projected_discoverable_not_comparable_count
accepted_proposal_count
rejected_proposal_count
needs_review_proposal_count
warning_count
```

## 12. Read-Only And Write Boundary

Report-only `repair-plan` and `repair-status` may read:

- `state/catalog.sqlite`;
- V4.2 inventory metadata;
- V4.5 result-evidence helper output;
- V4.7 canonicalization helper output;
- bounded source context already used by V4.5/V4.7 helpers;
- staged V4.8 repair artifacts for status commands.

Report-only commands must not write any workspace files.

`repair-plan --stage` and `repair-mark` may write only `staging/<repair-run-id>/` repair review files.

All V4.8 commands must not:

- call LLM providers;
- call embedding providers;
- run MinerU;
- run PDF parser backends;
- call add/import/ingest/apply;
- call ask/synthesis;
- call lint/clean;
- call CLI eval recursion;
- write `wiki/`;
- write `sources/`;
- write `state/catalog.sqlite`;
- write `state/corpus-batches/`;
- write `state/embeddings/`;
- write `state/ui-jobs/`;
- write `.tmp/`;
- expose API keys, raw prompts, raw responses, parser logs, or parser artifact contents.

## 13. Human Output

Human output should be compact:

```text
Metric repair plan
Proposals: 42
Year repairs: 5
Value repairs: 6
Metric alias reviews: 12
Dataset alias reviews: 8
Task alias reviews: 4
Blocked vague labels: 7

Projected readiness:
...

Top proposals:
...
```

Human output must not print all result rows by default. JSON may include paginated proposals.

## 14. Acceptance Reuse

V4.8 must reuse existing acceptance workspaces by default. It must not rerun MinerU+LLM.

Acceptance levels:

- L0: unit tests for proposal ID determinism, proposal type generation, decision append behavior, and projection logic.
- L1: synthetic catalog tests for JSON schema, CLI filters, staging artifacts, review decisions, and read-only boundaries.
- L2: run report-only and staged proposal generation against `.tmp\paper-v46-corpus-acceptance`.
- L3: not needed unless V4.8 scope changes.
- L4: not needed unless V4.8 scope changes.
- L5: full 20-paper MinerU+LLM rerun is not required for V4.8 and should not be performed by default.

Manual acceptance commands:

```powershell
.\.venv\Scripts\python.exe -m llmwiki metric repair-plan --root .tmp\paper-v46-corpus-acceptance --json
.\.venv\Scripts\python.exe -m llmwiki metric repair-plan --root .tmp\paper-v46-corpus-acceptance
.\.venv\Scripts\python.exe -m llmwiki metric repair-plan --root .tmp\paper-v46-corpus-acceptance --stage
.\.venv\Scripts\python.exe -m llmwiki metric repair-status <repair-run-id> --root .tmp\paper-v46-corpus-acceptance --json
```

Observation file:

```text
docs/specs/2026-06-05-llmwiki-v4-8-metric-repair-review-workflow-observations.md
```

Record only sanitized observations:

- proposal counts by type/status/risk;
- projected readiness changes;
- how many V4.7 `needs_year_repair` groups get proposals;
- how many V4.7 value repairs become review proposals;
- top alias review groups;
- blocked vague labels;
- read-only/staging boundary verification.

Do not commit `.tmp` workspace contents, API keys, source sidecars, staging files from acceptance workspaces, wiki output, catalog databases, parser logs, raw prompts, raw responses, or parser artifacts.

## 15. Testing Requirements

Automated tests should cover:

- stable schema constants;
- deterministic `proposal_id`;
- year repair proposal generation from paper identity;
- no year repair when year evidence conflicts;
- value repair proposal generation from V4.7 suggestions;
- no value repair for placeholder or ambiguous numeric values;
- metric alias review proposal generation;
- dataset/task alias review proposal generation;
- blocked vague labels;
- projection status before/after accepted proposals;
- `repair-plan` JSON and human output;
- `repair-plan --stage` writes only staging repair artifacts;
- `repair-status` reads staged artifacts without writing;
- `repair-mark` appends decisions and preserves history;
- invalid limit/offset and missing catalog behavior;
- monkeypatch read-only boundary for report-only commands;
- file snapshot proving no writes outside `staging/<repair-run-id>/` for staging commands.

## 16. Relationship To Future Durable Repair

V4.8 deliberately stops before catalog mutation.

A future durable repair phase can use accepted V4.8 proposals as input, but it must define a separate apply contract. That future phase should decide whether repairs are represented by:

- updating selected existing `metric_results` fields;
- adding a repair overlay table;
- adding curated metric/dataset/task alias files;
- changing `llmwiki metric timeline` to consume accepted overlays;
- or keeping repairs as review-only diagnostics.

Until that future phase exists, V4.8 proposals and decisions are review metadata only.

## 17. Open Questions

1. Should accepted repair decisions live under `staging/` permanently, or should a future generated `state/metric-repairs/` cache summarize them?
   - Default for V4.8: keep review decisions in staging only.
2. Should `repair-plan --stage` require a user-provided label?
   - Default for V4.8: optional `--label`; autogenerated run IDs are sufficient.
3. Should V4.8 allow accepting high-confidence value repairs automatically?
   - Default for V4.8: no. All proposal acceptance is explicit.
4. Should V4.8 include a curated alias file?
   - Default for V4.8: no. Alias files imply durable policy and should wait for a later spec.
5. Should future durable repair update `metric_results` directly?
   - Default for V4.8: undecided; do not mutate catalog in this phase.
