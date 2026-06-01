from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.pdf_quality import evaluate_pdf_quality, format_pdf_quality_report
from llmwiki.sources import import_source
from tests.helpers import make_workspace


def snapshot_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def seed_pdf_source(root: Path, monkeypatch) -> str:
    monkeypatch.setattr(
        "llmwiki.pdf_blocks.read_pdf_pages",
        lambda content: (
            {"title": "OSWorld: Benchmarking Multimodal Agents"},
            [
                "OSWorld: Benchmarking Multimodal Agents\n\n"
                "Abstract\n"
                "OSWorld evaluates computer-use agents.\n",
            ],
        ),
    )
    pdf = root / "osworld.pdf"
    pdf.write_bytes(b"%PDF fake")
    return import_source(root, str(pdf)).source_id


def test_evaluate_pdf_quality_summarizes_pdf_sidecars(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    seed_pdf_source(root, monkeypatch)

    summary = evaluate_pdf_quality(root)
    report = format_pdf_quality_report(summary)

    assert summary.schema_version == "eval.pdf_quality.v2.9.2"
    assert summary.pdf_source_count == 1
    assert summary.title_pass_rate == 1.0
    assert summary.sidecar_completeness == 1.0
    assert summary.block_locator_validity == 1.0
    assert summary.parser_backend_distribution == {"pypdf": 1}
    assert summary.backend_artifact_completeness == 1.0
    assert summary.block_locator_validity_by_backend == {"pypdf": 1.0}
    assert "PDF quality evaluation" in report
    assert "PDF sources: 1" in report


def test_cli_eval_pdf_quality_outputs_json_and_is_read_only(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    seed_pdf_source(root, monkeypatch)
    before = snapshot_files(root)

    monkeypatch.setattr(
        "llmwiki.llm.create_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    assert main(["eval", "pdf-quality", "--root", str(root), "--json"]) == 0
    out = capsys.readouterr().out
    after = snapshot_files(root)

    payload = json.loads(out)
    assert payload["schema_version"] == "eval.pdf_quality.v2.9.2"
    assert payload["pdf_source_count"] == 1
    assert payload["parser_backend_distribution"] == {"pypdf": 1}
    assert "backend_artifact_completeness" in payload
    assert before == after


def test_evaluate_pdf_quality_reports_parser_backend_structured_counts(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    pdf = root / "mineru.pdf"
    pdf.write_bytes(b"%PDF fake")
    import_source(root, str(pdf), parser_backend="mineru", parser_output_dir=Path("tests/fixtures/mineru"))

    payload = evaluate_pdf_quality(root).to_dict()

    assert payload["parser_backend_distribution"] == {"mineru": 1}
    assert payload["mineru_source_count"] == 1
    assert payload["pypdf_source_count"] == 0
    assert payload["structured_block_count"] >= 3
    assert payload["table_like_block_count"] == 1
    assert payload["equation_like_block_count"] == 1
    assert payload["image_or_caption_block_count"] == 1
    assert payload["block_locator_validity_by_backend"] == {"mineru": 1.0}


def test_evaluate_pdf_quality_reports_mineru_command_counters(capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    pdf = root / "mineru.pdf"
    pdf.write_bytes(b"%PDF fake")
    source_id = import_source(root, str(pdf), parser_backend="mineru", parser_output_dir=Path("tests/fixtures/mineru")).source_id
    metadata_path = root / "sources" / "metadata" / f"{source_id}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["parser_command_invoked"] = True
    metadata["parser_command_returncode"] = 1
    metadata["parser_backend_fallback_from"] = "mineru"
    metadata["parser_backend_fallback_reason"] = "MinerU command timed out"
    metadata["parser_content_list_path"] = "sources/parser-artifacts/missing/content_list.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    payload = evaluate_pdf_quality(root).to_dict()

    assert payload["mineru_command_invoked_count"] == 1
    assert payload["mineru_command_failure_count"] == 1
    assert payload["mineru_timeout_count"] == 1
    assert payload["mineru_content_list_missing_count"] == 1
    assert payload["auto_fallback_count"] == 1


def test_evaluate_pdf_quality_reports_identity_and_repair_counters(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    source_id = seed_pdf_source(root, monkeypatch)
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into aliases (alias, target_type, target_id, normalized_alias)
            values (?, ?, ?, ?)
            """,
            ("OSWorld: Benchmarking Multimodal Agents", "source", source_id, "osworldbenchmarkingmultimodalagents"),
        )
        conn.execute(
            """
            insert into aliases (alias, target_type, target_id, normalized_alias)
            values ('OSWorld', 'concept', 'concept:osworld', 'osworld')
            """
        )
        conn.execute(
            """
            insert into aliases (alias, target_type, target_id, normalized_alias)
            values ('OSWorld', 'entity', 'entity:osworld', 'osworld')
            """
        )
    run_dir = root / "staging" / "run_pdf_repair"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run_pdf_repair", "llm_json_repair_count": 2}),
        encoding="utf-8",
    )

    summary = evaluate_pdf_quality(root)
    payload = summary.to_dict()

    assert payload["source_title_alias_collision_count"] == 1
    assert payload["paper_identity_overlap_count"] == 1
    assert payload["llm_json_repair_observed_count"] == 2


def test_cli_eval_pdf_quality_outputs_human_report(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    seed_pdf_source(root, monkeypatch)

    assert main(["eval", "pdf-quality", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "PDF quality evaluation" in out
    assert "Title pass rate:" in out
