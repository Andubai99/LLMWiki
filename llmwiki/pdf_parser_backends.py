from __future__ import annotations

import json
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .llm import main_config_path
from . import mineru_runner


@dataclass(frozen=True)
class PdfParserConfig:
    default_backend: str = "auto"
    fallback_backend: str = "pypdf"
    mineru_enabled: bool = True
    mineru_command: str = "mineru"
    mineru_method: str = ""
    mineru_backend: str = ""
    mineru_api_url: str = ""
    mineru_timeout_seconds: int = 1800
    mineru_max_log_chars: int = 4000
    mineru_extra_args: tuple[str, ...] = ()
    artifact_dir: str = "sources/parser-artifacts"


@dataclass(frozen=True)
class PdfParseRequest:
    root: Path
    source_id: str
    raw_path: Path
    filename: str
    normalized_path: str
    metadata_path: str
    blocks_path: str
    chunks_path: str
    content: bytes
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParserArtifact:
    path: str
    artifact_type: str
    description: str = ""


@dataclass(frozen=True)
class PdfParseResult:
    metadata: Any
    blocks: list[Any]
    artifacts: list[ParserArtifact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    backend_name: str = "pypdf"
    backend_version: str | None = None
    fallback_from: str | None = None


@dataclass(frozen=True)
class PdfParserSelection:
    backend: "PdfParserBackend"
    config: PdfParserConfig
    fallback_from: str | None = None
    warnings: list[str] = field(default_factory=list)


class PdfParserBackendError(RuntimeError):
    pass


class PdfParserBackend(Protocol):
    name: str

    def available(self, config: PdfParserConfig) -> bool:
        ...

    def parse(self, request: PdfParseRequest) -> PdfParseResult:
        ...


class PypdfBackend:
    name = "pypdf"

    def available(self, config: PdfParserConfig) -> bool:
        return True

    def parse(self, request: PdfParseRequest) -> PdfParseResult:
        from .pdf_blocks import (
            SourceMetadata,
            choose_pdf_title,
            extract_abstract,
            extract_authors,
            first_venue_or_status_line,
            parse_pdf_blocks,
            parser_quality_from_blocks,
            read_pdf_pages,
            score_title_candidates,
        )

        pdf_metadata, pages = read_pdf_pages(request.content)
        if not pages:
            raise ValueError("No text pages extracted from PDF")

        blocks, warnings = parse_pdf_blocks(request.source_id, pages, parser_backend=self.name)
        title_candidates = score_title_candidates(metadata=pdf_metadata, blocks=blocks, filename=request.filename)
        title = choose_pdf_title(pdf_metadata, blocks, request.filename, warnings, title_candidates=title_candidates)
        authors = extract_authors(blocks)
        abstract = extract_abstract(blocks)
        selected_candidate = title_candidates[0] if title_candidates else None
        parser_quality = parser_quality_from_blocks(blocks, len(pages), warning_count=len(warnings))
        metadata = SourceMetadata(
            source_id=request.source_id,
            title=title,
            source_type="pdf",
            page_count=len(pages),
            raw_path=to_posix(request.raw_path),
            normalized_path=request.normalized_path,
            metadata_path=request.metadata_path,
            blocks_path=request.blocks_path,
            chunks_path=request.chunks_path,
            filename=request.filename,
            extraction_engine=self.name,
            parser_backend=self.name,
            parser_backend_version=None,
            authors=authors,
            abstract=abstract,
            warnings=warnings,
            title_quality={
                "status": "selected" if selected_candidate else "fallback",
                "selected_source": selected_candidate.source if selected_candidate else "filename",
                "score": selected_candidate.score if selected_candidate else 0.0,
                "reasons": selected_candidate.reasons if selected_candidate else ["filename_fallback"],
            },
            title_candidates=[candidate.to_dict() for candidate in title_candidates],
            paper_identity={
                "title": title,
                "authors": authors,
                "venue_or_status": first_venue_or_status_line(blocks),
                "canonical_names": [title] if title else [],
                "warnings": [],
            },
            parser_quality=parser_quality.to_dict(),
        )
        return PdfParseResult(metadata=metadata, blocks=blocks, warnings=warnings, backend_name=self.name)


class MinerUBackend:
    name = "mineru"

    def __init__(self, *, output_dir: Path | None = None, root: Path | None = None) -> None:
        self.output_dir = output_dir
        self.root = root

    def available(self, config: PdfParserConfig) -> bool:
        if not config.mineru_enabled and self.output_dir is None:
            return False
        if self.output_dir is not None:
            return self.output_dir.exists()
        return mineru_runner.discover_mineru_command(self.root or Path.cwd(), config).available

    def parse(self, request: PdfParseRequest) -> PdfParseResult:
        from .pdf_blocks import SourceBlock, SourceMetadata

        output_dir = self.output_dir or _request_output_dir(request)
        command_result = None
        if output_dir is None:
            config = load_pdf_parser_config(request.root)
            output_dir = _mineru_output_root(request, config)
            discovery = mineru_runner.discover_mineru_command(request.root, config)
            if not discovery.available:
                raise PdfParserBackendError("MinerU parser backend is unavailable")
            command_result = mineru_runner.run_mineru_command(
                mineru_runner.MinerUCommandRequest(
                    root=request.root,
                    source_id=request.source_id,
                    raw_path=request.root / request.raw_path,
                    output_root=output_dir,
                    config=config,
                    resolved_command=discovery.command_path,
                    command_source=discovery.command_source,
                )
            )
            if command_result.returncode != 0 or command_result.timed_out:
                reason = "; ".join(command_result.warnings) or f"MinerU command failed with code {command_result.returncode}"
                raise PdfParserBackendError(reason)
            try:
                content_list_path = mineru_runner.select_mineru_content_list(
                    command_result.content_list_candidates,
                    pdf_stem=Path(request.filename).stem,
                )
            except mineru_runner.MinerUCommandError as exc:
                raise PdfParserBackendError(str(exc)) from exc
        else:
            content_list_path = output_dir / "content_list.json"
        if not content_list_path.exists():
            raise PdfParserBackendError("MinerU content_list.json not found")
        try:
            content = json.loads(content_list_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PdfParserBackendError(f"Invalid MinerU content_list.json: {exc.msg}") from exc
        if not isinstance(content, list):
            raise PdfParserBackendError("MinerU content_list.json must contain a list")

        blocks: list[SourceBlock] = []
        page_counts: dict[int, int] = defaultdict(int)
        seen_title = False
        current_section: list[str] = []
        for index, item in enumerate(content):
            if not isinstance(item, dict):
                raise PdfParserBackendError("MinerU content_list.json entries must be objects")
            page = int(item.get("page_idx", item.get("page", 0))) + 1
            page_counts[page] += 1
            backend_type = str(item.get("type", item.get("category", "unknown")) or "unknown")
            text = _mineru_text(item, backend_type)
            block_type, content_role = _mineru_block_type_and_role(item, backend_type, text, seen_title)
            if block_type == "title":
                seen_title = True
            if block_type == "section_heading" and text:
                current_section = [text]
            block_id = f"{request.source_id}_p{page:03d}_b{page_counts[page]:04d}"
            blocks.append(
                SourceBlock(
                    source_id=request.source_id,
                    block_id=block_id,
                    block_type=block_type,
                    page_start=page,
                    page_end=page,
                    order=index + 1,
                    text_raw=text,
                    text_clean=text,
                    section_path=list(current_section),
                    content_role=content_role,
                    parser_backend=self.name,
                    backend_ref=f"content_list:{index}",
                    backend_type=backend_type,
                    bbox=_mineru_bbox(item),
                    asset_path=str(item.get("img_path", item.get("image_path", "")) or ""),
                    html=str(item.get("html", "")),
                    latex=str(item.get("latex", "")),
                    markdown=str(item.get("markdown", "")),
                    table_markdown=str(item.get("table_body", item.get("table_markdown", "")) or ""),
                )
            )

        title = _first_block_text(blocks, "title") or Path(request.filename).stem
        page_count = max((block.page_start for block in blocks), default=0)
        structured_counts = Counter(block.content_role for block in blocks if block.content_role != "content")
        artifact_path = to_posix(content_list_path)
        command_invoked = command_result is not None
        metadata = SourceMetadata(
            source_id=request.source_id,
            title=title,
            source_type="pdf",
            page_count=page_count,
            raw_path=to_posix(request.raw_path),
            normalized_path=request.normalized_path,
            metadata_path=request.metadata_path,
            blocks_path=request.blocks_path,
            chunks_path=request.chunks_path,
            filename=request.filename,
            extraction_engine=self.name,
            parser_backend=self.name,
            parser_backend_options={"parser_output_dir": to_posix(output_dir)},
            parser_artifact_paths=[artifact_path],
            structured_block_counts=dict(structured_counts),
            parser_command_invoked=command_invoked,
            parser_command=command_result.command if command_result else [],
            parser_command_returncode=command_result.returncode if command_result else None,
            parser_command_duration_seconds=command_result.duration_seconds if command_result else None,
            parser_command_stdout_snippet=command_result.stdout_snippet if command_result else "",
            parser_command_stderr_snippet=command_result.stderr_snippet if command_result else "",
            parser_content_list_path=artifact_path,
            parser_content_list_discovery_count=len(command_result.content_list_candidates) if command_result else 1,
            title_quality={"status": "selected", "selected_source": "mineru", "score": 1.0, "reasons": ["mineru_title"]},
            title_candidates=[{"text": title, "source": "mineru", "score": 1.0, "reasons": ["mineru_title"]}],
            paper_identity={"title": title, "authors": [], "venue_or_status": "", "canonical_names": [title], "warnings": []},
            parser_quality={
                "page_count": page_count,
                "block_count": len(blocks),
                "content_block_count": sum(1 for block in blocks if block.content_role != "ignored"),
                "ignored_block_count": sum(1 for block in blocks if block.content_role == "ignored"),
                "parser_marker_count": 0,
                "page_number_count": sum(1 for block in blocks if block.backend_type == "page_number"),
                "repeated_header_footer_count": 0,
                "warning_count": 0,
                "content_block_ratio": (
                    sum(1 for block in blocks if block.content_role != "ignored") / len(blocks) if blocks else 0.0
                ),
            },
        )
        return PdfParseResult(
            metadata=metadata,
            blocks=blocks,
            artifacts=[ParserArtifact(path=artifact_path, artifact_type="content_list")],
            backend_name=self.name,
        )


def load_pdf_parser_config(root: Path) -> PdfParserConfig:
    config_path = main_config_path(root)
    data: dict[str, Any] = {}
    if config_path.exists():
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    section = data.get("pdf_parser", {})
    extra_args = section.get("mineru_extra_args", [])
    if not isinstance(extra_args, list):
        extra_args = []
    return PdfParserConfig(
        default_backend=str(section.get("default_backend", "auto")),
        fallback_backend=str(section.get("fallback_backend", "pypdf")),
        mineru_enabled=bool(section.get("mineru_enabled", True)),
        mineru_command=str(section.get("mineru_command", "mineru")),
        mineru_method=str(section.get("mineru_method", "")),
        mineru_backend=str(section.get("mineru_backend", "")),
        mineru_api_url=str(section.get("mineru_api_url", "")),
        mineru_timeout_seconds=int(section.get("mineru_timeout_seconds", 1800)),
        mineru_max_log_chars=int(section.get("mineru_max_log_chars", 4000)),
        mineru_extra_args=tuple(str(item) for item in extra_args if isinstance(item, str)),
        artifact_dir=str(section.get("artifact_dir", "sources/parser-artifacts")),
    )


def select_pdf_parser_backend(
    root: Path,
    requested_backend: str | None = None,
    *,
    output_dir: Path | None = None,
) -> PdfParserSelection:
    config = load_pdf_parser_config(root)
    backend_name = (requested_backend or config.default_backend).strip().casefold()
    if backend_name == "pypdf":
        return PdfParserSelection(backend=PypdfBackend(), config=config)
    if backend_name == "mineru":
        backend = MinerUBackend(output_dir=output_dir, root=root)
        if not config.mineru_enabled and output_dir is None:
            raise PdfParserBackendError("MinerU parser backend is disabled in config")
        if not backend.available(config):
            raise PdfParserBackendError("MinerU parser backend is unavailable")
        return PdfParserSelection(backend=backend, config=config)
    if backend_name == "auto":
        mineru = MinerUBackend(output_dir=output_dir, root=root)
        if mineru.available(config):
            return PdfParserSelection(backend=mineru, config=config)
        if config.fallback_backend != "pypdf":
            raise PdfParserBackendError(f"Unsupported PDF parser fallback backend: {config.fallback_backend}")
        return PdfParserSelection(
            backend=PypdfBackend(),
            config=config,
            fallback_from="mineru",
            warnings=["MinerU parser backend unavailable; falling back to pypdf"],
        )
    raise PdfParserBackendError(f"Unsupported PDF parser backend: {backend_name}")


def to_posix(path: str | Path) -> str:
    return Path(path).as_posix()


def _mineru_output_root(request: PdfParseRequest, config: PdfParserConfig) -> Path:
    return request.root / config.artifact_dir / request.source_id / "mineru" / "attempt-0001"


def _request_output_dir(request: PdfParseRequest) -> Path | None:
    value = request.options.get("parser_output_dir")
    if not value:
        return None
    return Path(str(value))


def _mineru_text(item: dict[str, Any], backend_type: str) -> str:
    if backend_type in {"table", "chart"}:
        parts = _list_or_text(item.get("table_caption"))
        body = str(item.get("table_body", item.get("table_markdown", "")) or "")
        if body:
            parts.append(body)
        return "\n".join(part for part in parts if part).strip()
    if backend_type == "equation":
        return str(item.get("text", item.get("latex", "")) or "").strip()
    if backend_type == "image":
        parts = _list_or_text(item.get("caption"))
        if not parts:
            parts = _list_or_text(item.get("image_caption"))
        if not parts:
            parts = [str(item.get("text", ""))]
        return "\n".join(part for part in parts if part).strip()
    return str(item.get("text", item.get("content", "")) or "").strip()


def _list_or_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _mineru_block_type_and_role(
    item: dict[str, Any],
    backend_type: str,
    text: str,
    seen_title: bool,
) -> tuple[str, str]:
    if backend_type in {"header", "footer", "page_number"}:
        return backend_type, "ignored"
    if backend_type in {"table", "chart"}:
        return "table", "table_like"
    if backend_type == "equation":
        return "equation", "equation_like"
    if backend_type == "image":
        return ("caption" if text else "image"), ("caption" if text else "image")
    level = item.get("text_level", item.get("level"))
    if level is not None:
        if not seen_title and text:
            return "title", "content"
        return "section_heading", "content"
    return "paragraph", "content"


def _mineru_bbox(item: dict[str, Any]) -> list[float]:
    bbox = item.get("bbox")
    if not isinstance(bbox, list):
        return []
    values: list[float] = []
    for value in bbox:
        if not isinstance(value, (int, float)):
            return []
        values.append(value)
    return values


def _first_block_text(blocks: list[Any], block_type: str) -> str:
    for block in blocks:
        if getattr(block, "block_type", "") == block_type and getattr(block, "text_clean", ""):
            return str(block.text_clean)
    return ""
