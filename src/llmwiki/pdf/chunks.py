from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .blocks import SourceBlock, block_evidence_text


CHUNK_SCHEMA_VERSION = "source_chunk.v2.9.2"
DEFAULT_TARGET_TOKENS = 4500
DEFAULT_MAX_TOKENS = 6000


@dataclass(frozen=True)
class SourceChunk:
    source_id: str
    chunk_id: str
    chunk_type: str
    block_ids: list[str]
    context_block_ids: list[str]
    section_path: list[str]
    page_start: int
    page_end: int
    token_estimate: int
    schema_version: str = CHUNK_SCHEMA_VERSION
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def build_source_chunks(
    source_id: str,
    blocks: list[SourceBlock],
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[SourceChunk]:
    chunks: list[SourceChunk] = []
    next_index = 1
    diagnostics = chunk_diagnostics(blocks)
    content_blocks = [block for block in blocks if getattr(block, "content_role", "content") != "ignored"]

    metadata_ids = [
        block.block_id
        for block in content_blocks
        if block.block_type in {"title", "authors", "abstract"}
    ]
    if metadata_ids:
        chunks.append(
            make_chunk(
                source_id,
                next_index,
                "metadata_summary",
                [block for block in content_blocks if block.block_id in metadata_ids],
                [],
                target_tokens,
                max_tokens,
                diagnostics=diagnostics,
            )
        )
        next_index += 1

    headings_by_section: dict[tuple[str, ...], SourceBlock] = {}
    section_blocks: dict[tuple[str, ...], list[SourceBlock]] = {}
    for block in content_blocks:
        section_key = tuple(block.section_path)
        if block.block_type == "section_heading" and section_key:
            headings_by_section[section_key] = block
            continue
        if block.block_type in {"title", "authors", "abstract"}:
            continue
        if not section_key:
            section_key = ("Body",)
        section_blocks.setdefault(section_key, []).append(block)

    for section_key, section_items in section_blocks.items():
        context = [headings_by_section[section_key].block_id] if section_key in headings_by_section else []
        chunk_type = section_chunk_type(section_key, section_items)
        section_chunks = split_section_blocks(
            source_id,
            section_key,
            section_items,
            context,
            next_index,
            chunk_type,
            target_tokens,
            max_tokens,
            diagnostics,
        )
        chunks.extend(section_chunks)
        next_index += len(section_chunks)

        result_chunks = build_result_focused_chunks(
            source_id,
            section_key,
            section_items,
            context,
            next_index,
            target_tokens,
            max_tokens,
            diagnostics,
        )
        chunks.extend(result_chunks)
        next_index += len(result_chunks)

    return chunks


def build_result_focused_chunks(
    source_id: str,
    section_key: tuple[str, ...],
    section_blocks: list[SourceBlock],
    section_context_block_ids: list[str],
    start_index: int,
    target_tokens: int,
    max_tokens: int,
    diagnostics: dict[str, int] | None = None,
) -> list[SourceChunk]:
    chunks: list[SourceChunk] = []
    next_index = start_index
    for index, block in enumerate(section_blocks):
        if not is_result_focus_block(section_key, block):
            continue
        context_ids = result_context_block_ids(section_blocks, index, section_context_block_ids)
        warning = classify_result_focus_block(section_key, block)
        chunks.append(
            make_chunk(
                source_id,
                next_index,
                "result_evidence_extraction",
                [block],
                context_ids,
                target_tokens,
                max_tokens,
                warnings=[warning],
                diagnostics=diagnostics,
            )
        )
        next_index += 1
    return chunks


def result_context_block_ids(
    section_blocks: list[SourceBlock],
    focus_index: int,
    section_context_block_ids: list[str],
) -> list[str]:
    focus = section_blocks[focus_index]
    context: list[str] = []
    for block_id in section_context_block_ids:
        if block_id != focus.block_id:
            context.append(block_id)
    for candidate in nearby_blocks(section_blocks, focus_index):
        if candidate.block_id == focus.block_id:
            continue
        if getattr(candidate, "content_role", "content") == "ignored":
            continue
        if candidate.block_id not in context:
            context.append(candidate.block_id)
    return context


def nearby_blocks(section_blocks: list[SourceBlock], focus_index: int) -> list[SourceBlock]:
    start = max(0, focus_index - 2)
    end = min(len(section_blocks), focus_index + 3)
    return section_blocks[start:focus_index] + section_blocks[focus_index + 1 : end]


def split_section_blocks(
    source_id: str,
    section_key: tuple[str, ...],
    section_blocks: list[SourceBlock],
    context_block_ids: list[str],
    start_index: int,
    chunk_type: str,
    target_tokens: int,
    max_tokens: int,
    diagnostics: dict[str, int] | None = None,
) -> list[SourceChunk]:
    chunks: list[SourceChunk] = []
    current: list[SourceBlock] = []
    current_tokens = 0
    next_index = start_index
    split_needed = total_tokens(section_blocks) > max_tokens

    for block in section_blocks:
        block_tokens = estimate_tokens(block_evidence_text(block))
        if block_tokens > max_tokens:
            if current:
                chunks.append(
                    make_chunk(
                        source_id,
                        next_index,
                        "long_section_part" if split_needed else chunk_type,
                        current,
                        context_block_ids,
                        target_tokens,
                        max_tokens,
                        diagnostics=diagnostics,
                    )
                )
                next_index += 1
                current = []
                current_tokens = 0
            chunks.append(
                make_chunk(
                    source_id,
                    next_index,
                    "large_block_split",
                    [block],
                    context_block_ids,
                    target_tokens,
                    max_tokens,
                    warnings=["large_block_split"],
                    diagnostics=diagnostics,
                )
            )
            next_index += 1
            continue
        if current and current_tokens + block_tokens > target_tokens:
            chunks.append(
                make_chunk(
                    source_id,
                    next_index,
                    "long_section_part" if split_needed else chunk_type,
                    current,
                    context_block_ids,
                    target_tokens,
                    max_tokens,
                    diagnostics=diagnostics,
                )
            )
            next_index += 1
            current = []
            current_tokens = 0
        current.append(block)
        current_tokens += block_tokens

    if current:
        chunks.append(
            make_chunk(
                source_id,
                next_index,
                "long_section_part" if split_needed else chunk_type,
                current,
                context_block_ids,
                target_tokens,
                max_tokens,
                diagnostics=diagnostics,
            )
        )
    return chunks


def make_chunk(
    source_id: str,
    chunk_index: int,
    chunk_type: str,
    blocks: list[SourceBlock],
    context_block_ids: list[str],
    target_tokens: int,
    max_tokens: int,
    warnings: list[str] | None = None,
    diagnostics: dict[str, int] | None = None,
) -> SourceChunk:
    page_start = min(block.page_start for block in blocks)
    page_end = max(block.page_end for block in blocks)
    section_path = blocks[0].section_path if blocks else []
    return SourceChunk(
        source_id=source_id,
        chunk_id=f"{source_id}_c{chunk_index:04d}",
        chunk_type=chunk_type,
        block_ids=[block.block_id for block in blocks],
        context_block_ids=context_block_ids,
        section_path=list(section_path),
        page_start=page_start,
        page_end=page_end,
        token_estimate=estimate_tokens(" ".join(block_evidence_text(block) for block in blocks)),
        warnings=warnings or [],
        diagnostics=diagnostics or chunk_diagnostics(blocks),
    )


def section_chunk_type(section_key: tuple[str, ...], blocks: list[SourceBlock]) -> str:
    section_name = " ".join(section_key).lower()
    if "reference" in section_name or all(block.block_type == "reference" for block in blocks):
        return "reference_text"
    if any(term in section_name for term in ("conclusion", "limitations", "discussion")):
        return "conclusion_or_limitations"
    if "appendix" in section_name:
        return "appendix_text"
    return "section_claim_extraction"


def is_result_focus_block(section_key: tuple[str, ...], block: SourceBlock) -> bool:
    if getattr(block, "content_role", "content") == "ignored":
        return False
    role = str(getattr(block, "content_role", "") or "").casefold()
    block_type = str(getattr(block, "block_type", "") or "").casefold()
    if role not in {"table_like", "caption"} and not any(term in block_type for term in ("table", "caption")):
        return False
    classification = classify_result_focus_block(section_key, block)
    return classification not in {"paper_metadata_or_reference_table", "dataset_inventory_table"}


def classify_result_focus_block(section_key: tuple[str, ...], block: SourceBlock) -> str:
    section = " ".join(section_key).casefold()
    text = " ".join(
        str(value or "")
        for value in (
            getattr(block, "block_type", ""),
            getattr(block, "text_clean", ""),
            getattr(block, "table_markdown", ""),
            getattr(block, "markdown", ""),
        )
    ).casefold()
    if "reference" in section or "bibliography" in section:
        return "paper_metadata_or_reference_table"
    if any(term in text for term in ("author", "affiliation", "license", "copyright")):
        return "paper_metadata_or_reference_table"
    if any(term in text for term in ("dataset statistics", "dataset inventory", "data split", "statistics of")):
        return "dataset_inventory_table"
    if any(term in text for term in ("ablation", "diagnostic", "sensitivity", "variant")):
        return "ablation_or_diagnostic_table"
    if (
        any(term in section for term in ("result", "experiment", "evaluation", "benchmark", "performance", "comparison"))
        or any(term in text for term in ("result", "accuracy", "success", "score", "f1", "auc", "bleu", "pass rate", "win rate"))
    ):
        return "result_table"
    return "ambiguous_table"


def total_tokens(blocks: list[SourceBlock]) -> int:
    return estimate_tokens(" ".join(block_evidence_text(block) for block in blocks))


def write_chunks_jsonl(path: Path, chunks: list[SourceChunk]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n" for chunk in chunks)
    path.write_text(content, encoding="utf-8")


def load_chunks_jsonl(path: Path) -> list[SourceChunk]:
    chunks: list[SourceChunk] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            data = json.loads(line)
            data.setdefault(
                "diagnostics",
                {
                    "total_block_count": 0,
                    "content_block_count": 0,
                    "ignored_block_count": 0,
                    "structured_block_count": 0,
                    "table_like_block_count": 0,
                    "equation_like_block_count": 0,
                    "image_or_caption_block_count": 0,
                },
            )
            chunks.append(SourceChunk(**data))
    return chunks


def chunk_diagnostics(blocks: list[SourceBlock]) -> dict[str, int]:
    ignored = sum(1 for block in blocks if getattr(block, "content_role", "content") == "ignored")
    table_like = sum(1 for block in blocks if getattr(block, "content_role", "") == "table_like")
    equation_like = sum(1 for block in blocks if getattr(block, "content_role", "") == "equation_like")
    image_or_caption = sum(1 for block in blocks if getattr(block, "content_role", "") in {"image", "caption"})
    return {
        "total_block_count": len(blocks),
        "content_block_count": len(blocks) - ignored,
        "ignored_block_count": ignored,
        "structured_block_count": table_like + equation_like + image_or_caption,
        "table_like_block_count": table_like,
        "equation_like_block_count": equation_like,
        "image_or_caption_block_count": image_or_caption,
    }
