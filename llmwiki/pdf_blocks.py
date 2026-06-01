from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any


METADATA_SCHEMA_VERSION = "source_metadata.v2.9.1"
BLOCK_SCHEMA_VERSION = "source_block.v2.9.1"
PAGE_MARKER_RE = re.compile(r"^<!--\s*page:\d+\s*-->$")
NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*\s+\S")


@dataclass(frozen=True)
class SourceMetadata:
    source_id: str
    title: str
    source_type: str
    page_count: int
    raw_path: str
    normalized_path: str
    metadata_path: str
    blocks_path: str
    chunks_path: str
    filename: str
    extraction_engine: str = "pypdf"
    schema_version: str = METADATA_SCHEMA_VERSION
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceBlock:
    source_id: str
    block_id: str
    block_type: str
    page_start: int
    page_end: int
    order: int
    text_raw: str
    text_clean: str
    section_path: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    content_role: str = "content"
    cleaning_operations: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    schema_version: str = BLOCK_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PdfParseResult:
    metadata: SourceMetadata
    blocks: list[SourceBlock]


def read_pdf_pages(content: bytes) -> tuple[dict[str, Any], list[str]]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    info = reader.metadata or {}
    metadata = {
        "title": clean_metadata_value(getattr(info, "title", None) or info.get("/Title")),
        "author": clean_metadata_value(getattr(info, "author", None) or info.get("/Author")),
    }
    pages = [page.extract_text() or "" for page in reader.pages]
    return metadata, pages


def parse_pdf_source(
    *,
    source_id: str,
    content: bytes,
    filename: str,
    raw_path: str,
    normalized_path: str,
    metadata_path: str,
    blocks_path: str,
    chunks_path: str,
) -> PdfParseResult:
    pdf_metadata, pages = read_pdf_pages(content)
    if not pages:
        raise ValueError("No text pages extracted from PDF")

    blocks, warnings = parse_pdf_blocks(source_id, pages)
    title = choose_pdf_title(pdf_metadata, blocks, filename, warnings)
    authors = extract_authors(blocks)
    abstract = extract_abstract(blocks)
    metadata = SourceMetadata(
        source_id=source_id,
        title=title,
        source_type="pdf",
        page_count=len(pages),
        raw_path=raw_path,
        normalized_path=normalized_path,
        metadata_path=metadata_path,
        blocks_path=blocks_path,
        chunks_path=chunks_path,
        filename=filename,
        authors=authors,
        abstract=abstract,
        warnings=warnings,
    )
    return PdfParseResult(metadata=metadata, blocks=blocks)


def parse_pdf_blocks(source_id: str, pages: list[str]) -> tuple[list[SourceBlock], list[str]]:
    blocks: list[SourceBlock] = []
    document_warnings: list[str] = []
    order = 1
    seen_title = False
    seen_authors = False
    current_section: list[str] = []

    for page_index, page_text in enumerate(pages, start=1):
        page_block_index = 1
        for raw_part in split_pdf_paragraphs(page_text):
            cleaned, warnings = clean_pdf_text(raw_part)
            if not cleaned or PAGE_MARKER_RE.match(cleaned):
                continue
            document_warnings.extend(warnings)

            if is_references_heading(cleaned):
                current_section = ["References"]
                block_type = "section_heading"
            elif is_heading(cleaned):
                current_section = [strip_heading_number(cleaned)]
                block_type = "section_heading"
            elif not seen_title:
                block_type = "title"
                seen_title = True
            elif not seen_authors and not current_section and looks_like_authors(cleaned):
                block_type = "authors"
                seen_authors = True
            elif current_section and current_section[-1].lower() == "abstract":
                block_type = "abstract"
            elif current_section and current_section[-1].lower() == "references":
                block_type = "reference"
            else:
                block_type = "paragraph"

            if cleaned.lower() == "abstract":
                current_section = ["Abstract"]
                block_type = "section_heading"

            block_id = f"{source_id}_p{page_index:03d}_b{page_block_index:04d}"
            blocks.append(
                SourceBlock(
                    source_id=source_id,
                    block_id=block_id,
                    block_type=block_type,
                    page_start=page_index,
                    page_end=page_index,
                    order=order,
                    text_raw=raw_part.strip(),
                    text_clean=cleaned,
                    section_path=list(current_section),
                    warnings=warnings,
                )
            )
            order += 1
            page_block_index += 1

    return blocks, unique_preserve_order(document_warnings)


def split_pdf_paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    groups = re.split(r"\n\s*\n+", text)
    parts: list[str] = []
    for group in groups:
        lines = [line.rstrip() for line in group.splitlines()]
        if not lines:
            continue
        if len(lines) == 1:
            parts.append(lines[0])
            continue
        current: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if PAGE_MARKER_RE.match(stripped) or is_heading(stripped):
                if current:
                    parts.append("\n".join(current))
                    current = []
                parts.append(stripped)
                continue
            if current and looks_like_authors(stripped) and "," in stripped and "," not in " ".join(current):
                parts.append("\n".join(current))
                current = []
                parts.append(stripped)
                continue
            current.append(stripped)
        if current:
            parts.append("\n".join(current))
    return parts


def clean_pdf_text(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", cleaned)
    cleaned = re.sub(r"\n+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if "OSW ORLD" in cleaned:
        cleaned = cleaned.replace("OSW ORLD", "OSWorld")
        warnings.append("repaired spaced token: OSW ORLD -> OSWorld")
    return cleaned, warnings


def choose_pdf_title(
    metadata: dict[str, Any],
    blocks: list[SourceBlock],
    filename: str,
    warnings: list[str],
) -> str:
    metadata_title = clean_metadata_value(metadata.get("title"))
    if metadata_title and not is_parser_marker(metadata_title):
        return metadata_title
    for block in blocks:
        if block.block_type == "title" and not is_parser_marker(block.text_clean):
            return block.text_clean
    fallback = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    warnings.append("pdf title fallback used filename")
    return fallback or "Untitled PDF"


def render_normalized_markdown_from_blocks(metadata: SourceMetadata, blocks: list[SourceBlock]) -> str:
    lines = [
        "---",
        f"source_id: {metadata.source_id}",
        "source_type: pdf",
        f'title: "{escape_frontmatter_string(metadata.title)}"',
        f"page_count: {metadata.page_count}",
        f"metadata_path: {metadata.metadata_path}",
        f"blocks_path: {metadata.blocks_path}",
        f"chunks_path: {metadata.chunks_path}",
        "---",
        "",
        f"# {metadata.title}",
        "",
    ]
    for block in blocks:
        lines.append(block_comment(block))
        lines.append(block.text_clean)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_metadata_json(path: Path, metadata: SourceMetadata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_blocks_jsonl(path: Path, blocks: list[SourceBlock]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(block.to_dict(), ensure_ascii=False) + "\n" for block in blocks)
    path.write_text(content, encoding="utf-8")


def load_metadata_json(path: Path) -> SourceMetadata:
    data = json.loads(path.read_text(encoding="utf-8"))
    return SourceMetadata(**data)


def load_blocks_jsonl(path: Path) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            blocks.append(SourceBlock(**json.loads(line)))
    return blocks


def block_comment(block: SourceBlock) -> str:
    parts = [f"block:{block.block_id}", f"page:{block.page_start}", f"type:{block.block_type}"]
    if block.section_path:
        parts.append("section:" + " > ".join(block.section_path))
    return "<!-- " + "; ".join(parts) + " -->"


def clean_metadata_value(value: Any) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def is_parser_marker(text: str) -> bool:
    return bool(PAGE_MARKER_RE.match(text.strip()))


def is_heading(text: str) -> bool:
    stripped = text.strip()
    if stripped.lower() == "abstract":
        return True
    if NUMBERED_HEADING_RE.match(stripped):
        return True
    return stripped in {"References", "Bibliography", "Acknowledgements", "Appendix"}


def is_standalone_heading(text: str) -> bool:
    return is_heading(text) or looks_like_authors(text)


def is_references_heading(text: str) -> bool:
    return text.strip().lower() in {"references", "bibliography"}


def strip_heading_number(text: str) -> str:
    return re.sub(r"^\d+(?:\.\d+)*\s+", "", text).strip()


def looks_like_authors(text: str) -> bool:
    if len(text) > 200:
        return False
    if any(token in text.lower() for token in ("abstract", "introduction", "references")):
        return False
    return "," in text or bool(re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", text))


def extract_authors(blocks: list[SourceBlock]) -> list[str]:
    for block in blocks:
        if block.block_type == "authors":
            return [part.strip() for part in re.split(r",| and ", block.text_clean) if part.strip()]
    return []


def extract_abstract(blocks: list[SourceBlock]) -> str:
    parts = [block.text_clean for block in blocks if block.block_type == "abstract"]
    return "\n\n".join(parts)


def escape_frontmatter_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
