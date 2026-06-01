from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.retrieval import retrieve_context
from tests.test_ask_workflow import (
    answer_payload,
    patch_answer_provider,
    patch_planner_provider,
    patch_synthesis_provider,
    planner_payload,
    synthesis_plan_payload,
)
from tests.test_hybrid_retrieval import setup_seeded_workspace


def page_rows(root: Path) -> list[sqlite3.Row]:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "select page_id, path, page_type, title from pages where page_type = 'synthesis' order by path"
        ).fetchall()


def test_repeated_focused_questions_update_one_synthesis_page(monkeypatch, capsys):
    root = setup_seeded_workspace()
    context = retrieve_context(root, "草莓 保存", limit=1)["contexts"][0]
    assert context["source_id"] == "src_99ab0495789d"

    patch_planner_provider(monkeypatch, planner_payload("草莓 保存"))
    patch_answer_provider(monkeypatch, answer_payload(context, title="Strawberry Storage"))
    patch_synthesis_provider(
        monkeypatch,
        synthesis_plan_payload(
            context,
            title="Strawberry Storage",
            target_page_id="synthesis-strawberry-storage",
            target_path="wiki/syntheses/strawberry-storage.md",
        ),
    )
    capsys.readouterr()

    assert main(["ask", "草莓应该怎么保存？", "--root", str(root), "--writeback", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["writeback"]["action"] == "create"

    patch_planner_provider(monkeypatch, planner_payload("草莓 防止变坏"))
    patch_answer_provider(monkeypatch, answer_payload(context, title="Strawberry Storage"))
    patch_synthesis_provider(
        monkeypatch,
        synthesis_plan_payload(
            context,
            title="Strawberry Storage",
            action="update",
            target_page_id="synthesis-strawberry-storage",
            target_path="wiki/syntheses/strawberry-storage.md",
        ),
    )

    assert main(["ask", "草莓买回来怎样放才不容易坏？", "--root", str(root), "--writeback", "--json"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert second["writeback"]["action"] == "update"
    assert len(page_rows(root)) == 1
    page = root / "wiki" / "syntheses" / "strawberry-storage.md"
    content = page.read_text(encoding="utf-8")
    assert "question_count: 2" in content
    assert "revision_count: 2" in content
    assert "草莓应该怎么保存？" in content
    assert "草莓买回来怎样放才不容易坏？" in content


def test_comparison_question_uses_separate_synthesis_page(monkeypatch, capsys):
    root = setup_seeded_workspace()
    strawberry = retrieve_context(root, "草莓 保存", limit=1)["contexts"][0]
    orange = retrieve_context(root, "橙子 维生素 C", limit=1)["contexts"][0]

    patch_planner_provider(monkeypatch, planner_payload("草莓 保存"))
    patch_answer_provider(monkeypatch, answer_payload(strawberry, title="Strawberry Storage"))
    patch_synthesis_provider(
        monkeypatch,
        synthesis_plan_payload(
            strawberry,
            title="Strawberry Storage",
            target_page_id="synthesis-strawberry-storage",
            target_path="wiki/syntheses/strawberry-storage.md",
        ),
    )
    capsys.readouterr()
    assert main(["ask", "草莓应该怎么保存？", "--root", str(root), "--writeback", "--json"]) == 0
    capsys.readouterr()

    patch_planner_provider(monkeypatch, planner_payload("草莓 维生素 C", "橙子 维生素 C"))
    patch_answer_provider(monkeypatch, answer_payload(orange, title="Fruit Vitamin C Comparison"))
    patch_synthesis_provider(
        monkeypatch,
        synthesis_plan_payload(
            orange,
            title="Fruit Vitamin C Comparison",
            target_page_id="synthesis-fruit-vitamin-c-comparison",
            target_path="wiki/syntheses/fruit-vitamin-c-comparison.md",
        ),
    )

    assert main(["ask", "这五种水果里哪种更适合补充维生素 C？", "--root", str(root), "--writeback", "--json"]) == 0

    pages = page_rows(root)
    assert [row["path"] for row in pages] == [
        "wiki/syntheses/fruit-vitamin-c-comparison.md",
        "wiki/syntheses/strawberry-storage.md",
    ]
