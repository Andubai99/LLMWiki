from pathlib import Path

import llmwiki


def test_llmwiki_package_is_loaded_from_src_layout() -> None:
    package_path = Path(llmwiki.__file__).resolve()
    repo_root = Path(__file__).resolve().parents[1]

    assert repo_root / "src" in package_path.parents
    assert not (repo_root / "llmwiki").exists()
