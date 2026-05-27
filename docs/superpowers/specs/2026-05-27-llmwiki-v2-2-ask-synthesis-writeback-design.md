# LLMWiki V2.2: Evidence Ask And Synthesis Writeback

## 1. Background

V2.1 makes `llmwiki add <source> --root .` the normal source import entry. A source can now move through import, normalize, LLM ingest, staging, validation, apply, wiki page creation, and catalog updates through one user-facing command.

The next missing loop is use. After the wiki and catalog exist, the user should be able to ask a research question, receive an evidence-grounded LLM answer, and decide whether the useful result should become a durable synthesis page.

Target flow:

```text
user question
-> retrieve/query evidence from wiki + catalog
-> LLM answers only from retrieved evidence
-> user decides whether the answer is worth keeping
-> synthesis writeback goes through staging/apply
-> wiki/syntheses/*.md and catalog are updated
```

This phase turns LLMWiki from "can compile sources into a wiki" into "can answer against the compiled wiki and save good answers back into the wiki".

## 2. Goals

V2.2 adds an evidence-backed question answering workflow:

- Add a normal CLI entry for grounded answers:

```bash
llmwiki ask "问题" --root .
```

- Use existing `retrieve_context` as the evidence source.
- Call the configured LLM provider only after evidence is retrieved.
- Require answers to cite retrieved claim ids, source ids, and citation locators.
- Surface insufficient evidence, weak/uncited evidence, and contradictions instead of hiding uncertainty.
- Ask the user whether the answer should be written back as a synthesis page.
- When writing back, create a staging run and apply it through the existing safety path.
- Keep `retrieve` as the stable machine evidence API and keep `query` as a deterministic local context command.

## 3. Non-Goals

This phase does not implement:

- Web UI or Obsidian plugin.
- Vector database, embedding search, or reranking.
- MinerU, OCR, table extraction, or richer attachment parsing.
- Multi-turn chat memory.
- Web search or external live browsing.
- Automatic writeback for every answer.
- LLM direct writes to `wiki/`.
- Formal derived claims in the `claims` table as first-class source claims.
- Team sync, permissions, or cloud storage.

## 4. Command Model

### 4.1 `ask`

Primary command:

```bash
llmwiki ask "RAG 为什么需要引用锚点？" --root .
```

Default behavior:

```text
retrieve evidence
-> produce answer
-> print citations and warnings
-> ask whether to write back if running interactively
```

The default must be safe:

- If not running in an interactive terminal, `ask` must not write back unless `--writeback` is supplied.
- If evidence is empty, `ask` should not call the LLM by default; it should return an insufficient-evidence answer.
- If the LLM returns citations not present in retrieved evidence, the answer is invalid and must not be written back.

Useful flags:

```bash
llmwiki ask "问题" --root . --limit 8
llmwiki ask "问题" --root . --json
llmwiki ask "问题" --root . --writeback
llmwiki ask "问题" --root . --no-writeback
llmwiki ask "问题" --root . --source-id src_xxx
llmwiki ask "问题" --root . --page-type concept
llmwiki ask "问题" --root . --confidence cited
```

`--writeback` means the user has already approved writeback for this command invocation. It should still run staging validation and apply safety checks.

`--no-writeback` suppresses the interactive prompt and leaves the wiki unchanged.

### 4.2 `retrieve`

`retrieve` remains the stable evidence interface for external RAG systems, agents, and tests:

```bash
llmwiki retrieve "问题" --root . --json
llmwiki retrieve "问题" --root . --format prompt
```

V2.2 may improve retrieve warnings or output fields only in backward-compatible ways. Existing JSON keys must remain stable.

### 4.3 `query`

`query` remains a simple deterministic local command. It should not call the LLM. It may eventually become an alias for a human-readable retrieve output, but V2.2 should not rely on `query` for answer generation.

## 5. Public Output

Human-readable `ask` output should have this shape:

```text
Question: RAG 为什么需要引用锚点？

Answer:
RAG 需要引用锚点，因为后续回答必须能追溯到具体 source 和 locator...

Citations:
- clm_xxx src_abc line:12 wiki/concepts/rag.md
- clm_yyy src_def line:8 wiki/sources/src_def.md

Warnings:
- Contradictory evidence is present; answer keeps the conflict visible.

Writeback:
Not written. Run with --writeback or answer yes when prompted to create a synthesis page.
```

When writeback succeeds:

```text
Writeback:
Applied synthesis run: run_answer_xxx_...
Page:
- wiki/syntheses/rag-why-citation-anchors-matter.md
```

JSON output should be machine-readable and should not include secrets:

```json
{
  "question": "...",
  "answer": "...",
  "status": "answered",
  "citations": [
    {
      "claim_id": "clm_xxx",
      "source_id": "src_xxx",
      "citation_locator": "line:12",
      "page_path": "wiki/concepts/example.md"
    }
  ],
  "warnings": [],
  "writeback": {
    "status": "skipped",
    "run_id": null,
    "pages": []
  }
}
```

Allowed answer statuses:

- `answered`
- `insufficient_evidence`
- `llm_failed`
- `invalid_citations`
- `writeback_failed`

## 6. Internal Architecture

Add focused modules instead of expanding `cli.py`:

```text
llmwiki/answer.py
  answer_question(root, question, options) -> AskResult
  build_answer_prompt(...)
  validate_answer_citations(...)

llmwiki/synthesis.py
  create_synthesis_run(root, AskResult) -> SynthesisRunResult
  build_synthesis_patch(...)

llmwiki/cli.py
  cmd_ask(...)
```

The high-level ask pipeline:

```text
retrieve_context(root, question, filters)
-> if no cited evidence: return insufficient_evidence
-> create LLM provider from config/config.toml + config/api-keys.toml
-> ask LLM for structured grounded answer
-> validate all cited claim ids are in retrieved evidence
-> print answer
-> if confirmed writeback:
     create staging synthesis run
     apply_run(root, run_id)
     print applied synthesis page
```

`answer_question` should be read-only unless writeback is explicitly requested. The LLM answer itself must not write files.

## 7. Answer Contract

The LLM should be asked for structured JSON, then the project validates it.

Expected answer object:

```json
{
  "short_answer": "...",
  "analysis": "...",
  "citations": [
    {
      "claim_id": "clm_xxx",
      "source_id": "src_xxx",
      "citation_locator": "line:12"
    }
  ],
  "uncertainties": ["..."],
  "conflicts": ["..."],
  "suggested_title": "..."
}
```

Validation rules:

- Every cited `claim_id` must exist in the retrieved contexts.
- The cited `source_id` and `citation_locator` must match the retrieved context for that claim.
- At least one cited claim is required for `status=answered`.
- If retrieved warnings mention weak/uncited evidence, the answer must include uncertainty or warnings.
- If retrieved relationships include `contradicts`, the answer must mention the conflict instead of silently choosing a winner.
- If validation fails, do not write back.

The LLM may summarize and reason over evidence, but it may not introduce uncited factual conclusions as settled facts.

## 8. Synthesis Writeback

Writeback creates a `synthesis` page. It is not a new source import and should not create a fake raw source file.

Staging run shape:

```text
staging/<run-id>/
  run.json
  claims.jsonl
  triage.md
  patches/
    001-synthesis-<slug>.json
```

`claims.jsonl` may be empty in V2.2. The synthesis page should reuse existing evidence claim ids from the catalog instead of inventing new formal claims. This keeps source-backed claims separate from user-approved analysis pages.

`run.json` should include:

```json
{
  "run_id": "run_answer_xxx_...",
  "run_type": "synthesis_writeback",
  "trigger": "ask",
  "status": "staged",
  "question": "...",
  "answer_status": "answered",
  "evidence_claim_ids": ["clm_xxx"],
  "proposal_engine": "llm",
  "provider": "openai",
  "model": "deepseek-v4-pro"
}
```

Because the current catalog has `ingest_runs.source_id` as a required compatibility field, V2.2 should use a synthetic run source id such as `synthesis:<answer-id>` when `apply_run` records the run. This value must not be treated as a real source in `sources`.

The synthesis patch must target only:

```text
wiki/syntheses/<slug>.md
```

The patch should include:

```json
{
  "source_id": "synthesis:<answer-id>"
}
```

This is a catalog compatibility value for the applied run record, not a real imported source id.

The page must satisfy the existing `synthesis` page requirements:

```text
---
page_type: synthesis
title: "..."
aliases: []
source_count: N
claim_ids: ["clm_xxx", "clm_yyy"]
updated_at: "..."
---

# ...

## Question/Topic
## Short Answer
## Evidence
## Analysis
## Uncertainties
## Related Pages
```

The synthesis page should include:

- Original user question.
- Short answer.
- Evidence list with claim id, source id, locator, and page path.
- Analysis grounded in evidence.
- Uncertainties and conflicts.
- Related source/concept/entity pages.

Writeback must call `apply_run`. It must not write `wiki/syntheses/*.md`, `wiki/index.md`, `wiki/log.md`, or `state/catalog.sqlite` directly.

## 9. Safety And Failure Behavior

### No Evidence

If retrieval returns no contexts:

- Return `status=insufficient_evidence`.
- Do not call the LLM by default.
- Do not prompt for writeback.
- Suggest adding more sources.

### Weak Or Uncited Evidence

If retrieval contains weak/uncited evidence:

- Keep warnings visible.
- The answer may explain what weak evidence suggests.
- The answer must not present weak/uncited material as a formal conclusion.
- Writeback should be refused unless at least one cited claim supports the synthesis.

### Contradictions

If retrieved relationships include `contradicts`:

- The answer must expose the disagreement.
- The synthesis page must include it in `## Uncertainties`.
- The system must not choose a winner unless the evidence itself supports that conclusion.

### Invalid LLM Output

If the LLM returns malformed JSON, missing citations, or citations outside the retrieved evidence:

- Return `status=invalid_citations` or `llm_failed`.
- Do not write back.
- Do not leak prompt text containing API keys or config secrets.

### Writeback Failure

If synthesis staging or apply fails:

- Preserve the answer in CLI output.
- Mark the staging run failed when a run exists.
- Let existing apply rollback restore wiki/index/log/catalog state.
- Print a debug command:

```bash
llmwiki review <run-id> --detail --root .
```

## 10. Data And Catalog Behavior

V2.2 should avoid schema churn unless implementation proves it necessary.

Required behavior without new tables:

- Synthesis pages are registered in `pages` with `page_type=synthesis`.
- Synthesis page aliases are indexed in `aliases`.
- Synthesis page links are stored in `links`.
- Existing claim ids remain the evidence anchors for synthesis pages.
- `relationships` may add `supports` or `refines` records from synthesis page ids to evidence claim ids or related page ids, as long as retrieval can still expose contradictions.
- `ingest_runs` may record the applied synthesis run with a synthetic `source_id` compatibility value.

Do not create new `claims` rows for synthesized conclusions in V2.2. A later phase may add explicit derived-claim provenance, but this phase should keep the distinction clear:

```text
claims = source-backed facts
syntheses = user-approved analysis grounded in existing claims
```

## 11. CLI Help And Documentation

`llmwiki --help` should include:

```text
ask       Answer a question using local wiki evidence and the configured LLM.
```

README should describe the normal V2.2 flow:

```bash
llmwiki add docs/example.md --root .
llmwiki ask "问题" --root .
```

Advanced/debug docs should keep:

- `retrieve` for machine evidence.
- `query` for deterministic context.
- `review/apply` for inspecting failed or staged writeback runs.
- `lint` as an explicit maintenance command, not part of default ask.

AGENTS.md should be updated to say:

- `ask` may call the configured LLM.
- `ask` must only answer from retrieved local evidence.
- synthesis writeback must go through staging/apply.
- weak/uncited and contradicting evidence must remain visible.

## 12. Tests

Add tests before implementation:

- `ask` with no matching evidence returns `insufficient_evidence` and does not call the LLM.
- `ask` retrieves evidence, calls a monkeypatched provider, validates citations, and prints an answer.
- `ask --json` returns stable JSON without secrets.
- LLM citations outside retrieved evidence produce `invalid_citations` and no writeback.
- Contradictory evidence appears in answer warnings and synthesis uncertainties.
- `ask --writeback` creates a staging run, applies a synthesis page, updates `wiki/index.md`, `wiki/log.md`, and catalog pages.
- Non-interactive `ask` without `--writeback` does not write wiki files.
- Writeback apply failure marks run failed and does not leave partial wiki/catalog mutations.
- `retrieve` existing JSON tests continue to pass.
- `query` remains deterministic and does not call the LLM.

Do not add a production mock provider or no-network public path. Tests may monkeypatch provider construction at test boundaries.

## 13. Acceptance Criteria

V2.2 is complete when:

- `llmwiki ask "问题" --root .` answers from local wiki/catalog evidence.
- Answers include citations traceable to retrieved claim ids, source ids, and locators.
- The command refuses to answer as fact when evidence is absent or invalid.
- The command exposes retrieval warnings and contradictions.
- The user can approve writeback through `--writeback` or an interactive yes/no prompt.
- Writeback creates a valid `wiki/syntheses/*.md` page through staging/apply.
- Synthesis pages appear in `wiki/index.md` and catalog `pages`.
- API keys and local config secrets never appear in answer output, staging artifacts, tests, docs, or logs.
- Full pytest passes.

## 14. Implementation Defaults For The Plan

These choices are not product blockers. The implementation plan should adopt these defaults unless a test exposes a stronger reason to change them:

- Interactive confirmation should use a small injectable confirmation helper so tests can avoid stdin.
- Answer artifacts should not be saved when writeback is skipped. No approved writeback means no durable side effect.
- Synthesis slugs should use the sanitized LLM suggested title, with a question hash fallback.
- Invalid LLM JSON should retry once with a stricter repair prompt, then fail safe.
- Relationships should start with page links and existing claim ids. Add richer synthesis relationships only where tests prove value.
