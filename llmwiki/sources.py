from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .db import catalog_path, connect
from .pdf_blocks import (
    parse_pdf_source,
    render_normalized_markdown_from_blocks,
    write_blocks_jsonl,
    write_metadata_json,
)
from .source_chunks import build_source_chunks, write_chunks_jsonl
from .workspace import utc_now


@dataclass(frozen=True)
class ImportResult:
    source_id: str
    title: str
    raw_path: str
    normalized_path: str
    duplicate: bool


def import_source(
    root: Path,
    locator: str,
    *,
    parser_backend: str | None = None,
    parser_output_dir: Path | None = None,
) -> ImportResult:
    root = root.resolve()
    if is_url(locator):
        content, filename, url = fetch_url(locator)
    else:
        source_path = Path(locator).resolve()
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(locator)
        content = source_path.read_bytes()
        filename = source_path.name
        url = None

    digest = hashlib.sha256(content).hexdigest()
    with connect(catalog_path(root)) as conn:
        row = conn.execute(
            "select source_id, title, raw_path, normalized_path from sources where sha256 = ?",
            (digest,),
        ).fetchone()
        if row:
            return ImportResult(
                source_id=row["source_id"],
                title=row["title"],
                raw_path=row["raw_path"],
                normalized_path=row["normalized_path"],
                duplicate=True,
            )

    source_id = f"src_{digest[:12]}"
    safe_name = safe_filename(filename)
    source_type = infer_source_type(filename, content)
    raw_rel = Path("sources/raw") / f"{source_id}-{safe_name}"
    normalized_rel = Path("sources/normalized") / f"{source_id}.md"
    metadata_rel = Path("sources/metadata") / f"{source_id}.json"
    blocks_rel = Path("sources/blocks") / f"{source_id}.jsonl"
    chunks_rel = Path("sources/chunks") / f"{source_id}.jsonl"
    raw_abs = root / raw_rel
    normalized_abs = root / normalized_rel
    raw_abs.parent.mkdir(parents=True, exist_ok=True)
    normalized_abs.parent.mkdir(parents=True, exist_ok=True)
    raw_abs.write_bytes(content)

    if source_type == "pdf":
        parsed_pdf = parse_pdf_source(
            source_id=source_id,
            content=content,
            filename=filename,
            raw_path=to_posix(raw_rel),
            normalized_path=to_posix(normalized_rel),
            metadata_path=to_posix(metadata_rel),
            blocks_path=to_posix(blocks_rel),
            chunks_path=to_posix(chunks_rel),
            root=root,
            parser_backend=parser_backend,
            parser_output_dir=parser_output_dir,
        )
        write_metadata_json(root / metadata_rel, parsed_pdf.metadata)
        write_blocks_jsonl(root / blocks_rel, parsed_pdf.blocks)
        write_chunks_jsonl(root / chunks_rel, build_source_chunks(source_id, parsed_pdf.blocks))
        normalized_text = render_normalized_markdown_from_blocks(parsed_pdf.metadata, parsed_pdf.blocks)
        title = parsed_pdf.metadata.title
    else:
        normalized_text, title = normalize_content(
            source_id=source_id,
            source_type=source_type,
            raw_path=to_posix(raw_rel),
            sha256=digest,
            url=url,
            filename=filename,
            content=content,
        )
    normalized_abs.write_text(normalized_text, encoding="utf-8", newline="\n")

    with connect(catalog_path(root)) as conn:
        conn.execute(
            """
            insert into sources (
                source_id, title, source_type, raw_path, normalized_path,
                sha256, url, imported_at, status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                title,
                source_type,
                to_posix(raw_rel),
                to_posix(normalized_rel),
                digest,
                url,
                utc_now(),
                "imported",
            ),
        )
    return ImportResult(
        source_id=source_id,
        title=title,
        raw_path=to_posix(raw_rel),
        normalized_path=to_posix(normalized_rel),
        duplicate=False,
    )


def is_url(locator: str) -> bool:
    parsed = urlparse(locator)
    return parsed.scheme in {"http", "https"}


def fetch_url(url: str) -> tuple[bytes, str, str]:
    request = Request(url, headers={"User-Agent": "llmwiki/0.1"})
    with urlopen(request, timeout=30) as response:
        content = response.read()
        content_type = response.headers.get("content-type", "")
    parsed = urlparse(url)
    name = Path(parsed.path).name or "snapshot"
    if "." not in name:
        if "html" in content_type:
            name = f"{name}.html"
        else:
            name = f"{name}.txt"
    return content, name, url


def infer_source_type(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".pdf" or content.startswith(b"%PDF"):
        return "pdf"
    if suffix in {".html", ".htm"}:
        return "web"
    return "text"


def normalize_content(
    source_id: str,
    source_type: str,
    raw_path: str,
    sha256: str,
    url: str | None,
    filename: str,
    content: bytes,
) -> tuple[str, str]:
    body = extract_text(source_type, content)
    title = extract_title(body, filename)
    lines = body.splitlines()
    normalized_lines = [
        "---",
        f"source_id: {source_id}",
        f"title: {yaml_quote(title)}",
        f"source_type: {source_type}",
        f"raw_path: {raw_path}",
        f"sha256: {sha256}",
        f"url: {yaml_quote(url) if url else 'null'}",
        "---",
        "",
        f"# Normalized Source: {title}",
        "",
    ]
    current_paragraph = 0
    in_paragraph = False
    for index, line in enumerate(lines, start=1):
        heading = markdown_heading(line)
        if heading:
            normalized_lines.append(f"<!-- section:{heading} -->")
            in_paragraph = False
        elif line.strip():
            if not in_paragraph:
                current_paragraph += 1
                normalized_lines.append(f"<!-- paragraph:{current_paragraph} -->")
            in_paragraph = True
        else:
            in_paragraph = False
        normalized_lines.append(f"<!-- line:{index} -->")
        normalized_lines.append(f"[line:{index}] {line}")
    normalized_lines.append("")
    return "\n".join(normalized_lines), title


def markdown_heading(line: str) -> str | None:
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
    if not match:
        return None
    return match.group(1).strip()


def extract_text(source_type: str, content: bytes) -> str:
    if source_type == "pdf":
        return extract_pdf_text(content)
    text = content.decode("utf-8", errors="replace")
    if source_type == "web":
        text = html_to_text(text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return (
            "[unsupported-pdf-text-extraction]\n"
            "This PDF was imported, but text extraction requires pypdf."
        )

    import io

    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append(f"<!-- page:{index} -->")
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def html_to_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def extract_title(text: str, filename: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped:
            return stripped[:80]
    return Path(filename).stem.replace("-", " ").replace("_", " ").strip() or "Untitled Source"


def safe_filename(name: str) -> str:
    stem = Path(name).stem or "source"
    suffix = Path(name).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") or "source"
    suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix)
    return f"{stem}{suffix}"


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def to_posix(path: Path) -> str:
    return path.as_posix()
