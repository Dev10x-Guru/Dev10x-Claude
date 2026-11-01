from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def split_repo(tmp_path: Path) -> Path:
    for skill_dir in ("skills/afk", "plugins/qa/skills/tts", "plugins/infra/skills/k8s"):
        (tmp_path / skill_dir).mkdir(parents=True)
        (tmp_path / skill_dir / "SKILL.md").write_text("---\n")
    (tmp_path / "plugins" / "infra" / "skills" / "notes.md").write_text("")
    (tmp_path / "plugins" / "docs-only").mkdir()
    return tmp_path
