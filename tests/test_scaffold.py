import unittest
from pathlib import Path

from llmwiki.cli import COMMANDS, build_parser
from llmwiki.workspace import REQUIRED_PATHS, check_workspace
from tests.helpers import make_workspace


class ScaffoldTests(unittest.TestCase):
    def test_cli_exposes_planned_commands(self) -> None:
        parser = build_parser()
        self.assertEqual(
            set(COMMANDS),
            {
                "init",
                "add",
                "ingest",
                "review",
                "apply",
                "lint",
                "query",
                "retrieve",
                "ask",
                "eval",
                "embeddings",
                "llm-test",
                "doctor",
            },
        )
        self.assertEqual(parser.prog, "llmwiki")

    def test_workspace_check_reports_missing_paths(self) -> None:
        result = check_workspace(make_workspace())
        self.assertFalse(result.ok)
        self.assertEqual(set(result.missing), set(REQUIRED_PATHS))

    def test_workspace_check_accepts_required_paths(self) -> None:
        root = make_workspace()
        for required in REQUIRED_PATHS:
            target = root / required
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("", encoding="utf-8")
            else:
                target.mkdir(parents=True, exist_ok=True)

        result = check_workspace(root)
        self.assertTrue(result.ok)
        self.assertEqual(result.missing, ())


if __name__ == "__main__":
    unittest.main()
