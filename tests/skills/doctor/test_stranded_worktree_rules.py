"""GH-1709: the doctor reports rules stranded on another worktree's path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dev10x.domain.common.workspace import worktree_roots_in
from dev10x.skills.doctor.registry import load_strategies
from dev10x.skills.doctor.strategies.stranded_worktree_rules import (
    STRATEGY,
    detect,
    own_checkout,
)
from dev10x.skills.doctor.strategy import Context

from tests.skills.doctor.conftest import WriteSettings


@pytest.fixture
def herdr(tmp_path: Path) -> Path:
    return tmp_path / ".herdr" / "worktrees" / "repo"


class TestWorktreeRootsIn:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Bash(/work/repo/.worktrees/wt-1/bin/x.sh:*)", ["/work/repo/.worktrees/wt-1"]),
            ("Read(//work/repo/.worktrees/wt-1/**)", ["//work/repo/.worktrees/wt-1"]),
            (
                "Bash(~/.herdr/worktrees/repo/wt-2/skills/s.sh run)",
                ["~/.herdr/worktrees/repo/wt-2"],
            ),
            (
                "Bash(cp /a/.worktrees/x/f /work/.herdr/worktrees/r/y/g)",
                ["/a/.worktrees/x", "/work/.herdr/worktrees/r/y"],
            ),
            ("Bash(git log:*)", []),
            ("Bash(/work/repo/bin/x.sh:*)", []),
        ],
    )
    def test_finds_every_layout(self, text: str, expected: list[str]) -> None:
        assert worktree_roots_in(text) == expected


class TestOwnCheckout:
    def test_project_file_names_its_checkout(self, tmp_path: Path) -> None:
        assert own_checkout(tmp_path / "repo" / ".claude" / "settings.json") == tmp_path / "repo"

    def test_user_scope_has_no_checkout(self) -> None:
        assert own_checkout(Path.home() / ".claude" / "settings.json") is None

    def test_non_claude_file_has_no_checkout(self, tmp_path: Path) -> None:
        assert own_checkout(tmp_path / "settings.json") is None


class TestDetection:
    def test_rule_naming_own_checkout_is_clean(
        self, herdr: Path, write_settings: WriteSettings
    ) -> None:
        own = herdr / "wt-1"
        path = write_settings(checkout=own, allow=[f"Bash({own}/bin/x.sh:*)"])

        assert detect(Context(settings_paths=(path,))) == []

    @pytest.mark.parametrize(
        "layout",
        [Path(".herdr") / "worktrees" / "repo", Path("repo") / ".worktrees"],
        ids=["herdr", "dot-worktrees"],
    )
    def test_live_sibling_rule_is_offered_reanchored(
        self, tmp_path: Path, write_settings: WriteSettings, layout: Path
    ) -> None:
        own = tmp_path / layout / "wt-1"
        sibling = tmp_path / layout / "wt-2"
        sibling.mkdir(parents=True)
        rule = f"Bash({sibling}/skills/s.sh:*)"
        path = write_settings(checkout=own, allow=[rule])

        [finding] = detect(Context(settings_paths=(path,)))

        assert finding.severity == "suggestion"
        assert finding.location == str(path)
        assert finding.to_remediation().action == {
            "bucket": "permissions.allow",
            "remove": rule,
            "add": f"Bash({own}/skills/s.sh:*)",
        }

    def test_retired_sibling_rule_is_offered_for_removal(
        self, herdr: Path, write_settings: WriteSettings
    ) -> None:
        own = herdr / "wt-1"
        rule = f"Bash({herdr}/gone/skills/s.sh:*)"
        path = write_settings(checkout=own, allow=[rule])

        [finding] = detect(Context(settings_paths=(path,)))

        assert "no longer exists" in finding.proposed_fix
        assert STRATEGY.remediate(finding).action == {
            "bucket": "permissions.allow",
            "remove": rule,
        }

    def test_user_scope_file_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"permissions": {"allow": ["Bash(/a/.worktrees/x/y:*)"]}}))

        assert detect(Context(settings_paths=(path,))) == []

    def test_strategy_is_registered(self) -> None:
        assert STRATEGY.id in [strategy.id for strategy in load_strategies()]
