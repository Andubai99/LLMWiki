# LLMWiki V2.4: Hybrid Local Retrieval

## 1. Background

V2.1 made `llmwiki add <source> --root .` the normal source import path. V2.2 added evidence-grounded `ask` and synthesis writeback. V2.3 added `llmwiki eval retrieval`, retrieval diagnostics, and evidence-contract checks.

The current bottleneck is retrieval quality. The existing retriever is still a prototype:

- Chinese natural questions can collapse into one long search term. For example, `草莓应该怎么保存？` becomes `草莓应该怎么保存`, causing `candidate_miss`.
- `query` has its own weaker search path instead of reusing `retrieve`.
- Scoring is mostly lexical hit counting.
- Retrieval does not have separate retriever components, so it is hard to measure whether failure came from BM25, title/alias matching, graph expansion, or exact matching.
- Non-English, formula-like, symbol-heavy, and mixed-script questions are not handled as first-class cases.

V2.4 replaces the current ad hoc scoring with a local hybrid retrieval architecture. It remains deterministic and local by default. LLM query planning, embeddings, vector stores, and model rerankers are intentionally left for later stages.

## 2. Goal

V2.4 establishes a mature local retrieval baseline.

It adds:

- A retriever abstraction.
- Unicode-aware query normalization and feature extraction.
- Multiple local retrievers:
  - BM25/FTS claim retriever.
  - Catalog title/alias retriever.
  - Graph relationship retriever.
  - Exact/formula/symbol retriever.
- Reciprocal Rank Fusion (RRF) across retrievers.
- Per-retriever diagnostics.
- A `query` implementation that reuses `retrieve`.
- Fruit natural-question eval cases that measure the current failure mode directly.

V2.4 is successful when natural questions over the current five fruit documents no longer fail at candidate generation, while evidence-contract metrics remain intact.

## 3. Non-Goals

V2.4 does not implement:

- LLM query planning or LLM query rewrite.
- Embeddings or vector store.
- Cross-encoder, embedding, or LLM reranking.
- Rich source parsing for PDF tables, images, formulas, OCR, or MinerU output.
- New answer-generation behavior.
- Synthesis quality upgrades.
- New catalog schema tables unless implementation proves they are required.
- External web search.

Those belong to V2.5 through V2.9.

## 4. Design Principles

### 4.1 Local, Deterministic, Reproducible

`retrieve` and `query` must remain local and deterministic by default. V2.4 must not call external LLM APIs.

### 4.2 Hybrid Before Vector

The project should first exhaust structured local signals already present in the wiki and catalog:

- claim text,
- title,
- aliases,
- page type,
- source id,
- citation locator,
- graph relationships,
- exact spans and symbols.

Vector retrieval becomes more valuable after these local signals are organized behind stable interfaces.

### 4.3 Evidence Contract Is Non-Negotiable

Improving recall is not enough. Every returned context must still reference real catalog claims, source ids, locators, page paths, confidence labels, and relationships.

### 4.4 Unicode Is Normal, Not An Edge Case

Retrieval must not assume that useful search text is only ASCII words or Chinese words. The query analyzer must preserve and reason about:

- CJK text,
- Latin text,
- mixed-script terms,
- diacritics,
- full-width characters,
- numbers,
- mathematical symbols,
- formula-like spans,
- punctuation-significant strings,
- emoji or other Unicode symbols when they appear in sources.

## 5. Public Behavior

### 5.1 `retrieve`

Existing command:

```bash
llmwiki retrieve "草莓应该怎么保存？" --root . --json
```

Expected V2.4 behavior:

- Does not return empty evidence when the local catalog contains relevant strawberry storage claims.
- Returns contexts with valid claim ids and source locators.
- Reports which retrievers contributed through diagnostics or retrieval reasons.
- Preserves existing JSON fields:
  - `question`
  - `contexts`
  - `relationships`
  - `warnings`
  - `diagnostics`

V2.4 may update:

```json
"schema_version": "retrieval.v2.4"
```

This is additive. Existing consumers should keep working if they read the established fields.

### 5.2 `query`

`query` should become a human-readable formatter over `retrieve_context`.

Current problem:

```text
query -> query.py -> separate weak FTS path
retrieve -> retrieval.py -> richer but still prototype path
```

V2.4 target:

```text
query -> retrieve_context -> human-readable context output
retrieve -> retrieve_context -> JSON or prompt output
ask -> retrieve_context -> grounded answer
eval -> retrieve_context -> metrics
```

`query` must not call the LLM. It should inherit improvements from `retrieve` automatically.

### 5.3 `ask`

`ask` continues to use `retrieve_context` as its only evidence source.

V2.4 should make `ask "草莓应该怎么保存？"` move from `insufficient_evidence` to `answered` when the fruit workspace has been built, without adding LLM query planning.

## 6. Internal Architecture

Add focused retrieval components instead of expanding the current single retrieval function.

Recommended modules:

```text
llmwiki/query_analysis.py
  analyze_query(question, catalog_snapshot=None) -> RetrievalQuery
  normalize_unicode(...)
  extract_text_terms(...)
  extract_exact_spans(...)
  extract_symbol_spans(...)
  extract_ngrams(...)

llmwiki/retrievers.py
  RetrievalQuery
  RetrievalCandidate
  RetrieverResult
  Retriever protocol/base class
  BM25ClaimRetriever
  CatalogTitleAliasRetriever
  GraphRelationshipRetriever
  ExactFormulaSymbolRetriever
  HybridRetriever
  reciprocal_rank_fusion(...)

llmwiki/retrieval.py
  retrieve_context(...)
  context assembly
  relationship/warning assembly
  backward-compatible JSON contract
```

Existing module names can differ if implementation finds a cleaner fit, but the responsibilities should remain separate.

## 7. Query Analysis

### 7.1 Normalization

Query normalization should use Unicode-aware rules:

- Apply NFKC normalization for width and compatibility folding.
- Apply `casefold()` for case-insensitive matching.
- Preserve the original query for display and exact-span matching.
- Preserve symbols and formula-like spans instead of stripping them.
- Normalize common punctuation separators, but do not erase punctuation that is meaningful inside formulas or symbols.
- Keep both normalized and original forms when exact matching may need the original.

Examples:

| Input | Useful Features |
| --- | --- |
| `草莓应该怎么保存？` | `草莓`, `保存`, `冷藏`, `储存`, CJK n-grams |
| `维生素Ｃ水果` | `维生素C`, `维生素`, `C`, `水果` |
| `H₂O 的性质` | `H2O`, `H₂O`, `性质` |
| `E=mc²` | `E=mc2`, `E=mc²`, exact formula span |
| `α/β ratio` | `α/β`, `ratio`, symbol span |
| `🍎 营养` | `🍎`, `营养` |

### 7.2 Query Features

`analyze_query` should produce a structured query object with at least:

```json
{
  "original": "草莓应该怎么保存？",
  "normalized": "草莓应该怎么保存?",
  "text_terms": ["草莓", "保存"],
  "expanded_terms": ["草莓", "保存", "冷藏", "储存", "存放", "尽快食用", "保持干燥"],
  "catalog_terms": ["草莓"],
  "ngrams": ["草莓", "保存", "..."],
  "exact_spans": [],
  "symbol_spans": [],
  "formula_spans": [],
  "stop_terms": ["应该", "怎么"]
}
```

The exact shape may be a dataclass rather than JSON, but diagnostics should expose enough detail to debug failures.

### 7.3 Stop Terms And Expansions

V2.4 may include a small deterministic expansion table. It is not a replacement for V2.5 LLM query planning.

Initial useful expansions:

```text
保存 -> 冷藏, 储存, 存放, 久放, 尽快食用, 保持干燥
营养 -> 维生素, 膳食纤维, 矿物质, 热量
怎么吃 -> 食用, 搭配, 做法, 适合
适合 -> 建议, 不建议, 人群, 注意
补充 -> 富含, 含有, 摄入
比较 -> 哪种, 更, 优势, 差异
```

Chinese stop terms should remove weak question glue without removing domain terms:

```text
应该, 怎么, 如何, 为什么, 吗, 呢, 可以, 是否, 哪个, 哪种
```

These rules must be conservative and covered by tests. Later V2.5 can add LLM planning for richer rewrite.

## 8. Retriever Abstraction

Each retriever receives the same analyzed query and returns ranked candidates.

Suggested interface:

```python
class Retriever(Protocol):
    name: str

    def retrieve(
        self,
        conn,
        query: RetrievalQuery,
        *,
        limit: int,
        filters: RetrievalFilters,
    ) -> RetrieverResult:
        ...
```

Candidate fields:

```json
{
  "claim_id": "clm_src_xxx_llm_023",
  "source_id": "src_xxx",
  "claim_text": "草莓适合冷藏保存。",
  "citation_locator": "line:86;section:5.2 冷藏保存;paragraph:21",
  "confidence_status": "cited",
  "page_id": "src_xxx",
  "page_path": "wiki/sources/src_xxx.md",
  "page_type": "source",
  "retriever": "catalog_title_alias",
  "retriever_rank": 1,
  "raw_score": 12.4,
  "matched_terms": ["草莓", "冷藏", "保存"],
  "reasons": ["alias_match:草莓", "expanded_term_match:冷藏"]
}
```

The final public context can keep the current simplified fields, but diagnostics should preserve retriever-level details.

## 9. Required Retrievers

### 9.1 BM25/FTS Claim Retriever

Purpose:

- Search claim text with SQLite FTS/BM25.
- Continue serving English and tokenized queries well.
- Support mixed-script terms where FTS can tokenize them.

Behavior:

- Use normalized text terms and safe FTS query construction.
- Fall back gracefully when FTS rejects a query.
- Return ranked claim candidates.
- Include `bm25_fts` in retrieval reasons.

### 9.2 Catalog Title/Alias Retriever

Purpose:

- Use known wiki structure to find entities/concepts/sources even when the full natural question does not match claim text.
- Make `草莓应该怎么保存？` seed the query with page `concept:草莓` and related source claims.

Behavior:

- Match normalized query features against `aliases.normalized_alias`, `pages.title`, and page paths.
- Prefer exact alias/title match over substring match.
- Use matched pages to collect related claims:
  - source page id -> claims with that `source_id`;
  - concept/entity page id -> claims connected by relationships or links to source pages;
  - source title/alias -> claims from that source.
- Return claim candidates with reasons such as:
  - `alias_exact:草莓`
  - `title_match:草莓`
  - `page_source_claims`

This retriever is the main local fix for natural Chinese questions over known catalog objects.

### 9.3 Graph Relationship Retriever

Purpose:

- Expand from seed pages and seed claims through catalog relationships.
- Preserve source-backed graph context.
- Ensure `contradicts` evidence remains visible.

Behavior:

- Start from candidates found by BM25/title/alias/exact retrievers.
- Follow relationships involving seed source ids, page ids, and evidence claim ids.
- Include relationship-linked claims and related pages.
- Prioritize `contradicts` and `supports` relationships for exposure, but do not silently suppress weaker relationship types.
- Return reasons such as:
  - `graph_supports`
  - `graph_contains`
  - `graph_contradicts`

Graph expansion must be bounded to avoid turning one broad match into the whole catalog. V2.4 should use one-hop expansion by default.

### 9.4 Exact/Formula/Symbol Retriever

Purpose:

- Avoid losing non-word evidence such as formulas, mathematical symbols, chemical forms, code-like terms, IDs, or emoji.
- Make Unicode/multilingual smoke cases measurable.

Behavior:

- Extract exact spans from the original and normalized query.
- Search exact spans in:
  - `claims.claim_text`,
  - `claims.citation_locator`,
  - `pages.title`,
  - `aliases.alias`,
  - `sources.title`.
- Preserve symbols rather than filtering them out.
- Return reasons such as:
  - `exact_span:E=mc²`
  - `formula_span:H₂O`
  - `symbol_span:α/β`

V2.4 does not need full mathematical parsing. It only needs not to discard formulas and symbols before retrieval.

## 10. Hybrid Fusion

Use Reciprocal Rank Fusion to combine retriever results.

Formula:

```text
rrf_score(candidate) = sum(1 / (rrf_k + rank_in_retriever))
```

Default:

```text
rrf_k = 60
```

Rules:

- Deduplicate by `claim_id`.
- Preserve all contributing retriever names and reasons.
- Apply filters after or during retrieval consistently:
  - `source_id`,
  - `page_type`,
  - `confidence`.
- Stable tie-breaker:
  - higher fused score first;
  - higher best raw score second;
  - lexicographic `claim_id` last.

RRF is preferred over one global hand-tuned score because each retriever has different scoring semantics. BM25 scores, alias exact matches, graph expansion, and exact symbol hits should not be forced into one fragile numeric scale before fusion.

## 11. Context Assembly

After fusion, `retrieve_context` should assemble public contexts:

```json
{
  "rank": 1,
  "claim_id": "clm_src_xxx_llm_023",
  "source_id": "src_xxx",
  "citation_locator": "line:86;section:5.2 冷藏保存;paragraph:21",
  "claim_text": "草莓适合冷藏保存。",
  "page_path": "wiki/sources/src_xxx.md",
  "page_type": "source",
  "relationship_type": "supports",
  "confidence_status": "cited",
  "score": 0.87,
  "retrieval_reasons": [
    "alias_exact:草莓",
    "expanded_term_match:冷藏",
    "rrf:catalog_title_alias,bm25_fts"
  ]
}
```

`score` may be normalized from fused ranks for display. It must remain deterministic.

Relationships and warnings should keep current behavior:

- include relevant relationships for returned evidence;
- expose `contradicts`;
- warn for weak/uncited evidence;
- never forge ids or paths.

## 12. Diagnostics

V2.4 should extend diagnostics without removing V2.3 fields.

Current required fields remain:

```json
{
  "query_terms": [],
  "candidate_count": 0,
  "returned_count": 0,
  "failure_stage": null
}
```

Add:

```json
{
  "schema_version": "retrieval.v2.4",
  "query_features": {
    "text_terms": [],
    "expanded_terms": [],
    "catalog_terms": [],
    "ngrams": [],
    "exact_spans": [],
    "symbol_spans": [],
    "formula_spans": []
  },
  "retrievers": {
    "bm25_fts": {
      "candidate_count": 0,
      "returned_count": 0
    },
    "catalog_title_alias": {
      "candidate_count": 0,
      "returned_count": 0
    },
    "graph_relationship": {
      "candidate_count": 0,
      "returned_count": 0
    },
    "exact_formula_symbol": {
      "candidate_count": 0,
      "returned_count": 0
    }
  },
  "fusion": {
    "method": "rrf",
    "rrf_k": 60,
    "candidate_count_before_fusion": 0,
    "candidate_count_after_fusion": 0
  }
}
```

Failure stages should remain compatible with V2.3:

- `no_terms`
- `candidate_miss`
- `ranking_miss`
- `filter_miss`
- `relationship_miss`
- `contract_violation`
- `unexpected_evidence`
- `runtime_error`

For V2.4, `no_terms` should be rare because Unicode symbol/formula spans are valid features.

## 13. Evaluation Dataset

V2.4 should keep the V2.3 eval dataset and add fruit-focused cases.

Recommended new dataset:

```text
tests/evals/retrieval_v2_4_fruits.jsonl
```

The fruit dataset should be designed for the five committed documents under:

```text
docs/tests/
```

Because production LLM claim extraction can change claim granularity, fruit eval cases should prefer `expected_source_ids`, `expected_page_ids`, and `expected_terms` over exact claim ids.

Required fruit cases:

```json
{"id":"fruit_zh_strawberry_storage_natural","question":"草莓应该怎么保存？","language":"zh","query_type":"natural_question","expected_status":"has_evidence","expected_source_ids":["src_99ab0495789d"],"expected_page_ids":["concept:草莓"],"expected_terms":["草莓","保存","冷藏","干燥"],"must_expose_relationship_types":["supports"]}
{"id":"fruit_zh_vitamin_c_comparison","question":"这五种水果里哪种更适合补充维生素 C？","language":"zh","query_type":"comparison","expected_status":"has_evidence","expected_source_ids":["src_880c9f8a447c","src_99ab0495789d"],"expected_terms":["维生素 C","橙子","草莓"],"must_expose_relationship_types":["supports"]}
{"id":"fruit_zh_apple_orange_vitamin_c","question":"苹果和橙子哪个维生素 C 更有优势？","language":"zh","query_type":"comparison","expected_status":"has_evidence","expected_source_ids":["src_880c9f8a447c","src_9d0e46141e7c"],"expected_terms":["苹果","橙子","维生素 C"],"must_expose_relationship_types":["supports"]}
{"id":"fruit_zh_banana_blood_sugar","question":"香蕉适合需要控制血糖的人多吃吗？","language":"zh","query_type":"natural_question","expected_status":"has_evidence","expected_source_ids":["src_7f6840121921"],"expected_page_ids":["concept:香蕉"],"expected_terms":["香蕉","血糖","糖分","不建议"],"must_expose_relationship_types":["supports"]}
{"id":"fruit_zh_mango_energy_sugar","question":"芒果的能量和糖分需要注意什么？","language":"zh","query_type":"natural_question","expected_status":"has_evidence","expected_source_ids":["src_414a6aa7730d"],"expected_page_ids":["concept:芒果"],"expected_terms":["芒果","能量","糖分","注意"],"must_expose_relationship_types":["supports"]}
```

Add a Unicode/symbol smoke dataset or cases:

```json
{"id":"unicode_formula_h2o","question":"H₂O 的化学式是什么？","language":"mixed","query_type":"formula_symbol","expected_status":"has_evidence","expected_terms":["H₂O","H2O"]}
{"id":"unicode_math_e_mc2","question":"E=mc² 表示什么？","language":"mixed","query_type":"formula_symbol","expected_status":"has_evidence","expected_terms":["E=mc²","E=mc2"]}
{"id":"unicode_symbol_alpha_beta","question":"α/β ratio 怎么解释？","language":"mixed","query_type":"formula_symbol","expected_status":"has_evidence","expected_terms":["α/β","ratio"]}
```

These symbol cases may use small deterministic fixtures rather than the fruit documents.

## 14. Metrics And Acceptance Thresholds

V2.4 must improve measured retrieval quality over the V2.3 baseline.

Required metrics:

- `hit_at_5`
- `recall_at_5`
- `precision_at_5`
- `mrr`
- evidence-contract metrics from V2.3
- per-retriever candidate counts

Minimum acceptance on the fruit V2.4 dataset:

- Natural Chinese fruit questions: `hit_at_5 >= 0.80`.
- Natural Chinese fruit questions: no `candidate_miss` for expected `has_evidence` cases.
- Comparison fruit questions: retrieve evidence from at least two relevant fruit sources when the question asks for a comparison.
- Evidence contract:
  - `claim_id_validity = 1.00`
  - `source_id_validity = 1.00`
  - `citation_locator_presence = 1.00`
  - `page_path_validity = 1.00`
  - `relationship_validity = 1.00`
- `llm_calls = 0` for retrieval and retrieval eval.

The thresholds can be tightened after the first V2.4 implementation produces a measured baseline.

## 15. CLI And API Surface

### 15.1 No New User Command Required

The primary user-facing commands remain:

```bash
llmwiki retrieve "问题" --root . --json
llmwiki query "问题" --root .
llmwiki ask "问题" --root .
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_4_fruits.jsonl
```

### 15.2 Optional Debug Flags

V2.4 may add optional debug output, but it should not be required for normal use.

Potential flags:

```bash
llmwiki retrieve "草莓应该怎么保存？" --root . --json --debug-retrieval
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_4_fruits.jsonl --json
```

If added, debug output must not include API keys, prompt secrets, or local secret config contents.

### 15.3 Python API

Existing API should remain:

```python
retrieve_context(root, question, limit=8, source_id=None, page_type=None, confidence=None)
```

Internal V2.4 APIs can be added behind it. External callers should not need to know whether retrieval uses one retriever or several.

## 16. Testing Strategy

Add tests before implementation.

### 16.1 Query Analysis Tests

Cover:

- Chinese natural question:
  - `草莓应该怎么保存？` extracts `草莓` and `保存`.
- Full-width folding:
  - `维生素Ｃ` normalizes to include `维生素C`.
- Formula preservation:
  - `H₂O` produces original and normalized formula spans.
- Symbol preservation:
  - `α/β` is not dropped.
- Emoji preservation:
  - `🍎 营养` keeps `🍎` as a symbol span.
- Stop terms do not remove domain terms.

### 16.2 Retriever Unit Tests

Cover each retriever independently:

- BM25/FTS finds English and simple tokenized claims.
- Catalog title/alias retriever finds claims for `草莓应该怎么保存？`.
- Graph relationship retriever expands from matched page/source to related claims.
- Exact/formula/symbol retriever finds formula and symbol fixtures.
- Filters are respected.
- Candidate reasons are present.

### 16.3 Fusion Tests

Cover:

- RRF combines candidates from multiple retrievers.
- Duplicate claim ids merge reasons.
- Stable ordering for ties.
- Candidate scores are deterministic.

### 16.4 CLI Regression Tests

Cover:

- `retrieve "草莓应该怎么保存？" --json` returns contexts on a fruit workspace.
- `query "草莓应该怎么保存？"` returns the same evidence path as retrieve in human-readable form.
- `ask "草莓应该怎么保存？" --no-writeback --json` reaches LLM answer path when provider is monkeypatched.
- Existing V2.3 retrieval/eval tests still pass.

### 16.5 Eval Tests

Cover:

- V2.4 fruit eval dataset loads.
- V2.4 eval reports per-retriever diagnostics.
- No LLM calls happen in retrieval eval.
- Secret strings are absent from human and JSON eval output.

## 17. Data And Git Hygiene

Committed files may include:

- new query analysis and retriever modules;
- V2.4 eval datasets under `tests/evals/`;
- tests;
- README and AGENTS updates;
- this spec and later implementation plan.

Generated or ignored files must not be committed:

- `.test-workspaces/`
- `.pytest_cache/`
- `state/catalog.sqlite`
- `state/evals/*`
- generated `sources/raw/*`
- generated `sources/normalized/*`
- generated `staging/*`
- generated `wiki/**/*.md` pages except committed templates
- `config/api-keys.toml`

## 18. Documentation Updates

README should explain:

- `retrieve` is now hybrid local retrieval.
- `query` is human-readable retrieve output.
- `eval retrieval` is required before and after retrieval changes.
- V2.4 does not call LLMs during retrieval.
- Natural language support is improved by local query analysis, not by LLM planning.

AGENTS.md should explain:

- Retrieval changes must preserve evidence contract validity.
- Retrieval eval must be run for retrieval changes.
- `retrieve` and `query` must not call external LLM APIs by default.
- LLM query planning starts in V2.5, not V2.4.
- Formula/symbol evidence must not be discarded by normalization.

## 19. Rollout Plan

Suggested implementation order:

1. Add failing tests and V2.4 fruit/symbol eval cases.
2. Extract query analysis into a dedicated module.
3. Add retriever dataclasses and protocol.
4. Implement BM25/FTS retriever using current behavior.
5. Implement catalog title/alias retriever.
6. Implement exact/formula/symbol retriever.
7. Implement graph relationship retriever.
8. Add RRF fusion and diagnostics.
9. Switch `retrieve_context` to `HybridRetriever`.
10. Switch `query` to format `retrieve_context`.
11. Update docs and AGENTS.
12. Run V2.3 and V2.4 eval suites before and after.

## 20. Acceptance Criteria

V2.4 is complete when:

- `llmwiki retrieve "草莓应该怎么保存？" --root . --json` returns relevant cited contexts on the five-document fruit workspace.
- `llmwiki ask "草莓应该怎么保存？" --root . --no-writeback --json` no longer returns `insufficient_evidence` when relevant evidence exists.
- `llmwiki query "草莓应该怎么保存？" --root .` reuses `retrieve_context`.
- `llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_4_fruits.jsonl` runs and shows improved fruit natural-query metrics over the pre-V2.4 baseline.
- English, multilingual, formula, and symbol smoke cases preserve useful query features and do not fail only because normalization discarded them.
- All retrieval output still references valid catalog claims, sources, locators, pages, and relationships.
- `retrieve`, `query`, and retrieval eval make zero LLM calls by default.
- Existing `add`, `ask`, synthesis writeback, lint, and V2.3 eval tests continue to pass.

## 21. Relationship To Later Stages

V2.4 is the foundation for the next retrieval stages:

- V2.5 LLM Query Planning can add planner-generated intent, entities, subqueries, filters, and required evidence. It must feed those plans back into local `retrieve`.
- V2.6 Embedding + Vector Store can add a vector retriever into the same abstraction and RRF fusion.
- V2.7 Reranking + Evidence Selection can rerank the hybrid candidate pool and choose compact evidence for answers.
- V2.8 Synthesis Quality can rely on better evidence selection when writing durable synthesis pages.
- V2.9 Rich Source Parsing can add table/formula/image-caption evidence that the exact/formula/symbol retriever and later vector retriever can consume.

V2.4 must not solve all semantic retrieval problems. Its job is to replace the current fragile local baseline with a modular, measurable, Unicode-aware hybrid retrieval layer.
