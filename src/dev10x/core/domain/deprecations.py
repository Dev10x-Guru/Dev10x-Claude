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
        name="SKILL_NAME_ALIASES",
        audience=Audience.CONFIG,
        since="0.108.0",
        removed_in="0.114.0",
        replacement="dev10x-<area>:<skill>",
        issue="GH-1559",
        locations=("src/dev10x/core/skills/upgrade_cleanup/skill_names.py",),
    ),
)


def due(*, version: str) -> list[Deprecation]:
    return [entry for entry in REGISTER if entry.is_due(version=version)]
