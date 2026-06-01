from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .llm import main_config_path


@dataclass(frozen=True)
class PdfParserConfig:
    default_backend: str = "pypdf"
    fallback_backend: str = "pypdf"
    mineru_enabled: bool = False
    mineru_command: str = "mineru"
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

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir

    def available(self, config: PdfParserConfig) -> bool:
        if not config.mineru_enabled and self.output_dir is None:
            return False
        if self.output_dir is not None:
            return self.output_dir.exists()
        return shutil.which(config.mineru_command) is not None

    def parse(self, request: PdfParseRequest) -> PdfParseResult:
        raise PdfParserBackendError("MinerU parser backend is not implemented for direct parsing yet")


def load_pdf_parser_config(root: Path) -> PdfParserConfig:
    config_path = main_config_path(root)
    data: dict[str, Any] = {}
    if config_path.exists():
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    section = data.get("pdf_parser", {})
    return PdfParserConfig(
        default_backend=str(section.get("default_backend", "pypdf")),
        fallback_backend=str(section.get("fallback_backend", "pypdf")),
        mineru_enabled=bool(section.get("mineru_enabled", False)),
        mineru_command=str(section.get("mineru_command", "mineru")),
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
        backend = MinerUBackend(output_dir=output_dir)
        if not config.mineru_enabled and output_dir is None:
            raise PdfParserBackendError("MinerU parser backend is disabled in config")
        if not backend.available(config):
            raise PdfParserBackendError("MinerU parser backend is unavailable")
        return PdfParserSelection(backend=backend, config=config)
    if backend_name == "auto":
        mineru = MinerUBackend(output_dir=output_dir)
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
