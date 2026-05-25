from __future__ import annotations

import tomllib
from pathlib import Path


def test_pdf_text_import_dependency_is_declared():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]
    assert any(dep.lower().startswith("pypdf") for dep in dependencies)
