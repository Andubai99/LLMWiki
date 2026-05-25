from __future__ import annotations

import argparse
from pathlib import Path

from .db import catalog_path, schema_status
from .workspace import check_workspace, init_workspace


COMMANDS = ("init", "add", "ingest", "review", "apply", "lint", "query", "doctor")


def _scaffold_only(command: str) -> int:
    print(
        f"llmwiki {command}: scaffold interface only. "
        "See docs/CAPABILITY_STRUCTURE.md for the planned behavior."
    )
    return 1


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    init_workspace(root)
    print(f"Initialized workspace: {root}")
    print(f"Catalog schema OK: {catalog_path(root)}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    return _scaffold_only("add")


def cmd_ingest(args: argparse.Namespace) -> int:
    return _scaffold_only("ingest")


def cmd_review(args: argparse.Namespace) -> int:
    return _scaffold_only("review")


def cmd_apply(args: argparse.Namespace) -> int:
    return _scaffold_only("apply")


def cmd_lint(args: argparse.Namespace) -> int:
    return _scaffold_only("lint")


def cmd_query(args: argparse.Namespace) -> int:
    return _scaffold_only("query")


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = check_workspace(root)
    schema_ok, schema_problems = schema_status(catalog_path(root))
    if result.ok and schema_ok:
        print(f"Workspace OK: {result.root}")
        print("schema OK")
        return 0

    print(f"Workspace incomplete: {result.root}")
    for path in result.missing:
        print(f"- missing {path}")
    for problem in schema_problems:
        print(f"- {problem}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmwiki",
        description="Local source-backed Markdown wiki compiler.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a new LLM Wiki workspace.")
    init_parser.add_argument("--root", default=".")
    init_parser.set_defaults(func=cmd_init)

    add_parser = subparsers.add_parser("add", help="Add a Markdown, web, or text PDF source.")
    add_parser.add_argument("source")
    add_parser.add_argument("--root", default=".")
    add_parser.set_defaults(func=cmd_add)

    ingest_parser = subparsers.add_parser("ingest", help="Create a staged ingest run for a source.")
    ingest_parser.add_argument("source_id")
    ingest_parser.add_argument("--root", default=".")
    ingest_parser.set_defaults(func=cmd_ingest)

    review_parser = subparsers.add_parser("review", help="Review a staged ingest run.")
    review_parser.add_argument("run_id")
    review_parser.add_argument("--root", default=".")
    review_parser.set_defaults(func=cmd_review)

    apply_parser = subparsers.add_parser("apply", help="Apply a reviewed ingest run.")
    apply_parser.add_argument("run_id")
    apply_parser.add_argument("--root", default=".")
    apply_parser.set_defaults(func=cmd_apply)

    lint_parser = subparsers.add_parser("lint", help="Check wiki health.")
    lint_parser.add_argument("--root", default=".")
    lint_parser.set_defaults(func=cmd_lint)

    query_parser = subparsers.add_parser("query", help="Query the compiled wiki.")
    query_parser.add_argument("question")
    query_parser.add_argument("--root", default=".")
    query_parser.set_defaults(func=cmd_query)

    doctor_parser = subparsers.add_parser("doctor", help="Check workspace structure.")
    doctor_parser.add_argument("--root", default=".")
    doctor_parser.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
