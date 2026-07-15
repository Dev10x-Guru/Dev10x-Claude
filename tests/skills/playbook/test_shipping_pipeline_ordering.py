"""GH-858 F3: the shipped shipping pipeline must commit implementation
work BEFORE the code-review step.

Dev10x:review computes its diff from commits against base (develop-diff),
not the working tree, so a branch whose implementation is still
uncommitted would review an empty diff. The default ``shipping-pipeline``
fragment must therefore order a commit step ahead of "Code review".

Only the plugin-shipped default is asserted here — project overrides such
as ``.claude/Dev10x/playbooks/work-on.yaml`` are gitignored local
customizations, absent in CI, and kept in sync by their owner (see the
GH-858 follow-up on playbook-override versioning).
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PLAYBOOK = _ROOT / "skills" / "playbook" / "references" / "playbook.yaml"


def _subjects(playbook: Path, fragment: str) -> list[str]:
    doc = yaml.safe_load(playbook.read_text())
    steps = doc["fragments"][fragment]
    return [step.get("subject", "") for step in steps]


def test_commit_precedes_code_review() -> None:
    subjects = _subjects(_DEFAULT_PLAYBOOK, "shipping-pipeline")
    commit_idx = next(i for i, s in enumerate(subjects) if s.lower().startswith("commit"))
    review_idx = subjects.index("Code review")
    assert commit_idx < review_idx, (
        "shipping-pipeline: a commit step must precede 'Code review' so review "
        f"has a non-empty base diff; got order {subjects}"
    )
