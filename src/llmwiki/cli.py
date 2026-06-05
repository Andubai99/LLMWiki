from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tomllib
from pathlib import Path

from .ask.answer import AskOptions, AskResult, answer_question
from .corpus.formatting import (
    batch_payload,
    format_import_summary,
    format_inventory_summary,
    format_json,
    format_status_summary,
    inventory_payload,
)
from .corpus.inventory import build_inventory
from .corpus.runner import import_corpus, retry_corpus, skip_item, status as corpus_status
from .ingestion.apply import UnsafePatchError, apply_run
from .db import catalog_path, schema_status
from .ingestion.ingest import ingest_source, review_run
from .lint import lint_workspace
from .maintenance.clean import clean_workspace, format_clean_report
from .llm import create_provider, load_llm_config, override_llm_config
from .metrics.formatting import (
    format_metric_canonicalization,
    format_metric_json,
    format_metric_list,
    format_metric_timeline,
    metric_canonicalization_payload,
    metric_list_payload,
    metric_timeline_payload,
)
from .metrics.canonicalization import (
    MetricCanonicalizationCatalogError,
    MetricCanonicalizationFilterError,
    build_metric_canonicalization_report,
)
from .metrics.timeline import (
    TimelineCatalogError,
    TimelineFilterError,
    build_metric_list,
    build_metric_timeline,
)
from .ingestion.pipeline import AddPipelineError, add_and_process_source
from .pdf.quality import evaluate_pdf_quality, format_pdf_quality_report
from .pdf.parser_backends import load_pdf_parser_config
from .pdf.mineru_runner import probe_mineru_status
from .providers.base import LLMProviderError
from .retrieval.eval import evaluate_retrieval, format_eval_report, sanitize_error
from .retrieval.query import query_context
from .retrieval import format_retrieval_prompt, retrieve_context
from .evals.result_evidence import (
    ResultEvidenceCatalogError,
    ResultEvidenceFilterError,
    build_result_evidence_quality,
    format_result_evidence_json,
    format_result_evidence_quality,
)
from .evals.corpus_results import (
    CorpusResultsCatalogError,
    CorpusResultsFilterError,
    build_corpus_results_eval,
    format_corpus_results,
    format_corpus_results_json,
)
from .synthesis import SynthesisWritebackError, SynthesisWritebackResult, create_synthesis_run
from .synthesis.planner import (
    SynthesisPlan,
    SynthesisPlanningError,
    SynthesisPlanningOptions,
    plan_synthesis_writeback,
)
from .ui.server import serve_ui
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
    "corpus",
    "metric",
    "clean",
    "embeddings",
    "parsers",
    "ui",
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
        parser_output_dir = Path(args.parser_output_dir).resolve() if getattr(args, "parser_output_dir", None) else None
        result = add_and_process_source(
            root,
            args.source,
            parser_backend=getattr(args, "parser", None),
            parser_output_dir=parser_output_dir,
        )
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
    synthesis_plan: SynthesisPlan | None = None
    writeback: SynthesisWritebackResult | None = None
    writeback_error: SynthesisWritebackError | None = None
    if result.status == "answered" and should_plan_synthesis(args):
        planning_options = SynthesisPlanningOptions(writeback_mode=args.writeback_mode)
        try:
            synthesis_plan = plan_synthesis_writeback(root, result, planning_options)
        except SynthesisPlanningError as exc:
            writeback_error = SynthesisWritebackError(stage="prepare", reason=sanitize_error(exc))
        if synthesis_plan is not None and synthesis_plan.action == "needs_review":
            writeback_error = SynthesisWritebackError(
                stage="prepare",
                reason="Synthesis plan needs review before writeback.",
            )
        elif synthesis_plan is not None and should_apply_synthesis(args, synthesis_plan):
            try:
                writeback = create_synthesis_run(
                    root,
                    result,
                    synthesis_plan,
                    planning_options=planning_options,
                )
            except (SynthesisWritebackError, SynthesisPlanningError) as exc:
                if isinstance(exc, SynthesisWritebackError):
                    writeback_error = exc
                else:
                    writeback_error = SynthesisWritebackError(stage="prepare", reason=sanitize_error(exc))

    if args.json:
        print(
            json.dumps(
                ask_output_dict(result, writeback, writeback_error, synthesis_plan),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_ask_result(result, writeback, writeback_error, synthesis_plan))
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


def cmd_eval_pdf_quality(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        summary = evaluate_pdf_quality(root)
    except Exception as exc:
        print(f"PDF quality eval failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_pdf_quality_report(summary))
    return 0


def cmd_eval_result_evidence(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        summary = build_result_evidence_quality(
            root,
            source_id=args.source_id,
            paper_id=args.paper_id,
            metric=args.metric,
            dataset=args.dataset,
            task=args.task,
            limit=args.limit,
            offset=args.offset,
        )
    except (ResultEvidenceCatalogError, ResultEvidenceFilterError, OSError, ValueError) as exc:
        print(f"Result evidence eval failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(format_result_evidence_json(summary.to_dict()))
    else:
        print(format_result_evidence_quality(summary))
    return 0


def cmd_eval_corpus_results(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        summary = build_corpus_results_eval(
            root,
            metric=args.metric,
            dataset=args.dataset,
            task=args.task,
            limit=args.limit,
            offset=args.offset,
        )
    except (CorpusResultsCatalogError, CorpusResultsFilterError, OSError, ValueError) as exc:
        print(f"Corpus results eval failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(format_corpus_results_json(summary.to_dict()))
    else:
        print(format_corpus_results(summary))
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = clean_workspace(root, scope=args.scope, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"Clean failed: {exc}")
        return 1
    print(format_clean_report(result))
    return 0


def cmd_corpus_import(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    inputs = [args.path] if args.path else []
    try:
        result = import_corpus(
            root,
            inputs,
            recursive=args.recursive,
            list_file=args.list_file,
            dry_run=args.dry_run,
            fail_fast=args.fail_fast,
            parser_backend=args.parser,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Corpus import failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(format_json(batch_payload(result.batch, result.items, result.attempts)))  # type: ignore[arg-type]
    else:
        print(format_import_summary(result.batch, result.items, dry_run=result.dry_run))  # type: ignore[arg-type]
    return result.exit_code


def cmd_corpus_status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = corpus_status(root, args.batch_id)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Corpus status failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        if args.batch_id:
            print(format_json(batch_payload(result.batch, result.items, result.attempts)))  # type: ignore[arg-type]
        else:
            print(
                format_json(
                    {
                        "batches": [batch.to_dict() for batch in result.batches or []],
                        "items_by_batch": {
                            batch_id: [item.to_dict() for item in items]
                            for batch_id, items in (result.items_by_batch or {}).items()
                        },
                    }
                )
            )
    else:
        print(format_status_summary(result.batches or [], result.items_by_batch or {}))
    return 0


def cmd_corpus_retry(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = retry_corpus(
            root,
            args.batch_id,
            item_id=args.item,
            failed_only=args.failed_only,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Corpus retry failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(format_json(batch_payload(result.batch, result.items, result.attempts)))  # type: ignore[arg-type]
    else:
        print(format_import_summary(result.batch, result.items))  # type: ignore[arg-type]
    return result.exit_code


def cmd_corpus_skip(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = skip_item(root, args.batch_id, args.item, reason=args.reason or "")
    except (FileNotFoundError, ValueError) as exc:
        print(f"Corpus skip failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(format_json(batch_payload(result.batch, result.items, result.attempts)))  # type: ignore[arg-type]
    else:
        print(format_import_summary(result.batch, result.items))  # type: ignore[arg-type]
    return 0


def cmd_corpus_inventory(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = build_inventory(root)
    except (OSError, ValueError) as exc:
        print(f"Corpus inventory failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(format_json(inventory_payload(result)))
    else:
        print(format_inventory_summary(result))
    return 0


def cmd_metric_list(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = build_metric_list(
            root,
            query=args.query,
            dataset=args.dataset,
            task=args.task,
            limit=args.limit,
            offset=args.offset,
        )
    except (TimelineCatalogError, TimelineFilterError, OSError, ValueError) as exc:
        print(f"Metric list failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(format_metric_json(metric_list_payload(result)))
    else:
        print(format_metric_list(result))
    return 0


def cmd_metric_timeline(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = build_metric_timeline(
            root,
            metric=args.metric,
            dataset=args.dataset,
            task=args.task,
            method=args.method,
            source_id=args.source_id,
            paper_id=args.paper_id,
            year_from=args.year_from,
            year_to=args.year_to,
            limit=args.limit,
            offset=args.offset,
        )
    except (TimelineCatalogError, TimelineFilterError, OSError, ValueError) as exc:
        print(f"Metric timeline failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(format_metric_json(metric_timeline_payload(result)))
    else:
        print(format_metric_timeline(result))
    return 0


def cmd_metric_canonicalize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        result = build_metric_canonicalization_report(
            root,
            metric=args.metric,
            dataset=args.dataset,
            task=args.task,
            limit=args.limit,
            offset=args.offset,
        )
    except (MetricCanonicalizationCatalogError, MetricCanonicalizationFilterError, OSError, ValueError) as exc:
        print(f"Metric canonicalization failed: {sanitize_error(exc)}")
        return 1
    if args.json:
        print(format_metric_json(metric_canonicalization_payload(result)))
    else:
        print(format_metric_canonicalization(result))
    return 0


def cmd_parsers_status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    config = load_pdf_parser_config(root)
    mineru = probe_mineru_status(config, root)
    data = {
        "schema_version": "parser_status.v2.9.6",
        "default_backend": config.default_backend,
        "fallback_backend": config.fallback_backend,
        "mineru_enabled": config.mineru_enabled,
        "mineru_command": config.mineru_command,
        "mineru_command_path": mineru["mineru_command_path"],
        "mineru_command_source": mineru["mineru_command_source"],
        "mineru_backend": mineru["mineru_backend"],
        "mineru_method": mineru["mineru_method"],
        "mineru_extra_args": mineru["mineru_extra_args"],
        "mineru_available": bool(mineru["mineru_available"]),
        "warnings": list(mineru.get("warnings", [])),
        "pypdf_available": True,
        "artifact_dir": config.artifact_dir,
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"default_backend={data['default_backend']}")
    print(f"fallback_backend={data['fallback_backend']}")
    print(f"mineru_enabled={bool_text(bool(data['mineru_enabled']))}")
    print(f"mineru_available={bool_text(bool(data['mineru_available']))}")
    print(f"mineru_command={data['mineru_command']}")
    print(f"mineru_command_source={data['mineru_command_source']}")
    print(f"mineru_backend={data['mineru_backend']}")
    print(f"mineru_method={data['mineru_method']}")
    print(f"mineru_extra_args={json.dumps(data['mineru_extra_args'], ensure_ascii=False)}")
    if data["mineru_command_path"]:
        print(f"mineru_command_path={data['mineru_command_path']}")
    for warning in data["warnings"]:
        print(f"warning={warning}")
    print(f"pypdf_available={bool_text(bool(data['pypdf_available']))}")
    print(f"artifact_dir={data['artifact_dir']}")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    serve_ui(root, args.host, args.port, open_browser=not args.no_open)
    return 0


def cmd_embeddings_status(args: argparse.Namespace) -> int:
    from .vector.embeddings import load_embedding_config
    from .vector.index import vector_index_status

    root = Path(args.root).resolve()
    config = load_embedding_config(root)
    status = vector_index_status(root)
    print(f"enabled={bool_text(config.enabled)}")
    print(f"provider={config.provider}")
    print(f"model={config.model}")
    print(f"configured_dimension={config.dimension}")
    print(f"index_present={bool_text(status.index_present)}")
    print(f"stale={bool_text(status.stale)}")
    print(f"chunk_count={status.chunk_count}")
    if status.dimension is not None:
        print(f"index_dimension={status.dimension}")
    if status.failure_stage:
        print(f"failure_stage={status.failure_stage}")
    return 0


def cmd_embeddings_test(args: argparse.Namespace) -> int:
    from .vector import embeddings

    root = Path(args.root).resolve()
    config = embeddings.load_embedding_config(root)
    if not config.enabled:
        print("Embedding test failed: [embedding].enabled is false in config/config.toml")
        return 1
    try:
        provider = embeddings.create_embedding_provider(config, root=root)
        vectors = provider.embed_texts([args.text])
    except (embeddings.EmbeddingProviderError, ValueError) as exc:
        print(f"Embedding test failed: {embeddings.sanitize_embedding_error(str(exc))}")
        return 1
    dimension = len(vectors[0]) if vectors else 0
    print("status=ok")
    print(f"provider={config.provider}")
    print(f"model={config.model}")
    print(f"dimension={dimension}")
    print(f"vectors={len(vectors)}")
    return 0


def cmd_embeddings_rebuild(args: argparse.Namespace) -> int:
    from .vector import embeddings
    from .vector.index import (
        build_embedding_chunks,
        catalog_fingerprint,
        new_manifest,
        write_vector_index,
    )

    root = Path(args.root).resolve()
    config = embeddings.load_embedding_config(root)
    if not config.enabled:
        print("Embeddings rebuild failed: [embedding].enabled is false in config/config.toml")
        return 1
    try:
        chunks = build_embedding_chunks(root)
        provider = embeddings.create_embedding_provider(config, root=root)
        vectors: list[list[float]] = []
        for batch in batched([chunk.text for chunk in chunks], args.batch_size):
            vectors.extend(provider.embed_texts(batch))
        dimension = len(vectors[0]) if vectors else config.dimension
        manifest = new_manifest(
            provider=config.provider,
            model=config.model,
            dimension=dimension,
            chunk_count=len(chunks),
            catalog_fingerprint_value=catalog_fingerprint(root),
        )
        write_vector_index(root, chunks, vectors, manifest)
    except (embeddings.EmbeddingProviderError, ValueError, OSError) as exc:
        print(f"Embeddings rebuild failed: {embeddings.sanitize_embedding_error(str(exc))}")
        return 1

    print("status=rebuilt")
    print(f"provider={config.provider}")
    print(f"model={config.model}")
    print(f"dimension={dimension}")
    print(f"chunks={len(chunks)}")
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


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def batched(items: list[str], batch_size: int) -> list[list[str]]:
    size = max(1, batch_size)
    return [items[index : index + size] for index in range(0, len(items), size)]


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
    add_parser.add_argument("--parser", default=None, help=argparse.SUPPRESS)
    add_parser.add_argument("--parser-output-dir", default=None, help=argparse.SUPPRESS)
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
    ask_parser.add_argument("--preview-writeback", action="store_true", help="Preview synthesis create/update without writing.")
    ask_parser.add_argument(
        "--writeback-mode",
        choices=("auto", "create", "update"),
        default="auto",
        help="Constrain synthesis writeback planning.",
    )
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
    pdf_quality_eval_parser = eval_subparsers.add_parser(
        "pdf-quality",
        help="Evaluate local PDF parser quality metrics.",
    )
    pdf_quality_eval_parser.add_argument("--root", default=".")
    pdf_quality_eval_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    pdf_quality_eval_parser.set_defaults(func=cmd_eval_pdf_quality)
    result_evidence_eval_parser = eval_subparsers.add_parser(
        "result-evidence",
        help="Evaluate metric result evidence locator and context quality.",
    )
    result_evidence_eval_parser.add_argument("--root", default=".")
    result_evidence_eval_parser.add_argument("--source-id")
    result_evidence_eval_parser.add_argument("--paper-id")
    result_evidence_eval_parser.add_argument("--metric")
    result_evidence_eval_parser.add_argument("--dataset")
    result_evidence_eval_parser.add_argument("--task")
    result_evidence_eval_parser.add_argument("--limit", type=int, default=None)
    result_evidence_eval_parser.add_argument("--offset", type=int, default=None)
    result_evidence_eval_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    result_evidence_eval_parser.set_defaults(func=cmd_eval_result_evidence)
    corpus_results_eval_parser = eval_subparsers.add_parser(
        "corpus-results",
        help="Summarize corpus-level metric result acceptance quality.",
    )
    corpus_results_eval_parser.add_argument("--root", default=".")
    corpus_results_eval_parser.add_argument("--metric")
    corpus_results_eval_parser.add_argument("--dataset")
    corpus_results_eval_parser.add_argument("--task")
    corpus_results_eval_parser.add_argument("--limit", type=int, default=None)
    corpus_results_eval_parser.add_argument("--offset", type=int, default=None)
    corpus_results_eval_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    corpus_results_eval_parser.set_defaults(func=cmd_eval_corpus_results)

    metric_parser = subparsers.add_parser("metric", help="Query metric result timelines.")
    metric_subparsers = metric_parser.add_subparsers(dest="metric_command", required=True)
    metric_list_parser = metric_subparsers.add_parser(
        "list",
        help="List available metric names from durable result claims.",
    )
    metric_list_parser.add_argument("--root", default=".")
    metric_list_parser.add_argument("--query")
    metric_list_parser.add_argument("--dataset")
    metric_list_parser.add_argument("--task")
    metric_list_parser.add_argument("--limit", type=int, default=None)
    metric_list_parser.add_argument("--offset", type=int, default=None)
    metric_list_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    metric_list_parser.set_defaults(func=cmd_metric_list)

    metric_timeline_parser = metric_subparsers.add_parser(
        "timeline",
        help="Show a source-backed timeline for a metric.",
    )
    metric_timeline_parser.add_argument("metric")
    metric_timeline_parser.add_argument("--root", default=".")
    metric_timeline_parser.add_argument("--dataset")
    metric_timeline_parser.add_argument("--task")
    metric_timeline_parser.add_argument("--method")
    metric_timeline_parser.add_argument("--source-id")
    metric_timeline_parser.add_argument("--paper-id")
    metric_timeline_parser.add_argument("--year-from", type=int, default=None)
    metric_timeline_parser.add_argument("--year-to", type=int, default=None)
    metric_timeline_parser.add_argument("--limit", type=int, default=None)
    metric_timeline_parser.add_argument("--offset", type=int, default=None)
    metric_timeline_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    metric_timeline_parser.set_defaults(func=cmd_metric_timeline)

    metric_canonicalize_parser = metric_subparsers.add_parser(
        "canonicalize",
        help="Report conservative metric canonicalization and timeline readiness.",
    )
    metric_canonicalize_parser.add_argument("--root", default=".")
    metric_canonicalize_parser.add_argument("--metric")
    metric_canonicalize_parser.add_argument("--dataset")
    metric_canonicalize_parser.add_argument("--task")
    metric_canonicalize_parser.add_argument("--limit", type=int, default=None)
    metric_canonicalize_parser.add_argument("--offset", type=int, default=None)
    metric_canonicalize_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    metric_canonicalize_parser.set_defaults(func=cmd_metric_canonicalize)

    corpus_parser = subparsers.add_parser("corpus", help="Manage corpus import batches.")
    corpus_subparsers = corpus_parser.add_subparsers(dest="corpus_command", required=True)
    corpus_import_parser = corpus_subparsers.add_parser(
        "import",
        help="Queue and process a local corpus import batch.",
    )
    corpus_import_parser.add_argument("path", nargs="?")
    corpus_import_parser.add_argument("--root", default=".")
    corpus_import_parser.add_argument("--dry-run", action="store_true")
    corpus_import_parser.add_argument("--recursive", action="store_true")
    corpus_import_parser.add_argument("--list-file")
    corpus_import_parser.add_argument("--fail-fast", action="store_true")
    corpus_import_parser.add_argument("--parser", choices=("auto", "pypdf", "mineru"), default=None)
    corpus_import_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    corpus_import_parser.set_defaults(func=cmd_corpus_import)

    corpus_status_parser = corpus_subparsers.add_parser(
        "status",
        help="Show corpus import batch status without running imports.",
    )
    corpus_status_parser.add_argument("batch_id", nargs="?")
    corpus_status_parser.add_argument("--root", default=".")
    corpus_status_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    corpus_status_parser.set_defaults(func=cmd_corpus_status)

    corpus_retry_parser = corpus_subparsers.add_parser(
        "retry",
        help="Retry failed or interrupted corpus batch items.",
    )
    corpus_retry_parser.add_argument("batch_id")
    corpus_retry_parser.add_argument("--root", default=".")
    corpus_retry_parser.add_argument("--failed-only", action="store_true")
    corpus_retry_parser.add_argument("--item")
    corpus_retry_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    corpus_retry_parser.set_defaults(func=cmd_corpus_retry)

    corpus_skip_parser = corpus_subparsers.add_parser(
        "skip",
        help="Mark a pending or failed corpus batch item as skipped.",
    )
    corpus_skip_parser.add_argument("batch_id")
    corpus_skip_parser.add_argument("item")
    corpus_skip_parser.add_argument("--root", default=".")
    corpus_skip_parser.add_argument("--reason", default="")
    corpus_skip_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    corpus_skip_parser.set_defaults(func=cmd_corpus_skip)

    corpus_inventory_parser = corpus_subparsers.add_parser(
        "inventory",
        help="Show read-only paper identity inventory for catalog sources.",
    )
    corpus_inventory_parser.add_argument("--root", default=".")
    corpus_inventory_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    corpus_inventory_parser.set_defaults(func=cmd_corpus_inventory)

    clean_parser = subparsers.add_parser(
        "clean",
        help="Remove generated workspace caches and run artifacts.",
    )
    clean_parser.add_argument("--root", default=".")
    clean_parser.add_argument(
        "--scope",
        choices=("cache", "generated", "all"),
        default="cache",
        help="What to clean. Default only removes caches and test workspaces.",
    )
    clean_parser.add_argument("--dry-run", action="store_true", help="List removals without deleting files.")
    clean_parser.set_defaults(func=cmd_clean)

    parsers_parser = subparsers.add_parser("parsers", help="Inspect local parser backend availability.")
    parsers_subparsers = parsers_parser.add_subparsers(dest="parsers_command", required=True)
    parsers_status_parser = parsers_subparsers.add_parser(
        "status",
        help="Show parser backend status without parsing documents.",
    )
    parsers_status_parser.add_argument("--root", default=".")
    parsers_status_parser.add_argument("--json", action="store_true", help="Output stable machine-readable JSON.")
    parsers_status_parser.set_defaults(func=cmd_parsers_status)

    ui_parser = subparsers.add_parser("ui", help="Start the local dashboard UI.")
    ui_parser.add_argument("--root", default=".")
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--port", type=int, default=8765)
    ui_parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically.")
    ui_parser.set_defaults(func=cmd_ui)

    embeddings_parser = subparsers.add_parser(
        "embeddings",
        help="Manage the local rebuildable embedding vector index.",
    )
    embeddings_subparsers = embeddings_parser.add_subparsers(dest="embeddings_command", required=True)
    embeddings_status_parser = embeddings_subparsers.add_parser(
        "status",
        help="Show local embedding index status without calling the provider.",
    )
    embeddings_status_parser.add_argument("--root", default=".")
    embeddings_status_parser.set_defaults(func=cmd_embeddings_status)

    embeddings_test_parser = embeddings_subparsers.add_parser(
        "test",
        help="Call the configured embedding provider once.",
    )
    embeddings_test_parser.add_argument("--root", default=".")
    embeddings_test_parser.add_argument("--text", default="LLMWiki embedding test")
    embeddings_test_parser.set_defaults(func=cmd_embeddings_test)

    embeddings_rebuild_parser = embeddings_subparsers.add_parser(
        "rebuild",
        help="Rebuild state/embeddings from the local catalog.",
    )
    embeddings_rebuild_parser.add_argument("--root", default=".")
    embeddings_rebuild_parser.add_argument("--batch-size", type=int, default=16)
    embeddings_rebuild_parser.set_defaults(func=cmd_embeddings_rebuild)

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
    synthesis_plan: SynthesisPlan | None = None,
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
        lines.extend(["", format_synthesis_plan_dict(writeback.synthesis_plan), ""])
        lines.append(f"Applied synthesis run: {writeback.run_id}")
        lines.append("Page:")
        for page in writeback.pages:
            lines.append(f"- {page}")
    elif writeback_error is not None:
        lines.append(f"Writeback failed at: {writeback_error.stage}")
        lines.append(f"reason: {writeback_error.reason}")
        if writeback_error.run_id:
            lines.append(f"Debug: llmwiki review {writeback_error.run_id} --detail --root .")
    elif synthesis_plan is not None:
        lines.extend(["", format_synthesis_plan_dict(synthesis_plan.to_dict())])
        lines.append("Not written. Run with --writeback to apply this synthesis plan.")
    else:
        lines.append("Not written. Run with --writeback or answer yes when prompted to create a synthesis page.")
    return "\n".join(lines)


def should_plan_synthesis(args: argparse.Namespace) -> bool:
    if args.writeback or args.preview_writeback:
        return True
    if args.no_writeback or args.json:
        return False
    if not sys.stdin.isatty():
        return False
    return True


def should_apply_synthesis(args: argparse.Namespace, plan: SynthesisPlan) -> bool:
    if args.preview_writeback:
        return False
    if args.writeback:
        return True
    if args.no_writeback or args.json:
        return False
    if not sys.stdin.isatty():
        return False
    print(format_synthesis_plan_dict(plan.to_dict()))
    return confirm_writeback()


def confirm_writeback() -> bool:
    answer = input("Write this answer back as a synthesis page? [y/N] ").strip().casefold()
    return answer in {"y", "yes"}


def ask_output_dict(
    result: AskResult,
    writeback: SynthesisWritebackResult | None,
    writeback_error: SynthesisWritebackError | None,
    synthesis_plan: SynthesisPlan | None = None,
) -> dict[str, object]:
    data = result.to_dict()
    if synthesis_plan is not None:
        data["synthesis_plan"] = synthesis_plan.to_dict()
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


def format_synthesis_plan_dict(plan: dict[str, object]) -> str:
    lines = [
        "Synthesis proposal:",
        f"- action: {plan.get('action', '')}",
        f"- page: {plan.get('target_path', '')}",
        f"- title: {plan.get('title', '')}",
        f"- evidence claims: {len(plan.get('evidence_claim_ids', [])) if isinstance(plan.get('evidence_claim_ids'), list) else 0}",
    ]
    related_pages = plan.get("related_pages")
    if isinstance(related_pages, list) and related_pages:
        lines.append("- related pages:")
        lines.extend(f"  - {page}" for page in related_pages)
    warnings = plan.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append("- warnings:")
        lines.extend(f"  - {warning}" for warning in warnings)
    return "\n".join(lines)
