# LLMWiki V2.9.6: MinerU Operational Hardening

## 1. Background

V2.9.5 made PDF parsing default to `auto`: try MinerU first when available, then fall back to `pypdf` with visible diagnostics. A real local acceptance run on 2026-06-01 installed `mineru==3.2.1` into the project `.venv` and tested three PDFs from `docs/papers`.

The acceptance result was positive for the core pipeline:

- 3/3 PDFs completed `llmwiki add <pdf> --root <tmp>` and reached apply.
- 2/3 PDFs used MinerU successfully.
- 1/3 PDFs fell back from MinerU to `pypdf`.
- `llmwiki lint` passed.
- `llmwiki eval pdf-quality` reported valid sidecars and block locators.
- `llmwiki eval retrieval` passed the PDF foundation dataset.
- `llmwiki ask --no-writeback --json` answered from catalog-backed page/block citations.

The acceptance also exposed two operational gaps that should be fixed before expanding rich parsing:

1. MinerU installed in the project `.venv` is not discovered unless `.venv\Scripts` is on `PATH`.
2. When `auto` falls back from MinerU to `pypdf`, the final metadata records the fallback reason but loses the failed MinerU command diagnostics such as command path, return code, stdout/stderr snippets, timeout status, and content-list discovery result.

V2.9.6 is a focused hardening release for those issues. It should not add new parser capabilities.

## 2. Goals

V2.9.6 must:

- discover workspace-local MinerU executables before reporting MinerU unavailable;
- support Windows `.venv\Scripts\mineru.exe` and POSIX `.venv/bin/mineru` lookup;
- keep configured `mineru_command` as the primary explicit override;
- make `llmwiki parsers status --root . --json` report both configured command discovery and workspace-local discovery;
- preserve sanitized failed MinerU command diagnostics when `auto` falls back to `pypdf`;
- expose fallback command diagnostics in metadata, staging run manifests, triage, source pages, lint, and `eval pdf-quality`;
- distinguish command invocation, command failure, timeout, missing content-list, invalid output, and parser adapter failure;
- keep explicit `--parser mineru` strict: no fallback;
- keep explicit `--parser pypdf` from invoking or probing MinerU beyond read-only status checks;
- keep parser logs sanitized and bounded;
- preserve all V2.9.5 evidence contracts: parser artifacts are not evidence, claims require catalog-backed locators, and `retrieve/query/ask` expose only catalog-backed evidence.

## 3. Non-Goals

V2.9.6 does not implement:

- OCR quality improvements;
- table cell-level evidence;
- figure understanding;
- equation semantic interpretation;
- new catalog tables;
- new `page_type="paper"`;
- LLM-based parser backend selection;
- LLM repair of parser output;
- new retrieval, vector, reranker, planner, ask, or synthesis behavior;
- automatic dependency installation;
- automatic modification of the user's shell `PATH`;
- automatic mutation of committed config files based on local environment.

Installing MinerU remains an environment setup action. V2.9.6 only improves discovery, diagnostics, and quality reporting once MinerU is installed or configured.

## 4. Design Principles

### 4.1 Prefer Explicit Config, Then Workspace-Local Discovery

`mineru_command` remains the authoritative configured executable. If it is an absolute or relative path that resolves to an executable, LLMWiki should use it.

If `mineru_command = "mineru"` or another bare executable name is not found on `PATH`, LLMWiki should also probe common workspace-local virtual environment locations:

```text
<root>/.venv/Scripts/mineru.exe
<repo>/.venv/Scripts/mineru.exe
<root>/.venv/bin/mineru
<repo>/.venv/bin/mineru
```

This keeps normal activated-shell behavior unchanged while making Codex/app/non-activated sessions practical.

### 4.2 Discovery Is Read-Only

Parser status and command discovery must not parse documents, run model inference, call LLMs, call embeddings, contact network services, or write workspace files.

Discovery may call `shutil.which` and inspect expected executable paths. It may optionally call a safe version command only if the implementation can enforce a short timeout and sanitize output. V2.9.6 should not require version execution for correctness.

### 4.3 Fallback Diagnostics Must Survive The Fallback

When MinerU fails in `auto` mode and `pypdf` succeeds, the resulting source metadata currently describes the final backend but loses most failed MinerU attempt details. V2.9.6 should preserve an attempt record.

The final `SourceMetadata` should tell both stories:

- final parser backend: `pypdf`;
- fallback from: `mineru`;
- why fallback happened;
- the failed MinerU attempt command and sanitized result.

### 4.4 Diagnostics Are Audit Data, Not Evidence

MinerU command diagnostics, parser logs, content-list paths, and fallback warnings are audit data. They must not become source claims, wiki pages, retrieval contexts, or citations.

Formal evidence remains:

```text
normalized blocks/chunks -> LLM ingest claims -> staging validation -> catalog claims
```

### 4.5 Safety Before Detail

Logs and errors must be useful but safe:

- no API keys;
- no `config/api-keys.toml` contents;
- no environment dumps;
- no full unbounded stdout/stderr;
- no raw parser artifact dumps in `review --detail`;
- no command strings built through a shell.

## 5. Approaches Considered

### Option A: Document PATH Setup Only

Document that users must activate `.venv` before running LLMWiki.

Pros:

- no code change;
- simple mental model.

Cons:

- Codex/app sessions and automation jobs often run without activated shells;
- `parsers status` can report MinerU unavailable even when the project installed it locally;
- does not fix fallback diagnostics.

### Option B: Workspace-Local Discovery Plus Fallback Attempt Diagnostics

Add explicit discovery of local virtual environment executables and preserve failed MinerU command attempt data across fallback.

Pros:

- fixes both issues observed in real acceptance;
- keeps existing config behavior;
- avoids shell mutation and auto-installation;
- provides actionable diagnostics for future PDF failures.

Cons:

- adds a little platform-specific discovery logic;
- requires careful sanitization and bounded diagnostics.

### Option C: Require Absolute `mineru_command`

Require users to set `mineru_command` to an absolute path.

Pros:

- deterministic;
- simple runtime behavior.

Cons:

- less ergonomic;
- easy to break across machines;
- still does not solve fallback diagnostics by itself.

Recommendation: Option B.

## 6. User-Facing Behavior

### 6.1 Parser Status With Workspace-Local MinerU

If `.venv\Scripts\mineru.exe` exists under the workspace or repo root, this command should report MinerU available even when `.venv\Scripts` is not on `PATH`:

```powershell
python -m llmwiki parsers status --root . --json
```

Expected JSON shape:

```json
{
  "schema_version": "parser_status.v2.9.6",
  "default_backend": "auto",
  "fallback_backend": "pypdf",
  "mineru_enabled": true,
  "mineru_command": "mineru",
  "mineru_command_path": "F:\\LLMWiki\\.venv\\Scripts\\mineru.exe",
  "mineru_command_source": "workspace_venv",
  "mineru_available": true,
  "pypdf_available": true,
  "artifact_dir": "sources/parser-artifacts",
  "warnings": []
}
```

If MinerU is not found anywhere, status should remain safe and clear:

```json
{
  "mineru_available": false,
  "mineru_command_path": "",
  "mineru_command_source": "not_found",
  "warnings": ["MinerU command was not found on PATH or in workspace virtual environments."]
}
```

### 6.2 Auto Add Uses Discovered MinerU Path

When `default_backend = "auto"` and `mineru_enabled = true`, `llmwiki add <pdf> --root .` should use the resolved MinerU command path from the discovery layer.

If discovery found `.venv\Scripts\mineru.exe`, add should invoke that executable directly instead of failing to find bare `mineru`.

### 6.3 Auto Fallback Preserves Failed MinerU Attempt

If MinerU fails and pypdf succeeds, the source still imports, but metadata should include a bounded attempt record:

```json
{
  "parser_backend": "pypdf",
  "parser_backend_fallback_from": "mineru",
  "parser_backend_fallback_reason": "MinerU command exited with code 1; MinerU content-list output was not found",
  "parser_backend_attempts": [
    {
      "backend": "mineru",
      "status": "failed",
      "command_invoked": true,
      "command": ["F:\\LLMWiki\\.venv\\Scripts\\mineru.exe", "-p", "...", "-o", "..."],
      "command_source": "workspace_venv",
      "returncode": 1,
      "timed_out": false,
      "duration_seconds": 12.34,
      "stdout_snippet": "... sanitized bounded text ...",
      "stderr_snippet": "... sanitized bounded text ...",
      "content_list_discovery_count": 0,
      "failure_stage": "missing_content_list",
      "failure_reason": "MinerU content-list output was not found"
    },
    {
      "backend": "pypdf",
      "status": "succeeded"
    }
  ]
}
```

The legacy flat fields may stay for compatibility, but they should not overwrite or erase the failed attempt diagnostics.

### 6.4 Explicit MinerU Still Fails Strictly

```powershell
python -m llmwiki add docs/papers/example.pdf --root . --parser mineru
```

If MinerU fails, the command should fail at import/parser stage. It should include sanitized diagnostics, but it must not fall back to pypdf.

### 6.5 Explicit pypdf Does Not Invoke MinerU

```powershell
python -m llmwiki add docs/papers/example.pdf --root . --parser pypdf
```

This path must use pypdf only. It should not invoke MinerU or create MinerU parser artifacts.

## 7. Internal Interfaces

### 7.1 MinerU Discovery

Add or extend discovery helpers in `llmwiki/mineru_runner.py`.

Proposed types:

```python
@dataclass
class MinerUDiscoveryResult:
    command: str
    resolved_path: Path | None
    source: str  # path, PATH, workspace_venv, repo_venv, not_found
    available: bool
    warnings: list[str]
```

Proposed function:

```python
def discover_mineru_command(root: Path, config: PdfParserConfig) -> MinerUDiscoveryResult:
    ...
```

Discovery order:

1. If `mineru_command` is a path-like value, resolve it relative to `root` and current working directory, then check executability.
2. Use `shutil.which(mineru_command)`.
3. Check workspace-local virtual environment paths.
4. Return not-found result with safe warning.

The implementation should not mutate `PATH`.

### 7.2 Command Request

`MinerUCommandRequest` should store the resolved command path and command source, not just the configured command string.

`build_mineru_command(request)` should use `request.resolved_command` when present.

### 7.3 Parser Attempt Diagnostics

Introduce a serializable parser attempt model, or use a strict dict produced by a helper.

Recommended dataclass:

```python
@dataclass
class ParserBackendAttempt:
    backend: str
    status: str  # succeeded, failed, skipped
    command_invoked: bool = False
    command: list[str] = field(default_factory=list)
    command_source: str = ""
    returncode: int | None = None
    timed_out: bool = False
    duration_seconds: float | None = None
    stdout_snippet: str = ""
    stderr_snippet: str = ""
    content_list_candidates: list[str] = field(default_factory=list)
    content_list_discovery_count: int = 0
    failure_stage: str = ""
    failure_reason: str = ""
    warnings: list[str] = field(default_factory=list)
```

`SourceMetadata` should gain:

- `parser_backend_attempts: list[dict[str, object]]`

Backward compatibility:

- V2.9.1 through V2.9.5 metadata loaders must default this field to `[]`.
- Existing flat fields such as `parser_command_invoked`, `parser_command_returncode`, and `parser_backend_fallback_reason` remain readable.

### 7.4 Auto Fallback Flow

Current flow:

```text
MinerU parse fails -> catch error -> parse pypdf -> metadata describes pypdf
```

V2.9.6 flow:

```text
MinerU parse fails with attempt diagnostics
  -> catch error
  -> parse pypdf
  -> merge failed MinerU attempt and succeeded pypdf attempt into final metadata
  -> preserve fallback fields
```

Explicit `--parser mineru` should surface the failed attempt in the safe error or failed import result, but should not write formal wiki/catalog state.

## 8. Quality Reporting

### 8.1 `eval pdf-quality`

Extend `llmwiki eval pdf-quality --root . --json` with:

- `mineru_command_discovered_count`
- `mineru_command_source_distribution`
- `mineru_attempt_count`
- `mineru_attempt_failure_count`
- `mineru_attempt_timeout_count`
- `mineru_attempt_missing_content_list_count`
- `auto_fallback_with_attempt_diagnostics_count`
- `auto_fallback_missing_attempt_diagnostics_count`

Human output should include the same categories in concise form.

### 8.2 `lint`

`llmwiki lint --root .` should:

- fail if a source has `parser_backend_fallback_from="mineru"` but no failed MinerU attempt diagnostics;
- fail if parser snippets contain secret patterns;
- warn, not fail, for normal auto fallback with complete diagnostics;
- fail if declared parser artifact paths or selected content-list paths are missing;
- keep existing PDF locator and sidecar checks unchanged.

### 8.3 Staging And Review

For PDF add runs, `triage.md` and `review --detail` should show:

- selected parser backend;
- fallback source and reason;
- attempt count;
- each attempt backend and status;
- command source (`PATH`, `workspace_venv`, `configured_path`, etc.);
- return code or timeout;
- content-list discovery count;
- sanitized log snippets if present.

They must not dump raw content-list JSON, full parser logs, secrets, or environment variables.

## 9. Testing Strategy

Unit tests:

- `discover_mineru_command` finds configured absolute path.
- `discover_mineru_command` finds `mineru` on `PATH`.
- `discover_mineru_command` finds `.venv\Scripts\mineru.exe` when `PATH` does not include `.venv\Scripts`.
- POSIX `.venv/bin/mineru` discovery is covered with path fixtures.
- unknown/missing command returns `available=false` and safe warnings.
- `build_mineru_command` uses resolved command path.
- parser attempt diagnostics serialize without secrets.
- auto fallback metadata includes failed MinerU attempt plus succeeded pypdf attempt.
- old metadata without attempts still loads.

Integration tests:

- `llmwiki parsers status --root . --json` reports `schema_version="parser_status.v2.9.6"` and `mineru_command_source`.
- default auto PDF import uses workspace-local MinerU executable when present.
- fake MinerU failure in auto mode falls back to pypdf and preserves failed attempt diagnostics.
- fake MinerU failure in explicit `--parser mineru` fails without fallback.
- explicit `--parser pypdf` does not invoke MinerU.
- `lint` fails when fallback diagnostics are missing.
- `eval pdf-quality` reports attempt counters.
- `retrieve/query/ask` remain unaffected and still return only catalog-backed claims.

Real acceptance:

- Reuse the three PDFs from the V2.9.5 acceptance.
- Run from a non-activated shell with `.venv\Scripts\mineru.exe` installed.
- Confirm `parsers status` discovers workspace-local MinerU.
- Confirm the fallback case preserves failed command diagnostics.
- Confirm `lint` and `eval pdf-quality` pass.
- Confirm `eval retrieval` PDF foundation still passes.

## 10. Acceptance Criteria

V2.9.6 is accepted when:

- `llmwiki parsers status --root . --json` can find `.venv\Scripts\mineru.exe` without requiring an activated shell.
- auto parser add uses that resolved command path.
- auto fallback metadata includes failed MinerU command attempt diagnostics.
- explicit `--parser mineru` remains strict.
- explicit `--parser pypdf` does not invoke MinerU.
- `eval pdf-quality` reports parser attempt and command source metrics.
- `lint` detects missing fallback attempt diagnostics.
- no parser logs or errors leak API keys or `config/api-keys.toml` contents.
- all generated parser artifacts remain gitignored.
- all existing V2.9.5 parser backend tests continue to pass.
- real three-PDF acceptance passes with complete diagnostics.

## 11. Documentation Updates

README should explain:

- MinerU can be installed in the project `.venv`;
- `parsers status` checks `PATH` and workspace-local venv locations;
- users can still set `mineru_command` explicitly;
- auto fallback is expected and visible;
- complete fallback diagnostics are available in metadata, triage, lint, and pdf-quality eval.

AGENTS should add:

- parser command discovery is deterministic local environment logic, not LLM behavior;
- agents must preserve failed parser attempt diagnostics across fallback;
- agents must not mutate shell PATH, committed config, or secrets to make MinerU discoverable;
- parser attempt diagnostics remain audit data, not evidence.

## 12. Out Of Scope Follow-Ups

After V2.9.6, possible next work includes:

- wider 5-10 PDF acceptance with embeddings rebuilt;
- semantic PDF retrieval quality checks;
- richer table/formula/caption evidence contracts;
- more robust paper title extraction for pypdf fallback cases;
- planner quality improvements for empty `required_evidence` fields.
