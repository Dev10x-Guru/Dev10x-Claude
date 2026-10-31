"""The catalog reaches worktrees without settings and the global file (GH-1664)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.file_locks import LockTimeoutError
from dev10x.skills.permission.catalog_paths import load_catalog_document
from dev10x.skills.permission.catalog_prune import (
    prune_messages,
    prune_unmatchable_catalog_rules,
)

from dev10x.skills.permission import catalog_prune, enumerate_mcp
from dev10x.skills.permission import catalog_write as mod

CONFIG = {"base_permissions": ["Bash(ls:*)", "Bash(uptime:*)"]}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(enumerate_mcp, "discover_mcp_tools", lambda **_kw: {})
    monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(tmp_path / "claude-home"))
    ClaudeDir.reset_cache()


def _allow(path: Path) -> list[str]:
    return json.loads(path.read_text())["permissions"]["allow"]


class TestCreateMissingSettings:
    @pytest.fixture
    def missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(mod, "_is_git_tracked", lambda _path: False)
        worktree = tmp_path / "herdr" / "worktrees" / "proj" / "wt-1"
        worktree.mkdir(parents=True)
        return worktree / ".claude" / "settings.local.json"

    def test_creates_and_seeds_the_missing_file(self, missing: Path) -> None:
        result = mod.ensure_base(
            config=CONFIG,
            settings_files=[],
            dry_run=False,
            quiet=True,
            create_missing=[missing],
        )

        assert result["exit_code"] == 0
        assert _allow(missing) == ["Bash(ls:*)", "Bash(uptime:*)"]
        assert f"  Created {missing}" in result["messages"]

    def test_dry_run_reports_without_creating(self, missing: Path) -> None:
        result = mod.ensure_base(
            config=CONFIG,
            settings_files=[],
            dry_run=True,
            quiet=True,
            create_missing=[missing],
        )

        assert not missing.exists()
        assert f"  Would create {missing}" in result["messages"]

    def test_an_uncreatable_path_is_reported_not_raised(
        self,
        missing: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _refuse(*_args: object, **_kwargs: object) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr(Path, "mkdir", _refuse)

        result = mod.ensure_base(
            config=CONFIG,
            settings_files=[],
            dry_run=False,
            quiet=True,
            create_missing=[missing],
        )

        assert result["exit_code"] == 1
        assert any(f"cannot create {missing}" in e for e in result["errors"])

    def test_a_file_created_while_waiting_for_the_lock_is_kept(
        self,
        missing: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        concurrent = json.dumps({"permissions": {"allow": ["Bash(git log:*)"]}})

        @contextmanager
        def _racing_lock(path: Path) -> Iterator[None]:
            path.write_text(concurrent)
            yield

        monkeypatch.setattr(mod, "file_lock", _racing_lock)

        created, messages, errors = mod._create_missing_settings(paths=[missing], dry_run=False)

        assert (created, messages, errors) == ([], [], [])
        assert missing.read_text() == concurrent

    def test_an_existing_file_is_filled_not_recreated(self, missing: Path) -> None:
        missing.parent.mkdir(parents=True)
        missing.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}))

        result = mod.ensure_base(
            config=CONFIG,
            settings_files=[missing],
            dry_run=False,
            quiet=True,
            create_missing=[missing],
        )

        assert _allow(missing) == ["Bash(ls:*)", "Bash(uptime:*)"]
        assert f"  Created {missing}" not in result["messages"]


class TestGlobalOptIn:
    @pytest.fixture
    def tracked_global(self, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = ClaudeDir.settings_json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
        monkeypatch.setattr(mod, "_is_git_tracked", lambda candidate: candidate == path)
        return path

    def test_tracked_global_is_skipped_with_a_hint(self, tracked_global: Path) -> None:
        result = mod.ensure_base(
            config=CONFIG,
            settings_files=[tracked_global],
            dry_run=False,
            quiet=False,
        )

        assert json.loads(tracked_global.read_text()) == {}
        assert (
            "  (pass --global to write the tracked global settings.json anyway)"
            in (result["messages"])
        )

    def test_include_global_writes_the_tracked_file(self, tracked_global: Path) -> None:
        mod.ensure_base(
            config=CONFIG,
            settings_files=[tracked_global],
            dry_run=False,
            quiet=True,
            include_global=True,
        )

        assert _allow(tracked_global) == ["Bash(ls:*)", "Bash(uptime:*)"]


class TestSeedWorktreeSkippedTarget:
    @pytest.mark.parametrize("state", [True, None], ids=["tracked", "unknown"])
    def test_a_skipped_target_is_an_error_not_a_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        state: bool | None,
    ) -> None:
        monkeypatch.setattr(mod, "_is_git_tracked", lambda _path: state)

        result = mod.seed_worktree(worktree_root=tmp_path, config=CONFIG)

        assert isinstance(result, ErrorResult)
        assert "worktree settings not seeded" in result.error
        assert str(tmp_path / ".claude" / "settings.local.json") in result.error


class TestSeedWorktreeDryRun:
    def test_reports_the_full_catalog_for_a_worktree_without_settings(
        self,
        tmp_path: Path,
    ) -> None:
        result = mod.seed_worktree(worktree_root=tmp_path, config=CONFIG, dry_run=True)

        assert isinstance(result, SuccessResult)
        assert result.value["added"] == 2
        assert result.value["would_create"] is True
        assert not (tmp_path / ".claude" / "settings.local.json").exists()

    def test_reports_only_the_gap_for_an_existing_file(self, tmp_path: Path) -> None:
        settings = tmp_path / ".claude" / "settings.local.json"
        settings.parent.mkdir()
        before = json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}})
        settings.write_text(before)

        result = mod.seed_worktree(worktree_root=tmp_path, config=CONFIG, dry_run=True)

        assert isinstance(result, SuccessResult)
        assert result.value["added"] == 1
        assert settings.read_text() == before


class TestPruneUnmatchableCatalogRules:
    TEXT = (
        "# my catalog\n"
        "base_permissions:\n"
        '  - "Bash(ls:*)"  # keep\n'
        "  - 'Bash(~/.claude/tools/*.py:*)'\n"
        "  # a comment that stays\n"
        "  - Bash(git --git-dir=* --work-tree=* status:*)\n"
        '  - "Read(//tmp/Dev10x/**)"\n'
    )

    @pytest.fixture
    def catalog(self, tmp_path: Path) -> Path:
        path = tmp_path / "projects.yaml"
        path.write_text(self.TEXT)
        return path

    def test_removes_only_the_unmatchable_lines(self, catalog: Path) -> None:
        pruned = prune_unmatchable_catalog_rules(config_path=catalog, dry_run=False)

        assert pruned.removed == (
            "Bash(~/.claude/tools/*.py:*)",
            "Bash(git --git-dir=* --work-tree=* status:*)",
        )
        assert catalog.read_text() == (
            "# my catalog\n"
            "base_permissions:\n"
            '  - "Bash(ls:*)"  # keep\n'
            "  # a comment that stays\n"
            '  - "Read(//tmp/Dev10x/**)"\n'
        )
        assert pruned.backup is not None
        assert pruned.backup.read_text() == self.TEXT

    def test_dry_run_reports_without_writing(self, catalog: Path) -> None:
        pruned = prune_unmatchable_catalog_rules(config_path=catalog, dry_run=True)

        assert len(pruned.removed) == 2
        assert catalog.read_text() == self.TEXT
        assert "  Would remove 2 catalog rule(s)" in pruned.describe(path=catalog, dry_run=True)[1]

    def test_dead_deny_and_ask_rules_are_never_pruned(self, tmp_path: Path) -> None:
        """GH-1503: a guardrail is rewritten elsewhere, never silently dropped."""
        text = (
            "base_permissions:\n"
            "  - 'Bash(~/.claude/tools/*.py:*)'\n"
            "base_denies:\n"
            "  - 'Bash(rm -rf /work/**:*)'\n"
            "base_asks:\n"
            "  - 'Bash(mv * /dev/null:*)'\n"
        )
        path = tmp_path / "projects.yaml"
        path.write_text(text)

        pruned = prune_unmatchable_catalog_rules(config_path=path, dry_run=False)

        assert pruned.removed == ("Bash(~/.claude/tools/*.py:*)",)
        assert path.read_text() == text.replace("  - 'Bash(~/.claude/tools/*.py:*)'\n", "")

    def test_a_failing_prune_is_reported_not_raised(
        self,
        catalog: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _locked(_path: Path) -> None:
            raise LockTimeoutError("held")

        monkeypatch.setattr(catalog_prune, "file_lock", _locked)

        messages = prune_messages(config_path=catalog, dry_run=False)

        assert messages == [f"  SKIP (cannot prune {catalog}): held"]
        assert catalog.read_text() == self.TEXT

    def test_prune_messages_describes_a_successful_prune(self, catalog: Path) -> None:
        messages = prune_messages(config_path=catalog, dry_run=True)

        assert "  Would remove 2 catalog rule(s)" in messages[1]

    def test_clean_catalog_is_untouched(self, tmp_path: Path) -> None:
        path = tmp_path / "projects.yaml"
        path.write_text('base_permissions:\n  - "Bash(ls:*)"\n')

        pruned = prune_unmatchable_catalog_rules(config_path=path, dry_run=False)

        assert pruned.removed == ()
        assert pruned.describe(path=path, dry_run=False) == []

    def test_missing_catalog_is_a_no_op(self, tmp_path: Path) -> None:
        pruned = prune_unmatchable_catalog_rules(
            config_path=tmp_path / "absent.yaml",
            dry_run=False,
        )

        assert pruned.removed == ()


class TestShippedSafeDefaults:
    @pytest.mark.parametrize(
        "rule",
        ["Bash(npm ci:*)", "Bash(claude --version)", "Bash(uptime:*)"],
    )
    def test_catalog_carries_the_rule(self, projects_yaml: Path, rule: str) -> None:
        config = load_catalog_document(catalog_path=projects_yaml)

        assert rule in config["base_permissions"]
