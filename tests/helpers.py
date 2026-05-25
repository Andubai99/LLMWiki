from __future__ import annotations

import uuid
from pathlib import Path


def make_workspace() -> Path:
    root = Path(__file__).resolve().parents[1] / ".test-workspaces" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root
