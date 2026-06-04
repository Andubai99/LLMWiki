from __future__ import annotations

from dataclasses import dataclass, field
import ast
import re
from pathlib import Path
from typing import Any

from ..ask.answer import AskResult
from ..ingestion.ingest import yaml_quote
from ..workspace import utc_now
from .planner import SynthesisEvidenceItem, SynthesisPlan


MANAGED_SECTIONS = {
    "Scope",
    "Current Answer",
    "Evidence Map",
    "Analysis",
    "Conflicts And Limits",
    "Open Questions",
    "Related Pages",
    "Revision History",
}
OLD_SECTION_MAP = {
    "Question/Topic": "Scope",
    "Short Answer": "Current Answer",
    "Evidence": "Evidence Map",
    "Uncertainties": "Conflicts And Limits",
}


@dataclass(frozen=True)
class SynthesisPageModel:
    page_id: str
    title: str
    target_path: str
    aliases: list[str]
    claim_ids: list[str]
    evidence: list[SynthesisEvidenceItem]
    scope: str
    current_answer: str
    analysis: str
    conflicts_and_limits: list[str]
    open_questions: list[str]
    related_pages: list[str]
    revision_history: list[str]
    topic_key: str
    question_count: int = 1
    revision_count: int = 1
    custom_sections: list[tuple[str, str]] = field(default_factory=list)
    updated_at: str = ""

    @classmethod
    def from_plan(cls, plan: SynthesisPlan, ask_result: AskResult, run_id: str) -> SynthesisPageModel:
        now = utc_now()
        conflicts_and_limits = [
            *string_items(plan.sections.get("conflicts_and_limits")),
            *ask_result.uncertainties,
            *ask_result.conflicts,
        ]
        return cls(
            page_id=plan.target_page_id,
            title=plan.title,
            target_path=plan.target_path,
            aliases=plan.aliases,
            claim_ids=dedupe(plan.evidence_claim_ids),
            evidence=plan.evidence,
            scope=str(plan.sections.get("scope") or ask_result.question),
            current_answer=str(plan.sections.get("current_answer") or ask_result.answer),
            analysis=str(plan.sections.get("analysis") or ask_result.analysis or ask_result.answer),
            conflicts_and_limits=dedupe(conflicts_and_limits),
            open_questions=string_items(plan.sections.get("open_questions")),
            related_pages=dedupe(plan.related_pages),
            revision_history=[revision_line(now, run_id, plan.action, ask_result.question, plan.evidence_claim_ids)],
            topic_key=plan.topic_key,
            question_count=1,
            revision_count=1,
            updated_at=now,
        )


def parse_synthesis_page(path: Path) -> SynthesisPageModel:
    content = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(content)
    sections = normalize_sections(parse_sections(body))
    title = frontmatter.get("title") or first_heading(body) or path.stem
    claim_ids = parse_list_value(frontmatter.get("claim_ids", "[]"))
    aliases = parse_list_value(frontmatter.get("aliases", "[]"))
    page_id = frontmatter.get("synthesis_id") or f"synthesis-{path.stem}"
    target_path = posix_wiki_path(path)
    evidence = parse_evidence_items(sections.get("Evidence Map", ""), claim_ids)
    return SynthesisPageModel(
        page_id=page_id,
        title=title,
        target_path=target_path,
        aliases=aliases,
        claim_ids=claim_ids,
        evidence=evidence,
        scope=clean_section(sections.get("Scope", "")),
        current_answer=clean_section(sections.get("Current Answer", "")),
        analysis=clean_section(sections.get("Analysis", "")),
        conflicts_and_limits=bullet_items(sections.get("Conflicts And Limits", "")),
        open_questions=bullet_items(sections.get("Open Questions", "")),
        related_pages=parse_wiki_links(sections.get("Related Pages", "")),
        revision_history=bullet_items(sections.get("Revision History", "")),
        topic_key=frontmatter.get("topic_key") or path.stem,
        question_count=int_value(frontmatter.get("question_count"), default=1),
        revision_count=int_value(frontmatter.get("revision_count"), default=1),
        custom_sections=[
            (heading, text)
            for heading, text in sections.items()
            if heading not in MANAGED_SECTIONS
        ],
        updated_at=frontmatter.get("updated_at", ""),
    )


def render_synthesis_page_v2_8(model: SynthesisPageModel) -> str:
    source_count = len({item.source_id for item in model.evidence if item.source_id})
    now = model.updated_at or utc_now()
    lines = [
        "---",
        "page_type: synthesis",
        f"title: {yaml_quote(model.title)}",
        f"aliases: {model.aliases!r}",
        f"source_count: {source_count}",
        f"claim_ids: {model.claim_ids!r}",
        f"synthesis_id: {yaml_quote(model.page_id)}",
        f"topic_key: {yaml_quote(model.topic_key)}",
        f"question_count: {model.question_count}",
        f"revision_count: {model.revision_count}",
        f"updated_at: {yaml_quote(now)}",
        "---",
        "",
        f"# {model.title}",
        "",
        "## Scope",
        "",
        model.scope or "No scope recorded.",
        "",
        "## Current Answer",
        "",
        model.current_answer or "No answer recorded.",
        "",
        "## Evidence Map",
        "",
        "| Role | Claim | Source | Locator | Page |",
        "| --- | --- | --- | --- | --- |",
    ]
    if model.evidence:
        for item in model.evidence:
            lines.append(
                f"| {item.role} | `{item.claim_id}` | `{item.source_id}` | "
                f"`{item.citation_locator}` | [[{item.page_path}]] |"
            )
    else:
        lines.append("| background | none | none | none | none |")
    lines.extend(
        [
            "",
            "## Analysis",
            "",
            model.analysis or "No analysis recorded.",
            "",
            "## Conflicts And Limits",
            "",
        ]
    )
    lines.extend(format_bullets(model.conflicts_and_limits, fallback="None identified."))
    lines.extend(["", "## Open Questions", ""])
    lines.extend(format_bullets(model.open_questions, fallback="None identified."))
    lines.extend(["", "## Related Pages", ""])
    if model.related_pages:
        lines.extend(f"- [[{page}]]" for page in model.related_pages)
    else:
        lines.append("- None.")
    lines.extend(["", "## Revision History", ""])
    lines.extend(format_bullets(model.revision_history, fallback="No revisions recorded."))
    for heading, text in model.custom_sections:
        lines.extend(["", f"## {heading}", "", text.strip()])
    return "\n".join(lines).rstrip() + "\n"


def merge_synthesis_page(
    existing: SynthesisPageModel,
    plan: SynthesisPlan,
    ask_result: AskResult,
    run_id: str,
) -> SynthesisPageModel:
    now = utc_now()
    valid_claim_ids = {citation.claim_id for citation in ask_result.citations}
    valid_claim_ids.update(str(context.get("claim_id")) for context in ask_result.contexts if context.get("claim_id"))
    merged_claims = [claim_id for claim_id in existing.claim_ids if claim_id in valid_claim_ids]
    missing_claims = [claim_id for claim_id in existing.claim_ids if claim_id not in valid_claim_ids]
    for claim_id in plan.evidence_claim_ids:
        if claim_id not in merged_claims:
            merged_claims.append(claim_id)
    limits = [
        *existing.conflicts_and_limits,
        *string_items(plan.sections.get("conflicts_and_limits")),
    ]
    limits.extend(f"Previously referenced claim `{claim_id}` was not present in current catalog evidence." for claim_id in missing_claims)
    revisions = [
        *existing.revision_history,
        revision_line(now, run_id, plan.action, ask_result.question, plan.evidence_claim_ids),
    ]
    return SynthesisPageModel(
        page_id=existing.page_id or plan.target_page_id,
        title=plan.title or existing.title,
        target_path=existing.target_path or plan.target_path,
        aliases=dedupe([*existing.aliases, *plan.aliases]),
        claim_ids=merged_claims,
        evidence=plan.evidence,
        scope=str(plan.sections.get("scope") or existing.scope or ask_result.question),
        current_answer=str(plan.sections.get("current_answer") or ask_result.answer or existing.current_answer),
        analysis=str(plan.sections.get("analysis") or ask_result.analysis or existing.analysis),
        conflicts_and_limits=dedupe(limits),
        open_questions=dedupe([*existing.open_questions, *string_items(plan.sections.get("open_questions"))]),
        related_pages=dedupe([*existing.related_pages, *plan.related_pages]),
        revision_history=revisions,
        topic_key=existing.topic_key or plan.topic_key,
        question_count=existing.question_count + 1,
        revision_count=existing.revision_count + 1,
        custom_sections=existing.custom_sections,
        updated_at=now,
    )


def split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, content
    frontmatter: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = strip_quotes(value.strip())
    return frontmatter, "\n".join(lines[end + 1 :])


def parse_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def normalize_sections(sections: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for heading, text in sections.items():
        normalized[OLD_SECTION_MAP.get(heading, heading)] = text
    return normalized


def parse_evidence_items(text: str, claim_ids: list[str]) -> list[SynthesisEvidenceItem]:
    items: list[SynthesisEvidenceItem] = []
    for line in text.splitlines():
        if not line.strip().startswith("|") or "`" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] == "---" or cells[0].casefold() == "role":
            continue
        claim_id = unbacktick(cells[1])
        if not claim_id:
            continue
        items.append(
            SynthesisEvidenceItem(
                role=cells[0],
                claim_id=claim_id,
                source_id=unbacktick(cells[2]),
                citation_locator=unbacktick(cells[3]),
                page_path=first_wiki_link(cells[4]),
            )
        )
    if items:
        return items
    return [
        SynthesisEvidenceItem(
            role="supports",
            claim_id=claim_id,
            source_id="",
            citation_locator="",
            page_path="",
        )
        for claim_id in claim_ids
    ]


def parse_list_value(value: str) -> list[str]:
    try:
        parsed = ast.literal_eval(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def clean_section(text: str) -> str:
    return text.strip()


def bullet_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    if items:
        return items
    return [text.strip()] if text.strip() else []


def string_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def parse_wiki_links(text: str) -> list[str]:
    return dedupe(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", text))


def first_wiki_link(text: str) -> str:
    links = parse_wiki_links(text)
    return links[0] if links else text.strip()


def unbacktick(value: str) -> str:
    return value.strip().strip("`")


def first_heading(body: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
    return match.group(1).strip() if match else ""


def posix_wiki_path(path: Path) -> str:
    parts = path.as_posix().split("/")
    if "wiki" in parts:
        return "/".join(parts[parts.index("wiki") :])
    return path.name


def int_value(value: str | None, default: int) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def format_bullets(items: list[str], fallback: str) -> list[str]:
    return [f"- {item}" for item in items] if items else [f"- {fallback}"]


def revision_line(now: str, run_id: str, action: str, question: str, claim_ids: list[str]) -> str:
    claims = ", ".join(f"`{claim_id}`" for claim_id in claim_ids) or "none"
    return f"{now} `{run_id}` {action}: {question} (evidence: {claims})"


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
