from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .answer import AskResult
from .apply import apply_run
from .ingest import slugify, yaml_quote
from .pipeline import sanitize_error
from .workspace import utc_now


@dataclass(frozen=True)
class SynthesisWritebackResult:
    run_id: str
    pages: list[str]
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "pages": self.pages,
        }


class SynthesisWritebackError(Exception):
    def __init__(self, *, stage: str, reason: str, run_id: str | None = None) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
        self.run_id = run_id


def create_synthesis_run(root: Path, ask_result: AskResult) -> SynthesisWritebackResult:
    root = root.resolve()
    if ask_result.status != "answered":
        raise SynthesisWritebackError(stage="prepare", reason=f"Cannot write back answer status: {ask_result.status}")
    if not ask_result.citations:
        raise SynthesisWritebackError(stage="prepare", reason="Cannot write back without cited evidence")

    answer_id = answer_hash(ask_result)
    timestamp = compact_timestamp()
    run_id = f"run_answer_{timestamp}_{answer_id}"
    source_id = f"synthesis:{answer_id}"
    title = ask_result.suggested_title.strip() or ask_result.question.strip() or f"Synthesis {answer_id}"
    slug = slugify(title)
    if slug == "untitled":
        slug = f"answer-{answer_id}"
    target_path = f"wiki/syntheses/{slug}.md"
    page_id = f"synthesis-{slug}"
    run_dir = root / "staging" / run_id
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(parents=True, exist_ok=False)

    patch = build_synthesis_patch(
        ask_result=ask_result,
        page_id=page_id,
        target_path=target_path,
        title=title,
        source_id=source_id,
    )
    write_staging_files(run_dir, run_id, ask_result, source_id, patch)

    try:
        apply_run(root, run_id)
    except Exception as exc:
        mark_synthesis_run_failed(root, run_id, "apply", sanitize_error(exc))
        raise SynthesisWritebackError(stage="apply", reason=sanitize_error(exc), run_id=run_id) from exc

    return SynthesisWritebackResult(run_id=run_id, pages=[target_path], status="applied")


def build_synthesis_patch(
    *,
    ask_result: AskResult,
    page_id: str,
    target_path: str,
    title: str,
    source_id: str,
) -> dict[str, Any]:
    claim_ids = [citation.claim_id for citation in ask_result.citations]
    links = []
    seen_pages: set[str] = set()
    for citation in ask_result.citations:
        if citation.page_path in seen_pages:
            continue
        seen_pages.add(citation.page_path)
        links.append(
            {
                "from_page": page_id,
                "to_page": citation.page_path,
                "link_type": "supports",
            }
        )
    return {
        "patch_id": f"patch_{page_id}",
        "action": "upsert_page",
        "page_id": page_id,
        "page_type": "synthesis",
        "title": title,
        "target_path": target_path,
        "aliases": [],
        "source_id": source_id,
        "claim_ids": claim_ids,
        "links": links,
        "relationships": [],
        "content": render_synthesis_page(ask_result, title, claim_ids),
    }


def render_synthesis_page(ask_result: AskResult, title: str, claim_ids: list[str]) -> str:
    source_count = len({citation.source_id for citation in ask_result.citations})
    now = utc_now()
    lines = [
        "---",
        "page_type: synthesis",
        f"title: {yaml_quote(title)}",
        "aliases: []",
        f"source_count: {source_count}",
        f"claim_ids: {claim_ids!r}",
        f"updated_at: {yaml_quote(now)}",
        "---",
        "",
        f"# {title}",
        "",
        "## Question/Topic",
        "",
        ask_result.question,
        "",
        "## Short Answer",
        "",
        ask_result.answer or "No answer produced.",
        "",
        "## Evidence",
        "",
    ]
    for citation in ask_result.citations:
        lines.append(
            f"- `{citation.claim_id}` from `{citation.source_id}` at `{citation.citation_locator}` "
            f"([[{citation.page_path}]])"
        )
    lines.extend(
        [
            "",
            "## Analysis",
            "",
            ask_result.analysis or ask_result.answer or "No analysis produced.",
            "",
            "## Uncertainties",
            "",
        ]
    )
    uncertainty_lines = [*ask_result.uncertainties, *ask_result.conflicts]
    if uncertainty_lines:
        lines.extend(f"- {item}" for item in uncertainty_lines)
    else:
        lines.append("- None identified.")
    lines.extend(["", "## Related Pages", ""])
    for citation in ask_result.citations:
        lines.append(f"- [[{citation.page_path}]]")
    return "\n".join(lines) + "\n"


def write_staging_files(
    run_dir: Path,
    run_id: str,
    ask_result: AskResult,
    source_id: str,
    patch: dict[str, Any],
) -> None:
    now = utc_now()
    manifest = {
        "run_id": run_id,
        "run_type": "synthesis_writeback",
        "trigger": "ask",
        "status": "staged",
        "created_at": now,
        "source_id": source_id,
        "question": ask_result.question,
        "answer_status": ask_result.status,
        "evidence_claim_ids": [citation.claim_id for citation in ask_result.citations],
        "proposal_engine": "llm",
    }
    (run_dir / "run.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (run_dir / "claims.jsonl").write_text("", encoding="utf-8", newline="\n")
    (run_dir / "triage.md").write_text(
        "\n".join(
            [
                "# Synthesis Writeback",
                "",
                f"- question: {ask_result.question}",
                f"- answer_status: {ask_result.status}",
                f"- evidence_claims: {', '.join(c.claim_id for c in ask_result.citations)}",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    patch_path = run_dir / "patches" / f"001-synthesis-{patch['page_id']}.json"
    patch_path.write_text(
        json.dumps(patch, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def mark_synthesis_run_failed(root: Path, run_id: str, stage: str, reason: str) -> None:
    manifest_path = root / "staging" / run_id / "run.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "failed"
    manifest["failed_at"] = utc_now()
    manifest["failed_stage"] = stage
    manifest["failure_reason"] = reason
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def answer_hash(ask_result: AskResult) -> str:
    digest = hashlib.sha256()
    digest.update(ask_result.question.encode("utf-8"))
    digest.update(ask_result.answer.encode("utf-8"))
    for citation in ask_result.citations:
        digest.update(citation.claim_id.encode("utf-8"))
    return digest.hexdigest()[:8]


def compact_timestamp() -> str:
    return utc_now().replace("-", "").replace(":", "").replace("+00:00", "Z")
