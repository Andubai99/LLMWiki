from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from llmwiki.cli import main
from llmwiki.llm_ingest import normalize_payload
from llmwiki.sources import import_source
from tests.helpers import make_workspace


def _source_id(root: Path) -> str:
    import sqlite3

    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        return conn.execute("select source_id from sources order by imported_at desc").fetchone()[0]


def _wiki_snapshot(root: Path) -> dict[str, str]:
    wiki = root / "wiki"
    return {
        path.relative_to(wiki).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(wiki.rglob("*.md"))
    }


def _write_llm_sample(root: Path) -> Path:
    source = root / "stage3-llm-ingest.md"
    source.write_text(
        "# Stage 3 LLM Ingest Sample\n\n"
        "RAG systems need citation anchors so later synthesis remains auditable.\n"
        "LLM-maintained wiki pages should be updated through staging review before apply.\n",
        encoding="utf-8",
    )
    return source


def _repo_api_key() -> str:
    key_file = Path(__file__).resolve().parents[1] / "config" / "api-keys.toml"
    if not key_file.exists():
        return ""
    data = tomllib.loads(key_file.read_text(encoding="utf-8"))
    llm = data.get("llm", {}) if isinstance(data, dict) else {}
    return str(llm.get("api_key") or "").strip() if isinstance(llm, dict) else ""


def _write_api_key(root: Path, api_key: str) -> None:
    escaped = json.dumps(api_key)
    (root / "config" / "api-keys.toml").write_text(
        f"[llm]\napi_key = {escaped}\n",
        encoding="utf-8",
        newline="\n",
    )


def test_normalize_payload_promotes_valid_locator_claims_to_cited():
    proposal = normalize_payload(
        {
            "claims": [
                {
                    "claim_text": "First claim has a real locator.",
                    "citation_locator": "line:1",
                    "confidence_status": "uncited",
                },
                {
                    "claim_text": "Second claim has a real locator.",
                    "citation_locator": "line:2",
                    "confidence_status": "weak",
                },
            ]
        },
        "src_test",
        "[line:1] First claim has a real locator.\n[line:2] Second claim has a real locator.\n",
    )

    assert [claim["confidence_status"] for claim in proposal.claims] == ["cited", "cited"]
    assert proposal.claims[0]["citation_locator"] == "line:1"


def test_normalize_payload_does_not_promote_missing_or_invalid_locators():
    proposal = normalize_payload(
        {
            "claims": [
                {
                    "claim_text": "Missing locator is not cited.",
                    "citation_locator": "",
                    "confidence_status": "cited",
                },
                {
                    "claim_text": "Invalid locator is not cited.",
                    "citation_locator": "line:999",
                    "confidence_status": "uncited",
                },
            ]
        },
        "src_test",
        "[line:1] Only line one exists.\n",
    )

    assert proposal.claims[0]["citation_locator"] == ""
    assert proposal.claims[0]["confidence_status"] == "weak"
    assert proposal.claims[1]["citation_locator"] == ""
    assert proposal.claims[1]["confidence_status"] == "uncited"


def test_ingest_reports_missing_llm_api_key_without_modifying_wiki(monkeypatch, capsys):
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    source = _write_llm_sample(root)
    source_id = import_source(root, str(source)).source_id
    before = _wiki_snapshot(root)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-should-not-print-this")
    monkeypatch.setenv("OTHER_SECRET", "sk-other-do-not-print-this")
    capsys.readouterr()

    assert main(["ingest", source_id, "--root", str(root)]) == 1
    out = capsys.readouterr().out

    assert "Ingest failed" in out
    assert "config/api-keys.toml" in out
    assert "DEEPSEEK_API_KEY" not in out
    assert "sk-env-should-not-print-this" not in out
    assert "sk-other-do-not-print-this" not in out
    assert _wiki_snapshot(root) == before
    assert not any((root / "staging").glob("run_*"))


def test_real_llm_ingest_writes_staging_only_and_applies_safely(capsys):
    api_key = _repo_api_key()
    if not api_key:
        pytest.fail("config/api-keys.toml with [llm].api_key is required for the real LLM ingest integration test")

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    _write_api_key(root, api_key)
    source = _write_llm_sample(root)
    source_id = import_source(root, str(source)).source_id
    before = _wiki_snapshot(root)
    capsys.readouterr()

    assert main(["ingest", source_id, "--root", str(root)]) == 0
    out = capsys.readouterr().out
    run_id = out.split("run_id=", 1)[1].splitlines()[0].strip()

    assert "proposal_engine=llm" in out
    assert _wiki_snapshot(root) == before
    run_dir = root / "staging" / run_id
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["proposal_engine"] == "llm"
    assert manifest["llm_provider"] == "openai"
    assert manifest["llm_model"] == "deepseek-v4-flash"
    assert (run_dir / "llm-proposal.json").exists()

    claims = [
        json.loads(line)
        for line in (run_dir / "claims.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert claims
    assert all(claim["source_id"] == source_id for claim in claims)
    assert any("line:" in claim["citation_locator"] for claim in claims)
    assert all(claim["confidence_status"] == "cited" for claim in claims)

    triage = (run_dir / "triage.md").read_text(encoding="utf-8")
    assert "## LLM Proposal" in triage
    assert "proposal_engine: `llm`" in triage
    assert "DeepSeek" in triage or "openai" in triage
    assert api_key not in triage

    patch_paths = sorted((run_dir / "patches").glob("*.json"))
    assert patch_paths
    patches = [json.loads(path.read_text(encoding="utf-8")) for path in patch_paths]
    assert any(patch["target_path"].startswith("wiki/sources/") for patch in patches)
    assert any(patch["target_path"].startswith("wiki/concepts/") for patch in patches)
    assert api_key not in "\n".join(path.read_text(encoding="utf-8") for path in patch_paths)

    assert main(["apply", run_id, "--root", str(root)]) == 0
    apply_out = capsys.readouterr().out
    assert "Applied ingest run" in apply_out
    assert (root / "wiki" / "sources" / f"{source_id}.md").exists()
