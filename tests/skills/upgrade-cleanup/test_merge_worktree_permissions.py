"""Tests for merge_worktree_permissions module."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from dev10x.skills.permission import merge_worktree_permissions as mod
from dev10x.skills.permission.merge_worktree_permissions import (
    generalize_permission,
    is_noise,
)


def _make_worktree(*, main: Path, wt: Path, settings: bool = True) -> None:
    """Materialize a linked worktree whose .git points back at ``main``."""
    wt.mkdir(parents=True, exist_ok=True)
    (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/{wt.name}\n")
    if settings:
        claude = wt / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "settings.local.json").write_text("{}")


class TestIsNoise:
    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(find /work/example -name '*.py')",
            "Bash(find . -type f -name foo)",
            "Read(/tmp/Dev10x/session/abc.A1b2C3d4.txt)",
            "Bash(if [ -f foo ])",
            "Bash(then echo hello)",
            "Bash(else exit 1)",
            "Bash(fi)",
            "Bash(GROOM_SEQ_FILE=/tmp/foo git rebase)",
            'Bash("PAY-123" something)',
            "Bash(bash -c 'echo hello')",
            "Bash(git-push-safe.sh -u origin janusz/PAY-123/fix)",
            # GH-965: source-line references stay noise
            "Bash(uv run behave features/crm/tax.feature:60)",
            "Bash(pytest tests/test_foo.py:42)",
        ],
    )
    def test_detects_noise(self, entry: str) -> None:
        assert is_noise(entry) is True

    def test_reanchored_worktree_script_is_not_noise(self) -> None:
        # GH-594: a worktree project script, once re-anchored to the project
        # root by generalize_permission, is a stable rule — not noise.
        assert is_noise("Bash(/work/me/hooks/scripts/audit-wrap test *)") is False

    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(git log:*)",
            "Bash(docker compose up)",
            "mcp__plugin_Dev10x_cli__detect_tracker",
            "Read(/work/example/app-pos/src/file.py)",
        ],
    )
    def test_allows_stable_entries(self, entry: str) -> None:
        assert is_noise(entry) is False


class TestGeneralizePermission:
    @pytest.mark.parametrize(
        "entry,expected",
        [
            ("detect-tracker.sh PAY-123", "detect-tracker.sh"),
            ("gh-issue-get.sh 42", "gh-issue-get.sh"),
            ("git reset --hard origin/main", "git reset --hard"),
            ("git reset --soft abc123def", "git reset --soft"),
            # GH-594: re-anchor worktree-absolute project paths to the root.
            (
                "Bash(/work/dx/.worktrees/Dev10x-Claude-2/bin/release.sh:*)",
                "Bash(/work/dx/bin/release.sh:*)",
            ),
            (
                "Bash(/work/me/.worktrees/wt-1/hooks/scripts/audit-wrap test *)",
                "Bash(/work/me/hooks/scripts/audit-wrap test *)",
            ),
        ],
    )
    def test_generalizes_known_patterns(self, entry: str, expected: str) -> None:
        assert generalize_permission(entry) == expected

    def test_leaves_stable_entry_unchanged(self) -> None:
        assert generalize_permission("Bash(git log:*)") == "Bash(git log:*)"

    def test_non_worktree_path_unchanged(self) -> None:
        # Re-anchoring must only touch ``.worktrees`` paths (GH-594).
        assert generalize_permission("Read(/work/dx/bin/release.sh)") == (
            "Read(/work/dx/bin/release.sh)"
        )


class TestGitRegisteredWorktrees:
    """GH-813 Finding 2: discover worktrees via `git worktree list`."""

    def test_parses_porcelain_worktree_paths(self, tmp_path: Path, monkeypatch) -> None:
        out = "worktree /a/main\nHEAD abc\n\nworktree /a/side/wt1\nHEAD def\n"
        monkeypatch.setattr(
            mod.subprocess_utils,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout=out),
        )
        assert mod.git_registered_worktrees(tmp_path) == [
            Path("/a/main"),
            Path("/a/side/wt1"),
        ]

    def test_empty_when_not_a_git_repo(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            mod.subprocess_utils,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=128, stdout=""),
        )
        assert mod.git_registered_worktrees(tmp_path) == []


class TestFindWorktreeGroups:
    """GH-813 Finding 2: union the .worktrees/ glob with git-registered
    worktrees so a worktree living anywhere is discovered, not silently
    skipped."""

    def test_groups_git_registered_worktree_outside_layout(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        main = tmp_path / "proj"
        main.mkdir()
        wt = tmp_path / "elsewhere" / "wt1"
        _make_worktree(main=main, wt=wt)
        monkeypatch.setattr(mod, "git_registered_worktrees", lambda root_path: [wt])
        assert mod.find_worktree_groups([str(main)]) == {main: [wt]}

    def test_groups_conventional_worktrees_dir(self, tmp_path: Path, monkeypatch) -> None:
        main = tmp_path / "proj"
        wt = main / ".worktrees" / "wt1"
        _make_worktree(main=main, wt=wt)
        # Even with git unavailable, the glob still finds the conventional layout.
        monkeypatch.setattr(mod, "git_registered_worktrees", lambda root_path: [])
        assert mod.find_worktree_groups([str(main)]) == {main: [wt]}

    def test_dedupes_worktree_seen_by_both_sources(self, tmp_path: Path, monkeypatch) -> None:
        main = tmp_path / "proj"
        wt = main / ".worktrees" / "wt1"
        _make_worktree(main=main, wt=wt)
        monkeypatch.setattr(mod, "git_registered_worktrees", lambda root_path: [wt])
        assert mod.find_worktree_groups([str(main)]) == {main: [wt]}

    def test_skips_worktree_without_settings(self, tmp_path: Path, monkeypatch) -> None:
        main = tmp_path / "proj"
        main.mkdir()
        wt = tmp_path / "elsewhere" / "wt1"
        _make_worktree(main=main, wt=wt, settings=False)
        monkeypatch.setattr(mod, "git_registered_worktrees", lambda root_path: [wt])
        assert mod.find_worktree_groups([str(main)]) == {}
