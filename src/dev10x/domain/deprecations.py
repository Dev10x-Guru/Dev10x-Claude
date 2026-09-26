"""The register of every live deprecation shim (ADR-0028).

A shim that is not listed here does not have a removal date, and
``tests/domain/test_deprecations.py`` fails when one ships unlisted. An
entry whose ``removed_in`` the package version has reached fails the same
suite, so a stale shim is a red build rather than a forever-shim.

Windows are counted in minor versions, per audience:

``python``
    0 — remove in the same change as the rename; nothing outside this
    repo imports it.
``mcp``
    3 minor versions — agents, skill docs and user memory call tools by
    name from outside the repo.
``config``
    6 minor versions — a key in a user's hand-edited file is read on
    machines this repo cannot see, and nothing rewrites it.

Shims that predate the register are counted from ``0.106.0``, the version
it landed in, since their earlier "one release" promises were never
stated in versions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Audience(StrEnum):
    PYTHON = "python"
    MCP = "mcp"
    CONFIG = "config"


WINDOW_MINOR_VERSIONS: dict[Audience, int] = {
    Audience.PYTHON: 0,
    Audience.MCP: 3,
    Audience.CONFIG: 6,
}

_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


class UnparsableVersionError(ValueError):
    pass


def parse_release(version: str) -> tuple[int, int, int]:
    """Return ``(major, minor, patch)``, ignoring any ``.devN`` suffix.

    Dropping the suffix is what makes the register bite on the ``.dev0``
    bump that opens a cycle, which leaves the whole cycle to remove it.
    """
    found = _RELEASE.match(version)
    if found is None:
        raise UnparsableVersionError(f"Not a release version: {version!r}")
    major, minor, patch = (int(part) for part in found.groups())
    return major, minor, patch


@dataclass(frozen=True)
class Deprecation:
    name: str
    audience: Audience
    since: str
    removed_in: str
    replacement: str
    issue: str
    locations: tuple[str, ...]

    def is_due(self, *, version: str) -> bool:
        return parse_release(version) >= parse_release(self.removed_in)


REGISTER: tuple[Deprecation, ...] = (
    Deprecation(
        name="Rule",
        audience=Audience.PYTHON,
        since="0.88.0",
        removed_in="0.107.0",
        replacement="MatchingRule",
        issue="GH-846",
        locations=("src/dev10x/domain/rules/validation_rule.py",),
    ),
    Deprecation(
        name="match_globs_for",
        audience=Audience.PYTHON,
        since="0.92.0",
        removed_in="0.107.0",
        replacement="match_globs_for_repo",
        issue="GH-855",
        locations=("src/dev10x/domain/documents/friction_yaml.py",),
    ),
    Deprecation(
        name="seed_strict_baseline_if_absent",
        audience=Audience.PYTHON,
        since="0.97.0",
        removed_in="0.107.0",
        replacement="seed_safe_baseline_if_absent",
        issue="GH-1164",
        locations=(
            "src/dev10x/domain/documents/friction_yaml.py",
            "src/dev10x/domain/documents/session_yaml.py",
        ),
    ),
    Deprecation(
        name="read_human_review",
        audience=Audience.PYTHON,
        since="0.97.0",
        removed_in="0.107.0",
        replacement="read_supervisor_review",
        issue="GH-1161",
        locations=("src/dev10x/domain/documents/session_yaml.py",),
    ),
    Deprecation(
        name="human_review_status",
        audience=Audience.MCP,
        since="0.97.0",
        removed_in="0.109.0",
        replacement="supervisor_review_status",
        issue="GH-1161",
        locations=("src/dev10x/mcp/gate_tools.py",),
    ),
    Deprecation(
        name="human_review",
        audience=Audience.MCP,
        since="0.97.0",
        removed_in="0.109.0",
        replacement="supervisor_review",
        issue="GH-1161",
        locations=("src/dev10x/mcp/gate_tools.py",),
    ),
    Deprecation(
        name="human_review",
        audience=Audience.CONFIG,
        since="0.97.0",
        removed_in="0.112.0",
        replacement="supervisor_review",
        issue="GH-1161",
        locations=(
            "src/dev10x/domain/documents/session_yaml.py",
            "src/dev10x/domain/documents/friction_yaml.py",
        ),
    ),
    Deprecation(
        name="match",
        audience=Audience.CONFIG,
        since="0.104.0",
        removed_in="0.112.0",
        replacement="match_repo",
        issue="GH-1375",
        locations=("src/dev10x/domain/project_match.py",),
    ),
    Deprecation(
        name=".claude/Dev10x/session.yaml",
        audience=Audience.CONFIG,
        since="0.94.0",
        removed_in="0.112.0",
        replacement="~/.config/Dev10x/task-index/<repo-stem>.yaml",
        issue="GH-1009",
        locations=(
            "src/dev10x/session/task_index.py",
            "src/dev10x/mcp/task_index_tools.py",
            "src/dev10x/domain/dev10x_paths.py",
        ),
    ),
    Deprecation(
        name="memory/Dev10x/dod-acceptance-criteria.yaml",
        audience=Audience.CONFIG,
        since="0.94.0",
        removed_in="0.112.0",
        replacement="~/.config/Dev10x/dod-acceptance-criteria.yaml",
        issue="GH-1035",
        locations=("skills/verify-acc-dod/SKILL.md",),
    ),
)


def due(*, version: str) -> list[Deprecation]:
    return [entry for entry in REGISTER if entry.is_due(version=version)]
