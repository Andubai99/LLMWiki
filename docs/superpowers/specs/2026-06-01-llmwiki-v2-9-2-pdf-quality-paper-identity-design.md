# LLMWiki V2.9.2: PDF Quality And Paper Identity

## 1. Background

V2.9.1 established the PDF foundation:

- text PDFs are parsed into metadata, blocks, and chunks;
- `llmwiki add <pdf> --root .` processes the full document through chunked LLM ingest;
- PDF claims can cite `page:N;block:<block_id>` locators;
- lint can detect missing PDF sidecars and invalid PDF locators;
- the 20 local arXiv PDFs can be imported end to end.

The V2.9.1 acceptance run showed that the foundation works, but research-paper quality is still uneven. The remaining issues are not command failures; they are quality failures:

- some PDF titles still include venue headers, author lists, affiliations, or layout noise;
- `pypdf` text extraction still leaves split words, repeated headers/footers, page numbers, and symbol artifacts;
- block typing is too coarse for long research papers;
- concept/entity identity remains noisy for paper-introduced systems and benchmarks;
- retrieval works better after V2.9.1, but source identity and paper role are not explicit enough;
- there is no committed PDF-quality evaluation layer equivalent to retrieval eval.

V2.9.2 is therefore a stabilization slice: make text-PDF import cleaner, auditable, and measurable before moving to MinerU, OCR, tables, formulas, figures, and richer source types.

## 2. Goals

V2.9.2 must improve PDF import quality without expanding into full rich parsing.

It must:

- improve PDF title selection so source titles do not include parser markers, venue headers, author lists, or affiliations;
- extract cleaner paper metadata: title, authors, abstract, page count, section map, and parser warnings;
- classify recurring headers, footers, page numbers, affiliations, venue lines, captions, table-like text, equation-like text, references, and appendices as distinct block roles where possible;
- keep raw text and cleaned text traceable to the same block id;
- suppress obvious non-content blocks from normalized Markdown, chunk prompts, and claim extraction unless they are useful metadata;
- improve source-page metadata and triage diagnostics so users can see parser quality;
- reduce parser-created duplicate aliases and shared concept/entity confusion;
- add a deterministic PDF quality evaluation command or report path;
- preserve V2.9.1 safety: no new database schema, no new `page_type="paper"`, no direct wiki mutation outside staging/apply.

## 3. Non-Goals

V2.9.2 does not implement:

- MinerU integration;
- OCR for scanned PDFs;
- table structure extraction into rows/cells;
- figure image extraction;
- image caption OCR;
- equation object extraction;
- reference graph construction;
- external metadata fetching from arXiv, Semantic Scholar, Crossref, or other network services;
- new SQLite tables;
- new formal page types such as `paper`, `method`, `benchmark`, `dataset`, or `metric`;
- LLM reranking or LLM relationship classification;
- automatic semantic claim merging.

V2.9.2 may classify table-like, figure-caption-like, and equation-like text blocks as block roles, but it must not claim to parse their internal structure.

## 4. Design Principles

### 4.1 Parser Rules Are Structural, Not Domain Rules

V2.9.2 may use deterministic structural cleanup rules because PDF parsing needs structure recovery. These rules must be generic and auditable:

- repeated line detection for headers and footers;
- page-number detection;
- title-candidate scoring based on position, length, capitalization, metadata agreement, and author-density;
- author-line detection based on line shape and proximity to title;
- section-heading detection based on document structure;
- caption/table/equation-like detection based on layout text shape.

It must not add topic-specific rules such as `OSWorld`, `MobileAgentBench`, `vitamin C`, or any research-field keyword boost.

When the parser is uncertain, it should record warnings and candidates instead of silently rewriting the document.

### 4.2 Sidecars Are The Durable Parse Contract

Markdown remains the human-readable view. The durable parse artifacts are sidecars:

```text
sources/metadata/<source_id>.json
sources/blocks/<source_id>.jsonl
sources/chunks/<source_id>.jsonl
```

V2.9.2 may upgrade sidecar schema versions:

- `source_metadata.v2.9.2`
- `source_block.v2.9.2`
- `source_chunk.v2.9.2`

Loaders must continue to read V2.9.1 sidecars for backward compatibility.

### 4.3 Cleaned Text Must Stay Inspectable

Every block should preserve:

- `text_raw`: original extracted text;
- `text_clean`: cleaned text used for normalized Markdown and chunk prompts;
- `cleaning_operations`: a list of transformations such as dehyphenation or repeated-footer suppression;
- `warnings`: parse uncertainty or suspicious extraction artifacts.

Claims must cite block ids, not cleaned text offsets. A user should be able to inspect the sidecar and see what raw text produced the cited cleaned block.

### 4.4 Paper Identity Should Be Explicit But Schema-Compatible

V2.9.2 must improve paper identity without adding `page_type="paper"`.

The source page should carry a richer "Paper Metadata" section, and metadata sidecars should carry a `paper_identity` object:

```json
{
  "paper_identity": {
    "title": "...",
    "authors": ["..."],
    "venue_or_status": "Published as a conference paper at ICLR 2025",
    "arxiv_id": "2404.07972",
    "canonical_names": ["OSWorld"],
    "introduced_artifacts": [
      {"name": "OSWorld", "role": "benchmark", "confidence": "llm_proposed"}
    ]
  }
}
```

The catalog still uses existing page types:

- source pages for papers;
- concept/entity pages for introduced systems, benchmarks, methods, or datasets when the LLM proposal and validation support them;
- synthesis pages for user-approved answers.

If concept and entity proposals have the same normalized alias and the role distinction is unclear, V2.9.2 should surface an identity warning in triage instead of blindly creating noisy duplicates.

### 4.5 Quality Must Be Measured

V2.9.2 should make parser quality measurable through a local deterministic check.

The preferred user-facing command is:

```powershell
llmwiki eval pdf-quality --root .
```

If implementation keeps this inside `lint`, it must still expose the same metrics in a stable human-readable and JSON-compatible form.

The quality layer must not call chat LLM APIs and must not write wiki/source/staging/catalog data.

## 5. User-Facing Behavior

### 5.1 Add A Research PDF

The normal command remains:

```powershell
llmwiki add docs/papers/2404.07972.pdf --root .
```

Expected improvements:

- output source title is a real paper title;
- source page includes paper metadata and parser diagnostics;
- generated claims cite page/block locators;
- `triage.md` lists parser warnings, title candidates, block counts, chunk counts, and identity warnings;
- parser-created aliases such as `page1`, `published as a conference paper`, or author-list titles are not inserted into formal aliases.

### 5.2 Inspect Source Metadata

The metadata sidecar should include title-candidate diagnostics:

```json
{
  "schema_version": "source_metadata.v2.9.2",
  "source_id": "src_d4c6e20dd594",
  "title": "OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments",
  "title_quality": "high",
  "title_candidates": [
    {
      "text": "OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments",
      "source": "first_page_block",
      "score": 0.94,
      "reasons": ["early_large_text", "matches_metadata_tokens", "not_author_dense"]
    },
    {
      "text": "Published as a conference paper at ICLR 2025",
      "source": "first_page_block",
      "score": 0.22,
      "reasons": ["venue_or_status_line", "not_title_shape"]
    }
  ],
  "paper_identity": {
    "authors": ["Tianbao Xie", "Danyang Zhang"],
    "venue_or_status": "",
    "arxiv_id": "2404.07972",
    "canonical_names": ["OSWorld"]
  },
  "parser_quality": {
    "page_count": 53,
    "block_count": 420,
    "content_block_count": 310,
    "ignored_block_count": 62,
    "warning_count": 4
  }
}
```

### 5.3 Inspect Blocks

Blocks should distinguish content and non-content roles:

```json
{
  "schema_version": "source_block.v2.9.2",
  "block_id": "src_xxx_p001_b0004",
  "block_type": "abstract",
  "content_role": "content",
  "page_start": 1,
  "page_end": 1,
  "section_path": ["Abstract"],
  "text_raw": "Autonomous agents that accomplish complex computer tasks...",
  "text_clean": "Autonomous agents that accomplish complex computer tasks...",
  "cleaning_operations": ["dehyphenation"],
  "warnings": []
}
```

Non-content blocks remain inspectable but should not be sent to claim extraction by default:

```json
{
  "block_type": "header_footer",
  "content_role": "ignored",
  "text_clean": "Published as a conference paper at ICLR 2025",
  "warnings": ["venue_or_status_line"]
}
```

### 5.4 Run PDF Quality Evaluation

Human output:

```text
PDF quality eval:
- pdf_sources: 20
- title_quality_high_or_medium: 20
- parser_marker_titles: 0
- author_dense_titles: 0
- sidecar_completeness: 1.00
- block_locator_validity: 1.00
- non_intro_section_claim_rate: 0.85
- parser_created_duplicate_aliases: 0
- warnings: 3
```

JSON output should be stable:

```powershell
llmwiki eval pdf-quality --root . --json
```

```json
{
  "schema_version": "eval.pdf_quality.v2.9.2",
  "pdf_source_count": 20,
  "summary": {
    "title_pass_rate": 1.0,
    "sidecar_completeness": 1.0,
    "block_locator_validity": 1.0,
    "content_block_ratio": 0.74,
    "non_intro_section_claim_rate": 0.85,
    "parser_created_duplicate_alias_count": 0
  },
  "sources": [
    {
      "source_id": "src_d4c6e20dd594",
      "title_status": "pass",
      "block_locator_status": "pass",
      "warnings": []
    }
  ]
}
```

## 6. Architecture

### 6.1 Parser Quality Module

Add or extend a module such as:

```text
llmwiki/pdf_quality.py
```

Responsibilities:

- score title candidates;
- detect parser-marker titles;
- detect author-dense titles;
- detect venue/status lines;
- detect repeated headers and footers;
- detect page number blocks;
- classify block content roles;
- compute parser quality metrics.

It should be pure and deterministic. It should accept parsed pages/blocks and return updated metadata/blocks plus diagnostics.

### 6.2 Metadata Enhancement

Extend PDF metadata creation to include:

- `title_candidates`;
- `title_quality`;
- `paper_identity`;
- `section_map`;
- `parser_quality`;
- `schema_version`.

Existing V2.9.1 metadata should still load. Missing V2.9.2 fields should default to safe empty values.

### 6.3 Block Enhancement

Extend blocks with:

- `content_role`: `content`, `metadata`, `ignored`, or `uncertain`;
- `cleaning_operations`;
- `quality_flags`;
- richer `block_type` values:
  - `title`
  - `authors`
  - `affiliation`
  - `abstract`
  - `section_heading`
  - `paragraph`
  - `caption`
  - `table_like_text`
  - `equation_like_text`
  - `algorithm_like_text`
  - `reference_heading`
  - `reference_item`
  - `appendix_heading`
  - `header_footer`
  - `page_number`
  - `unknown`

V2.9.2 must not require all PDFs to classify every block perfectly. It should improve common cases and expose uncertainty.

### 6.4 Chunking Changes

The chunker should exclude `content_role="ignored"` blocks by default.

It should still include metadata context blocks where useful:

- title;
- abstract heading;
- parent section heading;
- local preceding heading.

Chunk diagnostics should include:

- total blocks;
- content blocks used;
- ignored blocks;
- chunks by section;
- sections with no claims after ingest.

### 6.5 LLM Ingest Changes

Chunk prompts should use the cleaner V2.9.2 blocks and include a compact metadata header:

- source id;
- selected paper title;
- authors;
- section path;
- chunk id;
- allowed block ids only.

Consolidation should receive:

- paper identity;
- section summaries;
- cited claim count per section;
- identity warnings.

It must not create formal claims during consolidation.

### 6.6 Catalog And Alias Safety

No schema changes are allowed.

Alias insertion should reject parser-generated aliases:

- page markers;
- author-list titles;
- venue/status-only strings;
- repeated headers/footers;
- strings mostly made of symbols or page numbers.

If a source title or proposed alias fails parser-quality checks, it should remain in diagnostics, not formal aliases.

## 7. Lint And Evaluation

### 7.1 Lint Additions

`llmwiki lint --root .` should continue to report PDF parser issues and expand counters:

- parser-marker titles;
- author-dense titles;
- venue/status-only titles;
- missing sidecars;
- invalid sidecar schema;
- PDF claims without page/block locators;
- PDF claims with unknown block ids;
- content blocks ignored from chunking;
- repeated header/footer blocks;
- high extraction-warning sources;
- parser-created duplicate aliases.

Structural parser issues should make lint return non-zero. Informational warnings should not fail lint unless a threshold is exceeded.

### 7.2 PDF Quality Eval

`llmwiki eval pdf-quality` should be local and deterministic.

It reads:

- `sources` table;
- `claims` table;
- `aliases` table;
- metadata/block/chunk sidecars;
- generated source pages if needed.

It does not call:

- chat LLM;
- embedding provider;
- network APIs.

It does not write:

- `wiki/`;
- `staging/`;
- `sources/`;
- `state/catalog.sqlite`.

## 8. Acceptance Criteria

Using the 20 PDFs under `docs/papers/` in a temporary workspace:

- all 20 PDFs complete `llmwiki add`;
- all 20 PDF sources have metadata, blocks, chunks, source pages, and catalog claims;
- `parser_marker_titles = 0`;
- `author_dense_titles = 0`;
- `venue_or_status_only_titles = 0`;
- `sidecar_completeness = 1.0`;
- `block_locator_validity = 1.0`;
- no PDF claim in catalog lacks `page:` and `block:` in `citation_locator`;
- no PDF claim references an unknown block id;
- no formal alias is created from page markers, repeated headers, or author-list titles;
- at least 80% of long PDFs have claims from sections beyond title/abstract/introduction;
- OSWorld original paper appears in top 3 for `OSWorld performance gap`;
- MobileAgentBench original paper appears in top 3 for `What does MobileAgentBench evaluate?`;
- `llmwiki eval retrieval --dataset tests/evals/retrieval_v2_9_1_pdf_foundation.jsonl` still passes;
- `llmwiki eval pdf-quality --root <tmp>` returns 0;
- `llmwiki lint --root <tmp>` has no PDF parser structural failures.

Known acceptable residuals:

- `shared concept/entity alias` may still appear when the paper genuinely introduces an artifact that can be viewed both as a system and a concept;
- extraction warnings may remain for mathematically dense or layout-heavy pages;
- table/figure/equation content may be present only as text blocks, not structured objects.

## 9. Test Plan

### Unit Tests

- title candidate scoring rejects parser markers, author lists, and venue-only lines;
- metadata title beats noisy first-page text only when it passes quality checks;
- first-page title fallback chooses the best title-shaped candidate;
- repeated header/footer detection marks recurring lines as ignored blocks;
- page number detection marks page numbers as ignored blocks;
- block role classification covers caption/table-like/equation-like/reference/appendix/header/footer cases;
- V2.9.1 sidecars still load with defaults.

### Integration Tests

- importing a fake PDF writes V2.9.2 metadata/blocks/chunks sidecars;
- normalized Markdown excludes ignored header/footer blocks from main body;
- chunker excludes ignored blocks from claim extraction prompts;
- LLM chunk prompts include only allowed block ids;
- source page includes Paper Metadata and Parser Quality;
- triage includes title candidates and identity warnings;
- alias sanitizer prevents parser-created aliases from entering formal catalog aliases.

### Eval And CLI Tests

- `llmwiki eval pdf-quality --root .` outputs stable human report;
- `llmwiki eval pdf-quality --root . --json` outputs `eval.pdf_quality.v2.9.2`;
- eval does not call LLM, embedding provider, or network;
- eval does not mutate workspace files or catalog;
- lint returns non-zero for parser-marker titles or invalid PDF block locators.

### Real Acceptance

Run in `.tmp/papers-v292-acceptance`:

```powershell
python -m llmwiki init --root .tmp/papers-v292-acceptance
copy config/api-keys.toml .tmp/papers-v292-acceptance/config/api-keys.toml
python -m llmwiki add docs/papers/<id>.pdf --root .tmp/papers-v292-acceptance
python -m llmwiki lint --root .tmp/papers-v292-acceptance
python -m llmwiki eval pdf-quality --root .tmp/papers-v292-acceptance
python -m llmwiki embeddings rebuild --root .tmp/papers-v292-acceptance
python -m llmwiki eval retrieval --root .tmp/papers-v292-acceptance --dataset tests/evals/retrieval_v2_9_1_pdf_foundation.jsonl
```

Commit only sanitized summary observations, not the temporary workspace, generated source artifacts, catalog, vector index, or API keys.

## 10. Risks And Mitigations

### Risk: Deterministic Cleanup Becomes Hidden Semantics

Mitigation: keep rules structural, record reasons, preserve raw text, and expose candidates/warnings.

### Risk: Better Filtering Removes Useful Evidence

Mitigation: ignored blocks remain in sidecars; chunk diagnostics count ignored blocks; uncertain blocks can be retained as `content_role="uncertain"` instead of dropped.

### Risk: Title Scoring Fails On Unusual Papers

Mitigation: store all candidates with scores and reasons; fallback to filename only with a warning; make title quality visible in lint/eval.

### Risk: More Diagnostics Increase Noise

Mitigation: distinguish structural failures from informational warnings; only structural parser defects fail lint/eval.

### Risk: LLM Cost Remains High

Mitigation: V2.9.2 does not increase chunk count by default; removing ignored blocks should reduce prompt size. Acceptance should record chunk counts and token usage.

## 11. Future Work After V2.9.2

After V2.9.2 stabilizes text-PDF quality, the next rich parsing slices can proceed:

- MinerU integration for layout-aware parsing;
- structured tables with row/cell citations;
- figure and caption extraction;
- equation object extraction;
- OCR for scanned PDFs;
- reference graph and paper-role modeling;
- dedicated paper/method/benchmark page types if catalog schema evolves.
