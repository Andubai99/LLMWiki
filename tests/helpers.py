from __future__ import annotations

import uuid
from pathlib import Path


def make_workspace() -> Path:
    root = Path(__file__).resolve().parents[1] / ".test-workspaces" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root


def disable_llm(root: Path) -> None:
    config_path = root / "config" / "config.toml"
    config = config_path.read_text(encoding="utf-8")
    config = config.replace("enabled = true", "enabled = false")
    config_path.write_text(config, encoding="utf-8", newline="\n")
