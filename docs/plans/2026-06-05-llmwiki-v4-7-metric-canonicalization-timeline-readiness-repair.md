# LLMWiki V4.7 Metric Canonicalization And Timeline Readiness Repair Implementation Plan

## Summary

Implement `docs/specs/2026-06-05-llmwiki-v4-7-metric-canonicalization-timeline-readiness-repair-design.md`: add a read-only `llmwiki metric canonicalize` command that reports deterministic metric canonicalization, value repair suggestions, comparability groups, and upgraded timeline readiness over existing durable `metric_results`.

Method: **spec-driven + contract-first + risk-based TDD**. V4.7 does not rerun MinerU+LLM, add UI, migrate catalog schema, write wiki/staging/source/state, or automatically repair durable rows.

## Key Changes

- Add CLI:
  - `llmwiki metric canonicalize --root .`
  - `llmwiki metric canonicalize --root . --json`
  - filters: `--metric`, `--dataset`, `--task`, `--limit`, `--offset`
- Add read-only model module: `src/llmwiki/metrics/canonicalization.py`.
- Extend metric formatting and CLI wiring.
- Fix schema versions:
  - `metric_canonicalization_report.v4.7`
  - `canonical_metric.v4.7`
  - `metric_result_value_repair.v4.7`
  - `metric_comparability_group.v4.7`
  - `metric_timeline_readiness.v4.7`
  - `metric_canonicalization_warning.v4.7`
- Reuse existing read-only helpers:
  - V4.2 inventory metadata
  - V4.4 filter semantics
  - V4.5 result-evidence bounded context
- Do not shell out to CLI subcommands or call providers, parser, import, ingest, apply, ask, synthesis, lint, clean, or eval recursion.
- Use `limit=200`, max `1000`, `offset>=0`; page `canonical_metrics`, `comparability_groups`, `timeline_readiness`, and `value_repairs` independently while summary keeps unpaged counts.

## Implementation Steps

1. Save plan and commit:
   - Add `docs/plans/2026-06-05-llmwiki-v4-7-metric-canonicalization-timeline-readiness-repair.md`.
   - Commit: `docs: 添加 V4.7 指标规范化执行计划`.

2. Write failing contract tests:
   - Add `tests/test_metric_canonicalization_model.py`.
   - Add `tests/test_metric_canonicalization_query.py`.
   - Add `tests/test_metric_canonicalization_cli.py`.
   - Add `tests/test_metric_canonicalization_readonly.py`.
   - Cover schema constants, canonical key normalization, vague-label detection, no synonym merge, value repair, placeholder rejection, multi-number ambiguity, comparability grouping, readiness statuses, CLI output, pagination, empty result, missing catalog, and read-only boundary.
   - Commit: `test: 固定 V4.7 指标规范化契约`.

3. Implement canonicalization model:
   - Implement canonical key normalization and display-name selection.
   - Implement deterministic value parsing and repair suggestion builder.
   - Implement comparability group key: `canonical_metric_key|dataset|task|unit|direction|value_scale`.
   - Implement readiness statuses and blocking/warning reasons.
   - Commit: `feat: 新增指标规范化只读模型`.

4. Wire CLI and formatting:
   - Add `metric canonicalize` parser and command handler.
   - Add JSON/human formatting.
   - Invalid args and incompatible catalog return exit code `1`; empty result returns `0` with warnings.
   - Commit: `feat: 接入指标规范化 CLI`.

5. Fix read-only boundary:
   - Monkeypatch forbidden surfaces: LLM, embedding, MinerU, parser, add/import, ingest, apply, ask, synthesis, lint, clean, CLI eval recursion.
   - Snapshot workspace outputs to prove no writes to `wiki/`, `sources/`, `staging/`, `state/catalog.sqlite`, `state/corpus-batches/`, `state/embeddings/`, `state/ui-jobs/`, or `.tmp/`.
   - Commit: `test: 固定 V4.7 只读边界`.

6. Update docs contract:
   - Update README and AGENTS.
   - Update `tests/test_regression_samples.py`.
   - Commit: `docs: 更新 V4.7 指标规范化契约`.

7. Acceptance reuse:
   - Do not rerun MinerU+LLM.
   - Reuse `.tmp/paper-v46-corpus-acceptance`.
   - Run JSON and human acceptance:
     - `.\.venv\Scripts\python.exe -m llmwiki metric canonicalize --root .tmp\paper-v46-corpus-acceptance --json`
     - `.\.venv\Scripts\python.exe -m llmwiki metric canonicalize --root .tmp\paper-v46-corpus-acceptance`
   - Record sanitized observations at `docs/observations/2026-06-05-llmwiki-v4-7-metric-canonicalization-timeline-readiness-repair-observations.md`.
   - Commit: `test: 记录 V4.7 指标规范化验收结果`.

## Test Plan

- Unit/model:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_canonicalization_model.py -q`
- Query/CLI:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_canonicalization_query.py tests\test_metric_canonicalization_cli.py -q`
- Read-only:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_canonicalization_readonly.py -q`
- Related regression:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_timeline_query.py tests\test_result_evidence_quality_model.py tests\test_corpus_results_eval_model.py -q`
- Docs:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_regression_samples.py -q`
- Final:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_metric_canonicalization_model.py tests\test_metric_canonicalization_query.py tests\test_metric_canonicalization_cli.py tests\test_metric_canonicalization_readonly.py tests\test_metric_timeline_query.py tests\test_result_evidence_quality_model.py tests\test_corpus_results_eval_model.py tests\test_regression_samples.py -q`
  - `git status --short --ignored`

## Acceptance Reuse

- V4.7 reuses `.tmp/paper-v46-corpus-acceptance`.
- L5 full 20-paper MinerU+LLM rerun is not required and must not be run by default.
- Keep `.tmp/paper-v46-corpus-acceptance` for user inspection.

## Assumptions

- V4.7 is report-only; no catalog migration or durable repair.
- `ready_after_value_repair` does not alter `llmwiki metric timeline`.
- `score`, `Avg`, and `Overall` remain ambiguous/context-dependent by default.
- Unit conversion is limited to recognizing compatible value scales; no cross-unit conversion.
