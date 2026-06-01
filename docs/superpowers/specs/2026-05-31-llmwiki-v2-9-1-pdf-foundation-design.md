# LLMWiki V2.9.1: PDF Foundation

## 1. Background

V2.9 was originally planned as Rich Source Parsing: MinerU, attachments, PDFs, tables, formulas, OCR, and image captions. The acceptance run over the 20 PDFs in `docs/papers/` showed that this direction is still correct, but the first slice must be narrower and more foundational.

The current system can process text PDFs end to end:

- `add` succeeds;
- normalized Markdown is generated;
- LLM ingest creates claims;
- staging/apply works;
- retrieval, embedding, and ask can operate over the resulting catalog.

However, the generated knowledge is not yet reliable enough for research PDFs:

- all 20 PDF source titles became `<!-- page:1 -->`;
- PDF extraction artifacts such as `OSW ORLD` polluted titles, aliases, claims, and retrieval;
- formal claim locators lost page context and collapsed into `line:N;paragraph:1`;
- every PDF exceeded the current first-16,000-character LLM ingest window;
- later methods, experiments, tables, ablations, limitations, appendices, and references were mostly absent from extracted claims;
- lint reported parser-created alias issues such as duplicate `page1`;
- retrieval sometimes preferred follow-up papers over the original paper because source role and canonical names were not modeled clearly enough.

V2.9.1 therefore focuses on the PDF foundation required before richer table, figure, formula, MinerU, and OCR work.

## 2. Goals

V2.9.1 must make text PDF import suitable as a stable foundation for research-paper knowledge extraction.

It must:

- extract real PDF titles instead of generated page markers;
- preserve source metadata such as title, authors, abstract, page count, and extraction warnings;
- output structured text blocks for PDF pages, sections, and paragraphs;
- generate page-aware and block-aware citation anchors;
- clean common PDF extraction artifacts without losing traceability to raw text;
- normalize canonical terms found in title/abstract/body, such as `OSW ORLD` to `OSWorld` when evidence supports the repair;
- preserve both raw and cleaned text where relevant;
- update normalized Markdown to be generated from structured blocks rather than one flat text stream;
- support full-document LLM ingest through chunked, section-aware processing rather than only the first 16,000 characters;
- keep `llmwiki add <pdf> --root .` as the normal user-facing import command;
- preserve staging/apply safety boundaries;
- improve `lint` so parser artifacts are visible and actionable.

V2.9.1 is successful when the 20 `docs/papers` PDFs produce real source titles, meaningful source aliases, page-aware locators, and claims that cover more than the abstract/introduction.

## 3. Non-Goals

V2.9.1 does not implement the full Rich Source Parsing program.

It does not include:

- table structure extraction into row/cell evidence;
- equation/formula object extraction beyond preserving formula-like text in paragraph blocks;
- figure or screenshot extraction;
- image caption OCR;
- scanned PDF OCR;
- MinerU integration;
- attachment bundle ingestion;
- reference graph construction beyond preserving reference-section text blocks;
- external hosted vector databases;
- UI or Obsidian plugin changes;
- LLM relationship classification;
- automatic contradiction resolution.

These remain for later V2.9 slices:

- V2.9.2: tables, figures, formulas, and richer block-type retrieval;
- V2.9.3: MinerU, OCR, image-heavy PDFs, and attachments.

## 4. Design Principles

### 4.1 Blocks Are The Source Parsing Contract

The parser should produce structured blocks first. Markdown is a view over those blocks, not the primary parse artifact.

A PDF paragraph, heading, title, abstract, reference item, or appendix paragraph should become a block with:

- stable `block_id`;
- source id;
- block type;
- page span;
- order;
- section path;
- raw extracted text;
- cleaned text;
- warnings;
- optional extraction metadata.

### 4.2 Clean Text Must Remain Traceable

Cleaning is required, but it must not destroy provenance.

Examples:

- dehyphenating line breaks;
- repairing split terms such as `OSW ORLD`;
- removing generated page markers from title candidates;
- reducing mojibake and footnote-symbol noise;
- joining wrapped lines within the same paragraph.

For research auditability, the system should preserve enough raw text and block metadata to inspect where cleaned text came from.

### 4.3 Citation Anchors Should Point To Blocks

PDF locators should no longer be only `line:N;paragraph:1`.

The preferred locator shape for V2.9.1 is:

```text
page:1;block:src_xxx_p001_b0004;section:Abstract
```

For multi-page or multi-block claims:

```text
page:3-4;block:src_xxx_p003_b0012..src_xxx_p004_b0002;section:2 Method
```

Line numbers may remain as debug metadata, but formal claim citations should prefer page and block anchors.

### 4.4 Full-Paper Ingest Must Be Chunked

Research PDFs cannot be represented by the first 16,000 characters.

V2.9.1 should process the whole paper through bounded chunks:

- metadata/title/abstract chunk;
- section map chunk;
- per-section text chunks;
- optional conclusion/limitations chunk;
- final paper-level consolidation.

The LLM should receive structured chunk context and return claims with block locators. It must not invent block ids.

### 4.5 Keep The Public Add Interface Simple

The normal user workflow remains:

```powershell
llmwiki add docs/papers/2404.07972.pdf --root .
```

Additional debug commands may exist, but normal users should not have to manually run a parser, chunker, ingest, review, and apply sequence.

## 5. User-Facing Behavior

### 5.1 Add A PDF

```powershell
llmwiki add docs/papers/2404.07972.pdf --root .
```

Expected output remains compatible with V2.1+ autonomous add:

```text
Added source: src_d4c6e20dd594
Processed with: llm
Applied run: run_src_d4c6e20dd594_...
Claims: 64
Patches: 3
Pages:
- wiki/sources/src_d4c6e20dd594.md
- wiki/papers/osworld.md
- wiki/benchmarks/osworld.md
Warnings:
- PDF extraction repaired spaced term: OSW ORLD -> OSWorld
- Some author affiliation symbols could not be normalized
```

The exact page taxonomy may be finalized during implementation, but the command should no longer create a source titled `<!-- page:1 -->`.

### 5.2 Inspect Normalized PDF

The normalized Markdown should remain readable in Obsidian and Git.

Expected shape:

```markdown
---
source_id: src_d4c6e20dd594
title: "OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments"
source_type: pdf
page_count: 53
blocks_path: sources/blocks/src_d4c6e20dd594.jsonl
metadata_path: sources/metadata/src_d4c6e20dd594.json
---

# Normalized Source: OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments

<!-- block:src_d4c6e20dd594_p001_b0001; page:1; type:title -->
# OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments

<!-- block:src_d4c6e20dd594_p001_b0002; page:1; type:authors -->
Tianbao Xie; Danyang Zhang; ...

<!-- block:src_d4c6e20dd594_p001_b0003; page:1; type:section_heading; section:Abstract -->
## Abstract

<!-- block:src_d4c6e20dd594_p001_b0004; page:1; type:paragraph; section:Abstract -->
Autonomous agents that accomplish complex computer tasks...
```

### 5.3 Retrieve PDF Evidence

Retrieval contexts should continue to expose catalog-backed claims, but PDF claims should carry page/block locators:

```json
{
  "claim_id": "clm_src_d4c6e20dd594_abstract_006",
  "source_id": "src_d4c6e20dd594",
  "citation_locator": "page:1;block:src_d4c6e20dd594_p001_b0004;section:Abstract",
  "page_path": "wiki/sources/src_d4c6e20dd594.md",
  "claim_text": "Humans accomplish over 72.36% of OSWorld tasks while the best model achieves 12.24%."
}
```

### 5.4 Ask Research Questions

For original-paper definition questions:

```text
What is OSWorld and what performance gap does it report?
```

The answer should prefer the original OSWorld paper for definition and core reported gap. Follow-up papers may appear only when they are directly relevant or when the question asks for comparison, later results, or follow-up work.

## 6. Parsing Outputs

V2.9.1 introduces structured parse artifacts under `sources/`.

### 6.1 Metadata Sidecar

Path:

```text
sources/metadata/<source_id>.json
```

Minimum fields:

```json
{
  "schema_version": "source_metadata.v2.9.1",
  "source_id": "src_d4c6e20dd594",
  "source_type": "pdf",
  "title": "OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments",
  "authors": ["Tianbao Xie", "Danyang Zhang"],
  "abstract": "Autonomous agents that accomplish complex computer tasks...",
  "page_count": 53,
  "extraction_engine": "pypdf",
  "extraction_warnings": [
    "repaired_spaced_term: OSW ORLD -> OSWorld"
  ],
  "raw_path": "sources/raw/src_d4c6e20dd594-2404.07972.pdf",
  "normalized_path": "sources/normalized/src_d4c6e20dd594.md",
  "blocks_path": "sources/blocks/src_d4c6e20dd594.jsonl"
}
```

### 6.2 Blocks JSONL

Path:

```text
sources/blocks/<source_id>.jsonl
```

Each line:

```json
{
  "schema_version": "source_block.v2.9.1",
  "block_id": "src_d4c6e20dd594_p001_b0004",
  "source_id": "src_d4c6e20dd594",
  "block_type": "paragraph",
  "page_start": 1,
  "page_end": 1,
  "section_path": ["Abstract"],
  "order": 4,
  "text_raw": "Autonomous agents that accomplish complex computer tasks with minimal human\\ninterventions...",
  "text_clean": "Autonomous agents that accomplish complex computer tasks with minimal human interventions...",
  "char_start": null,
  "char_end": null,
  "bbox": null,
  "warnings": []
}
```

Required V2.9.1 block types:

- `title`
- `authors`
- `abstract`
- `section_heading`
- `paragraph`
- `reference`
- `appendix_heading`
- `unknown`

Reserved for later V2.9 slices:

- `table`
- `table_row`
- `figure_caption`
- `equation`
- `algorithm`
- `image`
- `ocr_text`

## 7. Metadata And Title Extraction

Title extraction should follow a layered strategy:

1. PDF metadata title, if present and not obviously generic.
2. First-page title-like block before author lines.
3. First large/central text block if layout metadata is available.
4. Filename fallback only if no credible title exists.

The extractor must skip generated parser markers such as:

```text
<!-- page:1 -->
```

It should also reject obviously bad titles:

- `page 1`;
- `untitled`;
- whitespace-only;
- pure symbols;
- strings dominated by extraction markers;
- repeated header/footer fragments.

Warnings should be recorded when the title is low-confidence.

## 8. Text Cleanup

V2.9.1 should include conservative cleanup passes:

- normalize Unicode with NFKC where safe;
- repair common mojibake only when pattern confidence is high;
- remove or isolate author footnote markers;
- join hyphenated line breaks within paragraphs;
- join wrapped lines within the same paragraph;
- preserve paragraph breaks and section headings;
- normalize spaced artifact terms when title/abstract/body evidence agree.

Cleanup must be deterministic and auditable. When the cleaner makes a non-trivial repair, it should add a warning to the metadata or block.

Examples:

```text
OSW ORLD -> OSWorld
signif-\nicantly -> significantly
na-\nture -> nature
```

Do not apply broad domain-specific keyword rules. Repairs must come from general text extraction heuristics, repeated term evidence, metadata agreement, or explicit canonical alias detection.

## 9. Full-Document LLM Ingest

V2.9.1 should remove the first-16,000-character ingest bottleneck for PDFs.

Proposed ingest stages:

1. Parse PDF into metadata and blocks.
2. Build a section map.
3. Create bounded ingest chunks from adjacent blocks.
4. Run LLM claim extraction per chunk.
5. Validate claim locators against known block ids.
6. Merge and deduplicate claims across chunks.
7. Build page proposals for the paper and major artifacts.
8. Apply through existing staging/apply validation.

The LLM prompt should include:

- paper metadata;
- chunk section path;
- chunk blocks with block ids and page numbers;
- instructions to cite only provided block ids;
- existing local catalog overview for duplicate detection.

The LLM prompt should not include:

- API keys;
- raw PDF bytes;
- unrelated full-document chunks;
- unbounded full-paper text.

### 9.1 Chunking Contract

Chunk boundaries are system-owned, not LLM-owned.

The required data flow is:

```text
PDF parser -> blocks
deterministic chunker -> chunks
LLM ingest -> claims
```

The parser decides blocks. The chunker decides chunks. The LLM receives a chunk and extracts claims only from the blocks inside that chunk.

The LLM must not:

- create chunk ids;
- merge chunks;
- split chunks;
- rename chunks;
- change chunk boundaries;
- cite block ids outside the provided chunk;
- infer evidence from another chunk unless that evidence is explicitly included in the current chunk context.

The deterministic chunker should be generic and document-structure-aware, not domain-specific. It should use:

- parser blocks;
- section hierarchy;
- page order;
- block order;
- token budget;
- reserved output budget;
- optional overlap policy.

It must not use fruit-, medicine-, GUI-agent-, OSWorld-, benchmark-, or other domain-specific keyword rules.

Recommended chunk schema:

```json
{
  "schema_version": "source_chunk.v2.9.1",
  "chunk_id": "src_d4c6e20dd594_sec_abstract_chunk_001",
  "source_id": "src_d4c6e20dd594",
  "chunk_type": "section_claim_extraction",
  "section_path": ["Abstract"],
  "page_start": 1,
  "page_end": 1,
  "block_ids": [
    "src_d4c6e20dd594_p001_b0003",
    "src_d4c6e20dd594_p001_b0004"
  ],
  "context_block_ids": [
    "src_d4c6e20dd594_p001_b0001"
  ],
  "token_estimate": 4200,
  "purpose": "extract claims from the abstract"
}
```

Chunking rules:

- Prefer one chunk per section when the section fits within budget.
- Do not cross section boundaries unless a short heading/parent context block is explicitly included as context.
- If a section is too long, split it by paragraph block order.
- Do not split a block unless the block itself exceeds the maximum budget.
- If a single block exceeds budget, create a `large_block_split` chunk with explicit split offsets and warnings.
- Include parent section headings as context blocks when useful, but distinguish context blocks from evidence blocks.
- Use small overlap only for continuity, and mark overlap block ids explicitly.
- Keep abstract, conclusion, limitations, and appendix chunks identifiable through `chunk_type` or `purpose`.

Allowed chunk types for V2.9.1:

- `metadata_summary`
- `section_claim_extraction`
- `long_section_part`
- `conclusion_or_limitations`
- `appendix_text`
- `reference_text`
- `large_block_split`

The LLM may return observations about parser quality, such as "this block appears to be a section heading" or "this text appears to contain table residue," but those observations are not authoritative. Parser repair suggestions must go through a validator and must not directly change block ids, chunk ids, or citation anchors.

Claim validation must check:

- every cited block id exists;
- every cited block id belongs to the source;
- every cited evidence block is present in the current chunk, or is a declared context/overlap block;
- generated citation locators match the chunk's page and block metadata;
- no claim depends on text outside the provided chunk unless the claim is later produced by an explicit consolidation pass using validated chunk-level claims.

The consolidation pass may merge duplicate or overlapping claims across chunks, but it must preserve all source block locators that support the merged claim.

## 10. Catalog And Wiki Model

V2.9.1 may introduce paper-specific pages if needed, but should keep compatibility with existing `source`, `concept`, `entity`, and `synthesis` pages.

Recommended page roles:

- `source`: raw source-facing page, one per PDF;
- `paper`: research paper knowledge page;
- `concept`: general concept;
- `entity`: organization/person/model if clearly an entity;
- future reserved roles: `method`, `benchmark`, `dataset`, `result`.

If adding a new `page_type="paper"` is too large for V2.9.1 implementation, the source page must at minimum render paper metadata and section coverage clearly.

Source title and aliases must come from metadata, not from generated page markers.

## 11. Retrieval And Ask Expectations

V2.9.1 is not a new retriever phase, but it should improve retrieval by feeding cleaner source data.

Expected improvements:

- `OSWorld performance gap` retrieves the original OSWorld paper without requiring `OSW ORLD`.
- source title filters and aliases are meaningful;
- page/block locators are visible in contexts;
- original paper definition questions prefer original paper evidence;
- follow-up papers can still be retrieved for comparison or state-of-the-art questions.

V2.9.1 should not make retrieval depend on OCR or table extraction.

## 12. Lint And Diagnostics

`llmwiki lint` should detect parser-quality issues:

- generated marker used as source title;
- duplicate `page1` aliases;
- missing page-aware locators for PDF claims;
- missing block sidecar for PDF sources;
- claim locator references unknown block id;
- excessive extraction warnings;
- normalized PDF text contains high mojibake count.

These checks should help distinguish domain issues from parser artifacts.

## 13. Acceptance Dataset

Use the existing 20 PDFs in `docs/papers/` as the V2.9.1 acceptance corpus.

Required acceptance queries:

```text
What is OSWorld and what performance gap does it report?
Which papers introduce benchmarks for GUI or computer-use agents?
Compare OSWorld and MobileAgentBench.
What does MobileAgentBench evaluate?
What are the key limitations reported for current computer-use agents?
```

Required acceptance checks:

- all 20 PDFs import successfully;
- all 20 sources have real paper titles;
- no source has alias `page1`;
- `lint` does not report parser-created duplicate aliases;
- every PDF source has a metadata sidecar;
- every PDF source has a blocks JSONL sidecar;
- PDF claims cite `page` and `block`;
- at least one claim is extracted from a non-introduction section for long papers;
- `OSWorld` retrieves the original OSWorld paper in top 3 without needing artifact spelling;
- ask answers cite page/block locators;
- no generated API keys, raw secrets, or local config contents appear in parser artifacts.

## 14. Failure Modes And Safe Behavior

If PDF parsing partially fails:

- `add` should fail safely before applying wiki/catalog changes when no meaningful text can be extracted.
- If metadata extraction is weak but text extraction works, `add` may continue with a warning.
- If block parsing fails after raw import, the source should not be applied into wiki/catalog as if it were fully parsed.
- If LLM chunk ingest fails for one chunk, the run should either retry that chunk or mark the source run failed; it should not silently produce a partial paper page without warning.

All errors must be sanitized and must not expose `config/api-keys.toml` contents or API keys.

## 15. Documentation Requirements

README should explain:

- PDF import now produces metadata and blocks;
- page/block locators are the citation contract for PDFs;
- V2.9.1 handles text PDFs only;
- tables, formulas, figures, OCR, MinerU, and attachments are later V2.9 slices;
- parser warnings should be reviewed when importing research PDFs.

AGENTS.md should state:

- agents must not treat generated parser markers as source content;
- PDF claims should cite page/block locators;
- block sidecars are durable source artifacts;
- cleanup repairs must be traceable;
- table/figure/equation extraction is not part of V2.9.1 unless explicitly added later.

## 16. Open Questions

1. Should V2.9.1 add a new durable `wiki/papers/` page type, or should it first enrich existing source pages?
2. Should `sources/blocks/*.jsonl` be committed as durable source artifacts, or treated as rebuildable parser output?
3. Should PDF parser warnings block `add` by default, or only surface in lint?
4. How aggressive should canonical term repair be before it risks changing technical names incorrectly?
5. Should chunked ingest use one LLM call per section, or a fixed token budget across adjacent blocks?
6. Should V2.9.1 include a lightweight parser abstraction to allow later MinerU replacement without changing ingest code?

## 17. Summary

V2.9.1 turns PDF import from "flat extracted text passed to LLM" into a page-aware, block-aware, full-document text parsing foundation.

It deliberately stops before table, figure, equation, OCR, and MinerU work. Those later slices depend on the same block and locator contract. The immediate target is to make text PDFs produce clean titles, stable metadata, traceable blocks, page-aware citations, and full-paper coverage good enough for research wiki workflows.
