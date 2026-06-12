"""Tests for merge_worktree_permissions module."""

import pytest

from dev10x.skills.permission.merge_worktree_permissions import (
    generalize_permission,
    is_noise,
)


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
