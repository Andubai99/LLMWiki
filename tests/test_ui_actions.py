from __future__ import annotations

from pathlib import Path
import uuid

from llmwiki.cli import main


WORKSPACES = Path(".test-workspaces")


def make_workspace() -> Path:
    root = WORKSPACES / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_validate_add_source_rejects_empty_source() -> None:
    from llmwiki.ui.actions import UiActionError, validate_add_source_request

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    try:
        validate_add_source_request(root, {"source": "   "})
    except UiActionError as exc:
        assert exc.code == "invalid_source"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected UiActionError")


def test_validate_add_source_rejects_control_characters() -> None:
    from llmwiki.ui.actions import UiActionError, validate_add_source_request

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    try:
        validate_add_source_request(root, {"source": "docs/a.pdf\u0000"})
    except UiActionError as exc:
        assert exc.code == "invalid_source"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected UiActionError")


def test_validate_add_source_rejects_secret_config_path() -> None:
    from llmwiki.ui.actions import UiActionError, validate_add_source_request

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    try:
        validate_add_source_request(root, {"source": "config/api-keys.toml"})
    except UiActionError as exc:
        assert exc.code == "forbidden_source"
        assert "api-keys.toml" not in exc.to_dict()["message"]
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected UiActionError")


def test_validate_add_source_rejects_directory() -> None:
    from llmwiki.ui.actions import UiActionError, validate_add_source_request

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "docs").mkdir()

    try:
        validate_add_source_request(root, {"source": "docs"})
    except UiActionError as exc:
        assert exc.code == "directory_not_supported"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected UiActionError")


def test_validate_add_source_rejects_unsupported_parser() -> None:
    from llmwiki.ui.actions import UiActionError, validate_add_source_request

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "paper.pdf").write_text("fake", encoding="utf-8")

    try:
        validate_add_source_request(root, {"source": "paper.pdf", "parser": "bad"})
    except UiActionError as exc:
        assert exc.code == "invalid_parser"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected UiActionError")


def test_validate_add_source_accepts_urls_and_files() -> None:
    from llmwiki.ui.actions import validate_add_source_request

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "paper.pdf").write_text("fake", encoding="utf-8")

    local = validate_add_source_request(root, {"source": "paper.pdf", "parser": ""})
    url = validate_add_source_request(root, {"source": "https://example.com/source.html", "parser": "auto"})

    assert local.source == "paper.pdf"
    assert local.parser is None
    assert local.source_kind == "local_path"
    assert url.source_kind == "url"
    assert url.parser == "auto"


def test_enqueue_add_source_job_uses_job_manager() -> None:
    from llmwiki.ui.actions import enqueue_add_source_job

    class FakeJobManager:
        def __init__(self) -> None:
            self.jobs = []

        def enqueue(self, job):
            self.jobs.append(job)
            return job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "paper.pdf").write_text("fake", encoding="utf-8")
    manager = FakeJobManager()

    job = enqueue_add_source_job(root, {"source": "paper.pdf", "parser": "pypdf"}, manager)

    assert job.requested_parser == "pypdf"
    assert manager.jobs == [job]
