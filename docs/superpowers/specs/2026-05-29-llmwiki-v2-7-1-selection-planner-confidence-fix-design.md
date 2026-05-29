# LLMWiki V2.7.1: Evidence Selection, Planner Repair, and Confidence Semantics Fix

## 1. Background

V2.7 added reranking and evidence selection after hybrid/vector recall. The end-to-end acceptance run on the five fruit documents showed that the main pipeline works, but three quality issues remain:

- focused questions such as `草莓应该怎么保存？` can select evidence from other fruits because the selector over-prioritizes source diversity;
- `ask --writeback` can therefore create a synthesis page whose evidence map includes non-target sources;
- the LLM planner can output an invalid filter such as `confidence = "high"`, causing `planning_invalid` instead of attempting schema repair;
- ingest can leave a claim as `uncited` even when it has a valid source locator.

V2.7.1 is a repair release. It does not add a new retriever, vector store, UI, external benchmark, or LLM relationship classifier.

## 2. Goals

V2.7.1 must make evidence selection sensitive to question structure without adding domain-specific rules.

It must:

- distinguish focused, comparison, conflict, and broad evidence selection modes;
- prevent focused single-subject questions from mixing unrelated source evidence when enough target evidence exists;
- keep comparison questions multi-source and multi-subject;
- preserve explicit `contradicts` relationships and weak/uncited evidence visibility;
- repair invalid planner JSON once before failing;
- normalize confidence so claims with valid locators are not left as `uncited`;
- keep `retrieve/query/eval retrieval` free of chat LLM calls by default.

## 3. Non-Goals

V2.7.1 does not implement:

- V2.8 synthesis quality work;
- LLM evidence selection;
- LLM relationship classification;
- automatic contradiction inference;
- external search;
- new vector DB or embedding provider;
- domain-specific boosts such as fruit, vitamin, storage, sugar, or nutrition rules.

## 4. Evidence Selection Modes

Add a generic selection mode concept to `llmwiki/evidence_selection.py`.

Modes:

- `focused`: one dominant subject/source/page is enough to answer; do not force unrelated sources.
- `comparison`: multiple subjects or sources must be represented where evidence exists.
- `conflict`: explicit catalog `contradicts` relationships must be exposed.
- `broad`: exploratory or under-specified questions may use source diversity.

The mode is not a domain classifier. It is derived from generic signals:

- planner intent and required evidence coverage for `ask`;
- number of planner subqueries and catalog refs;
- number of catalog terms matched by query analysis;
- candidate distribution by `coverage_group`;
- explicit relationship requirements;
- retrieval/eval filters.

Default behavior:

- `ask` uses planner structure first.
- `retrieve/query` use local query-analysis and candidate-distribution signals only.
- if uncertain, choose `broad`, but do not override a strong single dominant coverage group.

## 5. Focused Selection Rules

For `focused` mode:

- select the best cited evidence from the dominant coverage group first;
- fill remaining slots from the same source/page/concept while high-quality same-group evidence exists;
- allow outside-source evidence only when same-group evidence is insufficient or when it is required by explicit relationship exposure;
- do not select weak/uncited evidence over cited evidence in the same coverage group;
- keep `max_contexts_per_source` from suppressing the target source in focused mode.

Acceptance examples:

- `retrieve "草莓买回来怎样放才不容易坏？"` should return strawberry storage evidence first and should not include apple/orange/banana/mango in the final contexts when enough strawberry evidence exists.
- `query "草莓应该怎么保存？"` should show only strawberry evidence under normal five-fruit catalog conditions.
- `ask "草莓应该怎么保存？" --no-writeback` should cite only `src_99ab0495789d`.
- `ask "草莓应该怎么保存？" --writeback` should create a synthesis page whose `claim_ids` all belong to strawberry evidence.

## 6. Comparison Selection Rules

For `comparison` mode:

- preserve coverage across compared subjects/sources where evidence exists;
- prefer one or two strong cited claims per subject before adding more from the same source;
- expose missing or uneven evidence via diagnostics/warnings instead of silently choosing a winner;
- keep rerank scores visible but do not let a single source monopolize the final context set.

Acceptance examples:

- `ask "这五种水果里哪种更适合补充维生素 C？"` should cite multiple fruit sources when retrieved evidence exists.
- if one fruit lacks evidence, answer output should make the evidence gap visible.

## 7. Planner Repair

Planner validation remains strict, but malformed or schema-invalid JSON gets one repair attempt.

Repair applies to:

- malformed JSON;
- invalid enum values such as `confidence = "high"`;
- invalid filter keys;
- source/page refs that are syntactically invalid or unknown;
- output that includes forbidden evidence fields.

Repair prompt must include:

- the validation error;
- the original planner output;
- the allowed planner schema;
- allowed filter values: `source_id`, `page_type`, `confidence`; `confidence` may only be `null`, `cited`, or `weak`.

Repair must not silently map `high` to `cited`. The LLM must produce a valid plan. If repair fails, return `planning_invalid` as today.

Acceptance example:

- when the planner first returns `confidence = "high"`, `ask` should attempt repair once; if repaired to valid JSON, it should proceed to local retrieval and answer generation.

## 8. Confidence Semantics During Ingest

`confidence_status` must reflect whether a claim has a valid locator.

Rules:

- if a claim has a valid source locator, normalize `confidence_status` to `cited`;
- if locator is missing or invalid, mark it `weak` or `uncited`;
- do not invent locators;
- keep locator validation generic and based on existing normalized source anchors, not on domain content.

Lint should distinguish:

- `uncited_without_locator`: real missing citation issue;
- `uncited_with_locator`: confidence inconsistency that should be normalized during ingest.

Acceptance example:

- after ingesting the five fruit documents, `llmwiki lint --root .` should not fail only because a claim with a valid locator was marked `uncited`.

## 9. Eval Dataset Semantics

The current V2.7 eval dataset mixes real five-fruit expectations with fixture-only expectations.

V2.7.1 should split this:

- keep a real five-fruit eval dataset that can pass against `docs/tests`;
- move conflict and weak-evidence cases to deterministic seeded test workspaces;
- do not require real fruit data to contain explicit `contradicts` or `src_weak`.

Acceptance examples:

- `llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_7_evidence_selection_fruits.jsonl` should not fail because the real fruit catalog has no explicit contradiction fixture.
- unit/integration tests must still prove explicit contradictions and weak evidence remain visible when seeded.

## 10. Diagnostics

`retrieve_context` diagnostics should include:

- `selection.mode`;
- `selection.mode_reason`;
- `selection.dominant_coverage_group`;
- `selection.outside_group_selected_count`;
- `selection.missing_required_coverage`;
- existing reranking and selection counters.

Contexts should keep existing V2.7 fields:

- `candidate_rank`;
- `rerank_score`;
- `selection_reason`;
- `coverage_group`;
- `redundancy_group`.

## 11. Safety And Compatibility

V2.7.1 must preserve:

- `retrieval.v2.7` schema compatibility;
- source-backed evidence contract;
- no default chat LLM calls in `retrieve/query/eval retrieval`;
- opt-in-only LLM reranking;
- explicit `contradicts` relationship visibility;
- staging/apply safety for synthesis writeback.

No database migration is required.

## 12. Test And Acceptance Plan

Required tests:

- focused selector keeps same-source evidence for single-subject questions;
- comparison selector keeps multi-source coverage;
- explicit contradiction evidence is still selected in conflict mode;
- weak/uncited evidence remains visible but is not upgraded;
- planner invalid `confidence = "high"` triggers one repair and proceeds if repaired;
- planner repair failure still returns `planning_invalid`;
- ingest normalizes valid-locator claims to `cited`;
- lint no longer fails on `uncited_with_locator`;
- synthesis writeback for `草莓应该怎么保存？` cites only strawberry evidence;
- V2.7 fruit eval passes against real `docs/tests` catalog;
- retrieve/query/eval retrieval still do not call chat LLM providers.

Real acceptance:

```powershell
llmwiki init --root .
llmwiki add docs/tests/草莓_酸甜可口的浆果类水果.md --root .
llmwiki add docs/tests/橙子_富含维生素C的柑橘类水果.md --root .
llmwiki add docs/tests/芒果_香甜浓郁的热带水果.md --root .
llmwiki add docs/tests/苹果_营养均衡的日常水果.md --root .
llmwiki add docs/tests/香蕉_方便食用的能量补充水果.md --root .
llmwiki embeddings rebuild --root .
llmwiki retrieve "草莓买回来怎样放才不容易坏？" --root . --json
llmwiki ask "草莓应该怎么保存？" --root . --no-writeback --json
llmwiki ask "草莓应该怎么保存？" --root . --writeback --json
llmwiki ask "这五种水果里哪种更适合补充维生素 C？" --root . --no-writeback --json
llmwiki lint --root .
llmwiki eval retrieval --root . --dataset tests/evals/retrieval_v2_7_evidence_selection_fruits.jsonl
```

The flow is accepted when:

- focused strawberry retrieve/ask/writeback cite only strawberry evidence;
- comparison vitamin C ask returns multiple fruit evidence where available;
- planner repair prevents valid repairable plans from failing on `confidence = "high"`;
- lint has no false failure caused by valid-locator uncited claims;
- generated wiki/catalog still preserve citation-backed evidence only.
