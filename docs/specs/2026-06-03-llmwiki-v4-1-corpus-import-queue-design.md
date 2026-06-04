# LLMWiki V4.1 Corpus Import Queue Design

## 1. Summary

V4.1 adds the first dedicated corpus workflow for LLMWiki. It should let a user import a folder or selected list of same-domain papers through a single CLI-first batch operation while preserving the existing source-backed pipeline:

```text
corpus input
-> batch inventory
-> per-source queue item
-> existing add_and_process_source(...)
-> staging validation
-> apply
-> batch status and recovery
```

V4.1 is not a UI feature and is not a new ingest pipeline. It is an orchestration layer around the existing `add` pipeline, with durable generated batch state, per-paper status, retry/skip behavior, and clean failure reporting.

The purpose is to make V4's research corpus workflow possible without weakening LLMWiki's core guarantees: raw sources are immutable, formal knowledge goes through staging/apply, generated state is ignored/cleanable, and failed papers do not invalidate successful papers.

## 2. Parent Spec Alignment

This spec refines V4.1 from `docs/specs/2026-06-03-llmwiki-v4-research-corpus-metric-evolution-design.md`.

V4's wider goal is to compile several same-field research papers into a maintained research wiki that can later support paper identity, metric/result claims, relationships, and metric evolution queries.

V4.1 provides only the corpus import queue foundation. Later V4 specs should build on it:

- V4.2 paper identity and corpus inventory;
- V4.3 metric/result claim extraction;
- V4.4 metric timeline CLI;
- V4.5 PDF evidence quality for research results;
- V4.6 corpus acceptance evaluation.

## 3. Goals

V4.1 must provide:

- a CLI-first way to queue a folder, one file, or an explicit list of source paths;
- deterministic source discovery and ordering;
- durable generated batch state;
- per-source status, run id, parser backend summary, and sanitized failure reason;
- retry of failed or interrupted sources without reprocessing successful ones;
- skip/mark behavior for sources the user wants to exclude;
- duplicate/already-imported detection against current workspace state;
- sequential processing by default;
- clear safety boundaries around staging/apply and generated files.

## 4. Non-Goals

V4.1 does not implement:

- metric/result extraction changes;
- paper/method/dataset/metric page types;
- relationship classification;
- metric timeline queries;
- automatic synthesis maintenance;
- concurrent ingest workers;
- UI batch controls;
- cloud storage or team workflows;
- direct writes to formal wiki/catalog outside the existing add pipeline;
- raw source mutation under `docs/papers` or `sources/raw`.

## 5. User Workflows

### 5.1 Import A Corpus Folder

The user runs:

```powershell
llmwiki corpus import docs/papers --root .
```

Expected behavior:

1. Discover supported source files in `docs/papers`.
2. Create a generated batch id.
3. Persist an initial batch manifest and item list.
4. Process items sequentially by default.
5. Call the existing source import pipeline for each item.
6. Record `applied`, `failed`, `skipped`, or `already_imported` per item.
7. Continue after a failed item unless the user requested fail-fast mode.
8. Print a concise final summary with debug commands.

### 5.2 Inspect Status

The user runs:

```powershell
llmwiki corpus status --root .
llmwiki corpus status <batch-id> --root .
llmwiki corpus status <batch-id> --json --root .
```

Expected behavior:

- list recent batches when no batch id is provided;
- show per-item status for a specific batch;
- include run ids and sanitized failure reasons;
- never read API key values or raw prompts;
- never call LLM, embedding, parser execution, add, apply, lint, eval, or clean from status.

### 5.3 Retry Failures

The user runs:

```powershell
llmwiki corpus retry <batch-id> --root .
llmwiki corpus retry <batch-id> --failed-only --root .
llmwiki corpus retry <batch-id> --item <item-id> --root .
```

Expected behavior:

- retry failed/interrupted items by default;
- leave successful items unchanged;
- create new item attempts or append attempt records instead of overwriting history;
- preserve original source path and batch id;
- call the same existing add pipeline used by `corpus import`.

### 5.4 Skip Items

The user runs:

```powershell
llmwiki corpus skip <batch-id> <item-id-or-path> --root .
```

Expected behavior:

- mark a pending/failed item as `skipped`;
- record a timestamp and optional reason;
- never delete source files, staging runs, wiki pages, or catalog rows;
- refuse to skip an actively running item unless a future cancellation spec exists.

### 5.5 Dry Run

The user runs:

```powershell
llmwiki corpus import docs/papers --root . --dry-run
```

Expected behavior:

- discover and classify sources;
- report which items would be queued, skipped, or marked already imported;
- write nothing;
- call no LLM, parser, add pipeline, or apply path.

## 6. CLI Contract

The implementation plan should refine exact flags, but V4.1 should target this CLI shape:

```text
llmwiki corpus import <path-or-list> [--root .] [--dry-run] [--fail-fast] [--parser auto|pypdf|mineru] [--json]
llmwiki corpus status [batch-id] [--root .] [--json]
llmwiki corpus retry <batch-id> [--root .] [--failed-only] [--item <item-id>] [--json]
llmwiki corpus skip <batch-id> <item-id-or-path> [--root .] [--reason <text>] [--json]
```

V4.1 should not overload `llmwiki add`. `add` remains the single-source import command. `corpus import` is the batch orchestration command.

### 6.1 Output Requirements

Human-readable output should include:

- batch id;
- workspace root;
- discovered item count;
- started/completed/failed/skipped/already-imported counts;
- current item when running;
- per-item source path, status, run id when available, and sanitized error when failed;
- debug commands such as `llmwiki corpus status <batch-id> --root .`.

JSON output should be stable enough for tests and future UI work.

## 7. Batch State Model

V4.1 should store generated state under an ignored directory, recommended:

```text
state/corpus-batches/<batch-id>/
  batch.json
  items.jsonl
  attempts.jsonl
  events.jsonl
```

The implementation plan may adjust filenames, but the model should preserve these concepts.

### 7.1 Batch Manifest

`batch.json` should contain:

```text
schema_version
batch_id
created_at
updated_at
root
input_paths
status
item_count
started_count
applied_count
failed_count
skipped_count
already_imported_count
interrupted_count
active_item_id
options
```

Status values should remain machine-readable and stable:

```text
pending
running
completed
completed_with_failures
failed
interrupted
```

### 7.2 Item Rows

Each item should contain:

```text
schema_version
batch_id
item_id
source_path
source_kind
status
source_id
latest_run_id
parser_requested
parser_backend
attempt_count
created_at
updated_at
failure_reason
warnings
```

Item status values should remain machine-readable:

```text
pending
running
applied
failed
skipped
already_imported
interrupted
```

### 7.3 Attempt Rows

Each attempt should contain:

```text
schema_version
batch_id
item_id
attempt_id
started_at
ended_at
status
source_id
run_id
parser_requested
parser_backend
failure_stage
failure_reason
warnings
```

Attempts should be append-only. Retrying an item should add an attempt rather than erase the original failure.

### 7.4 Event Rows

Events are optional but recommended for debugging:

```text
timestamp
batch_id
item_id
event_type
message
```

Messages must be sanitized and should not include API keys, raw prompts, raw LLM responses, or full parser logs.

## 8. Source Discovery

Source discovery should be deterministic and conservative.

Requirements:

- accept a file, folder, or explicit list path if the implementation plan includes list files;
- recurse into folders only when explicitly chosen or when the command contract states so;
- support current source types accepted by `llmwiki add`;
- sort discovered files by stable normalized path;
- ignore directories that are generated state, git metadata, virtualenvs, and parser artifacts;
- never modify input files;
- preserve original source path in batch state.

For the first implementation, it is acceptable to support only folder and file inputs, with recursive behavior defined in the implementation plan.

## 9. Duplicate And Already-Imported Detection

V4.1 should avoid reprocessing sources that are already applied.

Detection can use existing catalog/source metadata and import identity. The exact identity rules should be specified by the implementation plan, but status should distinguish:

- `pending`: not yet processed;
- `already_imported`: workspace already has an applied source for this item;
- `applied`: this batch processed and applied the source;
- `failed`: this batch attempted and failed the source.

If duplicate detection is uncertain, V4.1 should warn rather than silently skip.

## 10. Processing Semantics

### 10.1 Sequential Default

V4.1 should process one item at a time by default. This avoids catalog/wiki races and keeps the initial implementation compatible with the existing add pipeline.

Concurrent processing is out of scope for V4.1.

### 10.2 Existing Add Pipeline

Each queued item should call the existing `add_and_process_source(...)` path or an equivalent stable Python API that preserves current behavior:

```text
copy/import source
-> normalize/parse
-> LLM ingest
-> staging run
-> safety validation
-> apply
```

The corpus layer must not write formal wiki pages, `wiki/index.md`, `wiki/log.md`, `state/catalog.sqlite`, source sidecars, or staging artifacts directly except through existing import pipeline calls.

### 10.3 Failure Handling

A failed item should not fail the whole batch unless `--fail-fast` is set.

When an item fails:

- mark item `failed`;
- record failure stage and sanitized reason;
- append an attempt row;
- continue to the next item by default;
- print enough context to retry or debug.

### 10.4 Interruption Handling

If the process is interrupted:

- mark active item and batch as `interrupted` when possible;
- keep completed items as `applied` or `already_imported`;
- preserve attempt history;
- allow `corpus retry <batch-id>` to resume failed/interrupted items.

## 11. Safety Boundaries

V4.1 must preserve these invariants:

- no bypass of staging/apply;
- raw source files remain immutable;
- `docs/papers` is never modified;
- batch state is generated and ignored;
- API keys and `config/api-keys.toml` contents are never exposed;
- raw prompts and raw LLM responses are not printed or committed;
- status/dry-run commands are read-only;
- retry and import commands only mutate through generated batch state and existing add pipeline;
- no external hosted vector database is introduced;
- no UI POST route is added by this spec.

## 12. Cleaning And Git Hygiene

V4.1 generated artifacts should be cleanable or ignored.

Recommended generated paths:

```text
state/corpus-batches/
```

The implementation plan should update `llmwiki clean --scope generated` only if needed. Cleanup must not delete:

- `docs/papers/`;
- `config/api-keys.toml`;
- `.gitkeep`;
- user-requested retained acceptance outputs.

Before committing V4.1 implementation work, `git status --short --ignored` must not show tracked or staged generated batch state.

## 13. Test Strategy

The implementation plan should use spec-driven, contract-first, risk-based TDD.

Recommended tests:

- CLI parser exposes `corpus import/status/retry/skip`;
- dry-run discovers sources without writing;
- source discovery is deterministic;
- batch state serializes and reloads;
- failed item does not stop subsequent items by default;
- fail-fast stops after first failure;
- retry only reprocesses failed/interrupted items;
- skip marks an item without deleting files;
- already-imported detection avoids duplicate processing;
- status is read-only and does not call LLM/parser/add/apply;
- generated state is ignored/cleanable;
- sanitized failures do not expose API keys or raw prompts;
- corpus layer does not write wiki/catalog directly outside existing add pipeline.

Tests should use small fixtures and monkeypatched add pipeline calls where possible. Real `docs/papers` acceptance should remain manual or explicitly marked because it can be slow and LLM-dependent.

## 14. Manual Acceptance

Manual V4.1 acceptance should use a small subset first:

```powershell
llmwiki corpus import docs/papers --root . --dry-run
llmwiki corpus import docs/papers --root .
llmwiki corpus status --root .
llmwiki corpus status <batch-id> --json --root .
llmwiki corpus retry <batch-id> --root .
```

Acceptance checklist:

1. Dry run lists discovered papers and writes nothing.
2. Import creates one generated batch state directory.
3. Per-paper statuses are visible.
4. A failed paper records a sanitized reason.
5. Successful papers remain successful when retry is run.
6. Retry does not reprocess already applied items.
7. Skip does not delete source or wiki files.
8. Existing `llmwiki add` behavior remains unchanged.
9. Formal wiki/catalog writes only occur through the add pipeline.
10. Generated batch state is ignored and cleanable.

## 15. Success Criteria

V4.1 is successful when:

- a user can queue a folder of papers through one CLI command;
- batch state persists across process exits;
- status reports are useful without exposing secrets;
- failed papers do not invalidate successful imports;
- retry/skip behavior is deterministic;
- already-imported papers are not duplicated silently;
- no corpus command bypasses staging/apply;
- no generated batch state is committed;
- the design can support later paper identity and metric/result extraction specs.

## 16. Open Decisions For The Implementation Plan

- Should folder import recurse by default or require `--recursive`?
- Should batch state be JSON/JSONL only, SQLite only, or JSONL plus optional SQLite summaries?
- What exact source identity rules should determine `already_imported`?
- Should retry create a new batch id or append attempts to the original batch?
- Should `corpus import` support list files in the first implementation?
- Should `--parser` be exposed on corpus import or inherited from `add` defaults only?
- Should `--fail-fast` be default false?
- Should interruption handling use signal handlers in the first implementation?
- Which generated batch paths should `clean --scope generated` remove?
