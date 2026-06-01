# LLMWiki V2.9.4: Parser Backend Abstraction And MinerU Adapter

## 1. Background

V2.9.1 made PDF ingest source-backed instead of truncating a flat text extraction:

- PDFs are parsed into metadata, blocks, and chunks;
- PDF claims require page/block locators;
- chunk boundaries are deterministic;
- chunked LLM ingest covers the full extracted text instead of only the first 16k characters.

V2.9.2 improved parser quality and paper identity:

- repeated headers, footers, and page numbers can be ignored;
- title quality and parser-created aliases are measured;
- PDF quality evaluation is available through `llmwiki eval pdf-quality`.

V2.9.3 improved robustness:

- malformed PDF chunk/consolidation JSON can be repaired once;
- repair diagnostics are visible without persisting raw malformed model output;
- PDF source titles remain searchable without becoming formal source aliases.

The remaining V2.9 direction is rich source parsing. MinerU is the intended next parser candidate, but integrating it directly into the current `pdf_blocks.py` flow would mix backend-specific artifacts with LLMWiki's durable source contract. V2.9.4 should introduce a parser backend boundary first, keep the pypdf path stable, and add MinerU as an optional adapter that normalizes structured parser output into the existing metadata/block/chunk pipeline.

## 2. Goals

V2.9.4 must:

- introduce a PDF parser backend abstraction;
- keep `llmwiki add <pdf> --root .` as the normal user entry point;
- keep the current pypdf parser as the default backend;
- add an optional MinerU backend adapter;
- normalize pypdf and MinerU output into the same LLMWiki `SourceMetadata`, `SourceBlock`, and `SourceChunk` contracts;
- preserve deterministic block ids and page/block citation locators;
- store parser backend name, version, options, artifacts, and warnings in generated source sidecars;
- make MinerU structured content usable by chunked ingest without letting MinerU-specific files leak into formal wiki/catalog contracts;
- expose parser backend information in `triage.md`, source pages, lint, and `eval pdf-quality`;
- keep `retrieve/query/eval retrieval/eval pdf-quality` local and deterministic;
- keep parser artifacts gitignored and rebuildable.

## 3. Non-Goals

V2.9.4 does not implement:

- default OCR for scanned PDFs;
- table cell-level evidence validation;
- figure understanding or image caption reasoning beyond preserving parser-provided blocks;
- equation semantic interpretation beyond preserving formula blocks and locators;
- external hosted parsing services as default infrastructure;
- external metadata lookup from arXiv, Crossref, Semantic Scholar, or other services;
- new SQLite tables;
- new `page_type="paper"`;
- new retrieval, vector, reranker, or ask-answering behavior;
- LLM-based parser backend selection;
- domain-specific parsing rules for any research field.

## 4. Design Principles

### 4.1 Parser Backends Produce Source Artifacts, Not Wiki Knowledge

A parser backend may produce markdown, JSON, images, tables, formulas, bounding boxes, or debug files. Those outputs are parser artifacts. They are not formal wiki pages, claims, citations, or catalog rows by themselves.

Formal knowledge still enters the wiki only through the existing pipeline:

`parser backend -> normalized blocks/chunks -> LLM ingest proposal -> staging validation -> apply`

### 4.2 Normalize At The Boundary

MinerU-specific output should be consumed by an adapter and converted into LLMWiki's own source artifact schema. Downstream code should not need to know whether a block came from pypdf or MinerU except through diagnostic fields.

The normalized sidecars remain the stable internal contract:

- `sources/metadata/<source_id>.json`
- `sources/blocks/<source_id>.jsonl`
- `sources/chunks/<source_id>.jsonl`

Backend-native artifacts are preserved only for audit and debugging under a generated artifact directory.

### 4.3 Deterministic Boundaries

The LLM must not choose parser backend, block ids, chunk ids, chunk boundaries, page numbers, or citation anchors.

MinerU can provide structure, layout roles, bounding boxes, markdown, tables, formulas, and asset references. LLMWiki still assigns deterministic source ids, block ids, chunk ids, and canonical locators.

### 4.4 Fallback Must Be Explicit

The pypdf backend remains the default because it has already passed the current test and acceptance suite.

MinerU should be opt-in at first. If a user explicitly requests MinerU and it is unavailable or fails, `add` should fail with a clear parser-stage error. If a future `auto` mode is configured, fallback to pypdf may happen only with a visible warning recorded in metadata, triage, and pdf-quality eval.

## 5. User-Facing Behavior

Normal import remains:

```powershell
python -m llmwiki add docs/papers/example.pdf --root .
```

By default, this uses the configured PDF parser backend. The initial default remains `pypdf`.

Optional parser configuration:

```toml
[pdf_parser]
default_backend = "pypdf"
fallback_backend = "pypdf"
mineru_enabled = false
mineru_command = "mineru"
artifact_dir = "sources/parser-artifacts"
```

V2.9.4 may expose an advanced/debug parser override on `add`, for example:

```powershell
python -m llmwiki add docs/papers/example.pdf --root . --parser mineru
```

This is still the same `add` entry point, not a new import workflow. The option should be documented as parser/debug configuration, not as a separate user-facing pipeline.

## 6. Internal Interfaces

### 6.1 Parser Backend Protocol

Add a parser backend module, for example `llmwiki/pdf_parser_backends.py`.

Core types:

```python
@dataclass
class PdfParseRequest:
    root: Path
    source_id: str
    raw_path: Path
    backend_name: str
    options: dict[str, object]

@dataclass
class PdfParseResult:
    metadata: SourceMetadata
    blocks: list[SourceBlock]
    artifacts: list[ParserArtifact]
    warnings: list[str]
    backend_name: str
    backend_version: str | None

class PdfParserBackend(Protocol):
    name: str
    def available(self) -> bool: ...
    def parse(self, request: PdfParseRequest) -> PdfParseResult: ...
```

Implementations:

- `PypdfBackend`: wraps the current V2.9.3 parser path.
- `MinerUBackend`: invokes MinerU or reads existing MinerU output and converts it to LLMWiki blocks.

### 6.2 SourceMetadata Extensions

`SourceMetadata` should add backend diagnostics while remaining backward-compatible with V2.9.1, V2.9.2, and V2.9.3 sidecars:

- `parser_backend`
- `parser_backend_version`
- `parser_backend_options`
- `parser_artifact_paths`
- `parser_backend_warnings`
- `parser_backend_fallback_from`
- `parser_backend_fallback_reason`
- `structured_block_counts`

### 6.3 SourceBlock Extensions

`SourceBlock` should preserve current fields and add optional backend-aware fields:

- `parser_backend`
- `backend_ref`
- `backend_type`
- `bbox`
- `asset_path`
- `html`
- `latex`
- `markdown`
- `table_markdown`
- `quality_flags`

These fields are diagnostic and evidence-supporting. They do not replace canonical source locators. Claims still cite canonical LLMWiki locators such as:

```text
page:3;block:src_xxx_p003_b0012;section:Methods
```

## 7. MinerU Adapter

MinerU output should be treated as an optional parser backend artifact source.

The official MinerU output documentation describes markdown output plus auxiliary structured files, including `content_list.json`, `middle.json`, `model.json`, and newer `content_list_v2.json`. The `content_list.json` format is especially relevant because it stores readable content blocks in reading order as a flat structure. It can include content types such as `text`, `image`, `table`, `chart`, `equation`, `code`, `list`, `header`, `footer`, and `page_number`, with page index and bounding box fields.

V2.9.4 should prefer stable, documented content-list style outputs for normalized block construction. If `content_list_v2.json` is present, it can be read as a best-effort enhancement, but V2.9.4 should not depend on development-only fields for correctness.

MinerU artifact storage:

```text
sources/parser-artifacts/<source_id>/
  mineru/
    <backend-native files>
```

This directory is generated state and must be gitignored.

### 7.1 Content Mapping

MinerU content should map into normalized blocks as follows:

| MinerU type | LLMWiki block role | Notes |
| --- | --- | --- |
| `text` with heading level | `section_heading` | Preserve heading level when available. |
| `text` body | `paragraph` | Preserve reading order and page index. |
| `table` / `chart` | `table_like` | Preserve markdown/html/content if provided; no cell-level claim contract yet. |
| `equation` | `equation_like` | Preserve LaTeX or text payload if provided. |
| `image` | `image` or `caption` | Preserve asset path and caption/content when available. |
| `code` | `code` | Preserve code body and caption if provided. |
| `list` | `paragraph` or `reference` | Preserve list items; references should remain identifiable. |
| `header` / `footer` / `page_number` | `ignored` | Keep in sidecars for audit, exclude from chunk prompts by default. |

### 7.2 Asset Handling

If MinerU emits image/table/chart assets, LLMWiki should keep local references in parser artifacts and normalized blocks. Assets are not committed and are not formal wiki pages.

V2.9.4 does not ask an LLM to interpret image pixels. If MinerU provides textual captions or chart/table content, those textual fields may enter chunk prompts with their block locator.

## 8. Data Flow

```text
llmwiki add <pdf>
  -> import_source
  -> select_pdf_parser_backend
  -> backend.parse(...)
  -> write metadata/blocks/parser artifacts
  -> render normalized markdown from blocks
  -> build deterministic chunks
  -> chunked LLM ingest
  -> staging validation
  -> apply
  -> wiki/catalog/retrieval
```

The downstream chunked ingest path should not fork by backend. Once pypdf and MinerU output become normalized blocks and chunks, they use the same LLM ingest, citation validation, staging, apply, retrieval, and ask contracts.

## 9. Lint And Evaluation

### 9.1 Lint

`llmwiki lint` should report parser backend issues:

- unknown parser backend;
- declared MinerU backend but missing artifact directory;
- parser artifacts missing when metadata declares them;
- invalid backend output schema;
- non-ignored header/footer/page number blocks entering chunk prompts;
- table/formula/image blocks without usable text payload;
- block locators referencing missing backend-normalized blocks;
- fallback occurred but warning is missing.

### 9.2 PDF Quality Eval

`llmwiki eval pdf-quality --root . --json` should add backend-aware counters:

- `parser_backend_distribution`
- `mineru_source_count`
- `backend_artifact_completeness`
- `backend_fallback_count`
- `structured_block_count`
- `table_like_block_count`
- `equation_like_block_count`
- `image_or_caption_block_count`
- `ignored_block_prompt_exclusion_rate`
- `block_locator_validity_by_backend`

The eval command remains read-only and must not call LLM, embedding providers, MinerU, or the network. It reads already generated sidecars and catalog data only.

## 10. Testing Strategy

### 10.1 Unit Tests

Add tests for:

- backend selection from config;
- pypdf backend parity with current output;
- MinerU adapter parsing from small committed fixture JSON;
- MinerU content type mapping;
- deterministic block ids from MinerU blocks;
- ignored header/footer/page number exclusion;
- backend artifact path recording;
- V2.9.1/V2.9.2/V2.9.3 sidecar backward compatibility.

### 10.2 Integration Tests

Add tests for:

- `llmwiki add <pdf>` still works with default pypdf backend;
- `llmwiki add <pdf> --parser mineru` works with a fake MinerU command or fake output directory;
- chunk prompts include table/formula/caption text when available and exclude ignored blocks;
- PDF claims still require page/block locators;
- retrieval and ask citations still come from catalog claims, not parser artifacts.

### 10.3 Real Acceptance

If MinerU is installed locally, run an optional real acceptance in `.tmp/`:

```powershell
python -m llmwiki init --root .tmp\papers-v294-mineru
python -m llmwiki add docs\papers\2404.07972.pdf --root .tmp\papers-v294-mineru --parser mineru
python -m llmwiki eval pdf-quality --root .tmp\papers-v294-mineru --json
python -m llmwiki retrieve "What tables or equations are extracted from this paper?" --root .tmp\papers-v294-mineru --json
```

Generated `.tmp/`, parser artifacts, sidecars, catalog, staging, wiki outputs, and secrets must not be committed.

## 11. Acceptance Criteria

V2.9.4 is accepted when:

- existing pypdf PDF tests continue to pass;
- existing 20-paper pypdf acceptance remains stable;
- parser backend selection is covered by tests;
- MinerU adapter tests pass using small fake MinerU fixtures without requiring real MinerU installation;
- normalized sidecars record parser backend diagnostics;
- MinerU table/formula/image/caption content can become normalized blocks with canonical page/block locators;
- chunked ingest receives normalized blocks, not raw MinerU internals;
- `lint` and `eval pdf-quality` expose parser backend quality metrics;
- `retrieve/query/ask` evidence contracts remain unchanged;
- generated parser artifacts are ignored by git.

## 12. Open Questions

- Should `--parser mineru` be visible in normal help, or hidden under advanced/debug help?
- Should V2.9.4 support reading a precomputed MinerU output directory without invoking MinerU?
- Should MinerU failures in config-default mode fail hard or fall back to pypdf with warning?
- Which MinerU version should be the first supported version for real acceptance?
- Should image/table assets later be copied into wiki-adjacent media folders, or remain source artifacts only?

## 13. References

- MinerU official output file documentation: https://opendatalab.github.io/MinerU/reference/output_files/
- MinerU Chinese output file documentation: https://opendatalab.github.io/MinerU/zh/reference/output_files/
