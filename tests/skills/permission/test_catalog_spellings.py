"""What the shipped catalogs must still emit after GH-1317.

The spellings schema changes the *source* shape of two catalogs. These
tests pin the *emitted* shape: every rule the hand-listed entries
produced before the migration is still produced, the new spellings and
the foreman/watchdog verbs arrive, and no source key leaks downstream.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.domain.common.baseline_catalog import load_baseline_dict
from dev10x.domain.common.command_spellings import SPELLINGS_KEY, expand_spellings
from dev10x.skills.permission.catalog_paths import CATALOG_RELPATH

PERMISSION_DIR = Path(permission_pkg.__file__).resolve().parent
REPO_ROOT = PERMISSION_DIR.parents[3]
BASELINE_YAML = PERMISSION_DIR / "baseline-permissions.yaml"
PROJECTS_YAML = REPO_ROOT / CATALOG_RELPATH

#: Every rule the hand-listed `uvx dev10x …` block emitted before the
#: migration. Pinned literally so a source-shape change that silently
#: drops or rewrites one fails here rather than in a user's session.
PRE_MIGRATION_UVX_RULES = (
    "Bash(uvx dev10x permission clean:*)",
    "Bash(uvx dev10x permission doctor:*)",
    "Bash(uvx dev10x permission ensure-base:*)",
    "Bash(uvx dev10x permission ensure-reads:*)",
    "Bash(uvx dev10x permission ensure-scripts:*)",
    "Bash(uvx dev10x permission ensure-workspace:*)",
    "Bash(uvx dev10x permission enumerate-mcp:*)",
    "Bash(uvx dev10x permission generalize:*)",
    "Bash(uvx dev10x permission init:*)",
    "Bash(uvx dev10x permission investigate:*)",
    "Bash(uvx dev10x permission merge-worktree:*)",
    "Bash(uvx dev10x permission ensure-ignored:*)",
    "Bash(uvx dev10x permission record-upgrade:*)",
    "Bash(uvx dev10x permission update-paths:*)",
    "Bash(uvx dev10x playbook diff:*)",
    "Bash(uvx dev10x skill count-instructions:*)",
    "Bash(uvx dev10x config:*)",
    "Bash(uvx dev10x platform:*)",
    "Bash(uvx dev10x init:*)",
    "Bash(uvx dev10x github-app:*)",
)

#: The read-only verbs GH-1317 catalogued, absent in every spelling
#: before it — which is why an unattended pre-flight prompted on its own
#: heartbeat and collected seventeen unsynced per-checkout catch-alls.
FOREMAN_VERBS = (
    "dev10x foreman probe",
    "dev10x foreman watch",
    "dev10x watchdog probe",
    "dev10x watchdog sessions",
)

FOREMAN_PREFIXES = ("", "uvx ", "uv run ", "uv run --project $CLAUDE_PLUGIN_ROOT ")


def _projects() -> dict:
    return expand_spellings(yaml.safe_load(PROJECTS_YAML.read_text(encoding="utf-8")))


def _base_permissions() -> list[str]:
    return _projects()["base_permissions"]


class TestNoEmittedRuleChanged:
    @pytest.mark.parametrize("rule", PRE_MIGRATION_UVX_RULES)
    def test_every_hand_listed_uvx_rule_is_still_emitted(self, rule: str) -> None:
        assert rule in _base_permissions()

    def test_no_rule_is_emitted_twice(self) -> None:
        rules = _base_permissions()
        duplicates = sorted({rule for rule in rules if rules.count(rule) > 1})
        assert duplicates == [], f"the expansion duplicated shipped rules: {duplicates}"


class TestEverySpellingIsCovered:
    @pytest.mark.parametrize("prefix", ["", "uvx ", "uv run "])
    def test_the_observed_bare_and_runner_spellings_reach_the_catalog(self, prefix: str) -> None:
        # GH-1317's observed case: `dev10x permission ensure-base
        # --dry-run` prompted because only the `uvx` spelling existed.
        assert f"Bash({prefix}dev10x permission ensure-base:*)" in _base_permissions()

    @pytest.mark.parametrize("command", FOREMAN_VERBS)
    @pytest.mark.parametrize("prefix", FOREMAN_PREFIXES)
    def test_foreman_and_watchdog_verbs_are_catalogued(self, prefix: str, command: str) -> None:
        assert f"Bash({prefix}{command}:*)" in _base_permissions()


class TestNoSourceShapeLeaks:
    def test_projects_catalog_exposes_no_spellings_key(self) -> None:
        assert SPELLINGS_KEY not in _projects()

    def test_baseline_catalog_exposes_no_spellings_key(self) -> None:
        groups = load_baseline_dict(BASELINE_YAML, strict=True)["groups"]
        leaked = [name for name, group in groups.items() if SPELLINGS_KEY in group]
        assert leaked == [], f"groups leaking the source shape: {leaked}"

    def test_imagemagick_aliases_still_render_as_rules(self) -> None:
        rules = load_baseline_dict(BASELINE_YAML, strict=True)["groups"]["imagemagick-evidence"][
            "rules"
        ]
        assert rules == [
            "Bash(identify:*)",
            "Bash(magick:*)",
            "Bash(montage:*)",
            "Bash(convert:*)",
        ]
