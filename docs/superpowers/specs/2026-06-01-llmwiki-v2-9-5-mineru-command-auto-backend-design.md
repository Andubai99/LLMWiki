# LLMWiki V2.9.5: MinerU Command Invocation And Auto Parser Backend

## 1. Background

V2.9.1 changed PDF ingest from flat truncated text into metadata, blocks, chunks, and page/block citation-backed LLM ingest.

V2.9.2 improved PDF quality:

- title selection;
- ignored headers, footers, and page numbers;
- parser quality evaluation;
- paper identity diagnostics.

V2.9.3 made chunked PDF ingest more robust:

- one safe JSON repair attempt for malformed PDF chunk/consolidation output;
- repair diagnostics without persisting raw malformed responses;
- cleaner PDF source alias handling.

V2.9.4 introduced a parser backend boundary:

- `pypdf` remains the default parser;
- MinerU can be selected through hidden/debug parser options;
- precomputed MinerU `content_list.json` output can be adapted into LLMWiki blocks;
- parser-native artifacts are generated source artifacts, not wiki knowledge.

The remaining gap is operational. V2.9.4 still requires the user to run MinerU outside LLMWiki and pass `--parser-output-dir`. V2.9.5 should make `llmwiki add <pdf> --root .` capable of running MinerU automatically, while keeping pypdf as a reliable fallback.

The intended parser strategy becomes:

```text
auto parser backend = MinerU first when available, pypdf fallback when MinerU cannot run or parse
```

## 2. Goals

V2.9.5 must:

- make `llmwiki add <pdf> --root .` automatically attempt MinerU first when configured for `auto`;
- keep `llmwiki add` as the only normal source import entry point;
- change the repository and new-workspace PDF parser default to `auto`;
- enable MinerU-first behavior by default while preserving pypdf fallback;
- invoke the configured MinerU command without requiring a manually prepared `--parser-output-dir`;
- capture MinerU native output under `sources/parser-artifacts/<source_id>/mineru/`;
- discover MinerU content-list output from the generated artifact directory;
- normalize MinerU output into the existing V2.9.x metadata/block/chunk sidecars;
- preserve deterministic LLMWiki block ids, chunk ids, and page/block citation locators;
- keep explicit `--parser mineru` strict: if MinerU fails, the import fails instead of falling back silently;
- keep explicit `--parser pypdf` available as the lightweight fallback/debug path;
- expose parser command diagnostics in metadata, triage, source pages, lint, and `eval pdf-quality`;
- add a local read-only parser status command so users can see whether MinerU is installed/configured;
- keep `retrieve/query/eval retrieval/eval pdf-quality` deterministic and no-chat-LLM;
- keep parser-native artifacts, model output, extracted assets, and command logs gitignored.

## 3. Non-Goals

V2.9.5 does not implement:

- table cell-level evidence contracts;
- figure understanding or image reasoning;
- equation semantic interpretation;
- new catalog tables;
- new `page_type="paper"`;
- external metadata lookup from arXiv, Crossref, Semantic Scholar, or other services;
- external hosted parser services as default infrastructure;
- default remote API submission of user PDFs;
- LLM-based parser backend selection;
- LLM-based OCR correction;
- changes to retrieval, vector store, reranker, ask answer generation, or synthesis writeback semantics.

MinerU may internally run OCR or layout models depending on its own configuration and command flags. V2.9.5 only treats the resulting textual/structured outputs as parser artifacts. It does not add a new OCR quality contract beyond existing block/chunk locator validation and parser quality checks.

## 4. Design Principles

### 4.1 MinerU Is Preferred, pypdf Is The Floor

For research PDFs, MinerU is the preferred parser because it can preserve richer document structure than pypdf. However, it is a heavier dependency and may fail because of installation, model download, GPU/CPU backend, timeout, or version-specific output issues.

Therefore the default should be `auto`:

```text
try MinerU -> if unavailable or failed, record warning -> fallback to pypdf
```

This gives the project the better parser when it is available without making the whole wiki unusable on machines where MinerU is not installed.

### 4.2 Explicit Parser Selection Means Strict Semantics

If the user asks for:

```powershell
llmwiki add paper.pdf --root . --parser mineru
```

the command must either use MinerU successfully or fail at the parser/import stage. It must not silently use pypdf.

If the user asks for:

```powershell
llmwiki add paper.pdf --root . --parser pypdf
```

the command must use pypdf only and must not try MinerU.

### 4.3 Command Invocation Is Generic And Configurable

MinerU versions and hardware backends change. LLMWiki should not hard-code a GPU-only or provider-specific mode.

The default command shape should be based on MinerU's documented CLI:

```powershell
mineru -p <input_path> -o <output_path>
```

LLMWiki may append optional configured MinerU flags, but the default should let the user's MinerU installation and `mineru.json` decide model/backend details.

### 4.4 Parser Artifacts Are Audit Data, Not Evidence

MinerU-native outputs such as markdown, content lists, model JSON, layout PDFs, images, and logs are parser artifacts. They are not formal claims, citations, pages, or catalog rows.

Formal knowledge still enters the wiki through:

```text
MinerU/pypdf parser -> normalized blocks/chunks -> LLM ingest proposal -> staging validation -> apply
```

Claims still cite canonical LLMWiki locators such as:

```text
page:3;block:src_xxx_p003_b0012;section:Methods
```

### 4.5 Fallbacks Must Be Visible

If `auto` falls back from MinerU to pypdf, the user and quality tools must be able to see it.

The fallback reason should appear in:

- `sources/metadata/<source_id>.json`;
- `staging/<run-id>/run.json`;
- `staging/<run-id>/triage.md`;
- source page `Parser Quality` / parser backend section;
- `llmwiki eval pdf-quality --root . --json`;
- `llmwiki lint --root .` as a warning, not automatically as a failure.

## 5. User-Facing Behavior

### 5.1 Normal PDF Add

Default command:

```powershell
python -m llmwiki add docs/papers/2404.07972.pdf --root .
```

Expected behavior under V2.9.5:

1. Read `[pdf_parser]` config.
2. If `default_backend = "auto"` and MinerU is enabled, attempt MinerU.
3. If MinerU succeeds, parse its generated content-list output.
4. If MinerU cannot run or output is invalid, record a visible fallback warning and parse with pypdf.
5. Continue through the existing add pipeline: normalized source, chunks, LLM ingest, staging, validation, apply.

### 5.2 Explicit MinerU

```powershell
python -m llmwiki add docs/papers/2404.07972.pdf --root . --parser mineru
```

Expected behavior:

- run MinerU;
- fail if MinerU command is missing, times out, exits nonzero, or emits no valid content list;
- do not fallback to pypdf;
- show a safe parser-stage error with a debug hint.

### 5.3 Explicit pypdf

```powershell
python -m llmwiki add docs/papers/2404.07972.pdf --root . --parser pypdf
```

Expected behavior:

- skip MinerU entirely;
- use existing pypdf parser path;
- preserve current pypdf acceptance behavior.

### 5.4 Precomputed MinerU Output Remains Debug-Supported

The V2.9.4 debug path remains:

```powershell
python -m llmwiki add docs/papers/2404.07972.pdf --root . --parser mineru --parser-output-dir .tmp/mineru/2404.07972
```

When `--parser-output-dir` is provided, the MinerU backend reads that directory instead of invoking the command. This is important for tests, debugging, and reproducing parser issues without re-running expensive model inference.

### 5.5 Parser Status

V2.9.5 should add a read-only command:

```powershell
python -m llmwiki parsers status --root .
```

Human output should include:

- configured default backend;
- fallback backend;
- whether MinerU is enabled;
- MinerU command path or unavailable status;
- command probe result;
- artifact directory;
- whether pypdf fallback is available.

JSON output should be available:

```powershell
python -m llmwiki parsers status --root . --json
```

This command must not parse PDFs, call chat LLMs, call embeddings, run MinerU on a document, or write workspace files.

## 6. Configuration

V2.9.5 should update default workspace config:

```toml
[pdf_parser]
default_backend = "auto"
fallback_backend = "pypdf"
mineru_enabled = true
mineru_command = "mineru"
mineru_method = ""
mineru_backend = ""
mineru_api_url = ""
mineru_timeout_seconds = 1800
mineru_max_log_chars = 4000
mineru_extra_args = []
artifact_dir = "sources/parser-artifacts"
```

Field meanings:

- `default_backend`: `auto`, `mineru`, or `pypdf`.
- `fallback_backend`: currently only `pypdf` is supported.
- `mineru_enabled`: whether `auto` may attempt MinerU.
- `mineru_command`: executable name or absolute path.
- `mineru_method`: optional MinerU `-m/--method` value; empty means omit and let MinerU default.
- `mineru_backend`: optional MinerU `-b/--backend` value; empty means omit and let MinerU default.
- `mineru_api_url`: optional MinerU `--api-url` value; empty means omit.
- `mineru_timeout_seconds`: parser process timeout.
- `mineru_max_log_chars`: maximum retained sanitized stdout/stderr snippet length.
- `mineru_extra_args`: additional advanced arguments appended after standard args.
- `artifact_dir`: generated parser artifact root.

The command builder must use argument lists with `shell=False`, not shell string concatenation.

## 7. Internal Interfaces

### 7.1 Parser Config

Extend `PdfParserConfig`:

```python
@dataclass(frozen=True)
class PdfParserConfig:
    default_backend: str = "auto"
    fallback_backend: str = "pypdf"
    mineru_enabled: bool = True
    mineru_command: str = "mineru"
    mineru_method: str = ""
    mineru_backend: str = ""
    mineru_api_url: str = ""
    mineru_timeout_seconds: int = 1800
    mineru_max_log_chars: int = 4000
    mineru_extra_args: tuple[str, ...] = ()
    artifact_dir: str = "sources/parser-artifacts"
```

### 7.2 MinerU Command Runner

Add a small command runner boundary, either inside `llmwiki/pdf_parser_backends.py` or as `llmwiki/mineru_runner.py`.

Suggested types:

```python
@dataclass(frozen=True)
class MinerUCommandRequest:
    root: Path
    source_id: str
    raw_path: Path
    output_root: Path
    config: PdfParserConfig

@dataclass(frozen=True)
class MinerUCommandResult:
    command: list[str]
    output_root: Path
    returncode: int
    duration_seconds: float
    stdout_snippet: str
    stderr_snippet: str
    content_list_candidates: list[Path]
    warnings: list[str]
```

The runner must:

- create an isolated generated output directory under `sources/parser-artifacts/<source_id>/mineru/<attempt-id>/`;
- call MinerU using a safe argument list;
- enforce timeout;
- capture stdout/stderr snippets after sanitization;
- discover output files recursively;
- return candidates for `content_list.json`, `*_content_list.json`, `content_list_v2.json`, and `*_content_list_v2.json`;
- avoid logging environment variables or secrets;
- never commit parser artifacts.

### 7.3 Output Discovery

MinerU commonly writes output under a nested document/backend folder below the output root. V2.9.5 should not assume a single exact path.

Discovery should search the generated artifact root for:

- `content_list.json`;
- `*_content_list.json`;
- `content_list_v2.json`;
- `*_content_list_v2.json`.

If multiple candidates exist:

1. prefer non-empty `content_list.json` / `*_content_list.json`;
2. then `content_list_v2.json` / `*_content_list_v2.json`;
3. prefer paths under the input PDF stem if available;
4. if still ambiguous, fail explicit MinerU and fallback in `auto` with a warning.

V2.9.5 should continue to use the V2.9.4 adapter mapping once a content list is selected.

### 7.4 Parser Selection

`select_pdf_parser_backend(...)` should distinguish:

- requested backend from CLI;
- configured default backend;
- auto fallback mode;
- precomputed parser output mode.

Behavior matrix:

| Mode | MinerU unavailable | MinerU parse fails | pypdf available |
| --- | --- | --- | --- |
| `default_backend=auto` | fallback to pypdf with warning | fallback to pypdf with warning | yes |
| `--parser mineru` | fail | fail | no fallback |
| `--parser pypdf` | skip MinerU | skip MinerU | use pypdf |
| `--parser mineru --parser-output-dir <dir>` | read dir | fail if invalid | no fallback |

## 8. Metadata And Diagnostics

### 8.1 SourceMetadata

Existing V2.9.4 metadata fields should be used and extended as needed:

- `parser_backend`;
- `parser_backend_version`;
- `parser_backend_options`;
- `parser_artifact_paths`;
- `parser_backend_warnings`;
- `parser_backend_fallback_from`;
- `parser_backend_fallback_reason`;
- `structured_block_counts`.

V2.9.5 should add command diagnostics:

- `parser_command_invoked`;
- `parser_command`;
- `parser_command_returncode`;
- `parser_command_duration_seconds`;
- `parser_command_stdout_snippet`;
- `parser_command_stderr_snippet`;
- `parser_content_list_path`;
- `parser_content_list_discovery_count`.

The stored `parser_command` should not contain secrets. If `--api-url` contains credentials, it must be redacted.

### 8.2 Run And Review Diagnostics

`run.json`, `triage.md`, source pages, and `review --detail` should show:

- selected backend;
- whether MinerU command was invoked;
- fallback status;
- artifact count;
- selected content-list path;
- command duration;
- sanitized warning/error snippets.

They should not dump:

- full MinerU JSON;
- full model output;
- full stdout/stderr;
- API keys;
- local secret config contents.

## 9. Lint And PDF Quality Eval

### 9.1 Lint

`llmwiki lint --root .` should report:

- configured default parser backend;
- PDF sources parsed by MinerU vs pypdf;
- auto fallback count;
- explicit parser failures if staging artifacts record failed parser attempts;
- missing parser artifacts declared in metadata;
- missing selected content-list path for MinerU sources;
- command log snippets exceeding policy or containing suspicious secrets;
- pypdf fallback warnings as warnings, not automatic failures.

Structural failures still fail lint:

- metadata says `parser_backend="mineru"` but artifact/content-list path is missing;
- block locators are invalid;
- parser artifacts are treated as evidence;
- ignored header/footer/page-number blocks enter chunk prompts.

### 9.2 PDF Quality Eval

`llmwiki eval pdf-quality --root . --json` should add or preserve:

- `parser_backend_distribution`;
- `mineru_source_count`;
- `pypdf_source_count`;
- `auto_fallback_count`;
- `mineru_command_invoked_count`;
- `mineru_command_failure_count`;
- `mineru_timeout_count`;
- `mineru_content_list_missing_count`;
- `backend_artifact_completeness`;
- `block_locator_validity_by_backend`;
- `structured_block_count`;
- `table_like_block_count`;
- `equation_like_block_count`;
- `image_or_caption_block_count`.

This eval remains read-only. It must not run MinerU, call LLMs, call embedding providers, or write workspace files.

## 10. Tests

V2.9.5 should include tests for:

- default config becomes `auto` with MinerU enabled and pypdf fallback;
- `parsers status` human and JSON output;
- command builder uses `mineru -p <input> -o <output>` plus configured optional flags;
- command invocation uses `shell=False`;
- successful fake MinerU command output is discovered and parsed;
- nested MinerU output folders are discovered;
- multiple content-list candidates are handled deterministically;
- command timeout fails explicit MinerU and falls back in `auto`;
- nonzero command exit fails explicit MinerU and falls back in `auto`;
- missing `content_list.json` fails explicit MinerU and falls back in `auto`;
- precomputed `--parser-output-dir` still works without invoking command;
- explicit `--parser pypdf` does not invoke MinerU;
- fallback metadata appears in sidecars, triage, run, review, lint, and pdf-quality eval;
- parser logs are sanitized and truncated;
- read-only eval/status commands do not run MinerU or mutate workspace;
- retrieval/ask still see only catalog-backed evidence and never parser artifacts.

Default automated tests must use monkeypatched command runners or small fixture output. They must not require a real MinerU installation.

## 11. Real Acceptance

If MinerU is installed locally, run in a temporary workspace:

```powershell
python -m llmwiki init --root .tmp/papers-v295-mineru-auto
Copy-Item config/api-keys.toml .tmp/papers-v295-mineru-auto/config/api-keys.toml
python -m llmwiki parsers status --root .tmp/papers-v295-mineru-auto --json
python -m llmwiki add docs/papers/2404.07972.pdf --root .tmp/papers-v295-mineru-auto
python -m llmwiki add docs/papers/2405.14573.pdf --root .tmp/papers-v295-mineru-auto
python -m llmwiki add docs/papers/2406.01014.pdf --root .tmp/papers-v295-mineru-auto
python -m llmwiki eval pdf-quality --root .tmp/papers-v295-mineru-auto --json
python -m llmwiki lint --root .tmp/papers-v295-mineru-auto
```

Optional full acceptance may run all PDFs under `docs/papers`.

Acceptance targets for a machine with working MinerU:

- selected PDFs import successfully through `llmwiki add`;
- `parser_backend="mineru"` for PDFs where MinerU succeeds;
- parser artifacts are under `sources/parser-artifacts/<source_id>/mineru/`;
- sidecar completeness remains 1.0;
- block locator validity remains 1.0;
- no parser artifact is returned as evidence;
- PDF quality eval reports MinerU sources and command invocation counts;
- retrieval foundation queries still pass.

Acceptance targets for a machine without MinerU:

- `llmwiki parsers status` reports MinerU unavailable;
- normal `llmwiki add <pdf>` falls back to pypdf and succeeds when pypdf can parse the PDF;
- explicit `--parser mineru` fails safely with a parser-stage error;
- fallback warning is visible in metadata/triage/eval.

## 12. Documentation And Agent Contract

README should explain:

- pypdf remains available but normal PDF add is now auto MinerU-first;
- MinerU installation is optional for using the project, but recommended for research PDFs;
- `llmwiki parsers status` checks parser availability without parsing;
- parser artifacts are generated ignored files;
- explicit `--parser mineru` is strict;
- `--parser pypdf` is available for fallback/debug;
- table/formula/image blocks remain source artifacts until future evidence contracts define richer semantics.

AGENTS.md should add:

- parser backend choice is deterministic config/CLI behavior, not LLM behavior;
- LLMs must not choose parser backend, block ids, chunk ids, or artifact paths;
- MinerU artifacts are not evidence;
- auto fallback must be visible and auditable;
- status/eval commands must be read-only and no-LLM/no-embedding/no-MinerU-execution unless explicitly documented.

## 13. References

- MinerU CLI documentation describes the basic invocation as `mineru -p <input_path> -o <output_path>` and notes that MinerU supports local PDF and document inputs.
- MinerU output documentation describes output artifacts including Markdown, `content_list.json`, `content_list_v2.json`, `middle.json`, model output, and visualization files.
- LLMWiki V2.9.4 already normalizes MinerU content-list output into LLMWiki metadata/block/chunk sidecars; V2.9.5 builds on that boundary instead of changing downstream knowledge contracts.

## 14. Final Design Decision

V2.9.5 should implement:

```text
default PDF parser = auto
auto parser = MinerU command invocation first when enabled and available
fallback = pypdf with visible warning
explicit mineru = strict fail on MinerU error
explicit pypdf = skip MinerU
```

This is the practical "one step closer to MinerU by default" design: users get MinerU automatically where it is available, but the project remains usable and testable everywhere.
