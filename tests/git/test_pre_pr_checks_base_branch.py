"""pre_pr_checks accepts both spellings of the base branch (GH-1285).

Every use inside the script qualifies the argument as
``origin/$BASE_BRANCH``, so passing the already-qualified
``origin/develop`` — which is what the parameter name suggests, and what
the rest of the toolchain hands around — produced
``origin/origin/develop``. The failure then named the doubled ref, which
reads as a git problem rather than an argument one.

Asserted against the script text rather than by running it: the run
needs a repo with a populated ``origin/<base>`` and a working
``pre-commit``, neither of which the normalization depends on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "skills" / "gh-pr-create" / "scripts" / "pre-pr-checks.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


class TestBaseBranchNormalization:
    def test_a_leading_origin_prefix_is_stripped(self, script_text: str) -> None:
        assert 'BASE_BRANCH="${BASE_BRANCH#origin/}"' in script_text

    def test_the_strip_runs_after_detection_fills_the_default(self, script_text: str) -> None:
        # Detection sources a sibling script that sets BASE_BRANCH itself,
        # so a strip placed above it would normalize an empty string and
        # leave the detected value untouched.
        lines = script_text.splitlines()
        detect = next(i for i, line in enumerate(lines) if "detect-base-branch.sh" in line)
        strip = next(i for i, line in enumerate(lines) if "#origin/}" in line)
        assert strip > detect

    def test_every_use_still_qualifies_the_branch(self, script_text: str) -> None:
        # The strip is only correct while the script owns the qualification;
        # a bare "$BASE_BRANCH..HEAD" would silently compare against a local
        # ref instead.
        # Both spellings are matched: filtering on the bare `$BASE_BRANCH`
        # would exclude a future braced `${BASE_BRANCH}` from the filter
        # entirely, so the guard would pass on an empty list — vacuously
        # green on exactly the regression it exists to catch.
        expansion = re.compile(r"\$\{?BASE_BRANCH\b")
        # The two expansions that legitimately carry no origin/ prefix:
        # the emptiness guard that decides whether to detect a default,
        # and the normalization that strips the prefix in the first place.
        exempt = re.compile(r'-z\s+"\$\{?BASE_BRANCH|\{BASE_BRANCH#origin/\}')
        qualified = re.compile(r"origin/\$\{?BASE_BRANCH\b")

        expansions = [line for line in script_text.splitlines() if expansion.search(line)]
        unqualified = [
            line for line in expansions if not qualified.search(line) and not exempt.search(line)
        ]

        assert expansions, "filter matched nothing — the guard would pass vacuously"
        assert unqualified == []
