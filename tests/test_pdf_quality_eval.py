from __future__ import annotations

import json
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
    assert before == after


def test_cli_eval_pdf_quality_outputs_human_report(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    capsys.readouterr()
    seed_pdf_source(root, monkeypatch)

    assert main(["eval", "pdf-quality", "--root", str(root)]) == 0
    out = capsys.readouterr().out

    assert "PDF quality evaluation" in out
    assert "Title pass rate:" in out
