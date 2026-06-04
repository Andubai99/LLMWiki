from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from ..ask.answer import AskResult
from ..ingestion.apply import apply_run
from ..ingestion.pipeline import sanitize_error
from .pages import (
    SynthesisPageModel,
    merge_synthesis_page,
    parse_synthesis_page,
    render_synthesis_page_v2_8,
)
from .planner import (
    SynthesisPlan,
    SynthesisPlanningOptions,
    format_synthesis_preview,
    plan_synthesis_writeback,
    validate_synthesis_plan,
)
from ..workspace import utc_now


@dataclass(frozen=True)
class SynthesisWritebackResult:
    run_id: str
    pages: list[str]
    status: str
    action: str
    synthesis_plan: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "pages": self.pages,
            "action": self.action,
            "synthesis_plan": self.synthesis_plan,
        }


class SynthesisWritebackError(Exception):
    def __init__(self, *, stage: str, reason: str, run_id: str | None = None) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
        self.run_id = run_id


def create_synthesis_run(
    root: Path,
    ask_result: AskResult,
    plan: SynthesisPlan | None = None,
    *,
    planning_options: SynthesisPlanningOptions | None = None,
) -> SynthesisWritebackResult:
    root = root.resolve()
    if ask_result.status != "answered":
        raise SynthesisWritebackError(stage="prepare", reason=f"Cannot write back answer status: {ask_result.status}")
    if not ask_result.citations:
        raise SynthesisWritebackError(stage="prepare", reason="Cannot write back without cited evidence")
    if plan is None:
        plan = plan_synthesis_writeback(root, ask_result, planning_options or SynthesisPlanningOptions())
    else:
        validate_synthesis_plan(root, ask_result, plan, planning_options or SynthesisPlanningOptions())
    if plan.action == "needs_review":
        raise SynthesisWritebackError(
            stage="prepare",
            reason="Synthesis plan needs review before writeback.",
        )

    answer_id = answer_hash(ask_result)
    timestamp = compact_timestamp()
    run_id = f"run_synthesis_{timestamp}_{answer_id}"
    source_id = f"synthesis:{answer_id}"
    run_dir = root / "staging" / run_id
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(parents=True, exist_ok=False)

    patch = build_synthesis_patch_v2_8(
        root=root,
        ask_result=ask_result,
        plan=plan,
        run_id=run_id,
        source_id=source_id,
    )
    write_staging_files(run_dir, run_id, ask_result, source_id, patch, plan)

    try:
        apply_run(root, run_id)
    except Exception as exc:
        mark_synthesis_run_failed(root, run_id, "apply", sanitize_error(exc))
        raise SynthesisWritebackError(stage="apply", reason=sanitize_error(exc), run_id=run_id) from exc

    return SynthesisWritebackResult(
        run_id=run_id,
        pages=[plan.target_path],
        status="applied",
        action=plan.action,
        synthesis_plan=plan.to_dict(),
    )


def build_synthesis_patch_v2_8(
    *,
    root: Path,
    ask_result: AskResult,
    plan: SynthesisPlan,
    run_id: str,
    source_id: str,
) -> dict[str, Any]:
    if plan.action == "update":
        existing = parse_synthesis_page(root / plan.target_path)
        model = merge_synthesis_page(existing, plan, ask_result, run_id=run_id)
    else:
        model = SynthesisPageModel.from_plan(plan, ask_result, run_id=run_id)
    claim_ids = model.claim_ids
    links = []
    seen_pages: set[str] = set()
    for page_path in model.related_pages:
        if page_path in seen_pages:
            continue
        seen_pages.add(page_path)
        links.append(
            {
                "from_page": model.page_id,
                "to_page": page_path,
                "link_type": "supports",
            }
        )
    relationships = [relationship.to_dict() for relationship in plan.relationships]
    if not relationships:
        relationships = [
            {
                "subject_id": model.page_id,
                "object_id": item.claim_id,
                "relationship_type": "supports",
                "evidence_claim_id": item.claim_id,
                "source_id": item.source_id,
            }
            for item in plan.evidence
        ]
    return {
        "patch_id": f"patch_{model.page_id}",
        "action": "upsert_page",
        "page_id": model.page_id,
        "page_type": "synthesis",
        "title": model.title,
        "target_path": plan.target_path,
        "aliases": model.aliases,
        "source_id": source_id,
        "claim_ids": claim_ids,
        "links": links,
        "relationships": relationships,
        "content": render_synthesis_page_v2_8(model),
    }


def write_staging_files(
    run_dir: Path,
    run_id: str,
    ask_result: AskResult,
    source_id: str,
    patch: dict[str, Any],
    plan: SynthesisPlan,
) -> None:
    now = utc_now()
    manifest = {
        "run_id": run_id,
        "run_type": "synthesis_writeback",
        "schema_version": "synthesis_writeback.v2.8",
        "trigger": "ask",
        "status": "staged",
        "created_at": now,
        "source_id": source_id,
        "synthesis_action": plan.action,
        "target_page_id": plan.target_page_id,
        "target_path": plan.target_path,
        "question": ask_result.question,
        "answer_status": ask_result.status,
        "evidence_claim_ids": plan.evidence_claim_ids,
        "proposal_engine": "llm",
    }
    (run_dir / "run.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (run_dir / "claims.jsonl").write_text("", encoding="utf-8", newline="\n")
    (run_dir / "synthesis-plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (run_dir / "triage.md").write_text(
        "\n".join(
            [
                "# Synthesis Writeback",
                "",
                format_synthesis_preview(plan),
                "",
                f"- question: {ask_result.question}",
                f"- answer_status: {ask_result.status}",
                f"- evidence_claims: {', '.join(plan.evidence_claim_ids)}",
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
