"""GH-1992: the eval-gap CLI runs against whichever core root it is handed."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.teach.skills.audit.eval_gaps_cli import main

GATED_SKILL_MD = """---
name: dev10x:demo
allowed-tools:
  - AskUserQuestion
---

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
"""

UNGATED_SKILL_MD = """---
name: dev10x:demo
allowed-tools:
  - Read
---

No gates here.
"""


def _skill(*, root: Path, name: str, body: str) -> Path:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body)
    return skill_dir


class TestMain:
    def test_clean_root_exits_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _skill(root=tmp_path, name="plain", body=UNGATED_SKILL_MD)

        code = main(argv=["--all"], repo_root=tmp_path)

        assert (code, "no eval-coverage gaps" in capsys.readouterr().out) == (0, True)

    def test_gated_skill_without_evals_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _skill(root=tmp_path, name="gated", body=GATED_SKILL_MD)

        code = main(argv=[], repo_root=tmp_path)

        assert (code, "gated" in capsys.readouterr().err) == (1, True)

    def test_named_dirs_skip_those_without_skill_file(self, tmp_path: Path) -> None:
        gated = _skill(root=tmp_path, name="gated", body=GATED_SKILL_MD)
        missing = tmp_path / "skills" / "missing"
        missing.mkdir()

        code = main(argv=[str(missing), str(gated)], repo_root=tmp_path)

        assert code == 1

    def test_named_clean_dir_exits_zero(self, tmp_path: Path) -> None:
        plain = _skill(root=tmp_path, name="plain", body=UNGATED_SKILL_MD)

        code = main(argv=[str(plain)], repo_root=tmp_path)

        assert code == 0
