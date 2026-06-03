# LLMWiki V2.8: Synthesis Quality

## 1. Background

V2.2 introduced `llmwiki ask` and optional synthesis writeback. A useful answer can already be written through staging/apply into `wiki/syntheses/*.md`.

V2.4 through V2.7.1 then improved the evidence path behind `ask`:

- local hybrid retrieval;
- LLM query planning for `ask`;
- local vector recall;
- reranking and evidence selection;
- focused/comparison/conflict selection modes;
- planner repair and locator-backed confidence normalization.

The remaining quality gap is no longer only retrieval. It is the durability of written synthesis pages.

Today a synthesis writeback is still close to a saved answer:

- each approved answer tends to create a new page;
- repeated or near-duplicate questions can create duplicate syntheses;
- existing synthesis pages are not updated as living knowledge objects;
- the page does not clearly separate conclusion, evidence map, analysis, conflicts, and open questions as durable sections;
- the user cannot inspect the intended knowledge structure before confirming an interactive writeback;
- relationships between syntheses are not first-class enough to support long-term navigation.

V2.8 makes synthesis writeback produce maintainable research wiki pages instead of one-off Q&A records.

## 2. Goals

V2.8 must improve synthesis quality while preserving the source-backed evidence contract.

It must:

- plan synthesis writeback before applying it;
- decide whether to create a new synthesis page or update an existing one;
- avoid near-duplicate synthesis pages for equivalent or strongly overlapping topics;
- preserve and merge existing synthesis content instead of overwriting user-authored sections blindly;
- render synthesis pages as durable knowledge products with explicit evidence maps, analysis, conflicts, and open questions;
- show a concise writeback preview before interactive confirmation;
- keep `--writeback` available for explicit non-interactive approval;
- continue to write through `staging/<run-id>/` and `apply_run`;
- keep all formal evidence grounded in existing catalog claims;
- expose synthesis relationships in catalog links/relationships where useful.

V2.8 is successful when repeated questions such as:

```text
草莓应该怎么保存？
草莓买回来怎样放才不容易坏？
```

update one maintainable strawberry storage synthesis rather than creating duplicate pages, while comparison questions still produce or update a broader comparison synthesis.

## 3. Non-Goals

V2.8 does not implement:

- new source import or parsing;
- MinerU, PDF OCR, table extraction, or image evidence;
- new retrieval families;
- new vector database storage;
- LLM relationship classification;
- automatic contradiction resolution;
- concept/entity page rewriting from synthesis;
- external web search;
- UI or Obsidian plugin;
- multi-user review or permissions;
- automatic writeback without user approval.

V2.9 remains the rich source parsing phase.

## 4. Design Principles

### 4.1 Synthesis Is Not A Source

A synthesis page organizes and interprets existing source-backed evidence. It must not create new formal source-backed claims.

V2.8 may store analysis, conclusions, open questions, and user-approved synthesis text in Markdown, but formal citations must still point to existing catalog `claim_id`, `source_id`, `citation_locator`, and `page_path`.

### 4.2 LLM Can Propose Structure, Not Evidence

V2.8 may use the configured LLM to propose:

- topic title;
- create vs update action;
- section content;
- evidence roles;
- open questions;
- synthesis-to-synthesis relationships.

The LLM must not invent claim ids, source ids, locators, page paths, or relationship targets. Every proposed evidence reference must be validated against the retrieved contexts and catalog.

### 4.3 Existing Pages Are Living Documents

When a new answer is about an existing synthesis topic, the default action should be update, not create.

Updates must preserve:

- existing evidence claim ids unless the catalog no longer contains them;
- user-authored sections outside managed synthesis sections;
- prior revision notes;
- visible conflicts and uncertainties.

If a merge cannot be made safely, V2.8 should fail the writeback or stage a clearly inspectable debug run instead of silently overwriting the page.

### 4.4 Preview Before Interactive Writeback

Interactive writeback should show the user what will be written before asking for confirmation:

- action: `create` or `update`;
- target page;
- title;
- evidence claim ids;
- sections to create or update;
- conflicts and open questions;
- related pages and synthesis relationships.

`--writeback` remains explicit approval and may apply without a prompt, but it should still print or return the same plan summary.

### 4.5 Staging And Apply Remain Mandatory

V2.8 must not directly mutate:

- `wiki/syntheses/*.md`;
- `wiki/index.md`;
- `wiki/log.md`;
- `state/catalog.sqlite`.

All writeback changes still become a staging run and then pass existing apply validation.

## 5. User-Facing Behavior

### 5.1 Normal Ask Without Writeback

```powershell
llmwiki ask "草莓应该怎么保存？" --root .
```

The command still answers from retrieved local evidence. In an interactive terminal, after the answer it may show a synthesis proposal and ask whether to write or update a synthesis page.

If the user says no, no persistent artifact is written.

### 5.2 Explicit Writeback

```powershell
llmwiki ask "草莓应该怎么保存？" --root . --writeback
```

The command must:

1. answer from local evidence;
2. build a synthesis writeback plan;
3. validate the plan;
4. create a staging run;
5. apply it;
6. print the action and page path.

Example human output shape:

```text
Question: 草莓应该怎么保存？
Answer: ...
Citations:
- clm_strawberry_storage from src_99ab0495789d at line:12

Synthesis proposal:
- action: update
- page: wiki/syntheses/strawberry-storage.md
- title: Strawberry Storage
- evidence claims: 4
- sections: Current Answer, Evidence Map, Analysis, Open Questions, Revision History
- related pages: wiki/concepts/strawberry.md

Applied synthesis run: run_synthesis_...
Page: wiki/syntheses/strawberry-storage.md
```

### 5.3 JSON Output

`ask --json` keeps existing keys and adds a `synthesis_plan` object when writeback planning runs.

Required fields:

```json
{
  "writeback": {
    "status": "applied",
    "run_id": "run_synthesis_...",
    "pages": ["wiki/syntheses/strawberry-storage.md"],
    "action": "update"
  },
  "synthesis_plan": {
    "schema_version": "synthesis_plan.v2.8",
    "status": "planned",
    "action": "update",
    "target_page_id": "synthesis-strawberry-storage",
    "target_path": "wiki/syntheses/strawberry-storage.md",
    "title": "Strawberry Storage",
    "evidence_claim_ids": ["clm_strawberry_storage"],
    "sections": ["Current Answer", "Evidence Map", "Analysis", "Open Questions"],
    "warnings": []
  }
}
```

If no writeback is requested and the environment is non-interactive, `synthesis_plan` may be omitted or returned with `status="not_planned"` to avoid extra LLM calls.

### 5.4 Optional Preview Mode

V2.8 should add a non-mutating preview path:

```powershell
llmwiki ask "草莓应该怎么保存？" --root . --preview-writeback
```

This runs answer generation and synthesis planning, prints the planned create/update structure, and does not create staging or apply any patch.

`--preview-writeback` is useful for tests, scripts, and user review before an explicit `--writeback`.

## 6. Synthesis Planning

Add a planning layer before staging:

```text
llmwiki/synthesis_planner.py
```

Core types:

```python
SynthesisPlan
SynthesisTarget
SynthesisSection
SynthesisEvidenceItem
SynthesisRelationship
SynthesisPlanningOptions
SynthesisPlanningError
plan_synthesis_writeback(root, ask_result, options) -> SynthesisPlan
validate_synthesis_plan(root, ask_result, plan) -> None
format_synthesis_preview(plan) -> str
```

The planner input should include only bounded local context:

- the question;
- answer fields from `AskResult`;
- selected retrieved contexts and citations;
- planner/retrieval diagnostics needed for synthesis structure;
- summaries of existing synthesis pages:
  - page id;
  - title;
  - aliases;
  - path;
  - frontmatter claim ids;
  - first short summary paragraph;
  - linked page paths;
  - updated timestamp.

The planner must not receive raw source files, API keys, or unrelated wiki page bodies.

## 7. Create Vs Update

### 7.1 Candidate Matching

Before asking the LLM for a final plan, V2.8 should collect candidate existing syntheses.

Candidate sources:

- synthesis pages with overlapping `claim_ids`;
- synthesis pages linked to the same source/concept/entity pages;
- title or alias similarity from catalog aliases;
- same planner concepts/entities if available;
- same dominant evidence source or page for focused questions.

This candidate collection is generic and domain-agnostic. It must not contain fruit, nutrition, storage, or other domain-specific boosts.

### 7.2 LLM Plan Decision

The LLM may choose:

- `create`: no adequate existing synthesis exists;
- `update`: one existing synthesis should absorb the new answer;
- `needs_review`: multiple plausible targets or unsafe merge.

`needs_review` should not auto-apply. It may create a staged debug run only if explicitly requested by a future command; V2.8 default should fail safely with a clear reason and target candidates.

### 7.3 Deterministic Validation

Validation must enforce:

- `action` is one of `create`, `update`, `needs_review`;
- `target_path` is under `wiki/syntheses/`;
- update target exists and has `page_type: synthesis`;
- create target path does not collide unless action becomes `update`;
- every evidence claim id exists in `AskResult.citations` or the local catalog;
- every source id, locator, and page path matches catalog evidence;
- every related page path exists in catalog pages;
- every relationship type is one of catalog-supported values:
  - `supports`;
  - `contradicts`;
  - `refines`;
  - `contains`;
  - `similar_to`;
- no unknown evidence fields are accepted from LLM output;
- no secret config path or API key appears in plan text.

Validation failure returns a safe writeback failure and does not mutate wiki/catalog.

## 8. Page Model

V2.8 synthesis pages should use a stable, maintainable format.

Required frontmatter:

```yaml
---
page_type: synthesis
title: "Strawberry Storage"
aliases: []
source_count: 1
claim_ids: ["clm_strawberry_storage"]
synthesis_id: "synthesis-strawberry-storage"
topic_key: "strawberry-storage"
question_count: 2
revision_count: 3
updated_at: "2026-05-30T..."
---
```

Required sections:

- `## Scope`
- `## Current Answer`
- `## Evidence Map`
- `## Analysis`
- `## Conflicts And Limits`
- `## Open Questions`
- `## Related Pages`
- `## Revision History`

Existing V2.2 section names may be accepted for backward compatibility during parsing:

- `Question/Topic` maps to `Scope`;
- `Short Answer` maps to `Current Answer`;
- `Evidence` maps to `Evidence Map`;
- `Uncertainties` maps to `Conflicts And Limits`.

V2.8 should render new or updated pages using the V2.8 section model.

## 9. Evidence Map

`## Evidence Map` is the main durable upgrade.

It should contain a Markdown table:

```markdown
| Role | Claim | Source | Locator | Page |
| --- | --- | --- | --- | --- |
| supports | `clm_strawberry_storage` | `src_99ab0495789d` | `line:12` | [[wiki/concepts/strawberry.md]] |
```

Allowed evidence roles:

- `supports`;
- `limits`;
- `contradicts`;
- `background`;
- `open_question`.

Roles are synthesis-local labels. They do not create new formal relationship types unless a validated catalog relationship is also staged.

Rules:

- every evidence row must map to a real catalog claim;
- weak/uncited evidence must be visibly marked;
- explicit `contradicts` relationships must appear in `Conflicts And Limits`;
- selected evidence metadata from V2.7.1 may be included in staging diagnostics but does not become evidence by itself.

## 10. Updating Existing Pages

V2.8 must parse an existing synthesis page into a page model before updating it.

Update behavior:

- merge new claim ids with existing claim ids;
- preserve user-authored sections that are not part of the managed synthesis model;
- preserve existing revision history;
- append a new revision entry containing:
  - timestamp;
  - question;
  - run id;
  - action;
  - added evidence claim ids;
  - changed sections;
- do not remove old evidence unless it no longer exists in catalog;
- if old evidence is stale or missing, move it to `Conflicts And Limits` or add a warning rather than silently deleting it;
- if two existing synthesis pages are similar, use `similar_to` links/relationships and return `needs_review` rather than automatically merging pages.

Implementation may replace the full Markdown file in the patch, but it must build that replacement through a parsed page model and must include a backup through the existing apply workflow.

## 11. Relationships

V2.8 should improve synthesis navigation through existing catalog primitives.

Allowed staged relationships:

- `supports`: synthesis page is supported by cited evidence claim;
- `refines`: synthesis page refines or updates another synthesis;
- `contains`: synthesis page contains an evidence map or subtopic relation;
- `similar_to`: candidate duplicate or related synthesis;
- `contradicts`: only when there is an explicit catalog-backed contradiction relationship.

Rules:

- do not infer `contradicts` from negative words;
- do not create new claim ids for synthesis conclusions;
- relationship targets must exist as page ids, source ids, or claim ids allowed by current catalog validation;
- retrieval must continue to expose contradictions and weak evidence visibility.

## 12. Staging Artifacts

Synthesis writeback should create richer staging artifacts:

```text
staging/<run-id>/
  run.json
  claims.jsonl
  triage.md
  synthesis-plan.json
  patches/
    001-synthesis-<page-id>.json
```

`claims.jsonl` should remain empty unless a future version explicitly introduces derived claims. V2.8 does not.

`run.json` should include:

- `run_type: synthesis_writeback`;
- `trigger: ask`;
- `schema_version: synthesis_writeback.v2.8`;
- `synthesis_action`;
- `target_page_id`;
- `target_path`;
- `evidence_claim_ids`;
- `proposal_engine`;
- `status`.

`triage.md` should summarize:

- create/update decision;
- selected target;
- candidate duplicate pages;
- evidence additions;
- conflicts and open questions;
- validation warnings;
- debug command if apply fails.

## 13. CLI Changes

### 13.1 `ask`

Extend `ask` with:

```powershell
llmwiki ask "question" --root . --preview-writeback
llmwiki ask "question" --root . --writeback
llmwiki ask "question" --root . --writeback-mode auto
llmwiki ask "question" --root . --writeback-mode create
llmwiki ask "question" --root . --writeback-mode update
```

Defaults:

- `--writeback-mode auto` uses synthesis planning to decide create/update;
- `create` refuses to overwrite existing target pages;
- `update` requires a valid existing target, either chosen by planner or supplied later by an option if needed;
- `--json` never prompts interactively;
- `--no-writeback` skips synthesis planning unless `--preview-writeback` is also passed.

### 13.2 No Separate Mandatory Review Command

V2.8 should not add a new mandatory user review step.

Debug commands remain:

- `llmwiki review <run-id> --detail --root .`;
- `llmwiki apply <run-id> --root .`.

If automatic writeback fails after staging, the CLI should print the debug review command.

## 14. Error Handling

New statuses:

- `synthesis_not_planned`;
- `synthesis_planned`;
- `synthesis_needs_review`;
- `synthesis_invalid_plan`;
- `synthesis_writeback_failed`;
- `synthesis_applied`.

Failure behavior:

- no evidence: no synthesis planning;
- invalid answer citations: no synthesis planning;
- planner returns unknown claim/page/source: fail before staging;
- multiple plausible update targets: return `synthesis_needs_review`;
- apply failure: mark run failed and preserve rollback behavior;
- secret leakage detection: sanitize error, fail safely, do not write staging artifacts with secrets.

## 15. Backward Compatibility

V2.8 must read existing V2.2 synthesis pages.

Compatibility requirements:

- existing `wiki/syntheses/*.md` pages remain valid;
- existing catalog `page_type=synthesis` rows remain valid;
- old section names are parsed and migrated on next update;
- `apply.py` still accepts required synthesis sections, but V2.8 may expand accepted sections to include the new model;
- retrieval and ask citations remain unchanged;
- `retrieve/query/eval retrieval` behavior is not changed by synthesis page rendering unless synthesis pages are retrieved as related context.

## 16. Testing Requirements

Unit tests should cover:

- synthesis plan parsing and validation;
- unknown claim ids rejected;
- unknown page/source refs rejected;
- create plan renders the V2.8 page model;
- update plan merges existing evidence and revision history;
- duplicate candidate returns `needs_review` when ambiguous;
- preview mode does not write staging/wiki/catalog;
- `--writeback` creates or updates through staging/apply;
- old V2.2 synthesis pages are parsed and migrated on update;
- user-authored custom sections are preserved;
- weak/uncited and contradicting evidence remain visible;
- JSON output contains `synthesis_plan` and does not leak secrets.

Integration tests should cover:

- repeated focused strawberry storage questions update one page;
- comparison vitamin C question creates or updates a separate comparison synthesis;
- synthesis writeback after V2.7.1 focused retrieval cites only selected target evidence;
- failed plan validation leaves wiki/catalog unchanged;
- failed apply marks run failed and rolls back;
- `llmwiki lint --root .` accepts valid V2.8 synthesis pages.

## 17. Acceptance Plan

Using the five documents in `docs/tests`:

```powershell
llmwiki add docs/tests/苹果.md --root .
llmwiki add docs/tests/香蕉.md --root .
llmwiki add docs/tests/橙子.md --root .
llmwiki add docs/tests/草莓.md --root .
llmwiki add docs/tests/芒果.md --root .
```

Run:

```powershell
llmwiki ask "草莓应该怎么保存？" --root . --writeback --json
llmwiki ask "草莓买回来怎样放才不容易坏？" --root . --writeback --json
llmwiki ask "这五种水果里哪种更适合补充维生素 C？" --root . --writeback --json
llmwiki lint --root .
```

Acceptance:

- the two strawberry storage questions update one synthesis page;
- the comparison question creates or updates a separate comparison synthesis;
- each synthesis page has the V2.8 section model;
- evidence maps contain only valid catalog claim ids;
- revision history records repeated updates;
- no duplicate near-identical synthesis pages are created;
- `wiki/index.md`, `wiki/log.md`, and catalog are updated through apply;
- no generated `state/`, `sources/`, `staging/`, or `wiki/` artifacts are committed.

## 18. Documentation Updates

README should explain:

- `ask --writeback` now plans create/update synthesis writeback;
- synthesis pages are living wiki pages, not saved chat transcripts;
- `--preview-writeback` is read-only;
- synthesis conclusions are not new source-backed claims;
- evidence maps must cite existing catalog claims.

AGENTS.md should add:

- do not create duplicate synthesis pages when an existing page should be updated;
- synthesis planning may use LLM, but plan output is not evidence;
- preserve user-authored synthesis sections;
- writeback preview should show action, target, evidence, conflicts, and open questions;
- synthesis updates must still go through staging/apply.

## 19. Security And Secret Safety

V2.8 must not expose:

- `config/api-keys.toml`;
- API key values;
- raw provider responses containing secrets;
- hidden local file paths outside the workspace;
- raw source content beyond bounded evidence snippets already used by `ask`.

All planner errors and validation errors must pass through existing sanitization before being written to CLI output, JSON output, staging files, or logs.

## 20. Deferred Work

The following remain outside V2.8:

- automatic merge of two existing synthesis pages;
- derived formal claims;
- full synthesis quality scoring command;
- synthesis-specific public benchmark;
- rich source parsing and multimodal evidence;
- UI for reviewing proposed synthesis structure.

