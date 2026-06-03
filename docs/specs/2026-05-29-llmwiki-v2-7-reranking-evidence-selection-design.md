# LLMWiki V2.7: Reranking + Evidence Selection

## 1. Background

V2.4 introduced deterministic hybrid local retrieval: BM25/FTS, catalog title and alias matching, graph relationship expansion, exact formula/symbol matching, Unicode-aware query analysis, and RRF fusion.

V2.5 added LLM query planning for `ask`: the LLM can decompose a user question into subqueries, but every subquery still runs through local retrieval and every answer citation still comes from catalog evidence.

V2.6 added a rebuildable local vector index and vector retrieval as another recall signal. Vector retrieval improved semantic paraphrase recall, but the acceptance run on the five fruit documents exposed the next quality bottleneck:

- vector recall finds relevant candidates, but the final top contexts can still contain generic or weakly related claims;
- comparison questions can retrieve multiple sources but still present an unbalanced evidence set to the answer LLM;
- graph expansion can push broad background claims above more directly relevant evidence;
- `ask` can produce a plausible answer from an evidence set that is not selected carefully enough;
- current retrieval metrics pass, but evidence quality for answer generation needs better selection than top-k fusion order.

Examples from the V2.6 acceptance run:

```text
需要控糖的人吃水果要注意什么？
-> retrieved useful blood-sugar claims, but top contexts included broad fruit overview evidence.

这五种水果里哪种更适合补充维生素 C？
-> retrieved orange, strawberry, apple, and mango vitamin C evidence, but the answer selected one fruit too confidently from an imperfect evidence set.
```

V2.7 therefore does not add another retriever. It adds a modelable reranking and evidence selection layer between candidate retrieval and final returned contexts.

## 2. Goal

V2.7 makes LLMWiki better at choosing evidence after recall.

It adds:

- a reranker abstraction over retrieved catalog-backed candidates;
- a deterministic reranker fallback for tests, offline use, and graceful degradation;
- an embedding reranker that uses existing V2.6 query/chunk vectors where available;
- an optional LLM reranker for `ask` or explicit evaluation, never default `retrieve`;
- an evidence selector that controls coverage, diversity, conflict exposure, redundancy, and token budget;
- retrieval diagnostics showing candidate pool size, reranker behavior, and selection decisions;
- eval cases and metrics for comparison coverage, redundancy, source diversity, and selected-evidence quality.

V2.7 is successful when `retrieve/query/ask` still return only source-backed catalog evidence, but selected contexts are more useful for downstream grounded answers than raw RRF top-k.

## 3. Non-Goals

V2.7 does not implement:

- new retriever families;
- new vector database storage;
- new embedding models or multimodal image retrieval;
- rich PDF/table/formula parsing;
- automatic relationship classification;
- automatic conflict resolution;
- external web search;
- UI;
- synthesis page quality improvements;
- multi-turn chat memory.

Those remain in later phases:

- V2.8 synthesis quality;
- V2.9 rich source parsing;
- later public benchmark expansion and domain-specific dataset curation.

## 4. Design Principles

### 4.1 Recall And Selection Are Separate

Retrievers should maximize candidate recall. The selector should decide what evidence is worth showing to the answer layer.

V2.7 should not weaken BM25/catalog/exact/vector/graph recall to make top-k look cleaner. It should keep a larger candidate pool, then rerank and select.

### 4.2 No Domain-Specific Rules

V2.7 must not hard-code rules such as "vitamin C is important for fruit comparison" or "blood sugar terms should be boosted".

The selector may use generic signals:

- question text;
- planner subquery structure;
- source/page/claim metadata;
- retrieval reasons;
- relationship types;
- reranker scores;
- citation/confidence status;
- conflict/weak flags;
- redundancy against already selected evidence.

Any semantic judgment beyond those generic mechanics belongs to a reranker model, not a hand-written fruit-specific rule.

### 4.3 Vector And Reranker Scores Are Not Evidence

Reranking can change order and selection. It cannot create evidence.

Every returned context must still map to a real `claim_id`, `source_id`, `citation_locator`, `page_path`, and catalog relationship.

### 4.4 Default Public Retrieval Must Stay Safe

`retrieve` and `query` must not call chat LLM APIs by default.

Allowed defaults:

- deterministic reranker;
- embedding reranker when `[embedding].enabled = true` and a local vector index exists.

Optional LLM reranking may be available for `ask` or an explicit command/config, but it must be opt-in and visible in diagnostics.

### 4.5 Selection Must Preserve Uncertainty

The selector must not hide:

- weak/uncited evidence;
- `contradicts` relationships;
- missing evidence for a comparison item;
- uneven source coverage;
- open uncertainty exposed by the planner or retriever.

If evidence is insufficient or uneven, the selected context and answer prompt must make that visible.

## 5. Architecture

V2.7 inserts two stages after V2.6 hybrid candidate retrieval:

```text
question
-> optional ask planner
-> retrieve candidate pool from BM25/catalog/exact/vector/graph
-> rerank candidates
-> select evidence set
-> return contexts / query output / ask answer prompt
```

### 5.1 Candidate Pool

`retrieve_context` should request more candidates than the final context limit.

Default values:

```toml
[retrieval]
candidate_pool_limit = 80
context_limit = 8
```

The pool should include candidates from all enabled retrievers before final selection. Candidate rows must keep:

- original RRF rank;
- retriever names;
- retrieval reasons;
- source/page metadata;
- relationship type;
- confidence status;
- vector diagnostics when applicable.

### 5.2 Reranker Interface

Add a module:

```text
llmwiki/rerankers.py
```

Core types:

```python
RerankInput
RerankCandidate
RerankResult
Reranker
DeterministicReranker
EmbeddingReranker
LLMReranker
create_reranker(config, root)
```

`RerankResult` should include:

- `claim_id`;
- `relevance_score`;
- `coverage_labels`;
- `reason`;
- `warnings`;
- `model_or_method`;
- `used_external_llm`.

The interface accepts only existing candidate evidence. It must reject or ignore any reranker output that references unknown claim ids.

### 5.3 Deterministic Reranker

The deterministic reranker is the offline fallback.

It should be generic and conservative:

- preserve strong signals from existing RRF rank;
- prefer cited claims over weak/uncited claims when relevance is otherwise similar;
- prefer candidates whose retrieved text matches query/planner terms;
- keep exact/formula/symbol hits visible;
- never use domain-specific terms or fruit-specific boosts.

This fallback is for stable tests and graceful operation, not the ceiling for quality.

### 5.4 Embedding Reranker

The embedding reranker uses V2.6 vectors to score semantic similarity between the question/subquery and candidate chunks.

It should:

- reuse query embedding already produced by vector retrieval when available;
- use stored claim chunk vectors for candidate claims;
- degrade to deterministic reranking when vectors are missing, stale, or dimension-incompatible;
- expose `query_embedded`, `candidate_vectors_used`, `failure_stage`, provider, model, and dimension in diagnostics.

Embedding reranking is allowed for `retrieve/query/eval retrieval` because V2.6 already permits query embedding when embedding is enabled and a local index exists.

### 5.5 Optional LLM Reranker

The LLM reranker is opt-in.

It may be used by:

- `ask`, when configured;
- explicit local experiments;
- retrieval eval runs that intentionally measure LLM reranking.

It must not be the default for:

- `llmwiki retrieve`;
- `llmwiki query`;
- normal `llmwiki eval retrieval`.

The LLM reranker prompt should include only bounded candidate snippets and catalog metadata. It must not include raw source files, API keys, secret config content, or generated vectors.

The LLM reranker output must be schema-validated:

```json
{
  "schema_version": "rerank.v2.7",
  "ranked_claims": [
    {
      "claim_id": "clm_xxx",
      "relevance_score": 0.0,
      "coverage_labels": ["..."],
      "reason": "..."
    }
  ],
  "warnings": []
}
```

Invalid claim ids, fabricated citations, fabricated source ids, or malformed JSON should fail closed to deterministic/embedding reranking and emit diagnostics.

## 6. Evidence Selector

Add a module:

```text
llmwiki/evidence_selection.py
```

Core types:

```python
EvidenceSelectionOptions
EvidenceCandidate
SelectedEvidence
EvidenceSelectionResult
select_evidence(question, candidates, rerank_results, options)
```

The selector receives reranked candidates and returns the final context set.

### 6.1 Selection Objectives

The selector should balance:

- high relevance;
- source diversity;
- coverage of planner subqueries;
- coverage of comparison entities/concepts;
- conflict exposure;
- cited evidence over weak evidence;
- low redundancy;
- token budget.

These are generic objectives, not domain rules.

### 6.2 Coverage Groups

Coverage groups can come from:

- ask planner subqueries;
- source ids;
- page ids;
- concept/entity ids;
- relationship clusters;
- reranker `coverage_labels`;
- candidate retrieval reasons.

For `ask`, planned retrieval should preserve subquery provenance so the selector can avoid returning all evidence from the first successful subquery.

For plain `retrieve`, coverage groups are inferred from source/page/concept ids and relationship clusters.

### 6.3 Comparison Questions

Comparison questions must avoid single-source collapse when multiple requested items have evidence.

For planned `ask`, the selector should attempt to include:

- at least one relevant claim for each required subquery that has evidence;
- multiple sources when the plan asks for multiple entities/concepts;
- explicit gaps when a planned item has no evidence.

This should be driven by planner structure and reranker scores, not fruit-specific logic.

### 6.4 Conflict And Weak Evidence

If any selected or high-ranked candidate has a `contradicts` relationship, the selector must keep a contradiction context or warning visible.

Weak/uncited claims may be selected only when:

- no cited claim covers the same point;
- the answer should know that evidence is weak;
- diagnostics mark why it was selected.

The selector must not silently upgrade weak evidence into strong evidence.

### 6.5 Redundancy Control

The selector should avoid returning many near-duplicate claims from the same source when they state the same point.

V2.7 can use simple generic redundancy signals:

- same claim id;
- same source and very similar claim text;
- same locator;
- same reranker coverage label;
- high embedding similarity between selected claim chunks when vectors are available.

This is not evidence suppression. It is context budget management.

## 7. Retrieval Schema Changes

`retrieve_context` schema version should become:

```text
retrieval.v2.7
```

Existing keys remain:

```text
question
contexts
relationships
warnings
diagnostics
```

Each context may add:

```json
{
  "candidate_rank": 12,
  "rerank_score": 0.83,
  "selection_reason": "best_relevant_claim_for_coverage_group",
  "coverage_group": "source:src_xxx",
  "redundancy_group": "..."
}
```

Diagnostics should add:

```json
{
  "candidate_pool": {
    "requested_limit": 80,
    "candidate_count": 72
  },
  "reranking": {
    "enabled": true,
    "method": "embedding",
    "fallback_used": false,
    "input_count": 72,
    "ranked_count": 72,
    "used_external_llm": false,
    "failure_stage": null
  },
  "selection": {
    "selected_count": 8,
    "coverage_group_count": 4,
    "source_count": 3,
    "redundancy_filtered_count": 9,
    "conflict_contexts_selected": 0,
    "weak_contexts_selected": 0,
    "uncovered_required_groups": []
  }
}
```

## 8. Query, Ask, And Eval Behavior

### 8.1 `retrieve`

`retrieve` should use:

```text
candidate pool -> reranker -> evidence selector -> contexts
```

It should not call chat LLM reranking by default.

Human prompt output should include selection diagnostics only when useful and concise. JSON output should include full diagnostics.

### 8.2 `query`

`query` remains a human-readable view of `retrieve`.

It should display:

- claim id;
- source id;
- citation locator;
- page path;
- relationship type;
- score / rerank score;
- selection reason;
- claim text.

### 8.3 `ask`

`ask` benefits most from V2.7.

Flow:

```text
planner
-> planned subqueries
-> local retrieve candidate pools
-> rerank
-> select evidence with planner coverage
-> answer prompt
```

The answer prompt should tell the LLM when:

- some planned comparison item has no selected evidence;
- evidence is uneven across sources;
- selected evidence contains weak/uncited claims;
- selected evidence contains contradictions.

The answer LLM still cannot cite anything outside selected retrieved contexts.

### 8.4 `eval retrieval`

Eval should remain local by default.

Add V2.7 metrics:

- `ndcg_at_5`;
- `map_at_5`;
- `context_precision_at_5`;
- `context_recall_at_5`;
- `coverage_at_5`;
- `source_diversity_at_5`;
- `redundancy_rate_at_5`;
- `selected_conflict_exposure_rate`;
- `weak_evidence_visibility_rate`.

These complement existing V2.3 metrics:

- hit@5;
- recall@5;
- precision@5;
- MRR;
- evidence contract validity.

The term "context precision/recall" here follows common RAG evaluation language: it measures whether retrieved/selected contexts are relevant to the expected evidence, not whether the final natural-language answer is correct.

## 9. Configuration

Proposed config:

```toml
[reranking]
enabled = true
default_method = "embedding"
fallback_method = "deterministic"
candidate_pool_limit = 80
context_limit = 8
llm_reranker_enabled = false
timeout_seconds = 60

[evidence_selection]
max_contexts = 8
max_contexts_per_source = 3
prefer_cited = true
preserve_conflicts = true
preserve_required_coverage = true
deduplicate_similar_claims = true
```

If embedding reranking is configured but no usable vector index exists, the system falls back to deterministic reranking and records the fallback in diagnostics.

If LLM reranking is enabled for `ask`, it uses the existing `[llm]` provider config and must sanitize all errors.

## 10. Test Strategy

### 10.1 Unit Tests

Add tests for:

- deterministic reranker ordering and fallback behavior;
- embedding reranker vector scoring and dimension mismatch fallback;
- LLM reranker schema validation and forged claim rejection;
- selector coverage groups;
- selector source diversity;
- selector redundancy filtering;
- selector preservation of contradictions and weak evidence visibility.

### 10.2 Retrieval Regression Tests

Use deterministic seeded fixtures and the five fruit docs to cover:

- `需要控糖的人吃水果要注意什么？`
  - selected evidence should prioritize blood-sugar/intake/juice/portion claims over broad fruit overview claims.
- `这五种水果里哪种更适合补充维生素 C？`
  - selected evidence should include multiple relevant fruit sources when present, especially orange and strawberry.
- `运动后想快速补充能量，哪种水果证据更多？`
  - selected evidence should include banana energy evidence and avoid filling the set with unrelated caution claims.
- contradiction fixtures
  - selected evidence should still expose explicit `contradicts` relationships.

### 10.3 Ask Regression Tests

Use monkeypatched planner/answer providers.

Assert:

- answer citations must come from selected contexts;
- comparison plans include selected evidence from multiple planned groups;
- missing evidence for a planned item is visible in answer warnings or planning diagnostics;
- no writeback occurs without `--writeback`;
- LLM reranker cannot fabricate claim ids.

### 10.4 Eval Datasets

Add:

```text
tests/evals/retrieval_v2_7_evidence_selection_fruits.jsonl
```

Cases should include:

- vitamin C comparison;
- blood sugar control guidance;
- post-exercise energy comparison;
- storage paraphrase;
- explicit contradiction fixture;
- no-evidence comparison item.

Expected fields should support coverage assertions, for example:

```json
{
  "id": "fruit_vitamin_c_comparison_selection",
  "question": "这五种水果里哪种更适合补充维生素 C？",
  "expected_status": "has_evidence",
  "expected_source_ids": ["src_880c9f8a447c", "src_99ab0495789d"],
  "expected_terms": ["维生素 C", "橙子", "草莓"],
  "expected_coverage_groups": ["source:src_880c9f8a447c", "source:src_99ab0495789d"]
}
```

## 11. Acceptance Criteria

V2.7 is accepted when:

- `retrieve_context` returns `retrieval.v2.7`;
- returned contexts still satisfy evidence contract validity at 1.00 on existing evals;
- V2.4 and V2.6 eval suites do not regress materially;
- V2.7 eval passes committed evidence-selection cases;
- comparison questions select evidence from multiple relevant sources when those sources exist;
- generic graph/background claims do not outrank directly relevant selected evidence for final contexts;
- `ask` comparison answers cite selected contexts and expose uneven evidence when relevant;
- `retrieve/query/eval retrieval` do not call chat LLM APIs by default;
- optional LLM reranker is schema-validated, opt-in, and cannot fabricate evidence;
- diagnostics clearly explain reranking method, fallback, candidate pool size, and selection decisions.

## 12. Failure Handling

Reranking and selection must fail safely.

If deterministic reranking fails:

- this is a runtime bug and should fail the command.

If embedding reranking fails:

- fallback to deterministic reranking;
- add a warning;
- record `failure_stage`.

If LLM reranking fails:

- fallback to embedding or deterministic reranking;
- do not fail `ask` unless answer generation itself fails;
- record sanitized error diagnostics;
- never expose API keys or secret config contents.

If selection cannot satisfy all coverage groups:

- return the best available evidence;
- expose `uncovered_required_groups`;
- allow the answer layer to say evidence is incomplete.

## 13. Security And Secret Safety

V2.7 must not write or expose:

- API keys;
- `config/api-keys.toml` contents;
- raw provider responses containing secrets;
- raw prompt text containing sensitive local paths;
- generated vectors in answer prompts;
- reranker hidden chain-of-thought.

LLM reranker prompts should use bounded snippets and should ask for concise reasons, not private reasoning.

## 14. Open Questions

These should be answered during implementation planning or after first usage:

- Should embedding reranking be the default when vector index exists, or should V2.7 default to deterministic until eval proves improvement?
- Should LLM reranking be allowed only inside `ask`, or should there be an explicit `retrieve --reranker llm` debug option?
- How strict should `max_contexts_per_source` be for small datasets where one source truly has most evidence?
- Should answer generation receive non-selected but high-ranked "near miss" diagnostics, or only selected evidence?
- Should V2.8 synthesis writeback store evidence-selection metadata in synthesis pages?

## 15. Out Of Scope For The Implementation Plan

The V2.7 implementation plan should not include:

- new source parsing;
- external benchmark downloads;
- web search;
- UI;
- synthesis page merging;
- hosted vector DB setup;
- replacing DashScope embedding provider;
- changing `add` ingest behavior.

The implementation should stay focused on candidate reranking, selected-evidence quality, diagnostics, and eval coverage.
