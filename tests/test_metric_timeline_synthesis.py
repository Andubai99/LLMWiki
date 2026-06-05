from __future__ import annotations

from llmwiki.metrics.llm_normalization import (
    build_metric_normalization_run,
    build_timeline_synthesis_response,
)
from tests.test_metric_llm_normalization_cli import FakeProvider
from tests.test_metric_repair_query import workspace_with_metric_repair_cases


def test_timeline_synthesis_reads_staged_preview_without_second_llm_call(monkeypatch) -> None:
    root = workspace_with_metric_repair_cases()
    calls = {"count": 0}

    def fake_create_provider(config, root=None):
        calls["count"] += 1
        return FakeProvider()

    monkeypatch.setattr("llmwiki.metrics.llm_normalization.create_provider", fake_create_provider)
    run = build_metric_normalization_run(root, source_id="src_pdf")

    monkeypatch.setattr(
        "llmwiki.metrics.llm_normalization.create_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("timeline-synthesis must not call LLM")),
    )
    payload = build_timeline_synthesis_response(root, run.normalization_run_id).to_dict()

    assert calls["count"] == 1
    assert payload["schema_version"] == "metric_timeline_synthesis.v4.9"
    assert payload["normalization_run_id"] == run.normalization_run_id
    assert payload["timeline_point_count"] >= 1
    assert all(ref["result_id"] and ref["claim_id"] and ref["source_id"] for ref in payload["evidence_refs"])
