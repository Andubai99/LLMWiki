# LLMWiki V4.2 Paper Identity And Corpus Inventory Design

## 1. Summary

V4.2 adds the paper identity layer that V4 needs before metric/result extraction.

V4.1 can queue and process a corpus. V4.2 should make each imported research paper identifiable and inspectable:

```text
catalog source
-> parser/source metadata sidecars
-> deterministic paper identity summary
-> duplicate warnings
-> corpus inventory CLI
```

The first user-facing command is:

```powershell
llmwiki corpus inventory --root .
llmwiki corpus inventory --root . --json
```

V4.2 is still CLI-first. It does not add UI, does not extract metric/result claims, does not merge duplicate papers automatically, and does not call external metadata services.

## 2. Motivation

Metric evolution requires stable paper identity. Before LLMWiki can answer:

```text
How did this metric evolve across these papers?
Which paper reported this result first?
Which papers are duplicates or near-duplicates?
```

it must know which imported source corresponds to which paper, with enough auditable metadata to sort, filter, and warn.

V4.2 should answer simpler questions first:

- Which papers are in this workspace?
- What is each paper's source id, title, authors, year, DOI, arXiv id, and parser status?
- Which papers are applied, failed, pending, or only visible through a batch state?
- Which papers look like duplicates?
- Which identity fields are missing or low-confidence?

The answer must come from local catalog/source metadata, not from invented LLM output.

## 3. Relationship To V4.1

V4.1 created corpus batch orchestration under `state/corpus-batches/`.

V4.2 builds on that state but does not change V4.1 import semantics:

- `llmwiki corpus import` remains the batch import command.
- `llmwiki corpus status` remains the batch status command.
- `llmwiki corpus retry` and `llmwiki corpus skip` keep their existing meaning.
- `llmwiki corpus inventory` is an inventory/read-only command over catalog sources and optional batch context.

V4.2 should not reprocess files just to build an inventory. If identity metadata is missing, inventory should report the gap instead of invoking parser, LLM, MinerU, add, ingest, apply, or clean.

## 4. Scope

V4.2 includes:

- paper identity extraction from local catalog rows and existing source sidecars;
- stable workspace-local paper identity anchored by `source_id`;
- deterministic DOI, arXiv id, and year detection where available;
- author and venue/status reporting when already present in source metadata;
- duplicate and near-duplicate warnings;
- `llmwiki corpus inventory` human and JSON output;
- tests for identity parsing, inventory output, duplicate warnings, and read-only boundaries.

V4.2 does not include:

- metric/result extraction;
- metric timeline queries;
- new UI screens;
- automatic duplicate merging;
- external DOI/arXiv/Semantic Scholar/OpenAlex metadata lookups;
- LLM-based metadata enrichment;
- new hosted vector database;
- paper citation graph extraction;
- author disambiguation beyond source-supported strings;
- new formal claims derived only from metadata.

## 5. Paper Identity Model

### 5.1 Stable Identity

For V4.2, the stable paper identity anchor is `source_id`.

The JSON output may expose `paper_id`, but the default value should be the same as `source_id` unless a later implementation plan introduces an explicit paper table or page type.

This keeps V4.2 compatible with the current catalog:

```text
sources.source_id
sources.title
sources.source_type
sources.raw_path
sources.normalized_path
sources.sha256
sources.url
sources.imported_at
sources.status
pages.page_id / pages.path / pages.title
ingest_runs.status
```

V4.2 should not require a catalog migration for the first implementation. If an implementation plan later chooses a migration, it must preserve the `source_id` anchor and add migration tests.

### 5.2 Identity Fields

A paper identity summary should support these fields:

```text
schema_version
source_id
paper_id
source_type
title
title_source
title_confidence
authors
authors_source
year
year_source
venue_or_status
venue_or_status_source
doi
doi_source
arxiv_id
arxiv_id_source
sha256
raw_path
normalized_path
metadata_path
blocks_path
chunks_path
page_id
page_path
applied_run_id
applied_status
imported_at
parser_backend
parser_backend_fallback_from
parser_quality
identity_status
warnings
duplicate_warnings
```

Only source-supported fields should be populated. Missing values should remain empty, `null`, or omitted according to the final JSON model. They must not be invented.

### 5.3 Field Provenance

Every non-trivial identity field should carry provenance, either as a sibling `*_source` field or a structured provenance map.

Recommended source labels:

- `catalog`: value came from `state/catalog.sqlite`;
- `pdf_metadata`: value came from `sources/metadata/<source-id>.json`;
- `pdf_block`: value came from `sources/blocks/<source-id>.jsonl`;
- `filename`: value came from source filename or raw path;
- `url`: value came from source URL;
- `normalized_source`: value came from normalized source frontmatter;
- `batch_state`: value came from V4.1 corpus batch state;
- `unknown`: value is missing or cannot be attributed safely.

Inventory must expose warnings when provenance is weak or missing.

## 6. Identity Sources

### 6.1 Catalog

The catalog is the primary source for workspace identity:

- `source_id`;
- source title;
- source type;
- SHA-256;
- raw and normalized paths;
- imported time;
- source status;
- applied run status;
- source page path when available.

Catalog values are local audit data. They are not automatically formal research claims.

### 6.2 PDF Metadata Sidecar

For PDF sources, V4.2 should read:

```text
sources/metadata/<source-id>.json
```

The current sidecar schema is `source_metadata.v2.9.2`. It already contains:

- `title`;
- `authors`;
- `abstract`;
- `paper_identity`;
- `title_quality`;
- `parser_backend`;
- `parser_backend_fallback_from`;
- `parser_quality`;
- sidecar paths.

V4.2 should treat this as parser/source metadata, not evidence.

Malformed, missing, or legacy metadata sidecars should produce warnings and should not cause `corpus inventory` to fail for the whole corpus.

### 6.3 Blocks And Normalized Sources

When deterministic extraction needs supporting text, V4.2 may bounded-read:

- `sources/blocks/<source-id>.jsonl`;
- `sources/normalized/<source-id>.md`.

Reads must be path-bounded to the workspace and to the expected generated source directories.

Inventory should not scan `sources/raw/` for full document text except for filename/path identity signals. It must not parse PDFs during inventory.

### 6.4 Batch State

If V4.1 batch state exists, inventory may attach batch context:

```text
batch_id
item_id
item_status
attempt_count
latest_run_id
failure_reason
parser_requested
```

Batch context is generated status, not formal paper identity. It should be optional and must not override catalog identity values.

## 7. Deterministic Extraction Rules

### 7.1 DOI

DOI detection should use a conservative regex over local metadata strings, normalized frontmatter, filename, URL, and bounded first-page/block text when available.

Recommended normalized output:

```text
10.<registrant>/<suffix>
```

The implementation should:

- strip URL prefixes such as `https://doi.org/`;
- strip trailing punctuation;
- preserve DOI case or normalize to lowercase consistently;
- report ambiguous multiple DOI candidates as warnings;
- avoid selecting DOI-like text from references unless the implementation can identify that it belongs to the paper itself.

### 7.2 arXiv ID

arXiv id detection should support:

```text
2404.07972
2404.07972v2
arXiv:2404.07972
https://arxiv.org/abs/2404.07972
```

For the `docs/papers` corpus, filenames such as `2404.07972.pdf` should be enough to populate `arxiv_id` with `arxiv_id_source="filename"`.

### 7.3 Year

Year can be derived from:

- explicit metadata/year text;
- venue/status line;
- arXiv id prefix;
- DOI or URL only when deterministic;
- filename only when it is an arXiv id or an explicit year pattern.

For arXiv-style ids:

```text
YYMM.NNNNN -> 20YY for current modern papers
```

The implementation should not infer a year from arbitrary two-digit numbers in titles or filenames.

### 7.4 Authors

Authors should come from existing parser metadata or author blocks.

V4.2 should preserve author strings as observed. It should not attempt global author disambiguation, affiliation parsing, or reformatting beyond safe whitespace cleanup.

When author extraction is ambiguous, inventory should show an empty list or warning instead of inventing names.

### 7.5 Venue Or Status

Existing PDF parser logic can expose `venue_or_status`. V4.2 should keep it as `venue_or_status` rather than pretending it is a canonical venue.

Examples:

```text
Published as a conference paper at ICLR 2025
Preprint
Proceedings of ...
```

The field may help year detection, but it should remain auditable text.

## 8. Duplicate Warnings

V4.2 should distinguish exact duplicates from likely duplicates.

### 8.1 Exact Duplicate

Exact duplicates are sources with the same SHA-256. The import layer already treats those as duplicate source content.

Inventory should surface exact duplicates if they exist in catalog or batch state, but it should not merge or delete anything.

### 8.2 Likely Duplicate

Likely duplicate warnings may be raised when any of these match:

- same DOI;
- same arXiv id;
- normalized titles match exactly;
- normalized title plus first author plus year match;
- raw filenames encode the same arXiv id.

The duplicate warning should include:

```text
warning_type
source_id
other_source_id
reason
shared_value
confidence
```

Suggested confidence values:

- `exact`: same SHA-256;
- `high`: same DOI or same arXiv id;
- `medium`: same normalized title plus first author/year;
- `low`: same normalized title only.

V4.2 must not automatically resolve duplicates or change formal wiki pages because of these warnings.

## 9. Inventory Command

### 9.1 CLI Shape

Required:

```powershell
llmwiki corpus inventory --root .
llmwiki corpus inventory --root . --json
```

Recommended optional flags for the implementation plan:

```powershell
llmwiki corpus inventory --root . --source-type pdf
llmwiki corpus inventory --root . --batch-id <batch-id>
llmwiki corpus inventory --root . --include-batch-items
llmwiki corpus inventory --root . --missing-only
```

The first implementation can keep flags minimal if the JSON schema already includes enough data for later filtering.

### 9.2 Human Output

Human output should be compact and audit-oriented:

```text
Corpus inventory
Papers: 20
Warnings: 3

source_id        year  title                         arxiv_id     status
src_...          2024  ...                           2404.07972   applied
src_...          2025  ...                           2505.13909   applied

Warnings:
- likely_duplicate: src_a and src_b share arxiv_id=...
- missing_year: src_c has no supported year signal.
```

Do not print API keys, raw prompts, raw LLM responses, full parser logs, or raw parser artifact contents.

### 9.3 JSON Output

Recommended schema:

```json
{
  "schema_version": "corpus_inventory.v4.2",
  "root": "F:/LLMWiki",
  "generated_at": "2026-06-03T00:00:00+00:00",
  "paper_count": 1,
  "warning_count": 1,
  "papers": [
    {
      "schema_version": "paper_identity.v4.2",
      "source_id": "src_...",
      "paper_id": "src_...",
      "source_type": "pdf",
      "title": "Example Paper",
      "title_source": "catalog",
      "title_confidence": "high",
      "authors": ["Alice Example", "Bob Example"],
      "authors_source": "pdf_metadata",
      "year": 2024,
      "year_source": "arxiv_id",
      "venue_or_status": "",
      "venue_or_status_source": "unknown",
      "doi": "",
      "doi_source": "unknown",
      "arxiv_id": "2404.07972",
      "arxiv_id_source": "filename",
      "sha256": "...",
      "raw_path": "sources/raw/src_...",
      "normalized_path": "sources/normalized/src_....md",
      "metadata_path": "sources/metadata/src_....json",
      "blocks_path": "sources/blocks/src_....jsonl",
      "chunks_path": "sources/chunks/src_....jsonl",
      "page_id": "src_...",
      "page_path": "wiki/sources/src_....md",
      "applied_run_id": "run_...",
      "applied_status": "applied",
      "imported_at": "...",
      "parser_backend": "mineru",
      "parser_backend_fallback_from": "",
      "parser_quality": {},
      "identity_status": "complete",
      "warnings": [],
      "duplicate_warnings": []
    }
  ],
  "duplicates": [],
  "warnings": []
}
```

All paths should be workspace-relative where possible. If absolute paths are needed for debugging, they must be sanitized and bounded to the workspace.

### 9.4 Status Values

Suggested `identity_status` values:

- `complete`: title and at least one durable external or temporal identifier are available;
- `partial`: title is available but key fields such as year, DOI, arXiv id, or authors are missing;
- `missing_metadata`: catalog source exists but expected sidecar metadata is missing;
- `malformed_metadata`: sidecar exists but cannot be parsed safely;
- `not_paper`: source exists but is not a PDF or research paper-like source;
- `batch_only`: item appears only in corpus batch state and has no catalog source row.

These are UI/CLI identity status values. They must not be confused with source status, job status, or claim confidence.

## 10. Source Page Behavior

V4.2 should keep source pages as the paper-facing wiki pages for the first implementation.

Recommended source page section:

```markdown
## Paper Identity

- source_id: ...
- title: ...
- authors: ...
- year: ...
- DOI: ...
- arXiv: ...
- venue_or_status: ...
- metadata_path: ...
```

This section should only be created or updated through existing ingest/staging/apply paths. The inventory command must not write source pages.

Paper title should be stored as source/page metadata. It should not be inserted as a formal alias unless the source explicitly supports that alias and the existing alias rules allow it.

V4.2 should not introduce `page_type="paper"` by default. V4.5 can revisit paper/method/dataset/metric/result page types after metric/result extraction requirements are clearer.

## 11. Retrieval Behavior

Paper identity improves retrieval by making source titles and page titles reliable.

V4.2 should not change retrieval semantics broadly. It may rely on existing catalog title/page title retrievers and vector source-title chunks after identity data is reflected in catalog/source pages.

Inventory output is not retrieval evidence. DOI, arXiv id, authors, venue/status, and parser diagnostics are metadata unless they are separately converted into source-backed claims through a future spec.

## 12. Safety Boundaries

V4.2 must preserve these invariants:

- `corpus inventory` is read-only.
- `corpus inventory` must not call LLM providers.
- `corpus inventory` must not call embedding providers.
- `corpus inventory` must not run MinerU, pypdf parsing, or parser repair.
- `corpus inventory` must not call `add_and_process_source`, `ingest_source`, `apply_run`, ask, synthesis, lint, eval, or clean.
- `corpus inventory` must not write `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/embeddings/`, or `state/corpus-batches/`.
- `docs/papers/` must never be modified.
- Missing metadata should become warnings, not fabricated values.
- Duplicate warnings must not merge, delete, or overwrite sources.
- Raw parser logs, raw prompts, raw LLM responses, and secrets must not be returned.

## 13. Suggested Implementation Shape

The implementation plan should refine exact file names, but this structure is recommended:

```text
src/llmwiki/corpus/identity.py
src/llmwiki/corpus/inventory.py
src/llmwiki/corpus/formatting.py
tests/test_corpus_identity.py
tests/test_corpus_inventory.py
```

`identity.py` should be deterministic and unit-testable:

- parse DOI;
- parse arXiv id;
- infer year from safe signals;
- normalize title for duplicate comparison;
- load PDF metadata with warnings;
- build `PaperIdentity` objects.

`inventory.py` should be read-only:

- query catalog sources;
- join applied run status;
- read source pages and metadata sidecars safely;
- attach optional V4.1 batch context;
- compute duplicate warnings;
- return a structured response.

## 14. Test Strategy

Use spec-driven, contract-first, risk-based TDD.

Recommended tests:

- DOI parsing handles `doi.org` URLs and strips trailing punctuation.
- arXiv parsing handles filename, `arXiv:` prefix, and arxiv.org URLs.
- year inference uses arXiv id and explicit year strings but ignores unrelated two-digit numbers.
- author extraction preserves source strings and does not invent authors.
- missing/malformed sidecars return warnings, not crashes.
- inventory JSON has `schema_version="corpus_inventory.v4.2"` and paper items have `paper_identity.v4.2`.
- inventory includes source id, title, raw/normalized paths, SHA-256, applied status, page path, parser backend, and warnings.
- duplicate warnings are emitted for same DOI, same arXiv id, same title plus first author/year.
- exact duplicate and likely duplicate warnings are distinct.
- `corpus inventory --json` is read-only and does not call LLM, embedding, parser, add, ingest, apply, ask, synthesis, lint, eval, or clean.
- inventory does not write generated batch state or corpus caches.
- CLI parser exposes `llmwiki corpus inventory`.
- README/AGENTS contract tests are updated if public docs are changed.

## 15. Manual Acceptance

Manual acceptance should use a small imported subset first.

Suggested flow:

```powershell
.\.venv\Scripts\python.exe -m llmwiki corpus import <tmp-corpus> --root .
.\.venv\Scripts\python.exe -m llmwiki corpus inventory --root .
.\.venv\Scripts\python.exe -m llmwiki corpus inventory --root . --json
```

Acceptance checks:

1. Inventory lists each imported paper.
2. Each row has stable `source_id`.
3. Title comes from catalog/source metadata.
4. arXiv id is detected from filenames such as `2404.07972.pdf`.
5. Year is derived from safe metadata or arXiv id.
6. Authors are shown when already present in PDF metadata.
7. Missing DOI/authors/year produce warnings instead of fabricated values.
8. Duplicate warnings are visible for repeated DOI, arXiv id, or normalized title.
9. Inventory does not create or modify `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/corpus-batches/`, or `state/embeddings/`.
10. `git status --short --ignored` does not show tracked generated inventory state.

Full `docs/papers` acceptance can run after the small subset passes:

```powershell
.\.venv\Scripts\python.exe -m llmwiki corpus inventory --root . --json
```

The full run should remain read-only and should not require re-importing papers.

## 16. Success Criteria

V4.2 is successful when:

- every imported paper can be listed from `llmwiki corpus inventory`;
- inventory JSON has stable schema and source-backed provenance;
- paper identity is anchored by `source_id`;
- title/authors/year/DOI/arXiv fields are populated only when supported;
- duplicate warnings are visible but non-mutating;
- inventory can explain missing identity data;
- source/page title retrieval has reliable paper titles;
- the design can support V4.3 metric/result extraction without rethinking paper identity.

## 17. Open Questions

- Should a future V4.5 introduce `page_type="paper"`, or should source pages remain the paper-facing pages permanently?
- Should V4.2 persist a `paper_identities` catalog table, or is existing catalog plus sidecars sufficient until V4.3?
- Should DOI/arXiv extraction scan reference blocks, or should it only scan frontmatter/title/first-page metadata to avoid selecting cited papers?
- Should inventory support CSV output, or is JSON plus human table enough?
- Should batch-only pending/failed items appear in inventory by default or only with `--include-batch-items`?
- Which subset of `docs/papers` should become the deterministic V4 paper identity fixture set?
