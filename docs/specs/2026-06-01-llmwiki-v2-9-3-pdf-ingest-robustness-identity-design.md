# LLMWiki V2.9.3: PDF Ingest Robustness And Paper Identity Refinement

## 1. Background

V2.9.2 made text-PDF import measurable and cleaner:

- PDF sidecars now use V2.9.2 metadata/block/chunk schemas;
- repeated headers, footers, page numbers, and parser-created aliases are filtered from claim extraction;
- PDF quality eval reports 20/20 local PDFs with complete sidecars, valid block locators, and no parser-created duplicate aliases;
- retrieval eval for the PDF foundation dataset passes 4/4.

The real 20-paper acceptance still exposed two non-parser issues:

- 2 PDFs failed on first `llmwiki add` because the LLM returned malformed JSON, then succeeded on retry;
- lint found one non-parser duplicate alias caused by source/entity identity collision around a paper-introduced artifact name.

V2.9.3 is a narrow robustness and identity slice. It should make the existing PDF pipeline less brittle before the project moves to MinerU, OCR, tables, figures, formulas, and richer document structure.

## 2. Goals

V2.9.3 must:

- add one safe repair/retry path for malformed JSON from PDF chunk extraction and PDF consolidation calls;
- preserve strict schema validation after repair;
- avoid logging or committing raw malformed LLM responses;
- record repair diagnostics in staging artifacts without exposing secrets or excessive prompt/source text;
- make first-pass PDF `add` resilient to transient LLM formatting errors;
- reduce source/entity/concept alias collisions caused by paper-introduced artifact names;
- keep PDF source titles searchable without inserting noisy source title aliases into the formal alias table;
- make lint distinguish parser-created aliases, expected paper-artifact identity overlap, and true duplicate aliases;
- keep `retrieve/query/eval retrieval/eval pdf-quality` local and deterministic.

## 3. Non-Goals

V2.9.3 does not implement:

- MinerU integration;
- OCR for scanned PDFs;
- table structure extraction;
- figure extraction or caption OCR;
- equation object extraction;
- external metadata lookup from arXiv, Crossref, Semantic Scholar, or other services;
- new SQLite tables;
- new `page_type="paper"`;
- LLM relationship classification;
- semantic claim merging;
- new retrievers, vector-store changes, or reranker changes;
- automatic merging of concept and entity pages.

## 4. Design Principles

### 4.1 Repair Formatting, Not Meaning

The JSON repair path is only allowed to repair syntax and shape.

It must not ask the LLM to reinterpret the source, add new claims, enrich evidence, rewrite citations, or make new paper-identity decisions. The repair prompt should say:

- the previous response was invalid JSON;
- return the same information as valid JSON;
- do not add new facts;
- preserve claim text and citation locators;
- conform to the expected JSON object shape.

After repair, existing validation still applies:

- chunk claims need valid block locators;
- PDF consolidation must not add formal claims;
- invalid or unknown block ids are rejected or downgraded exactly as before;
- no weak/uncited claim becomes formal evidence.

### 4.2 Retry Once

Each LLM response may get at most one JSON repair attempt.

The pipeline must not loop indefinitely, silently retry until success, or hide systemic provider failures. If repair also fails, the add pipeline fails with a safe error that includes:

- stage: `ingest`;
- source_id;
- run_id if one exists;
- response kind: `chunk` or `consolidation`;
- chunk_id when applicable;
- sanitized parse error.

It must not include:

- API keys;
- `config/api-keys.toml` contents;
- full source text;
- full raw malformed response;
- full prompt.

### 4.3 Diagnostics Are Small And Auditable

Staging artifacts should record repair facts, not raw sensitive payloads.

`llm-proposal.json` and `run.json` should be able to report:

```json
{
  "llm_json_repair_count": 1,
  "llm_json_repair_failed_count": 0,
  "llm_json_repair_events": [
    {
      "response_kind": "chunk",
      "chunk_id": "src_xxx_c0012",
      "error": "Expecting ',' delimiter",
      "repaired": true
    }
  ]
}
```

The event should not contain raw response content. A short sanitized error message is enough.

### 4.4 Paper Source Identity Is Not The Same As Artifact Identity

A paper source page, a concept page, and an entity page can naturally share a name. For example:

- source page title: `GTA1: GUI Test-time Scaling Agent`;
- entity page title: `GTA1`;
- concept page title: `GUI Test-time Scaling Agent`.

The source page title should remain searchable through the source title and page title fields. It does not need to be inserted as a formal alias that competes with concept/entity aliases.

For PDF source pages, V2.9.3 should prefer source-page aliases like:

```yaml
aliases: ["src_xxx"]
```

instead of:

```yaml
aliases: ["GTA1: GUI Test-time Scaling Agent", "src_xxx"]
```

The formal page title still remains:

```yaml
title: "GTA1: GUI Test-time Scaling Agent"
```

Retrieval must continue to search source titles and page titles, so removing the source title from aliases must not reduce source-title retrieval.

### 4.5 Identity Warnings Beat Silent Pollution

If the LLM proposes concept/entity aliases that collide with PDF source titles or with each other, the system should surface an identity warning in triage rather than silently creating noisy aliases.

The warning should be specific:

```text
Identity warning: alias `GTA1: GUI Test-time Scaling Agent` overlaps source title and entity `GTA1`.
```

This is not a contradiction. It should not create a `contradicts` relationship.

## 5. User-Facing Behavior

### 5.1 Robust PDF Add

Command remains:

```powershell
llmwiki add docs/papers/2503.15661.pdf --root .
```

Expected behavior:

- if a chunk response is malformed JSON, the system tries one repair call;
- if repair succeeds, add continues normally;
- if repair fails, add fails safely and reports stage/source/run/debug command;
- `triage.md` and `llm-proposal.json` record repair counts and sanitized events.

Example output after a successful repair may include:

```text
Warnings:
- LLM JSON repair was used for 1 PDF chunk response.
```

The warning should be visible but should not make the run unsafe if all repaired claims validate.

### 5.2 Review Repair Diagnostics

`llmwiki review <run-id> --detail --root .` should expose a small diagnostics section:

```text
LLM JSON repair:
- repairs: 1
- failures: 0
- chunk: src_xxx_c0012, repaired=true, error=Expecting ',' delimiter
```

It should not print the full malformed response.

### 5.3 Lint Paper Identity

`llmwiki lint --root .` should not fail only because a PDF source title and an introduced artifact entity have related names, as long as the source title is not stored as a duplicate formal alias.

It should still fail for:

- source title aliases inserted into formal aliases when they collide with concept/entity aliases;
- parser-created aliases such as `page1`;
- unrelated aliases mapped to unrelated pages;
- exact duplicate aliases that cannot be explained as source/page title identity.

### 5.4 PDF Quality Eval

`llmwiki eval pdf-quality --root . --json` should add identity robustness counters:

```json
{
  "paper_identity_collision_count": 0,
  "source_title_alias_collision_count": 0,
  "llm_json_repair_observed_count": 0
}
```

The eval remains read-only and no-LLM.

## 6. Data Flow

### 6.1 PDF Chunk Extraction

```text
chunk evidence
  -> provider.complete(chunk prompt)
  -> parse JSON
  -> if parse fails: repair once
  -> parse repaired JSON
  -> normalize payload
  -> validate block locators
  -> merge cited claims
```

The repair step receives only:

- response kind;
- expected JSON shape;
- sanitized parse error;
- malformed response content if needed for repair, but never written to logs or staging.

The repair step must not receive unrelated chunks or full source text.

### 6.2 PDF Consolidation

```text
chunk summaries
  -> provider.complete(consolidation prompt)
  -> parse JSON
  -> if parse fails: repair once
  -> parse repaired JSON
  -> force claims=[]
  -> normalize source summary / concept / entity / duplicate candidates
```

Even if the repaired consolidation returns claims, they must be ignored as in V2.9.1/V2.9.2.

### 6.3 Alias Application

```text
PDF source page
  -> title remains paper title
  -> aliases exclude paper title by default
  -> aliases include source_id

LLM concept/entity proposal
  -> parser-created aliases removed
  -> source-title collisions produce identity warnings
  -> valid short artifact aliases may remain
```

## 7. Interfaces

### 7.1 LLM JSON Repair Helpers

Add or extend helpers in `llmwiki/llm_ingest.py`:

```python
@dataclass(frozen=True)
class LLMJsonRepairEvent:
    response_kind: str
    chunk_id: str | None
    error: str
    repaired: bool

def parse_llm_json_with_repair(
    provider,
    *,
    content: str,
    schema: dict[str, object],
    response_kind: str,
    chunk_id: str | None = None,
) -> tuple[dict[str, object], list[LLMJsonRepairEvent], dict[str, object]]:
    ...
```

The exact signature can change during implementation, but the behavior must remain:

- parse normally first;
- repair once on parse failure;
- aggregate usage from repair call;
- return sanitized repair events.

### 7.2 Proposal Diagnostics

`LLMIngestProposal` may gain:

```python
repair_events: list[dict[str, object]]
```

`llm-proposal.json` should include repair diagnostics in a compact form.

### 7.3 Source Page Alias Policy

`render_source_page(...)` or patch construction should support a source-type-aware alias list:

```python
def source_page_aliases(source: dict[str, str]) -> list[str]:
    if source["source_type"] == "pdf":
        return [source["source_id"]]
    return [source["title"], source["source_id"]]
```

This keeps older Markdown/text behavior unchanged while preventing PDF source-title aliases from competing with artifact aliases.

### 7.4 Identity Diagnostics

Add a deterministic identity diagnostic helper around PDF source/concept/entity proposals:

```python
def pdf_identity_warnings(source, concept_title, concept_aliases, entity) -> list[str]:
    ...
```

It should detect:

- alias equal to source title;
- alias equal to parser-created alias;
- concept and entity sharing normalized alias without clear type distinction;
- source title duplicated as formal alias.

It should not make domain-specific judgments about whether a term is a benchmark, model, dataset, or method.

## 8. Acceptance Criteria

### 8.1 Unit And Integration

- Malformed chunk JSON triggers one repair call and then succeeds when repaired JSON is valid.
- Malformed consolidation JSON triggers one repair call and then succeeds when repaired JSON is valid.
- Repair failure returns a safe ingest error without leaking secrets or raw prompt/source text.
- Repair usage is aggregated into proposal usage.
- `llm-proposal.json`, `run.json`, and `review --detail` expose repair counts/events.
- Repaired chunk claims still require valid page/block locators.
- Repaired consolidation cannot create formal claims.
- PDF source page aliases do not include the paper title by default.
- Markdown/text source page aliases remain unchanged.
- PDF source title remains searchable through source title/page title retrieval.
- Lint no longer fails for the V2.9.2 acceptance source/entity collision if the source title is not stored as a formal alias.

### 8.2 Real 20-Paper Acceptance

On the 20 local PDFs:

- first-pass `llmwiki add` should complete 20/20, or any JSON repair should be recorded and then complete without manual rerun;
- `llmwiki lint` should not fail due to PDF source-title/entity alias collision;
- `llmwiki eval pdf-quality --json` should keep:
  - title_pass_rate: 1.0
  - sidecar_completeness: 1.0
  - block_locator_validity: 1.0
  - parser_created_duplicate_alias_count: 0
- `llmwiki eval retrieval --dataset tests/evals/retrieval_v2_9_1_pdf_foundation.jsonl` should still pass 4/4.

## 9. Test Plan

Add tests for:

- chunk JSON repair success;
- chunk JSON repair failure;
- consolidation JSON repair success;
- consolidation JSON repair failure;
- repair diagnostics in `llm-proposal.json` and `review --detail`;
- source page alias policy for PDF vs Markdown/text;
- PDF source title retrieval after removing source title from formal aliases;
- lint behavior for source/entity identity overlap;
- `eval pdf-quality` identity counters;
- regression that `retrieve/query/eval retrieval/eval pdf-quality` do not call chat LLM.

## 10. Risks

- Repair prompts may hide a real provider regression if used too broadly. Mitigation: one retry only and visible diagnostics.
- Removing PDF source title aliases could reduce retrieval if title retrieval relies only on aliases. Mitigation: retrieval already uses `sources.title` and `pages.title`; add regression tests.
- Identity warnings can become noisy. Mitigation: keep them deterministic, short, and focused on exact normalized alias overlap.
- Real 20-paper acceptance still costs LLM tokens. Mitigation: tests use monkeypatch providers; real acceptance remains a final/manual verification step.

## 11. Out Of Scope For Next Plan

Do not include these in the V2.9.3 implementation plan:

- MinerU;
- OCR;
- table/figure/equation structured extraction;
- paper/method/benchmark page types;
- external metadata services;
- semantic identity classification;
- automatic page merge.

Those should move to a later rich parsing or knowledge-modeling version after the current PDF ingest path is robust.
