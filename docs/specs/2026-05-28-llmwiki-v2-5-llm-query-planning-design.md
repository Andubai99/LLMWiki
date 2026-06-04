# LLMWiki V2.5: LLM Query Planning

## 1. Background

V2.4 introduced a hybrid local retrieval baseline: Unicode-aware query analysis, BM25/FTS, catalog title/alias retrieval, graph expansion, exact formula/symbol matching, RRF fusion, and `query` reuse of `retrieve`.

That improved natural Chinese lookup questions, but it still exposes a structural limitation: some questions require understanding the user's intent before retrieval can be shaped correctly. For example:

```text
这五种水果里哪种更适合补充维生素 C？
```

The local retriever can find many relevant claims, but it does not reliably understand that the question needs comparison across multiple fruit sources and evidence about a shared attribute. Continuing to fix this with keyword lists, domain-specific boosts, or phrase rules would make the system brittle. LLMWiki is meant to work on unknown research domains, not only fruit notes.

V2.5 adds an LLM query planning layer for `ask`. The planner may understand the question, decompose it, and propose retrieval subqueries. It must not create evidence. Every answer citation must still come from local `wiki + catalog` retrieval.

## 2. Goal

V2.5 makes `ask` capable of using an LLM to plan retrieval before grounded answer generation.

It adds:

- A structured query planning layer.
- A planner JSON contract.
- Validation that planner output cannot forge claims, sources, pages, or citations.
- Execution of planner subqueries through the existing local `retrieve_context` API.
- Aggregation of retrieved evidence across subqueries.
- Planner diagnostics in `ask --json`.
- Regression coverage for comparison questions and weak local recall cases.

V2.5 is successful when complex natural questions can be decomposed into useful local retrieval requests, while the evidence contract remains unchanged: final citations must be retrieved local catalog claims.

## 3. Non-Goals

V2.5 does not implement:

- Rule-based intent classifiers.
- Domain-specific term boosting such as special handling for fruit, nutrition, vitamins, storage, or medical words.
- LLM-generated evidence.
- LLM direct retrieval from raw files outside the catalog.
- Changes to `retrieve` default behavior; `retrieve` remains local and deterministic.
- Changes to `query`; `query` remains a human-readable local retrieve output.
- Embeddings or vector store.
- Reranking or model-based evidence selection.
- Rich source parsing, OCR, MinerU, table extraction, or formula extraction from attachments.
- Multi-turn chat memory.
- Web search.

Those belong to later phases, especially V2.6 for embeddings and V2.7 for reranking/evidence selection.

## 4. Design Principles

### 4.1 No Domain Rules

The planner must not be replaced by hard-coded rules such as:

- If the question contains `哪种`, treat it as a comparison.
- If the question contains `维生素 C`, boost nutrition claims.
- If the question contains `保存`, expand to a fixed storage vocabulary.

V2.5 should rely on the configured LLM to infer intent and produce a structured plan. Code may enforce schema, limits, safety, and evidence-contract validation, but it should not encode content-domain semantics.

### 4.2 Planner Output Is Not Evidence

The planner may produce:

- intent,
- entities,
- concepts,
- attributes,
- subqueries,
- suggested filters,
- required evidence descriptions,
- uncertainty notes.

The planner must not produce accepted evidence. It cannot invent or validate claim ids, source ids, citation locators, page paths, scores, or relationships. Those can only come from local retrieval results.

### 4.3 `retrieve` Stays Local

`llmwiki retrieve` must remain deterministic and local by default. External systems that depend on reproducible local retrieval should not suddenly call an LLM.

LLM planning is introduced through `ask`, because `ask` already calls the configured LLM for grounded answer generation.

### 4.4 Plan Every `ask` By Default

V2.5 should not use a rule to decide whether a question is "complex enough" for planning. Inside `ask`, the default flow should be planner-first:

```text
question
-> LLM planner creates query plan
-> local retrieve executes each subquery
-> evidence is merged and validated
-> LLM answer is generated from retrieved evidence
-> optional synthesis writeback still goes through staging/apply
```

If the planner fails schema validation after one repair attempt, `ask` should fail safely with a planning status instead of silently inventing a rule-based fallback.

### 4.5 Keep Evidence Traceable

The answer prompt must only receive retrieved contexts. It may include the query plan as planning metadata, but the answer must cite retrieved claim ids, source ids, and citation locators.

## 5. Public Behavior

### 5.1 `ask`

Existing command:

```bash
llmwiki ask "这五种水果里哪种更适合补充维生素 C？" --root .
```

V2.5 expected flow:

```text
Plan:
- identify that the user asks for a comparison across available fruit sources
- produce subqueries for vitamin C evidence across the relevant fruits
- state that answer needs comparative evidence

Retrieve:
- run local retrieve for each subquery
- merge contexts by claim id
- preserve source ids, citation locators, page paths, relationships, and warnings

Answer:
- generate an answer only from retrieved contexts
- cite retrieved evidence
- expose uncertainty if coverage is incomplete
```

Human output should continue to show:

```text
Question:
Answer:
Citations:
Warnings:
Writeback:
```

It may add a compact planning section when useful:

```text
Planning:
- subqueries: 5
- evidence contexts: 12
- coverage: partial
```

### 5.2 `ask --json`

JSON output should remain backward compatible with V2.2 fields:

```json
{
  "question": "...",
  "answer": "...",
  "status": "answered",
  "citations": [],
  "warnings": [],
  "writeback": {}
}
```

V2.5 may add:

```json
{
  "planning": {
    "schema_version": "query_plan.v2.5",
    "status": "planned",
    "intent": "compare",
    "subquery_count": 5,
    "retrieved_context_count": 12,
    "coverage_notes": ["..."],
    "warnings": []
  }
}
```

Raw prompts and API keys must not appear in JSON output.

### 5.3 `retrieve`

No public behavior change:

```bash
llmwiki retrieve "问题" --root . --json
```

It must not call the LLM.

### 5.4 `query`

No public behavior change:

```bash
llmwiki query "问题" --root .
```

It must not call the LLM.

## 6. Planner Contract

### 6.1 Planner Input

The planner prompt should receive only safe, bounded local metadata:

- user question,
- optional retrieve filters from CLI,
- small catalog overview:
  - source ids and titles,
  - page ids, titles, page types,
  - aliases,
  - known relationship types,
- output schema,
- safety rules.

It must not receive:

- API keys,
- `config/api-keys.toml` contents,
- raw full source files,
- entire wiki pages by default,
- previous private prompts,
- unrelated local files.

The catalog overview is not evidence; it only helps the planner form local subqueries and avoid impossible source/page filters.

### 6.2 Planner Output Schema

The planner must output JSON:

```json
{
  "schema_version": "query_plan.v2.5",
  "intent": "lookup | compare | explain | summarize | verify | unknown",
  "question_summary": "short restatement",
  "entities": [
    {
      "text": "橙子",
      "role": "candidate_subject",
      "catalog_refs": ["concept:橙子"]
    }
  ],
  "concepts": [
    {
      "text": "维生素 C",
      "role": "attribute",
      "catalog_refs": []
    }
  ],
  "subqueries": [
    {
      "query": "橙子 维生素 C",
      "purpose": "find source-backed evidence about orange vitamin C",
      "filters": {
        "source_id": null,
        "page_type": null,
        "confidence": "cited"
      },
      "required": true
    }
  ],
  "required_evidence": [
    {
      "description": "Evidence about vitamin C for each candidate fruit when available.",
      "coverage": "per_entity"
    }
  ],
  "uncertainties": [],
  "warnings": []
}
```

Allowed `intent` values are an interface contract, not a rule engine. The answer layer may display them and use them for diagnostics. V2.5 should not hard-code content-specific behavior based on these values.

### 6.3 Validation

Planner output must be validated before any retrieval execution.

Validation rules:

- Output must be JSON.
- `schema_version` must be `query_plan.v2.5`.
- `subqueries` must be a non-empty list.
- Maximum subqueries: 8.
- Maximum query length per subquery: 240 characters.
- `filters.source_id` must be null or exist in local catalog.
- `filters.page_type` must be null or one of the existing page types.
- `filters.confidence` must be null, `cited`, or `weak`.
- `catalog_refs` must be empty or refer to known local page ids/source ids.
- Planner must not include `claim_id`, `citation_locator`, `page_path`, score, relationship evidence, or answer text as accepted evidence.
- Unsafe or unknown fields should be ignored or recorded as validation warnings, not executed blindly.

Malformed JSON gets one repair prompt. If repair still fails, `ask` returns a safe planning failure.

## 7. Planned Retrieval Execution

Add a small orchestration layer between `answer_question` and `retrieve_context`.

Recommended module:

```text
llmwiki/planner.py
  QueryPlan
  QuerySubquery
  RequiredEvidence
  PlanningOptions
  PlanningResult
  plan_question(root, question, options) -> PlanningResult
  build_planner_prompt(...)
  parse_query_plan(...)
  validate_query_plan(...)

llmwiki/planned_retrieval.py
  execute_query_plan(root, plan, options) -> PlannedRetrievalResult
  merge_planned_contexts(...)
```

Execution flow:

```text
answer_question
-> plan_question
-> execute_query_plan
   -> retrieve_context(subquery 1)
   -> retrieve_context(subquery 2)
   -> ...
   -> merge contexts by claim_id
-> build answer prompt from merged retrieved contexts
-> validate answer citations against merged contexts
```

Merge behavior should be structural and domain-agnostic:

- Deduplicate by `claim_id`.
- Preserve the first retrieved context object plus merged retrieval reasons.
- Preserve per-subquery diagnostics.
- Keep source/page/relationship/citation fields from retrieval, not from the planner.
- Use a bounded context budget for the answer prompt.

V2.5 should not implement model reranking. If more candidates are retrieved than the prompt can hold, select a stable bounded set by subquery order and retrieval rank. More advanced evidence selection belongs to V2.7.

## 8. Statuses And Error Handling

Existing `ask` statuses remain:

- `answered`
- `insufficient_evidence`
- `llm_failed`
- `invalid_citations`
- `writeback_failed`

V2.5 adds:

- `planning_failed`
- `planning_invalid`
- `planned_insufficient_evidence`

Failure behavior:

- If planner call fails, return `planning_failed`.
- If planner output is invalid after repair, return `planning_invalid`.
- If planned retrieval returns no evidence, return `planned_insufficient_evidence` and do not call the answer-generation LLM.
- If answer citations refer to contexts not retrieved by planned retrieval, return `invalid_citations`.
- If writeback is requested, synthesis still uses staging/apply and cannot bypass validation.

All error messages must be sanitized. They must not include API keys, raw secret config, full prompts, or local file contents outside intended diagnostics.

## 9. Evaluation

V2.5 should extend tests and local eval without relying on real LLM calls.

Use monkeypatched provider responses for planner and answer tests. Do not add a production mock provider or a public no-network mode.

Suggested regression questions:

- `这五种水果里哪种更适合补充维生素 C？`
- `苹果和橙子哪个维生素 C 更有优势？`
- `香蕉适合需要控制血糖的人多吃吗？`
- `保存方法上草莓和芒果有什么不同？`

Quality checks:

- Planner JSON validates.
- Planner does not invent claim ids, source ids, page ids, citation locators, or page paths.
- Planned retrieval executes through `retrieve_context`.
- Planned retrieval improves evidence coverage for comparison questions compared with single-query ask.
- Final answer citations are a subset of retrieved contexts.
- `retrieve`, `query`, and `eval retrieval` still make zero LLM calls.
- Secrets do not appear in planner artifacts, JSON output, staging, or logs.

The committed V2.4 retrieval eval should remain unchanged. V2.5 may add ask/planning-specific tests rather than changing the retrieval eval schema.

## 10. Documentation

README should explain:

- `retrieve` is hybrid local retrieval and does not call LLM.
- `query` is human-readable local retrieval output and does not call LLM.
- `ask` uses LLM query planning before local retrieval, then uses LLM answer generation only from retrieved evidence.
- Planner output is not evidence.
- Citations still come only from local catalog claims.

AGENTS.md should add:

- LLM query planning is allowed for `ask`.
- LLM query planning is not allowed for default `retrieve`, `query`, or `eval retrieval`.
- Planner output must be schema-validated before execution.
- Planner output must not be treated as source-backed evidence.
- No domain-specific query rules or term boosts should be added for V2.5.

## 11. Acceptance Criteria

V2.5 is complete when:

- `ask` uses planner-first retrieval by default.
- Planner output is schema-validated and sanitized.
- Invalid planner output fails safely.
- Planned retrieval calls local `retrieve_context` for subqueries.
- Answers cite only retrieved local contexts.
- Complex comparison questions over the five fruit documents retrieve broader, more useful evidence than a single unplanned query.
- `retrieve`, `query`, and `eval retrieval` remain local and deterministic.
- Existing V2.1-V2.4 tests continue to pass.
- New planner tests cover malformed JSON, forged ids, insufficient evidence, valid planned answer, and no writeback unless requested.

## 12. Implementation Boundaries

V2.5 should be small enough to implement as one stage:

- Add planner data structures and validation.
- Add planner invocation to `ask`.
- Add planned retrieval execution.
- Add tests and docs.

Do not include embeddings, vector DB, reranking, UI, MinerU, OCR, or synthesis quality redesign in this phase.
