from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tomllib
from pathlib import Path

from .answer import AskOptions, AskResult, answer_question
from .apply import UnsafePatchError, apply_run
from .db import catalog_path, schema_status
from .ingest import ingest_source, review_run
from .lint import lint_workspace
from .llm import create_provider, load_llm_config, override_llm_config
from .pipeline import AddPipelineError, add_and_process_source
from .providers.base import LLMProviderError
from .query import query_context
from .retrieval_eval import evaluate_retrieval, format_eval_report, sanitize_error
from .retrieval import format_retrieval_prompt, retrieve_context
from .synthesis import SynthesisWritebackError, SynthesisWritebackResult, create_synthesis_run
from .workspace import check_workspace, init_workspace


COMMANDS = (
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
    "llm-test",
    "doctor",
)


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
        result = add_and_process_source(root, args.source)
    except AddPipelineError as exc:
        print(f"Add pipeline failed at: {exc.stage}")
        if exc.source_id:
            print(f"source_id: {exc.source_id}")
        if exc.run_id:
            print(f"run_id: {exc.run_id}")
        print(f"reason: {exc.reason}")
        if exc.debug_command:
            print(f"Debug: {exc.debug_command}")
        return 1

    if result.status == "already_applied":
        print(f"Source already imported: {result.source_id}")
        print("Wiki is already up to date for this source.")
        return 0

    print(f"Added source: {result.source_id}")
    print(f"Processed with: {result.proposal_engine}")
    print(f"Applied run: {result.run_id}")
    print(f"Claims: {result.claim_count}")
    print(f"Patches: {result.patch_count}")
    print("Pages:")
    for page in result.applied_pages:
        print(f"- {page}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    else:
        print("Warnings: none")
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
    print(f"proposal_engine={result.proposal_engine}")
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


def cmd_retrieve(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = retrieve_context(
        root,
        args.question,
        limit=args.limit,
        source_id=args.source_id,
        page_type=args.page_type,
        confidence=args.confidence,
    )
    if args.json or args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_retrieval_prompt(result))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = answer_question(
        root,
        args.question,
        AskOptions(
            limit=args.limit,
            source_id=args.source_id,
            page_type=args.page_type,
            confidence=args.confidence,
        ),
    )
    writeback: SynthesisWritebackResult | None = None
    writeback_error: SynthesisWritebackError | None = None
    if result.status == "answered" and should_writeback(args):
        try:
            writeback = create_synthesis_run(root, result)
        except SynthesisWritebackError as exc:
            writeback_error = exc

    if args.json:
        print(json.dumps(ask_output_dict(result, writeback, writeback_error), ensure_ascii=False, indent=2))
    else:
        print(format_ask_result(result, writeback, writeback_error))
    if writeback_error is not None:
        return 1
    return 0 if result.status in {"answered", "insufficient_evidence", "planned_insufficient_evidence"} else 1


def cmd_eval_retrieval(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    dataset = Path(args.dataset).resolve()
    try:
        summary = evaluate_retrieval(root, dataset, limit=args.limit)
    except Exception as exc:
        print(f"Retrieval eval failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_eval_report(summary))
    return 0


def cmd_llm_test(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    config = override_llm_config(
        load_llm_config(root),
        model=args.model,
        base_url=args.base_url,
        timeout_seconds=args.timeout,
    )
    if not config.enabled:
        print("LLM test failed: [llm].enabled is false in config/config.toml")
        return 1
    provider = create_provider(config, root=root)
    messages = [
        {
            "role": "system",
            "content": "You are a concise test responder for LLMWiki.",
        },
        {
            "role": "user",
            "content": "Reply with one short sentence saying LLMWiki LLM provider is reachable.",
        },
    ]
    try:
        result = provider.complete(messages)
    except (LLMProviderError, ValueError) as exc:
        print(f"LLM test failed: {exc}")
        return 1

    print(f"provider={result['provider']}")
    print(f"model={result['model']}")
    print(f"base_url={config.base_url}")
    print("real_call=true")
    print(f"finish_reason={result.get('finish_reason')}")
    print(f"usage={result.get('usage')}")
    print(f"content_summary={summarize_text(str(result.get('content') or ''))}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = check_workspace(root)
    schema_ok, schema_problems = schema_status(catalog_path(root))
    index_log_ok = (root / "wiki" / "index.md").exists() and (root / "wiki" / "log.md").exists()
    deps_ok, dep_problems = dependency_status()
    _, venv_line = virtualenv_status()
    print(f"Python OK: {sys.version.split()[0]}")
    print(venv_line)
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


def virtualenv_status() -> tuple[bool, str]:
    in_virtualenv = (
        sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        or hasattr(sys, "real_prefix")
        or bool(os.environ.get("VIRTUAL_ENV"))
    )
    if in_virtualenv:
        location = os.environ.get("VIRTUAL_ENV") or sys.prefix
        return True, f"virtual environment OK: {location}"
    return False, "warning: not running inside a Python virtual environment"


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

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Internal/debug: create a staged ingest run for a source.",
    )
    ingest_parser.add_argument("source_id")
    ingest_parser.add_argument("--root", default=".")
    ingest_parser.set_defaults(func=cmd_ingest)

    review_parser = subparsers.add_parser(
        "review",
        help="Internal/debug: inspect a staged or applied ingest run.",
    )
    review_parser.add_argument("run_id")
    review_parser.add_argument("--detail", action="store_true", help="Show full claims and triage details.")
    review_parser.add_argument("--patches", action="store_true", help="Show candidate Markdown patch contents.")
    review_parser.add_argument("--root", default=".")
    review_parser.set_defaults(func=cmd_review)

    apply_parser = subparsers.add_parser(
        "apply",
        help="Internal/debug: apply a staged ingest run.",
    )
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

    retrieve_parser = subparsers.add_parser(
        "retrieve",
        help="Return citation-backed retrieval contexts for RAG or agents.",
    )
    retrieve_parser.add_argument("question")
    retrieve_parser.add_argument("--root", default=".")
    retrieve_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    retrieve_parser.add_argument(
        "--format",
        choices=("json", "prompt"),
        default="json",
        help="Output format. Use prompt for an LLM evidence prompt.",
    )
    retrieve_parser.add_argument("--limit", type=int, default=8)
    retrieve_parser.add_argument("--source-id")
    retrieve_parser.add_argument("--page-type")
    retrieve_parser.add_argument("--confidence")
    retrieve_parser.set_defaults(func=cmd_retrieve)

    ask_parser = subparsers.add_parser(
        "ask",
        help="Answer a question using local wiki evidence and the configured LLM.",
    )
    ask_parser.add_argument("question")
    ask_parser.add_argument("--root", default=".")
    ask_parser.add_argument("--limit", type=int, default=8)
    ask_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    ask_parser.add_argument("--writeback", action="store_true", help="Write the answer back as a synthesis page.")
    ask_parser.add_argument("--no-writeback", action="store_true", help="Do not prompt or write back.")
    ask_parser.add_argument("--source-id")
    ask_parser.add_argument("--page-type")
    ask_parser.add_argument("--confidence")
    ask_parser.set_defaults(func=cmd_ask)

    eval_parser = subparsers.add_parser("eval", help="Run local evaluation suites.")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)
    retrieval_eval_parser = eval_subparsers.add_parser(
        "retrieval",
        help="Evaluate retrieval quality and evidence contract metrics.",
    )
    retrieval_eval_parser.add_argument("--root", default=".")
    retrieval_eval_parser.add_argument("--dataset", required=True)
    retrieval_eval_parser.add_argument("--limit", type=int, default=5)
    retrieval_eval_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    retrieval_eval_parser.set_defaults(func=cmd_eval_retrieval)

    llm_test_parser = subparsers.add_parser(
        "llm-test",
        help="Call the configured real LLM provider once.",
    )
    llm_test_parser.add_argument("--root", default=".")
    llm_test_parser.add_argument("--model")
    llm_test_parser.add_argument("--base-url")
    llm_test_parser.add_argument("--timeout", type=int)
    llm_test_parser.set_defaults(func=cmd_llm_test)

    doctor_parser = subparsers.add_parser("doctor", help="Check workspace structure.")
    doctor_parser.add_argument("--root", default=".")
    doctor_parser.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def summarize_text(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def format_ask_result(
    result: AskResult,
    writeback: SynthesisWritebackResult | None = None,
    writeback_error: SynthesisWritebackError | None = None,
) -> str:
    lines = [
        f"Question: {result.question}",
        "",
        "Answer:",
    ]
    if result.status == "insufficient_evidence":
        lines.append("insufficient_evidence")
    elif result.answer:
        lines.append(result.answer)
    else:
        lines.append(result.status)

    if result.planning:
        lines.extend(["", "Planning:"])
        lines.append(f"- status: {result.planning.get('status', '')}")
        lines.append(f"- subqueries: {result.planning.get('subquery_count', 0)}")
        lines.append(f"- evidence contexts: {result.planning.get('retrieved_context_count', 0)}")

    lines.extend(["", "Citations:"])
    if result.citations:
        for citation in result.citations:
            lines.append(
                f"- {citation.claim_id} {citation.source_id} "
                f"{citation.citation_locator} {citation.page_path}"
            )
    else:
        lines.append("- none")

    if result.warnings:
        lines.extend(["", "Warnings:"])
        for warning in result.warnings:
            lines.append(f"- {warning}")
    else:
        lines.extend(["", "Warnings: none"])

    lines.extend(["", "Writeback:"])
    if writeback is not None:
        lines.append(f"Applied synthesis run: {writeback.run_id}")
        lines.append("Page:")
        for page in writeback.pages:
            lines.append(f"- {page}")
    elif writeback_error is not None:
        lines.append(f"Writeback failed at: {writeback_error.stage}")
        lines.append(f"reason: {writeback_error.reason}")
        if writeback_error.run_id:
            lines.append(f"Debug: llmwiki review {writeback_error.run_id} --detail --root .")
    else:
        lines.append("Not written. Run with --writeback or answer yes when prompted to create a synthesis page.")
    return "\n".join(lines)


def should_writeback(args: argparse.Namespace) -> bool:
    if args.writeback:
        return True
    if args.no_writeback or args.json:
        return False
    if not sys.stdin.isatty():
        return False
    return confirm_writeback()


def confirm_writeback() -> bool:
    answer = input("Write this answer back as a synthesis page? [y/N] ").strip().casefold()
    return answer in {"y", "yes"}


def ask_output_dict(
    result: AskResult,
    writeback: SynthesisWritebackResult | None,
    writeback_error: SynthesisWritebackError | None,
) -> dict[str, object]:
    data = result.to_dict()
    if writeback is not None:
        data["writeback"] = writeback.to_dict()
    elif writeback_error is not None:
        data["writeback"] = {
            "status": "failed",
            "run_id": writeback_error.run_id,
            "pages": [],
            "reason": writeback_error.reason,
        }
    return data
