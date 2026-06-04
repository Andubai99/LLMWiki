# LLMWiki V2.1: Autonomous Add Pipeline

## 1. Background

LLMWiki V1 already has the core source-backed pipeline:

```text
source -> normalized source -> LLM claims -> staging -> apply -> wiki/catalog -> retrieve
```

This is reliable and auditable, but the user-facing workflow still exposes implementation steps:

```bash
llmwiki add <source>
llmwiki ingest <source-id>
llmwiki review <run-id>
llmwiki apply <run-id>
```

The product direction is different. For source import, users should only need one public command:

```bash
llmwiki add <source-or-url>
```

After that, LLMWiki should parse the source, run the LLM/wiki workflow, validate outputs, write the wiki, update the catalog, and report what happened. `ingest`, `review`, and `apply` remain available as internal/debug commands, not as the normal user workflow.

## 2. Goal

Make `llmwiki add` the only public import interface for a single file or URL.

When users add a source, the system should automatically complete the import-to-wiki flow:

```text
资料导入
-> 文档解析 / normalize
-> LLM ingest
-> staging run creation
-> automated validation
-> apply to wiki/catalog
-> index/log update
-> user-facing summary
```

The user should not need to know source ids, run ids, review commands, patch files, or apply commands for normal operation.

## 3. Non-Goals

This phase does not implement:

- MinerU integration.
- Full PDF/table/image parsing beyond current source import behavior.
- Query-time `ask` command.
- Answer writeback to `wiki/syntheses/`.
- Multi-source concept/entity merge logic beyond the current patch generation behavior.
- Vector search, reranking, or external search engines.
- Web UI or desktop UI.
- Removing the internal staging/apply machinery.

## 4. Public Workflow

The normal user flow becomes:

```bash
llmwiki add docs/example.md --root .
```

Expected successful output should include:

- imported or reused source id
- created run id
- proposal engine
- claim count
- patch count
- applied wiki pages
- warnings, if any
- next suggested action, such as asking a question or opening `wiki/index.md`

Example shape:

```text
Added source: src_xxx
Processed with: llm
Applied run: run_src_xxx_...
Claims: 18
Patches: 2
Pages:
- wiki/sources/src_xxx.md
- wiki/concepts/example.md
Warnings: none
```

If the source is a duplicate, `add` should still be safe and clear:

```text
Source already imported: src_xxx
Wiki is already up to date for this source.
```

If the source exists in `sources` but has not yet been applied, `add` may resume the autonomous pipeline for that source.

## 5. Internal Workflow

`llmwiki add` should orchestrate the existing primitives instead of replacing them:

```text
import_source
-> ingest_source
-> validate staged run
-> apply_run
-> summarize result
```

The implementation may expose an internal function such as:

```python
add_and_process_source(root: Path, locator: str) -> AddPipelineResult
```

This function owns orchestration. CLI `cmd_add` should call it by default.

The lower-level functions remain independently testable:

- `import_source`
- `ingest_source`
- `review_run`
- `apply_run`

## 6. Debug Commands

The commands below remain available for development and failure recovery:

```bash
llmwiki ingest <source-id> --root .
llmwiki review <run-id> --root .
llmwiki review <run-id> --detail --root .
llmwiki review <run-id> --patches --root .
llmwiki apply <run-id> --root .
```

They should be treated as visible internal/debug commands:

- They may remain in the CLI parser.
- README primary workflow should not require them.
- Help text should label them as internal/debug instead of hiding them.
- Failure messages from `add` may mention them for diagnostics.

This preserves debuggability without making manual review/apply part of normal use.

## 7. Safety Contract

The user-facing review step is removed, but the safety layer is not removed.

`add` must still enforce:

- raw sources are immutable after import
- LLM output writes only to `staging/<run-id>/`
- formal wiki writes happen only through `apply_run`
- patch target paths stay under `wiki/`
- `wiki/log.md` remains append-only
- existing wiki pages are backed up before overwrite
- weak/uncited claims do not become formal page conclusions
- every formal claim has a source locator
- API keys and sensitive config are never written to staging, logs, README, tests, or wiki

In short:

```text
No manual review, but still staged, validated, logged, and recoverable.
```

## 8. Failure Behavior

If the autonomous pipeline fails before `apply_run`, it must not mutate `wiki/` or the catalog beyond source import.

If it fails during `apply_run`, existing apply rollback behavior must restore wiki targets, index/log, and catalog snapshot.

Failure output should include:

- failed stage
- source id, if available
- run id, if available
- short error reason
- debug command suggestion

Example:

```text
Add pipeline failed at: apply
source_id: src_xxx
run_id: run_src_xxx_...
reason: Unsafe patch references weak/uncited claim(s): clm_xxx
Debug:
  llmwiki review run_src_xxx_... --detail --root .
```

## 9. Data Contracts

The existing staging files remain durable debug/audit artifacts:

```text
staging/<run-id>/run.json
staging/<run-id>/claims.jsonl
staging/<run-id>/triage.md
staging/<run-id>/llm-proposal.json
staging/<run-id>/patches/*.json
staging/<run-id>/backups/
```

`run.json` should record that the run was automatically applied through the add pipeline. A minimal addition is acceptable:

```json
{
  "status": "applied",
  "trigger": "add",
  "proposal_engine": "llm"
}
```

The exact field name can be settled during implementation, but the run must remain auditable.

## 10. CLI Behavior Changes

`llmwiki add` currently imports and normalizes a source. In V2.1 it becomes an autonomous pipeline command.

Proposed flags:

```bash
llmwiki add <source> --root .
```

There is no `--no-process` or `--no-llm` mode in V2.1. Source import always proceeds into the LLM-backed autonomous pipeline. Import-only behavior can remain available through internal tests or lower-level Python functions, but it is not part of the public CLI contract.

Potential future flags, not required in this phase:

```bash
--dry-run
--parser mineru
--force-reprocess
```

These should not be implemented unless needed for V2.1 acceptance.

## 11. Documentation Changes

README should describe the primary import workflow as:

```bash
llmwiki add docs/example.md --root .
```

The README should explain that this command:

- imports the source
- normalizes it
- runs LLM processing
- stages candidate changes internally
- validates and applies them
- updates wiki and catalog

`ingest`, `review`, and `apply` should move to an advanced/debug section.

AGENTS.md should be updated to clarify:

- agents should use `llmwiki add` for normal source import
- agents may use `ingest/review/apply` only for debugging or recovery
- LLM output still must not bypass staging/apply internally

## 12. Acceptance Criteria

V2.1 is complete when:

1. `llmwiki add <markdown-file> --root .` imports the source and applies generated wiki pages without requiring manual `ingest/review/apply`.
2. A successful add updates `wiki/`, `wiki/index.md`, `wiki/log.md`, and `state/catalog.sqlite`.
3. The generated staging run is still present and marked applied.
4. `ingest`, `review`, and `apply` still work for existing tests and debug use.
5. Failed LLM/validation/apply runs do not leave partial wiki mutations.
6. README primary workflow no longer presents manual review/apply as the normal path.
7. Full test suite passes.

## 13. Test Plan

Add or update tests for:

- `add` imports, ingests, applies, and updates wiki in one command.
- `add` creates a staging run with status `applied`.
- `add` updates catalog pages and claims.
- duplicate source add does not create duplicate wiki pages.
- failure during apply rolls back wiki/catalog mutations.
- debug commands still work on a generated run.
- CLI output does not leak API keys.

Existing tests around `ingest`, `review`, `apply`, `lint`, `doctor`, and retrieval should continue to pass.

## 14. Operational Decisions

The following decisions are settled for V2.1:

- Keep V2.1 single-source only.
- Mark failed runs when a run exists.
- Keep debug commands callable and visible, but label them as internal/debug.
- Do not run full `lint` as part of `add`.
- `lint` remains a separate maintenance action that the user can explicitly request from the LLM or run through `llmwiki lint --root .`.

## 15. Later Phases

This spec intentionally prepares the project for, but does not implement:

- ingest-time retrieval of existing wiki context
- multi-source concept/entity merge
- query-time evidence answer
- answer writeback to `wiki/syntheses/`
- MinerU parser integration
- stronger search infrastructure

Those should be separate specs after the autonomous add pipeline is stable. Folder and inbox batch processing belong to a later workflow automation phase, not V2.1.
