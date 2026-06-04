# LLM Wiki V1 CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first usable local-first LLM Wiki CLI with immutable raw source import, normalized sources, SQLite catalog, staging review/apply, query, lint, doctor, docs, and regression samples.

**Architecture:** Keep the implementation small and stdlib-first. Split the CLI into focused modules for database schema, workspace files, source import/normalization, staged ingest, patch application, querying, and linting. Treat Markdown files as the durable wiki surface and SQLite as a rebuildable index/audit cache.

**Tech Stack:** Python 3.10+, argparse, sqlite3, pathlib, hashlib, json, urllib, unittest/pytest-compatible tests.

---

### Task 1: Schema And Workspace Init

**Files:**
- Create: `llmwiki/db.py`
- Modify: `llmwiki/workspace.py`
- Modify: `llmwiki/cli.py`
- Test: `tests/test_init_schema.py`

- [ ] **Step 1: Write the failing test**

```python
def test_init_creates_schema_and_required_files(tmp_path):
    rc = main(["init", "--root", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "state" / "catalog.sqlite").exists()
    tables = table_names(tmp_path / "state" / "catalog.sqlite")
    assert {"sources", "claims", "aliases", "pages", "links", "relationships", "ingest_runs"}.issubset(tables)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_init_schema.py -q`
Expected: FAIL because `init --root` and schema creation are not implemented.

- [ ] **Step 3: Write minimal implementation**

Create schema helpers in `llmwiki/db.py`; make `init_workspace(root)` create required directories, `config.toml`, `AGENTS.md`, `wiki/index.md`, `wiki/log.md`, and call `init_db(root / "state/catalog.sqlite")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_init_schema.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add llmwiki/db.py llmwiki/workspace.py llmwiki/cli.py tests/test_init_schema.py && git commit -m "feat(init): initialize workspace schema" -m "Adds init workspace creation and SQLite schema. Verification: pytest tests/test_init_schema.py -q. Limitations: source ingest behavior remains separate."`

### Task 2: Source Add And Normalization

**Files:**
- Create: `llmwiki/sources.py`
- Modify: `llmwiki/cli.py`
- Test: `tests/test_add_source.py`

- [ ] **Step 1: Write the failing test**

```python
def test_add_markdown_imports_raw_normalized_and_deduplicates(tmp_path):
    main(["init", "--root", str(tmp_path)])
    source = tmp_path / "sample.md"
    source.write_text("# Alpha\n\nAlpha supports retrieval.\n", encoding="utf-8")
    assert main(["add", str(source), "--root", str(tmp_path)]) == 0
    assert main(["add", str(source), "--root", str(tmp_path)]) == 0
    rows = fetch_rows(tmp_path / "state" / "catalog.sqlite", "select source_id, raw_path, normalized_path from sources")
    assert len(rows) == 1
    assert (tmp_path / rows[0]["raw_path"]).exists()
    assert "line:3" in (tmp_path / rows[0]["normalized_path"]).read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_add_source.py -q`
Expected: FAIL because `add` is still scaffold-only.

- [ ] **Step 3: Write minimal implementation**

Copy files into `sources/raw/<source_id>-<name>`, create `sources/normalized/<source_id>.md` with source metadata and line anchors, calculate SHA-256, and insert one source row unless that hash already exists.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_add_source.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add llmwiki/sources.py llmwiki/cli.py tests/test_add_source.py && git commit -m "feat(add): import and normalize sources" -m "Adds Markdown/text/web source import with hash dedupe and normalized line anchors. Verification: pytest tests/test_add_source.py -q. Limitations: scanned PDF OCR is intentionally unsupported."`

### Task 3: Claim-First Staging

**Files:**
- Create: `llmwiki/ingest.py`
- Modify: `llmwiki/cli.py`
- Test: `tests/test_ingest_review.py`

- [ ] **Step 1: Write the failing test**

```python
def test_ingest_writes_only_staging(tmp_path):
    source_id = add_sample_source(tmp_path)
    before = snapshot_tree(tmp_path / "wiki")
    assert main(["ingest", source_id, "--root", str(tmp_path)]) == 0
    after = snapshot_tree(tmp_path / "wiki")
    assert after == before
    run_dir = next((tmp_path / "staging").iterdir())
    assert (run_dir / "claims.jsonl").exists()
    assert (run_dir / "triage.md").exists()
    assert list((run_dir / "patches").glob("*.json"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_review.py -q`
Expected: FAIL because staging generation does not exist.

- [ ] **Step 3: Write minimal implementation**

Extract simple claims from normalized non-heading lines, assign citation locators from line anchors, run identity resolution against `pages` and `aliases`, emit `claims.jsonl`, `triage.md`, and safe JSON patch files under `staging/<run-id>/patches/`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_review.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add llmwiki/ingest.py llmwiki/cli.py tests/test_ingest_review.py && git commit -m "feat(ingest): stage claim-first wiki patches" -m "Adds claim extraction, triage, duplicate/conflict candidates, and staging-only patches. Verification: pytest tests/test_ingest_review.py -q. Limitations: extraction is deterministic heuristic, not an external LLM call."`

### Task 4: Safe Apply, Index, Log, Catalog Sync

**Files:**
- Create: `llmwiki/apply.py`
- Modify: `llmwiki/cli.py`
- Test: `tests/test_apply_workflow.py`

- [ ] **Step 1: Write the failing test**

```python
def test_apply_updates_wiki_index_log_and_catalog(tmp_path):
    run_id = create_staged_sample(tmp_path)
    assert main(["apply", run_id, "--root", str(tmp_path)]) == 0
    assert (tmp_path / "wiki" / "sources").glob("*.md")
    assert "Applied ingest run" in (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
    pages = fetch_rows(tmp_path / "state" / "catalog.sqlite", "select path from pages")
    claims = fetch_rows(tmp_path / "state" / "catalog.sqlite", "select claim_text, citation_locator from claims")
    assert pages and claims
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_apply_workflow.py -q`
Expected: FAIL because apply is scaffold-only.

- [ ] **Step 3: Write minimal implementation**

Validate each patch path stays under `wiki/`, reject deletes and raw paths, write/merge Markdown pages, rebuild `wiki/index.md`, append to `wiki/log.md`, insert claims/pages/aliases/links/relationships, and mark the run applied.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_apply_workflow.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add llmwiki/apply.py llmwiki/cli.py tests/test_apply_workflow.py && git commit -m "feat(apply): apply staged wiki patches safely" -m "Adds safe patch application, wiki index/log updates, and catalog synchronization. Verification: pytest tests/test_apply_workflow.py -q. Limitations: patch format is first-party JSON, not arbitrary unified diff."`

### Task 5: Query, Lint, Doctor, Docs, Samples

**Files:**
- Create: `llmwiki/query.py`
- Create: `llmwiki/lint.py`
- Modify: `llmwiki/workspace.py`
- Modify: `llmwiki/cli.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Create: `tests/fixtures/minimal_source.md`
- Create: `tests/fixtures/regression_alias.md`
- Create: `tests/fixtures/regression_entity.md`
- Create: `tests/fixtures/regression_conflict.md`
- Test: `tests/test_query_lint_doctor.py`
- Test: `tests/test_regression_samples.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_query_returns_retrieval_context_with_citation(tmp_path):
    run_full_sample_flow(tmp_path)
    out = run_cli_capture(["query", "retrieval", "--root", str(tmp_path)])
    assert "Retrieval context" in out
    assert "source_id=" in out and "line:" in out

def test_lint_detects_duplicate_alias_and_contradiction_relationship(tmp_path):
    run_regression_flow(tmp_path)
    out = run_cli_capture(["lint", "--root", str(tmp_path)])
    assert "duplicate alias" in out
    assert "contradicts" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_query_lint_doctor.py tests/test_regression_samples.py -q`
Expected: FAIL because query/lint/docs/samples are incomplete.

- [ ] **Step 3: Write minimal implementation**

Implement SQLite FTS-backed search where available, fallback `LIKE` search, wiki link checks, duplicate alias checks, uncited claim checks, source hash drift checks, contradiction reporting, and richer `doctor` schema checks. Add README usage and regression fixtures.

- [ ] **Step 4: Run all tests and sample workflow**

Run: `pytest -q`
Run: `python -m llmwiki init --root .`
Run: `python -m llmwiki add tests/fixtures/minimal_source.md --root .`
Run: `python -m llmwiki ingest <source-id> --root .`
Run: `python -m llmwiki review <run-id> --root .`
Run: `python -m llmwiki apply <run-id> --root .`
Run: `python -m llmwiki query "retrieval" --root .`
Run: `python -m llmwiki lint --root .`
Run: `python -m llmwiki doctor --root .`
Expected: all tests pass and commands exit 0 or print documented lint warnings for intentional regression data.

- [ ] **Step 5: Commit**

Run: `git add llmwiki/query.py llmwiki/lint.py llmwiki/workspace.py llmwiki/cli.py README.md AGENTS.md tests/fixtures tests/test_query_lint_doctor.py tests/test_regression_samples.py && git commit -m "feat(cli): add query lint doctor docs and samples" -m "Adds retrieval, lint checks, richer doctor, docs, and sample/regression fixtures. Verification: pytest -q plus full init/add/ingest/review/apply/query/lint/doctor sample flow. Limitations: first version uses deterministic local heuristics and no external LLM API."`
