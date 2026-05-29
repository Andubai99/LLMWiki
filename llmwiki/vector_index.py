from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .db import catalog_path, connect


VECTOR_INDEX_SCHEMA_VERSION = "vector_index.v2.6"


@dataclass(frozen=True)
class EmbeddingChunk:
    chunk_id: str
    chunk_type: str
    text: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbeddingChunk":
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return cls(
            chunk_id=str(data["chunk_id"]),
            chunk_type=str(data["chunk_type"]),
            text=str(data["text"]),
            metadata=metadata,
        )


@dataclass(frozen=True)
class VectorIndexManifest:
    schema_version: str
    provider: str
    model: str
    dimension: int
    chunk_count: int
    catalog_fingerprint: str
    built_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VectorIndexManifest":
        return cls(
            schema_version=str(data["schema_version"]),
            provider=str(data["provider"]),
            model=str(data["model"]),
            dimension=int(data["dimension"]),
            chunk_count=int(data["chunk_count"]),
            catalog_fingerprint=str(data["catalog_fingerprint"]),
            built_at=str(data["built_at"]),
        )


@dataclass(frozen=True)
class VectorIndex:
    manifest: VectorIndexManifest
    chunks: list[EmbeddingChunk]
    vectors: list[list[float]]


@dataclass(frozen=True)
class VectorIndexStatus:
    index_present: bool
    stale: bool
    chunk_count: int
    provider: str | None
    model: str | None
    dimension: int | None
    catalog_fingerprint: str | None
    current_catalog_fingerprint: str | None
    failure_stage: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def vector_index_dir(root: Path) -> Path:
    return root / "state" / "embeddings"


def manifest_path(root: Path) -> Path:
    return vector_index_dir(root) / "manifest.json"


def chunks_path(root: Path) -> Path:
    return vector_index_dir(root) / "chunks.jsonl"


def vectors_path(root: Path) -> Path:
    return vector_index_dir(root) / "vectors.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_embedding_chunks(root: Path) -> list[EmbeddingChunk]:
    db_path = catalog_path(root)
    chunks: list[EmbeddingChunk] = []
    with connect(db_path) as conn:
        claim_rows = conn.execute(
            """
            select c.claim_id, c.source_id, c.claim_text, c.citation_locator,
                   c.confidence_status, s.title as source_title
            from claims c
            left join sources s on s.source_id = c.source_id
            order by c.claim_id
            """
        ).fetchall()
        for row in claim_rows:
            chunks.append(
                EmbeddingChunk(
                    chunk_id=f"claim:{row['claim_id']}",
                    chunk_type="claim",
                    text=row["claim_text"],
                    metadata={
                        "claim_id": row["claim_id"],
                        "source_id": row["source_id"],
                        "citation_locator": row["citation_locator"] or "",
                        "confidence_status": row["confidence_status"],
                        "source_title": row["source_title"] or "",
                    },
                )
            )

        page_rows = conn.execute(
            """
            select page_id, path, page_type, title, aliases
            from pages
            order by page_id
            """
        ).fetchall()
        for row in page_rows:
            chunks.append(
                EmbeddingChunk(
                    chunk_id=f"page_title:{row['page_id']}",
                    chunk_type="page_title",
                    text=_join_text(row["title"], row["aliases"]),
                    metadata={
                        "page_id": row["page_id"],
                        "page_path": row["path"],
                        "page_type": row["page_type"],
                        "title": row["title"],
                    },
                )
            )

        source_rows = conn.execute(
            """
            select source_id, title, source_type, raw_path, normalized_path
            from sources
            order by source_id
            """
        ).fetchall()
        for row in source_rows:
            chunks.append(
                EmbeddingChunk(
                    chunk_id=f"source_title:{row['source_id']}",
                    chunk_type="source_title",
                    text=row["title"],
                    metadata={
                        "source_id": row["source_id"],
                        "source_type": row["source_type"],
                        "raw_path": row["raw_path"],
                        "normalized_path": row["normalized_path"],
                    },
                )
            )
    return chunks


def catalog_fingerprint(root: Path) -> str:
    db_path = catalog_path(root)
    if not db_path.exists():
        return hashlib.sha256(b"missing-catalog").hexdigest()
    hasher = hashlib.sha256()
    with connect(db_path) as conn:
        for table in ("sources", "claims", "pages", "aliases"):
            hasher.update(table.encode("utf-8"))
            rows = conn.execute(f"select * from {table} order by 1, 2").fetchall()
            for row in rows:
                payload = json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
                hasher.update(payload.encode("utf-8"))
    return hasher.hexdigest()


def write_vector_index(
    root: Path,
    chunks: list[EmbeddingChunk],
    vectors: list[list[float]],
    manifest: VectorIndexManifest,
) -> None:
    if len(chunks) != len(vectors):
        raise ValueError(f"chunk/vector count mismatch: {len(chunks)} chunks, {len(vectors)} vectors")
    index_dir = vector_index_dir(root)
    index_dir.mkdir(parents=True, exist_ok=True)

    manifest_path(root).write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    chunks_path(root).write_text(
        "".join(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n" for chunk in chunks),
        encoding="utf-8",
        newline="\n",
    )
    vectors_path(root).write_text(
        "".join(
            json.dumps({"chunk_id": chunk.chunk_id, "vector": vector}, ensure_ascii=False) + "\n"
            for chunk, vector in zip(chunks, vectors)
        ),
        encoding="utf-8",
        newline="\n",
    )


def load_vector_index(root: Path) -> VectorIndex:
    with manifest_path(root).open("r", encoding="utf-8") as handle:
        manifest = VectorIndexManifest.from_dict(json.load(handle))
    chunks = [
        EmbeddingChunk.from_dict(json.loads(line))
        for line in chunks_path(root).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    vector_rows = [
        json.loads(line)
        for line in vectors_path(root).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(chunks) != manifest.chunk_count or len(vector_rows) != manifest.chunk_count:
        raise ValueError("vector index chunk count mismatch")

    vectors: list[list[float]] = []
    for index, (chunk, row) in enumerate(zip(chunks, vector_rows), start=1):
        if row.get("chunk_id") != chunk.chunk_id:
            raise ValueError(f"vector index chunk id mismatch at row {index}")
        vector = row.get("vector")
        if not isinstance(vector, list):
            raise ValueError(f"vector index row {index} is missing a vector")
        if len(vector) != manifest.dimension:
            raise ValueError(
                f"vector index dimension mismatch at row {index}: "
                f"expected {manifest.dimension}, got {len(vector)}"
            )
        try:
            vectors.append([float(value) for value in vector])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"vector index row {index} contains non-numeric values") from exc
    return VectorIndex(manifest=manifest, chunks=chunks, vectors=vectors)


def vector_index_status(root: Path) -> VectorIndexStatus:
    current_fingerprint = catalog_fingerprint(root)
    if not manifest_path(root).exists() or not chunks_path(root).exists() or not vectors_path(root).exists():
        return VectorIndexStatus(
            index_present=False,
            stale=True,
            chunk_count=0,
            provider=None,
            model=None,
            dimension=None,
            catalog_fingerprint=None,
            current_catalog_fingerprint=current_fingerprint,
            failure_stage="missing_index",
        )
    try:
        index = load_vector_index(root)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return VectorIndexStatus(
            index_present=True,
            stale=True,
            chunk_count=0,
            provider=None,
            model=None,
            dimension=None,
            catalog_fingerprint=None,
            current_catalog_fingerprint=current_fingerprint,
            failure_stage="invalid_index",
            reason=str(exc),
        )
    manifest = index.manifest
    return VectorIndexStatus(
        index_present=True,
        stale=manifest.catalog_fingerprint != current_fingerprint,
        chunk_count=manifest.chunk_count,
        provider=manifest.provider,
        model=manifest.model,
        dimension=manifest.dimension,
        catalog_fingerprint=manifest.catalog_fingerprint,
        current_catalog_fingerprint=current_fingerprint,
    )


def new_manifest(
    *,
    provider: str,
    model: str,
    dimension: int,
    chunk_count: int,
    catalog_fingerprint_value: str,
) -> VectorIndexManifest:
    return VectorIndexManifest(
        schema_version=VECTOR_INDEX_SCHEMA_VERSION,
        provider=provider,
        model=model,
        dimension=dimension,
        chunk_count=chunk_count,
        catalog_fingerprint=catalog_fingerprint_value,
        built_at=utc_now(),
    )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(left * right for left, right in zip(a, b))
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _join_text(*parts: str | None) -> str:
    return " ".join(part for part in parts if part)
