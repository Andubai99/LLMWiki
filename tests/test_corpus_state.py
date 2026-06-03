from __future__ import annotations

from pathlib import Path

from llmwiki.corpus.state import (
    ATTEMPT_SCHEMA_VERSION,
    BATCH_SCHEMA_VERSION,
    ITEM_SCHEMA_VERSION,
    BatchManifest,
    CorpusAttempt,
    CorpusItem,
    append_attempt,
    append_event,
    batch_dir,
    create_batch_id,
    item_id_for_path,
    read_attempts,
    read_batch,
    read_events,
    read_items,
    write_batch,
    write_items,
)
from tests.helpers import make_workspace


def test_corpus_state_round_trips_json_and_jsonl() -> None:
    root = make_workspace()
    batch_id = create_batch_id(root, ["papers/a.pdf"])
    item_id = item_id_for_path(root, root / "papers" / "a.pdf")
    manifest = BatchManifest(
        batch_id=batch_id,
        root=str(root.resolve()),
        input_paths=["papers/a.pdf"],
        status="pending",
        item_count=1,
        options={"recursive": False},
    )
    item = CorpusItem(
        batch_id=batch_id,
        item_id=item_id,
        source_path="papers/a.pdf",
        source_kind="pdf",
        status="pending",
    )
    attempt = CorpusAttempt(
        batch_id=batch_id,
        item_id=item_id,
        attempt_id=f"{item_id}_attempt_001",
        status="failed",
        failure_stage="ingest",
        failure_reason="LLM ingest is required",
    )

    write_batch(root, manifest)
    write_items(root, batch_id, [item])
    append_attempt(root, attempt)
    append_event(root, batch_id=batch_id, item_id=item_id, event_type="failed", message="failed safely")

    assert (batch_dir(root, batch_id) / "batch.json").exists()
    assert (batch_dir(root, batch_id) / "items.jsonl").exists()
    assert (batch_dir(root, batch_id) / "attempts.jsonl").exists()
    assert read_batch(root, batch_id).schema_version == BATCH_SCHEMA_VERSION
    assert read_items(root, batch_id)[0].schema_version == ITEM_SCHEMA_VERSION
    assert read_attempts(root, batch_id)[0].schema_version == ATTEMPT_SCHEMA_VERSION
    assert read_attempts(root, batch_id)[0].failure_reason == "LLM ingest is required"
    assert read_events(root, batch_id)[0]["event_type"] == "failed"


def test_item_id_for_path_is_stable_and_workspace_relative() -> None:
    root = Path("F:/workspace").resolve()
    first = item_id_for_path(root, root / "docs" / "papers" / "paper.pdf")
    second = item_id_for_path(root, root / "docs" / "papers" / "paper.pdf")
    other = item_id_for_path(root, root / "docs" / "papers" / "other.pdf")

    assert first == second
    assert first.startswith("item_")
    assert first != other
