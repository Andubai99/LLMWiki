from __future__ import annotations

import argparse
import importlib.util
import sys
import tomllib
from pathlib import Path

from .apply import UnsafePatchError, apply_run
from .db import catalog_path, schema_status
from .ingest import ingest_source, review_run
from .lint import lint_workspace
from .query import query_context
from .sources import import_source
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
    root = Path(args.root).resolve()
    try:
        result = import_source(root, args.source)
    except FileNotFoundError:
        print(f"Source not found: {args.source}")
        return 1
    except Exception as exc:
        print(f"Source import failed: {exc}")
        return 1

    if result.duplicate:
        print(f"Source already imported: source_id={result.source_id} title={result.title}")
    else:
        print(f"Imported source: source_id={result.source_id} title={result.title}")
    print(f"raw_path={result.raw_path}")
    print(f"normalized_path={result.normalized_path}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = ingest_source(root, args.source_id)
    except Exception as exc:
        print(f"Ingest failed: {exc}")
        return 1
    print(f"Created ingest run: run_id={result.run_id}")
    print(f"source_id={result.source_id}")
    print(f"claims={result.claim_count}")
    print(f"patches={result.patch_count}")
    print(f"citation_coverage={result.citation_coverage}%")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        print(review_run(root, args.run_id, detail=args.detail, show_patches=args.patches))
    except FileNotFoundError:
        print(f"Run not found: {args.run_id}")
        return 1
    except Exception as exc:
        print(f"Review failed: {exc}")
        return 1
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = apply_run(root, args.run_id)
    except UnsafePatchError as exc:
        print(f"Unsafe patch: {exc}")
        return 1
    except FileNotFoundError:
        print(f"Run not found: {args.run_id}")
        return 1
    except Exception as exc:
        print(f"Apply failed: {exc}")
        return 1
    print(f"Applied ingest run: {result['run_id']}")
    print(f"claims={result['claims']}")
    print(f"patches={result['patches']}")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    report = lint_workspace(root)
    print("\n".join(report.lines))
    return 0 if report.issue_count == 0 else 1


def cmd_query(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    print(query_context(root, args.question))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = check_workspace(root)
    schema_ok, schema_problems = schema_status(catalog_path(root))
    index_log_ok = (root / "wiki" / "index.md").exists() and (root / "wiki" / "log.md").exists()
    deps_ok, dep_problems = dependency_status()
    print(f"Python OK: {sys.version.split()[0]}")
    if result.ok and schema_ok and index_log_ok and deps_ok:
        print("dependencies OK")
        print(f"Workspace OK: {result.root}")
        print("schema OK")
        print("index/log OK")
        return 0

    print(f"Workspace incomplete: {result.root}")
    for path in result.missing:
        print(f"- missing {path}")
    for problem in schema_problems:
        print(f"- {problem}")
    if not index_log_ok:
        print("- index/log missing")
    for problem in dep_problems:
        print(f"- dependency {problem}")
    return 1


def dependency_status() -> tuple[bool, list[str]]:
    problems: list[str] = []
    required = {"pypdf": "pypdf"}
    declared = declared_dependencies()
    for module_name, package_name in required.items():
        importable = importlib.util.find_spec(module_name) is not None
        declared_ok = any(dep.casefold().startswith(package_name) for dep in declared)
        if not importable and not declared_ok:
            problems.append(f"{package_name} missing from runtime and pyproject")
    return not problems, problems


def declared_dependencies() -> list[str]:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if not pyproject.exists():
        return []
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return list(data.get("project", {}).get("dependencies", []))


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
    review_parser.add_argument("--detail", action="store_true", help="Show full claims and triage details.")
    review_parser.add_argument("--patches", action="store_true", help="Show candidate Markdown patch contents.")
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
