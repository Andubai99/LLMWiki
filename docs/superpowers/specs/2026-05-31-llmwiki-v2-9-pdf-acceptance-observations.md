# LLMWiki V2.9 PDF Acceptance Observations

Date: 2026-05-31

This note records a real acceptance run using the 20 PDFs under `docs/papers/`. It is not a V2.9 design spec yet. Its purpose is to capture concrete failure modes that should shape V2.9 Rich Source Parsing.

## Test Setup

- Workspace: `.tmp/papers-v29-acceptance`
- Inputs: 20 arXiv PDFs under `docs/papers/`
- Commands exercised:
  - `llmwiki add <paper.pdf> --root .tmp/papers-v29-acceptance`
  - `llmwiki lint --root .tmp/papers-v29-acceptance`
  - `llmwiki embeddings status/rebuild --root .tmp/papers-v29-acceptance`
  - `llmwiki retrieve ... --json`
  - `llmwiki ask ... --no-writeback --json`
- Real LLM ingest was enabled.
- Embedding rebuild was run after add.

## High-Level Result

All 20 PDFs were imported and processed without command-level `add` failures.

Catalog summary after add:

- Sources: 20
- Claims: 311
- Pages: 47
- Source pages: 20
- Concept pages: 20
- Entity pages: 7
- Relationships: 338
- `contradicts`: 0
- Weak/uncited claims: 0

Embedding rebuild:

- Provider: `dashscope_multimodal`
- Model: `tongyi-embedding-vision-flash-2026-03-06`
- Dimension: 768
- Chunks: 378

LLM ingest token usage across the 20 papers:

- Total tokens: 112,281
- Typical per-paper total: roughly 4,800 to 7,000 tokens
- Every normalized PDF exceeded the current 16,000 character ingest window.

## Issues Found

### 1. Source Titles Are Wrong For Every PDF

All 20 `sources.title` values became:

```text
<!-- page:1 -->
```

Cause observed:

- `extract_pdf_text` prepends `<!-- page:1 -->`.
- `extract_title` takes the first non-empty line.
- Therefore the page marker becomes the source title.

Effects:

- Every source receives a duplicate alias like `page1`.
- Source pages are not meaningfully identifiable.
- Catalog title/alias retrieval is polluted.
- `lint` reports duplicate alias issues.

V2.9 implication:

- PDF normalization must distinguish metadata markers from content lines.
- Title extraction should use PDF metadata when reliable, then first title-like text block, and must skip generated page markers.

### 2. PDF Text Extraction Produces Layout Noise And Mojibake

Example from `2404.07972.pdf` normalized text:

```text
OSW ORLD : Benchmarking Multimodal Agents for
Open-Ended Tasks in Real Computer Environments
Tianbao Xie鈾?Danyang Zhang鈾?...
```

Observed noise:

- `OSWorld` becomes `OSW ORLD`.
- Author footnote/symbol text becomes mojibake such as `鈾?`.
- Some PDFs contain dozens to hundreds of mojibake-like artifacts.
- Multi-column and line-wrapped content is flattened into unstable line order.
- Hyphenation and word splitting remain in the normalized source.

V2.9 implication:

- Rich source parsing needs cleanup passes: dehyphenation, Unicode repair, column/layout detection, generated marker separation, and paper-title/name normalization.
- The parser should preserve both raw extracted text and cleaned text, with traceable anchors back to the source.

### 3. Formal Citations Lose Page Context

Normalized sources contain page markers, but catalog claim locators typically look like:

```text
line:85;paragraph:1
```

Problems:

- Page number is not carried into formal `citation_locator`.
- Paragraph anchors collapse heavily; many claims are under `paragraph:1`.
- For long papers, line-only locators are hard to inspect manually.

V2.9 implication:

- Claims should cite stable source blocks such as `page:N`, section, paragraph, table, figure, equation, or bibliography anchor.
- Locator normalization should preserve page context when the original source is a PDF.

### 4. Current LLM Ingest Sees Only The First 16,000 Characters

The current LLM ingest layer truncates normalized text to the first 16,000 characters.

In this run, all 20 PDFs were longer than 16,000 characters. Normalized sizes ranged from about 50,000 to 307,000 characters.

Effects:

- Claims are biased toward title, abstract, and introduction.
- Later sections, experiments, tables, ablations, limitations, and references are usually not extracted.
- A paper with 50+ pages can produce a wiki entry based almost entirely on its opening pages.

V2.9 implication:

- Rich PDF import should be chunked and section-aware.
- Ingest should process the whole paper through a multi-pass workflow:
  - metadata/abstract pass
  - section map pass
  - claim extraction per section
  - table/figure/equation extraction
  - final paper-level synthesis

### 5. Tables, Figures, Equations, And References Are Not Structured Evidence

Current PDF normalization is plain text extraction. It does not create structured blocks for:

- tables
- equations
- figures and captions
- screenshots
- algorithms
- appendices
- references and citation graph

Effects:

- Numeric benchmark results can be extracted if they appear in prose, but table-only evidence is unreliable.
- Evaluation comparisons and ablations are incomplete.
- Claims cannot cite a table cell, figure caption, or equation anchor.

V2.9 implication:

- Parser output should be block-based, not only line-based Markdown.
- Each block should carry type, page, section, text, and source coordinates when available.
- Table rows/cells and figure captions should be retrievable and citable.

### 6. Concept/Entity Boundary Is Unstable For Paper Systems

Lint showed shared concept/entity aliases for system names such as:

- `OSWorld`
- `CoAct-1`
- `MobileAgent-v2`

The current LLM proposal often creates both a concept page and an entity page for the same paper-introduced system.

V2.9 implication:

- Paper import should model paper-introduced artifacts explicitly:
  - paper
  - method/system
  - benchmark/dataset
  - model
  - metric/result
- The concept/entity dichotomy is too weak for research papers.

### 7. Local Retrieve Is Sensitive To Extraction Artifacts

Before embedding rebuild:

- Query: `OSWorld performance gap`
- Top result came from a later ReVision paper, not the original OSWorld paper.

When querying the extracted artifact:

- Query: `OSW ORLD performance gap`
- The original OSWorld paper was retrieved correctly.

After embedding rebuild:

- Query: `OSWorld performance gap`
- The original OSWorld paper appeared near the top, but a related OSWorld-Human paper ranked first.

V2.9 implication:

- Parsing and normalization quality directly affects retrieval.
- Vector retrieval can reduce but not fully fix polluted source text.
- V2.9 should normalize canonical terms and preserve alias mappings from paper metadata and body text.

### 8. Ask Can Answer, But Evidence Selection Can Mix Original And Follow-Up Papers

Question:

```text
What is OSWorld and what performance gap does it report?
```

Before vector rebuild, `ask` returned a strong answer citing the original OSWorld paper, including the human/model performance gap.

After vector rebuild, the answer mixed evidence from:

- original OSWorld paper
- Agent S paper
- CoAct-1 paper

This made the answer less clean for a question asking about the original OSWorld paper.

V2.9 implication:

- Research-paper retrieval needs paper-role awareness:
  - original method/benchmark paper
  - follow-up evaluator paper
  - improvement paper
  - survey/position paper
- Evidence selection should distinguish "definition from original source" from "later reported result on the same benchmark."

### 9. `lint` Correctly Exposes Structural Problems

`lint` result:

```text
duplicate alias: 2
shared concept/entity alias: 4
```

Concrete duplicate alias examples:

- `page1`: produced for all 20 sources because every source title became `<!-- page:1 -->`
- `page`: observed as an alias on more than one concept

V2.9 implication:

- Parser quality should be tested through `lint`.
- Rich PDF import should fail or warn loudly when extracted metadata is obviously invalid.

## What Worked

- The current pipeline can process 20 text PDFs end-to-end without crashing.
- LLM ingest produced citation-backed claims with valid source ids and locators.
- `ask` can answer research-domain questions when relevant evidence is retrieved.
- Embedding rebuild completed successfully on the generated catalog.
- Relationship semantics remained clean; no false `contradicts` relationships were produced.

## V2.9 Development Directions Suggested By This Run

1. Add a structured PDF parser output format.
   - `blocks.jsonl` or equivalent.
   - Block types: title, author, abstract, section_heading, paragraph, table, table_row, figure_caption, equation, algorithm, reference, appendix.

2. Replace single-pass first-16k ingest with section-aware multi-pass ingest.
   - Use the full document.
   - Preserve per-section provenance.
   - Generate paper-level summary only after section-level extraction.

3. Fix PDF metadata and title extraction.
   - Skip generated page markers.
   - Use PDF metadata and first-page layout cues.
   - Detect and repair spaced artifact terms such as `OSW ORLD`.

4. Make citations page/block-aware.
   - Include page number in formal claim locators.
   - Prefer `page + section + paragraph/table/figure/equation` anchors over line-only anchors.

5. Introduce research-paper artifact types.
   - Paper
   - System/method
   - Benchmark/dataset
   - Metric/result
   - Model/baseline

6. Preserve and index tables, figures, equations, and references.
   - Table values should be retrievable as evidence.
   - Figure captions should be claim sources.
   - References should support citation graph and related-work retrieval.

7. Add PDF acceptance eval cases.
   - Original-paper definition query.
   - Follow-up-paper benchmark query.
   - Table result query.
   - Method comparison query.
   - Citation/page-anchor inspection query.

## Acceptance Baseline For V2.9

V2.9 should be considered meaningfully better than the current baseline only if the same 20 PDFs satisfy these checks:

- Source titles are real paper titles, not page markers.
- No duplicate `page1` source aliases.
- Canonical terms such as `OSWorld` retrieve the correct original paper without needing artifact spelling like `OSW ORLD`.
- Claims include page-aware locators.
- Table/figure/equation evidence is queryable and citable.
- Ingest covers methods, experiments, limitations, and appendices, not just abstract/introduction.
- `lint` passes or reports only meaningful domain issues, not parser artifacts.
- Ask answers about original papers do not silently mix follow-up paper evidence unless the question asks for cross-paper comparison.
