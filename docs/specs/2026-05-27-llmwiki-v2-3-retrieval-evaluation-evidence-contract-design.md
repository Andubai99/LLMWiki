# LLMWiki V2.3: Retrieval Evaluation And Evidence Contract

## 1. Background

V2.1 made `llmwiki add <source> --root .` the normal import path. V2.2 added `llmwiki ask "问题" --root .`, where `ask` first retrieves local evidence from `wiki + catalog`, then asks the configured LLM to answer only from that evidence, and optionally writes a useful answer back as a synthesis page through staging/apply.

The next bottleneck is retrieval quality. The current retrieval layer can return citation-backed claims, but its matching and ranking are still prototype-level. In the fruit-document walkthrough, keyword-style queries such as `草莓 维生素 C 保存` worked, while natural Chinese questions such as `草莓应该怎么保存？` returned insufficient evidence. The failure happened before the LLM answer stage: local evidence was not retrieved.

This means the project should not rush directly into vector databases, LLM query planners, or rerankers. First, LLMWiki needs a durable way to measure retrieval and evidence quality. Without an evaluation harness, later changes may feel better while silently breaking citation validity, contradiction exposure, or reproducibility.

The metrics in this spec are RAG metrics, but adapted to LLMWiki. Common RAG evaluation work measures context precision, context recall, answer relevance, and faithfulness or groundedness. LLMWiki must also measure source-backed evidence properties: claim ids, source ids, citation locators, page paths, confidence warnings, and graph relationships.

## 2. Goal

V2.3 establishes the evaluation and contract layer for future retrieval improvements.

The stage adds:

- A versioned evidence contract for `retrieve_context` and CLI `retrieve --json`.
- A retrieval evaluation dataset format.
- A retrieval evaluation runner.
- Baseline metrics for the current retrieval implementation.
- Failure diagnostics that explain where retrieval or answer grounding broke.
- Documentation that distinguishes RAG-wide metrics from LLMWiki-specific evidence metrics.

V2.3 is successful when LLMWiki can run a repeatable eval suite and produce a structured report showing current retrieval strengths, current failures, and whether later retrieval changes improved or regressed quality.

## 3. Non-Goals

V2.3 does not implement:

- Vector database or embedding search.
- LLM query planning or query rewriting.
- Cross-encoder, embedding, or LLM reranking.
- MinerU, OCR, table parsing, or formula parsing improvements.
- A Web UI or Obsidian plugin.
- A new answer-generation prompt.
- Automatic synthesis quality upgrades.
- Any change that lets LLMs write formal wiki pages outside staging/apply.

Those belong to later stages. V2.3 creates the measurement layer they must pass.

## 4. Design Principles

### 4.1 Evaluation Before Retrieval Redesign

Future retrieval work must be judged against stable eval cases instead of ad hoc examples. A change is not accepted only because one question looks better; it must improve or preserve measured quality across the suite.

### 4.2 Evidence Is The Product Boundary

LLMWiki is not only a RAG chatbot. It is a source-backed research wiki. Retrieval output must remain auditable:

- Every returned claim must exist in the catalog.
- Every citation must point to a source id and locator.
- Every page path must exist or be a valid catalog page path.
- `contradicts` relationships must remain visible.
- weak or uncited evidence must be labeled.

### 4.3 Local Baseline First, Model Evaluation Later

The default V2.3 eval runner must not call an external LLM. It should evaluate retrieval and evidence-contract properties deterministically. Optional LLM-as-judge metrics may be added later behind explicit flags, but they are not required for the first V2.3 implementation.

### 4.4 Backward Compatibility

Existing `retrieve` JSON keys must remain valid:

- `question`
- `contexts`
- `relationships`
- `warnings`

V2.3 may add fields, but it must not remove or rename existing fields.

## 5. Evidence Contract

V2.3 defines a versioned evidence bundle. Existing callers can keep using the current shape, while new fields make evaluation and diagnostics possible.

### 5.1 Retrieval Result

`retrieve_context(...)` should return:

```json
{
  "schema_version": "retrieval.v2.3",
  "question": "草莓应该怎么保存？",
  "contexts": [],
  "relationships": [],
  "warnings": [],
  "diagnostics": {
    "query_terms": [],
    "candidate_count": 0,
    "returned_count": 0,
    "failure_stage": null
  }
}
```

`schema_version` and `diagnostics` are additive. Existing consumers that only use `contexts`, `relationships`, and `warnings` continue to work.

### 5.2 Evidence Context

Each context should be treated as an evidence unit:

```json
{
  "rank": 1,
  "claim_id": "clm_src_xxx_llm_001",
  "source_id": "src_xxx",
  "citation_locator": "section:保存方法",
  "claim_text": "草莓适合冷藏保存。",
  "page_path": "wiki/concepts/草莓.md",
  "page_type": "concept",
  "relationship_type": "supports",
  "confidence_status": "cited",
  "score": 0.82,
  "retrieval_reasons": [
    "catalog_title_match",
    "lexical_match"
  ]
}
```

Required fields for V2.3 evaluation:

- `claim_id`
- `source_id`
- `citation_locator`
- `claim_text`
- `page_path`
- `relationship_type`
- `score`

Recommended additive fields:

- `rank`
- `page_type`
- `confidence_status`
- `retrieval_reasons`

### 5.3 Relationship Contract

Relationships must preserve the existing shape:

```json
{
  "subject_id": "concept:草莓",
  "object_id": "src_xxx",
  "relationship_type": "supports",
  "evidence_claim_id": "clm_src_xxx_llm_001",
  "source_id": "src_xxx"
}
```

Evaluation must check that:

- relationship endpoints refer to catalog pages or known source ids when applicable;
- `evidence_claim_id` exists in catalog claims;
- contradictions are returned when the retrieved evidence set contains them;
- graph relationship output does not forge ids.

## 6. Evaluation Dataset

V2.3 introduces a committed eval dataset format. The first implementation should support JSONL because it is easy to diff and extend.

Recommended path:

```text
tests/evals/retrieval_v2_3.jsonl
```

Each case:

```json
{
  "id": "fruit_zh_strawberry_storage_natural",
  "question": "草莓应该怎么保存？",
  "language": "zh",
  "query_type": "natural_question",
  "expected_status": "has_evidence",
  "expected_claim_ids": [],
  "expected_source_ids": ["src_99ab0495789d"],
  "expected_page_ids": ["concept:草莓"],
  "expected_terms": ["草莓", "保存", "冷藏"],
  "must_expose_relationship_types": ["supports"],
  "notes": "Natural Chinese wording should retrieve strawberry storage evidence."
}
```

### 6.1 Expected Claim IDs Are Optional

For deterministic unit fixtures, eval cases should use exact `expected_claim_ids`.

For live LLM-generated workspaces, exact claim ids can be brittle because LLM extraction may change claim granularity. In those cases, the eval case may use:

- `expected_source_ids`
- `expected_page_ids`
- `expected_terms`
- `must_expose_relationship_types`

This lets the suite evaluate both stable test fixtures and real project walkthroughs.

### 6.2 Required Case Families

The initial dataset should include:

- English keyword query.
- English natural question.
- Chinese keyword query.
- Chinese natural question.
- Multi-source comparison question.
- No-evidence negative question.
- Contradiction exposure case.
- Alias case such as `RAG` and `retrieval augmented generation`.
- Unicode/multilingual smoke case.
- Formula or symbol smoke case.

The first fruit cases should cover:

- `草莓应该怎么保存？`
- `这五种水果里，哪种更适合补充维生素 C？`
- `香蕉适合需要控制血糖的人多吃吗？`
- `苹果和橙子哪个维生素 C 更有优势？`
- `芒果的能量和糖分需要注意什么？`

## 7. Metrics

The metrics are split into three groups: retrieval metrics, answer metrics, and LLMWiki evidence metrics.

### 7.1 Retrieval Metrics

These measure whether the retrieval layer found the right evidence.

- `hit_at_k`: whether at least one expected evidence item appears in top K.
- `recall_at_k`: expected relevant items retrieved in top K divided by expected relevant items.
- `precision_at_k`: retrieved relevant items in top K divided by K.
- `mrr`: reciprocal rank of the first relevant evidence item.
- `ndcg_at_k`: ranking quality when eval cases provide graded relevance.
- `context_precision`: whether retrieved contexts are relevant to the question.
- `context_recall`: whether retrieved contexts cover the evidence needed to answer.
- `context_entity_recall`: whether expected entities or concepts appear in retrieved contexts.

For V2.3, `hit_at_k`, `recall_at_k`, `precision_at_k`, and `mrr` are required. `ndcg_at_k` and entity recall are recommended if the dataset includes graded relevance or entity labels.

### 7.2 Answer Metrics

These are RAG generator metrics. They are recorded in the spec now, but V2.3 does not need to fully automate them unless deterministic answer fixtures already exist.

- `faithfulness`: generated answer claims are supported by retrieved context.
- `groundedness`: generated answer can be traced to retrieved evidence.
- `answer_relevance`: answer addresses the user question.
- `answer_correctness`: answer matches a reference answer when one exists.
- `citation_coverage`: every factual answer claim has at least one citation.
- `unsupported_claim_rate`: fraction of answer claims not supported by retrieved evidence.
- `insufficient_evidence_accuracy`: no-evidence questions return insufficient evidence instead of a fabricated answer.

These metrics are mostly for `ask`, not bare `retrieve`.

### 7.3 LLMWiki Evidence Metrics

These are specific to this project:

- `claim_id_validity`: all returned claim ids exist in catalog.
- `source_id_validity`: all returned source ids exist in catalog sources or accepted synthetic source namespace.
- `citation_locator_presence`: returned evidence includes non-empty source locators when available.
- `page_path_validity`: returned page paths exist in catalog pages.
- `relationship_validity`: returned relationship rows reference valid subject/object/evidence ids.
- `contradiction_exposure_rate`: contradiction cases return `contradicts` relationships or warnings.
- `weak_uncited_warning_rate`: weak or uncited evidence produces visible warnings.
- `filter_correctness`: `--source-id`, `--page-type`, and `--confidence` filters are respected.
- `no_secret_leak_rate`: eval output does not include API keys, config secrets, or local secret file contents.

These metrics should be treated as hard quality gates. A retrieval method that improves semantic recall but breaks citation validity is not acceptable.

### 7.4 Operational Metrics

The eval report should also capture:

- `latency_ms_p50`
- `latency_ms_p95`
- `llm_calls`
- `estimated_cost`
- `deterministic_reproducibility`
- `error_count`

For V2.3 local evaluation, `llm_calls` should normally be `0`.

## 8. RAG Metric References

V2.3 aligns with common RAG evaluation practice:

- Ragas uses metrics such as faithfulness, response relevancy, context precision, context recall, context entity recall, and noise sensitivity for RAG evaluation.
- TruLens describes the RAG triad as context relevance, groundedness, and answer relevance.
- DeepEval lists RAG metrics including answer relevancy, faithfulness, contextual relevancy, contextual precision, and contextual recall.
- RAGChecker separates overall claim-level precision/recall/F1, retriever metrics, and generator metrics.

LLMWiki should use these as vocabulary, but it must not stop there. The project also needs evidence-contract metrics because its unit of trust is not just a text chunk; it is a catalog claim with source provenance.

Reference links:

- https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/
- https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/faithfulness/
- https://www.trulens.org/getting_started/core_concepts/rag_triad/
- https://deepeval.com/docs/getting-started-rag
- https://arxiv.org/abs/2408.08067

## 9. CLI And API Surface

V2.3 should add an evaluation command for development and regression checking:

```bash
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_3.jsonl
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_3.jsonl --json
```

Expected human output:

```text
Retrieval eval: tests/evals/retrieval_v2_3.jsonl

Cases: 12
Passed: 8
Failed: 4

Core metrics:
- hit@5: 0.75
- recall@5: 0.62
- precision@5: 0.41
- mrr: 0.58

Evidence contract:
- claim_id_validity: 1.00
- source_id_validity: 1.00
- citation_locator_presence: 1.00
- contradiction_exposure_rate: 0.50

Failures:
- fruit_zh_strawberry_storage_natural: candidate_miss
- fruit_zh_vitamin_c_comparison: ranking_miss
```

Expected JSON output:

```json
{
  "schema_version": "eval.retrieval.v2.3",
  "dataset": "tests/evals/retrieval_v2_3.jsonl",
  "case_count": 12,
  "summary": {
    "passed": 8,
    "failed": 4,
    "hit_at_5": 0.75,
    "recall_at_5": 0.62,
    "precision_at_5": 0.41,
    "mrr": 0.58
  },
  "evidence_contract": {
    "claim_id_validity": 1.0,
    "source_id_validity": 1.0,
    "citation_locator_presence": 1.0,
    "contradiction_exposure_rate": 0.5
  },
  "cases": []
}
```

Generated eval reports should be treated as local artifacts, not source files. Recommended output path when saving reports:

```text
state/evals/
```

## 10. Failure Diagnostics

Each failed case should be classified into one primary failure stage:

- `no_terms`: query analysis produced no useful searchable features.
- `candidate_miss`: no expected source/page/claim entered the candidate set.
- `ranking_miss`: expected evidence was found but ranked below K.
- `filter_miss`: CLI/API filters removed evidence unexpectedly.
- `relationship_miss`: evidence was returned, but required relationships were missing.
- `warning_miss`: weak/uncited or contradiction warning was missing.
- `contract_violation`: returned ids, locators, or paths were invalid.
- `unexpected_evidence`: no-evidence case returned evidence.
- `runtime_error`: command or API crashed.

This matters because different failures require different future fixes. For example:

- `no_terms` points to query analysis.
- `candidate_miss` points to retriever coverage.
- `ranking_miss` points to fusion or reranking.
- `relationship_miss` points to catalog graph handling.
- `contract_violation` blocks release even if recall improved.

## 11. Testing Strategy

V2.3 implementation should add tests for:

- Eval dataset parsing.
- Exact claim-id matching.
- Source/page/term fallback matching.
- Metrics calculation for hit@K, recall@K, precision@K, and MRR.
- Evidence-contract validation.
- Failure-stage classification.
- CLI human output.
- CLI JSON output.
- Secret redaction.
- Existing `retrieve`, `query`, and `ask` tests continuing to pass.

The first test command should be:

```bash
python -m pytest tests/test_retrieval_eval.py -q
```

Regression commands:

```bash
python -m pytest tests/test_retrieval.py tests/test_query_lint_doctor.py tests/test_ask_workflow.py -q
python -m pytest -q
python -m llmwiki --help
```

## 12. Data And Git Hygiene

Committed files:

- Eval dataset definitions under `tests/evals/`.
- Eval unit tests.
- V2.3 documentation and implementation.

Ignored/generated files:

- `state/evals/*.json`
- `state/evals/*.md`
- generated wiki pages
- generated staging runs
- `state/catalog.sqlite`
- secret config files

The eval runner must not write to `wiki/`, `staging/`, or `sources/`. It is read-only against the workspace catalog.

## 13. Acceptance Criteria

V2.3 is complete when:

- `llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_3.jsonl` runs successfully.
- JSON eval output is stable and parseable.
- The eval suite records current retrieval failures, including natural Chinese question failures if still present.
- Core retrieval metrics are computed.
- Evidence-contract metrics are computed.
- Each failed case includes a failure-stage diagnosis.
- No LLM API is called by default during retrieval eval.
- No API keys or secret config contents appear in eval output.
- Existing `retrieve`, `query`, `ask`, `add`, staging/apply, and lint tests continue to pass.

## 14. Relationship To Later Stages

V2.3 is the quality gate for later retrieval work:

- V2.4 Hybrid Local Retrieval must improve retrieval metrics without weakening evidence-contract metrics.
- V2.5 LLM Query Planning must improve recall on natural and comparison questions while keeping `retrieve` deterministic by default.
- V2.6 Embedding + Vector Store must improve semantic recall and preserve citation validity.
- V2.7 Reranking + Evidence Selection must improve precision, MRR, and answer faithfulness.
- V2.8 Synthesis Quality must improve writeback usefulness while preserving citation coverage and contradiction visibility.

The project should not accept major retrieval changes without running the V2.3 eval suite first.
