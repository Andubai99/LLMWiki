# LLMWiki V2.6: Embedding + Vector Store

## 1. Background

V2.4 replaced ad hoc local retrieval with deterministic hybrid retrieval: Unicode-aware query analysis, BM25/FTS, catalog title/alias matching, graph relationship expansion, exact formula/symbol matching, and RRF fusion.

V2.5 added LLM query planning for `ask`: the LLM can decompose a question into subqueries, but every subquery still runs through local `retrieve_context`, and every answer citation still comes from local catalog evidence.

V2.5.1 fixed relationship semantics so `contradicts` means actual source-backed disagreement, not the presence of negation.

The next retrieval gap is semantic recall. Local lexical retrieval can still miss evidence when the user's wording differs from the source wording. Examples:

```text
保存方法
-> cold storage, keep dry, avoid squeezing, eat soon

适合运动后吃吗
-> energy supply, sugar, digestion, satiety, intake amount
```

V2.6 adds embeddings and a local vector index as an additional retrieval signal. It must not replace source-backed citations or make vector similarity itself a source of truth.

## 2. Goal

V2.6 makes LLMWiki capable of semantic evidence recall through a rebuildable local vector index.

It adds:

- an embedding provider abstraction;
- a DashScope multimodal embedding provider for the configured default model;
- chunk extraction from catalog claims and selected page/source text;
- a local rebuildable vector index under `state/`;
- vector retrieval as another retriever inside the existing hybrid retrieval architecture;
- RRF fusion of lexical, catalog, graph, exact, and vector candidates;
- CLI commands for embedding health checks, indexing, and index status;
- eval coverage showing recall improvements while preserving evidence contracts.

V2.6 is successful when semantic paraphrase questions retrieve source-backed claims that lexical retrieval may miss, while returned contexts still include valid `claim_id`, `source_id`, `citation_locator`, `page_path`, confidence, relationships, and warnings.

## 3. Current Configuration Decision

The default embedding provider for V2.6 is:

```toml
[embedding]
enabled = true
provider = "dashscope_multimodal"
model = "tongyi-embedding-vision-flash-2026-03-06"
endpoint_url = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
api_key_file = "config/api-keys.toml"
dimension = 768
timeout_seconds = 60
```

The API key is local-only:

```toml
[embedding]
api_key = "paste-your-dashscope-api-key-here"
```

inside `config/api-keys.toml`, which is gitignored.

The model was tested successfully through DashScope's native multimodal embedding endpoint and returned 768-dimensional vectors for text input. It was not accepted by the OpenAI-compatible `/embeddings` endpoint, so V2.6 must not model this provider as a plain OpenAI-compatible embedding provider.

## 4. Non-Goals

V2.6 does not implement:

- reranking or model-based evidence selection;
- LLM reranker;
- vector-only answer generation;
- direct citation to vectors;
- external hosted vector databases;
- UI;
- MinerU, OCR, PDF layout parsing, table extraction, or image ingestion;
- multimodal image retrieval as a user-facing behavior;
- automatic conflict classification;
- multi-turn chat memory.

Those belong to later phases:

- V2.7 reranking + evidence selection;
- V2.8 synthesis quality;
- V2.9 rich source parsing and multimodal source blocks.

V2.6 may design the provider and chunk schema so future image/table/formula blocks can be embedded later, but it should only index text evidence in this phase.

## 5. Design Principles

### 5.1 Vector Is Recall, Not Evidence

Embedding similarity can only select candidate evidence. It must not create claims, citations, relationships, or conclusions.

Every returned context must still come from local catalog/wiki records.

### 5.2 Local And Rebuildable

The vector index is cache state, not durable knowledge. It should live under `state/`, be ignored by git, and be rebuildable from catalog/wiki content.

The durable assets remain:

- raw sources;
- normalized sources;
- wiki Markdown pages;
- committed source code/config templates;
- eval datasets.

### 5.3 Provider Abstraction First

The implementation should not hard-code DashScope throughout retrieval. It should define a small embedding provider interface and one production provider:

```text
dashscope_multimodal
```

Future providers can include local embedding models or OpenAI-compatible text embeddings without changing retrieval callers.

### 5.4 Text First, Multimodal-Ready

The selected default model is multimodal. V2.6 should use it for text chunks only:

```text
claim text -> vector
page summary/title text -> vector
source title + selected normalized text -> vector
```

The index schema should include `modality = "text"` so V2.9 can add `image`, `table`, `formula`, or `caption` chunks later.

### 5.5 Preserve Deterministic Public Retrieval Unless Indexed

`llmwiki retrieve` should remain local and deterministic after the vector index exists. It may read the local vector index, but it must not call the embedding API at query time unless V2.6 explicitly enables query embedding for vector retrieval.

V2.6 chooses this behavior:

- `llmwiki retrieve` may call the embedding provider to embed the user's query when `[embedding].enabled = true` and a vector index exists.
- If embedding query fails, retrieval must degrade to existing local hybrid retrieval and emit a warning, not fail the whole command.
- `llmwiki query` inherits the same behavior because it reuses `retrieve`.
- `llmwiki eval retrieval` must default to the same retrieval behavior as `retrieve`, but should record embedding calls in diagnostics.

This means V2.6 changes `retrieve` from strictly no-network to optionally provider-assisted when embeddings are enabled. The behavior must be explicit in config, docs, and diagnostics.

## 6. Public Commands

### 6.1 `llmwiki embeddings test`

New command:

```bash
llmwiki embeddings test --root .
```

Behavior:

- loads `[embedding]` config;
- reads `[embedding].api_key` from `config/api-keys.toml`;
- sends one short text sample to the configured provider;
- prints provider, model, endpoint type, dimension, and success/failure;
- never prints API key or raw secret config.

Optional:

```bash
llmwiki embeddings test --root . --text "草莓应该怎么保存？"
```

### 6.2 `llmwiki embeddings rebuild`

New command:

```bash
llmwiki embeddings rebuild --root .
```

Behavior:

- reads catalog/wiki records;
- builds text chunks;
- calls the embedding provider in batches;
- writes a rebuildable index under `state/embeddings/`;
- records provider, model, dimension, chunk count, source catalog fingerprint, and created timestamp;
- replaces the previous index atomically.

Optional:

```bash
llmwiki embeddings rebuild --root . --batch-size 16
```

### 6.3 `llmwiki embeddings status`

New command:

```bash
llmwiki embeddings status --root .
```

Behavior:

- reports whether embedding config is enabled;
- reports whether local vector index exists;
- reports provider/model/dimension/chunk count;
- reports whether index appears stale relative to catalog fingerprint;
- does not call the provider.

### 6.4 Existing `retrieve`, `query`, `ask`, `eval retrieval`

After V2.6:

- `retrieve` includes vector candidates when enabled and indexed;
- `query` displays vector retrieval reasons because it formats `retrieve`;
- `ask` benefits through planned subqueries using `retrieve`;
- `eval retrieval` can measure vector-enhanced recall.

JSON diagnostics should expose:

```json
{
  "retrievers": {
    "vector": {
      "enabled": true,
      "index_present": true,
      "query_embedded": true,
      "candidate_count": 12,
      "provider": "dashscope_multimodal",
      "model": "tongyi-embedding-vision-flash-2026-03-06",
      "dimension": 768
    }
  }
}
```

## 7. Architecture

### 7.1 Embedding Provider

Add a provider layer with a small interface:

```python
class EmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError
```

Production provider:

```text
DashScopeMultimodalEmbeddingProvider
```

Request format:

```json
{
  "model": "tongyi-embedding-vision-flash-2026-03-06",
  "input": {
    "contents": [
      {"text": "草莓应该怎么保存？"}
    ]
  },
  "parameters": {
    "dimension": 768
  }
}
```

Response validation:

- response must contain one vector per input text;
- every vector dimension must equal configured dimension;
- non-numeric values fail safely;
- errors must be sanitized so API keys are never printed.

### 7.2 Embedding Config

Add:

```python
EmbeddingConfig
load_embedding_config(root: Path) -> EmbeddingConfig
create_embedding_provider(config: EmbeddingConfig, root: Path) -> EmbeddingProvider
```

Config should be independent from `[llm]`, because chat completion and embedding providers may use different endpoints, models, and keys.

### 7.3 Chunk Builder

Build text chunks from catalog/wiki.

Minimum V2.6 chunk types:

- `claim`
- `page_title`
- `page_summary` if a concise page section can be extracted safely
- `source_title`

Required chunk metadata:

```text
chunk_id
chunk_type
modality
text
claim_id
source_id
page_id
page_path
citation_locator
confidence_status
content_hash
created_at
```

For `claim` chunks:

- `claim_id` is required;
- `source_id` is required;
- `citation_locator` should be copied from catalog claim;
- `page_path` should resolve from the relevant page if available.

For non-claim chunks:

- they may help recall but must map back to source-backed claims before becoming returned evidence;
- V2.6 should prefer claim chunks in returned contexts.

### 7.4 Local Vector Index

V2.6 should avoid adding a heavy external vector DB. Use local rebuildable storage under:

```text
state/embeddings/
  manifest.json
  chunks.jsonl
  vectors.npy or vectors.jsonl
```

Preferred implementation:

- if NumPy is already available or added as a dependency, store vectors as `.npy`;
- otherwise store JSONL float arrays for V2.6 simplicity.

The index must include enough metadata to rebuild, validate, and skip stale records.

Manifest fields:

```json
{
  "schema_version": "embeddings.v2.6",
  "provider": "dashscope_multimodal",
  "model": "tongyi-embedding-vision-flash-2026-03-06",
  "dimension": 768,
  "chunk_count": 0,
  "catalog_fingerprint": "sha256:3b7d4a8f0b6c2a1d9e5f0a4b8c6d2e1f3a5b7c9d0e2f4a6b8c0d2e4f6a8b0c2d",
  "created_at": "2026-05-29T00:00:00+00:00"
}
```

### 7.5 Vector Retriever

Add `VectorRetriever` to the existing retriever abstraction.

Flow:

```text
query
-> embed query text
-> cosine similarity against local vectors
-> return RetrievalCandidate objects with real claim ids
-> RRF fusion with BM25/catalog/exact/graph
```

Candidate rules:

- vector candidates must map to real catalog claims before being returned;
- claim chunks map directly;
- page/source chunks may expand to related claims only through catalog links/relationships/source ids;
- vector scores are internal ranking features, not evidence confidence.

Retrieval reasons:

```text
vector_semantic
```

Diagnostics should include query embedding success/failure, vector index staleness, and candidate counts.

## 8. Data Flow

### 8.1 Build Index

```text
catalog/wiki
-> chunk builder
-> embedding provider
-> state/embeddings temporary index
-> atomic replace active index
```

### 8.2 Retrieve

```text
question
-> V2.4 query analysis
-> lexical/catalog/exact retrievers
-> vector query embedding if enabled + index present
-> vector retriever candidates
-> graph expansion
-> RRF fusion
-> contexts assembled from catalog evidence
```

### 8.3 Ask

```text
question
-> V2.5 planner
-> subqueries
-> retrieve_context for each subquery
-> vector-enhanced evidence when available
-> grounded answer
```

The planner output still cannot become evidence.

## 9. Failure Modes

### 9.1 Missing Embedding Key

`embeddings test` and `embeddings rebuild` should fail with a sanitized message.

`retrieve` should continue without vector retrieval and add a warning if vector is enabled but unusable.

### 9.2 Provider Error

Provider errors should include:

- provider name;
- model;
- endpoint type;
- HTTP status if available;
- sanitized provider error message.

They must not include:

- API key;
- full local secret file contents;
- raw payload if it could include sensitive user source text unless explicitly in debug mode.

### 9.3 Index Missing Or Stale

If index is missing:

- `retrieve` continues without vector candidates;
- diagnostics show `index_present=false`.

If index is stale:

- `retrieve` may still use it only if chunk ids still validate against catalog;
- diagnostics show `stale=true`;
- `embeddings status` recommends rebuild.

### 9.4 Dimension Mismatch

If stored vectors do not match configured dimension:

- vector retriever disables itself for that call;
- diagnostics show `failure_stage="dimension_mismatch"`;
- status recommends rebuild.

## 10. Testing Requirements

### 10.1 Unit Tests

Tests should use monkeypatched provider responses, not real DashScope calls by default.

Cover:

- embedding config loads from `[embedding]`;
- key is read from `config/api-keys.toml`;
- provider request body matches DashScope multimodal format;
- provider validates vector count and dimensions;
- secret values are not present in errors;
- chunk builder creates claim chunks with citation metadata;
- index manifest/chunks/vectors round-trip locally;
- vector retriever maps candidates back to real catalog claims.

### 10.2 CLI Tests

Cover:

- `llmwiki embeddings test --root .` with monkeypatched provider;
- `llmwiki embeddings rebuild --root .` writes `state/embeddings/`;
- `llmwiki embeddings status --root .` reports index present/stale;
- missing key fails safely without leaking `sk-`;
- `llmwiki --help` includes `embeddings`.

### 10.3 Retrieval Tests

Cover:

- vector retriever improves recall for paraphrase queries in deterministic fixtures;
- vector candidates are fused with RRF;
- contexts still have valid `claim_id`, `source_id`, `citation_locator`, `page_path`;
- `query` reuses vector-enhanced `retrieve`;
- `ask` citations still come only from retrieved contexts.

### 10.4 Eval Tests

Add a V2.6 eval dataset or extend V2.4 fruit eval with semantic paraphrases:

```jsonl
{"id":"fruit_semantic_storage","question":"草莓买回来怎样放才不容易坏？","expected_terms":["冷藏","干燥","尽快食用"]}
{"id":"fruit_semantic_post_exercise","question":"运动后想快速补充能量，哪种水果证据更多？","expected_terms":["能量","香蕉","糖分"]}
{"id":"fruit_semantic_sugar_control","question":"需要控糖的人吃水果要注意什么？","expected_terms":["血糖","糖分","摄入量"]}
```

Eval should report vector diagnostics, but the existing evidence contract metrics remain mandatory.

### 10.5 Real Provider Smoke Test

Keep real DashScope smoke tests separate from default unit tests.

They may run only when `config/api-keys.toml` contains `[embedding].api_key`.

Expected:

- model returns 768-dimensional vector for a short Chinese text;
- no key appears in output.

## 11. Documentation Updates

Update:

- README
- AGENTS.md
- config examples

Documentation must state:

- V2.6 uses DashScope multimodal embedding provider by default;
- current phase indexes text chunks only;
- vector retrieval is a recall signal, not source evidence;
- returned citations still come from local catalog;
- `state/embeddings/` is rebuildable cache and should not be committed;
- real embedding keys stay in `config/api-keys.toml`.

AGENTS should also update the earlier boundary:

- do not default to external vector databases;
- local rebuildable vector index is allowed in V2.6.

## 12. Acceptance Criteria

V2.6 is complete when:

- embedding provider config loads separately from LLM config;
- DashScope multimodal provider can embed text and validate 768-dimensional vectors;
- `llmwiki embeddings test/rebuild/status` work;
- local vector index is rebuildable under `state/embeddings/`;
- vector retriever participates in hybrid retrieval through RRF;
- vector candidates never bypass catalog evidence validation;
- semantic paraphrase retrieval improves on the current fruit docs;
- `ask` benefits through retrieved local evidence and still cites claim ids;
- eval reports vector diagnostics and evidence contract remains valid;
- default tests do not require real network calls;
- real provider smoke test can be run manually with local ignored key;
- generated vector index and API keys are not committed.

## 13. Open Questions Deferred

These should not block V2.6:

- Should V2.7 use an embedding reranker, LLM reranker, or both?
- Should V2.9 embed raw image/table/formula blocks before or after OCR/MinerU normalization?
- Should vector index support incremental updates after every `add`, or is rebuild enough for the first version?
- Should embeddings be compressed or quantized for large workspaces?

V2.6 should choose rebuild-first semantics. Incremental indexing can be added after the correctness contract is proven.
