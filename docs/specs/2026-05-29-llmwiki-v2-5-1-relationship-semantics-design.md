# LLMWiki V2.5.1: Relationship Semantics Fix

## 1. Background

V2.5 added LLM query planning for `ask`, and the actual answer generation now correctly depends on local retrieved evidence. During real acceptance on the five fruit documents in `docs/tests`, every normal answer still surfaced the warning:

```text
Contradictory evidence is present.
```

The warning itself comes from retrieval and is correct when real `contradicts` relationships exist. The false positives come earlier, during ingest. Current ingest treats negative wording as a conflict signal:

```python
conflict_terms = ("contradict", "conflict", "disagree", "not ", "不", "无需", "不需要", "冲突", "矛盾")
```

This means claims such as "不建议多吃", "不耐储存", "不要提前清洗", or "不需要..." can become `contradicts` relationships even when they are merely cautions, limitations, storage instructions, or negative factual claims.

That is not the intended semantics. In LLMWiki, a contradiction means a source-backed claim conflicts with another source-backed claim about the same subject, property, scope, and context. A single negative claim is not a contradiction by itself.

## 2. Goal

V2.5.1 fixes relationship semantics so `contradicts` means actual disagreement between claims, not the presence of negation.

The immediate goals are:

- Remove rule-based negation conflict detection from ingest.
- Stop converting ordinary negative/caution claims into `contradicts` relationships.
- Keep genuine `contradicts` relationships visible in `retrieve`, `query`, `ask`, synthesis, and eval.
- Preserve uncertainty without fabricating conflict relationships.
- Make tests and docs distinguish "negative claim" from "contradictory evidence".

V2.5.1 is successful when the five fruit documents can be ingested and asked against without broad false `Contradictory evidence is present` warnings, while explicit contradiction fixtures still surface as contradictions.

## 3. Non-Goals

V2.5.1 does not implement:

- A full contradiction detection model.
- Embedding, vector search, or reranking.
- Domain-specific nutrition, fruit, storage, medical, or Chinese keyword rules.
- Automatic resolution of conflicts.
- A database schema migration for pairwise claim relationships.
- UI changes.
- Web search or external benchmark ingestion.

Richer conflict discovery and evidence selection belong to later work, especially V2.7 reranking/evidence selection or a dedicated relationship-classification phase.

## 4. Relationship Semantics

### 4.1 `supports`

`supports` means the page/source relationship is backed by a source-backed claim. It is the default relationship for claims that support a concept, entity, source page, or synthesis evidence map.

### 4.2 `contains`

`contains` means a source page contains or contributes to a concept/entity page. It is structural, not evidential disagreement.

### 4.3 `contradicts`

`contradicts` means two source-backed assertions cannot both be accepted as true under the same relevant context.

A valid contradiction should involve:

- a new or retrieved claim,
- an existing opposing claim or explicit opposing source-backed assertion,
- the same subject or clearly linked subjects,
- the same property or proposition,
- comparable scope and context,
- a reason explaining why both claims cannot simultaneously hold.

Examples that can be contradictions:

- Source A says a method requires citation anchors; Source B says the same method does not require citation anchors.
- Source A says a value is 10 under a named condition; Source B says the same value under the same condition is 20.
- Source A says a policy allows an action; Source B says the same policy forbids it.

Examples that are not contradictions by themselves:

- "草莓不耐储存。"
- "香蕉糖分较高，不建议需要控制血糖的人多吃。"
- "芒果不适合所有人群大量食用。"
- "食用前不需要提前清洗。"
- "This workflow does not require X" when no opposing source-backed claim about X exists in the catalog.

These are negative or cautionary claims. They may be important evidence, but they must remain normal claims unless there is an actual opposing claim.

### 4.4 Conflict Notes Versus Formal Relationships

LLM or human triage may still record possible conflict notes. A possible conflict note is not automatically a formal `contradicts` relationship.

Formal `contradicts` relationships must be created only when the system can validate that the relationship refers to real local catalog/staged claims and does not rely only on lexical negation.

The current `relationships` table is page/source-oriented and cannot fully represent both sides of a pairwise claim conflict. V2.5.1 therefore treats `contradicts` rows as an exposure signal and keeps exact opposing claim details in triage when available. A future schema can add explicit `subject_claim_id` and `object_claim_id`; V2.5.1 should not block on that migration.

## 5. Public Behavior

### 5.1 `llmwiki add`

Normal import remains:

```bash
llmwiki add docs/tests/<file>.md --root .
```

After V2.5.1:

- Ingest must not create `contradicts` because a claim contains `不`, `not`, `不需要`, `不建议`, or similar negation.
- Negative/caution claims still become cited claims.
- `triage.md` may mention uncertainty or weak evidence, but should not label every negative statement as a conflict.
- The staged patch should include `contradicts` only for a validated actual disagreement.

### 5.2 `llmwiki retrieve`

`retrieve` behavior remains:

- It exposes existing local catalog relationships.
- If genuine `contradicts` relationships exist, it still returns them and emits the contradiction warning.
- If no genuine `contradicts` exists, it must not warn only because retrieved text contains negation.

### 5.3 `llmwiki ask`

`ask` behavior remains planner-first:

```text
question
-> LLM planner
-> local retrieve
-> grounded answer from retrieved evidence
```

After V2.5.1, ordinary fruit questions should not all include contradiction warnings. Answers should still remain conservative when evidence is insufficient, weak, or not quantitative.

### 5.4 `llmwiki lint`

`lint` may continue reporting recorded `contradicts` relationships. It must not infer unresolved contradictions from negation terms alone.

## 6. Design

### 6.1 Disable Rule-Based Conflict Discovery

`llmwiki.ingest.find_conflict_candidates` should no longer use hard-coded negation or conflict keyword rules to create formal conflict candidates.

The V2.5.1 default should be:

```text
heuristic conflict candidates = []
```

This preserves the project direction: no brittle domain/content rules for unknown research corpora.

### 6.2 Treat LLM Conflict Output As Triage Until Validated

LLM ingest proposals may still produce `conflict_candidates`, but arbitrary strings from the LLM must not automatically become `contradicts` relationships.

Acceptable V2.5.1 behavior:

- Keep LLM conflict text in `triage.md` as a possible conflict note.
- Do not create a formal `contradicts` row unless a strict validator can identify real known claim ids or staged claim ids on both sides.
- If validation fails, keep the note visible but do not promote it to catalog relationship.

This prevents an LLM from creating forged or vague contradiction relationships while still preserving uncertainty for review/debug.

### 6.3 Preserve Explicit Relationship Fixtures

Tests and fixtures that need a contradiction should create it explicitly rather than relying on negation text.

Valid paths:

- seed a catalog `relationships` row directly in retrieval tests;
- stage a patch with an explicit `contradicts` relationship and valid local ids;
- use a future structured relationship proposal once implemented.

Invalid path:

- write a claim containing `not`, `不`, or `不需要` and expect ingest to infer `contradicts`.

### 6.4 Keep Retrieval Warning Logic

`llmwiki.retrieval` should not hide `contradicts`. Its current responsibility is correct:

- if a returned context or relationship is `contradicts`, warn;
- otherwise do not warn.

The fix belongs in relationship creation, not warning display.

## 7. Data Contract

No SQLite migration is required in V2.5.1.

Existing relationship rows remain:

```text
subject_id
object_id
relationship_type
evidence_claim_id
source_id
```

For `contradicts`, the implementation must ensure:

- `relationship_type == "contradicts"`;
- `evidence_claim_id` references a real staged or catalog claim;
- `source_id` references a real source;
- `subject_id` and `object_id` remain valid local identifiers accepted by existing apply/retrieval logic;
- if there is an opposing claim id, it is recorded in triage until the schema can store it directly.

## 8. Error Handling

If a proposed contradiction cannot be validated:

- do not fail the whole `add` pipeline only because conflict validation failed;
- do not create the formal relationship;
- add a warning or triage note such as `Unvalidated conflict candidate`;
- do not leak API keys, raw provider payload secrets, or config file contents.

If apply validation rejects an explicit relationship:

- the run should fail in the existing staging/apply failure path;
- no partial wiki/catalog mutation should remain.

## 9. Testing Requirements

### 9.1 Unit Tests

Add or update tests covering:

- `find_conflict_candidates` returns no candidates for ordinary negative statements.
- `possible_conflict` or equivalent keyword heuristic no longer promotes negation to contradiction.
- LLM conflict strings without valid claim ids remain triage notes, not relationships.
- Explicit `contradicts` relationships are still preserved and retrievable.

Example negative non-conflicts:

```text
草莓不耐储存。
香蕉不建议需要控制血糖的人多吃。
芒果不适合所有人群大量食用。
食用前不需要提前清洗。
This workflow does not require citation anchors.
```

### 9.2 Ingest Regression

Using the five `docs/tests` fruit documents:

- clean generated wiki/source/staging/state artifacts;
- run the normal `llmwiki add` flow for all five documents;
- assert broad false `contradicts` relationships are not created;
- assert negative/caution claims still exist as normal claims;
- run representative `ask` questions and assert contradiction warning is absent unless a real contradiction was explicitly seeded.

### 9.3 Retrieval Regression

Existing retrieval behavior must still pass:

- `retrieve` returns real relationships from the catalog.
- `query` reuses `retrieve`.
- `ask` uses retrieved relationships and warnings.
- `eval retrieval` can still measure contradiction exposure for explicitly curated contradiction cases.

V2.3 contradiction eval cases may need to be updated so they rely on explicit contradiction fixtures, not negation-triggered ingest heuristics.

## 10. Documentation Updates

Update:

- `AGENTS.md`
- `README.md`
- any retrieval/ingest sections that imply negation means contradiction

Documentation should state:

- `contradicts` means source-backed disagreement between claims;
- negative or cautionary claims are not contradictions by themselves;
- `retrieve` exposes contradictions but does not decide whether text is contradictory;
- automatic rule-based contradiction detection is disabled in V2.5.1.

## 11. Acceptance Criteria

V2.5.1 is complete when:

- Ingest no longer creates `contradicts` from negation keywords.
- The five fruit documents no longer produce broad false contradiction warnings.
- `ask "草莓应该怎么保存？"` can answer from storage evidence without `Contradictory evidence is present`.
- `ask "香蕉适合需要控制血糖的人多吃吗？"` can cite caution evidence without treating caution as contradiction.
- Explicit contradiction fixtures still return `contradicts` in `retrieve` and trigger the warning.
- Retrieval eval still measures contradiction exposure using explicit contradiction cases.
- Full tests pass.
- Generated wiki/source/staging/state artifacts remain untracked.

## 12. Open Questions

These are intentionally deferred from V2.5.1:

- Should the database add pairwise claim relationship fields such as `subject_claim_id` and `object_claim_id`?
- Should contradiction classification become an LLM relationship classifier after ingest?
- Should contradiction detection run during `add`, during eval/lint, or as a separate maintenance command?
- Should synthesis pages summarize unresolved contradictions as separate durable knowledge objects?

The immediate fix does not require answering these. It only restores the correct semantics by stopping false contradiction creation.
