"""Dev10x's own state must not leave every worktree dirty (GH-1275).

Driven against real repositories on purpose: the check is "does git
ignore this path", and only git can answer it. A mock would assert that
the mock agrees with the implementation.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from dev10x.skills.permission.ignore_session_state import (
    IGNORE_PATTERN,
    SUGGESTED_TRACKED_PATTERN,
    ensure_ignored,
    ensure_ignored_for_roots,
    is_already_ignored,
    suggestion_for,
)

_TIMEOUT_SECONDS = 30


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scrub the developer's git config for BOTH halves of every test.

    A global `core.excludesFile` covering `.claude/` makes
    `is_already_ignored` true before anything is written, so eight of
    these tests pass or fail on a property of the machine.

    It has to go on `os.environ` rather than an `env=` argument: the code
    under test reaches git through `subprocess_utils.run`, which forwards
    no `env`, so a per-call scrub reaches the test's own git calls and not
    the ones being tested — and the two halves of an assertion then run
    under different configurations. That is worse than a machine-dependent
    failure, because it can hide one.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        timeout=_TIMEOUT_SECONDS,
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repo that tracks `.claude/`, with an UNTRACKED Dev10x state dir.

    The state directory is created after the commit on purpose. Dev10x
    writes it at run time and nobody commits it — and `git check-ignore`
    skips tracked paths by default, so a fixture that committed it would
    report "not ignored" no matter what rule was in force, testing the
    fixture rather than the code.
    """
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(tmp_path)],
        check=True,
        timeout=_TIMEOUT_SECONDS,
    )
    _git("config", "user.name", "test", cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=tmp_path)
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (rules / "essentials.md").write_text("tracked\n", encoding="utf-8")
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-q", "-m", "root", cwd=tmp_path)

    state = tmp_path / ".claude" / "Dev10x"
    state.mkdir()
    (state / "auto-advance-records.md").write_text("state\n", encoding="utf-8")
    return tmp_path


def _status(repo: Path) -> str:
    return _git("status", "--porcelain", cwd=repo)


class TestTheStateDirectoryStopsShowingAsUntracked:
    def test_it_is_dirty_before(self, tmp_path: Path) -> None:
        # Establish the symptom, so the test below cannot pass vacuously
        # on a repo that was already clean.
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(tmp_path)],
            check=True,
            timeout=_TIMEOUT_SECONDS,
        )
        state = tmp_path / ".claude" / "Dev10x"
        state.mkdir(parents=True)
        (state / "records.md").write_text("state\n", encoding="utf-8")

        assert ".claude/" in _status(tmp_path)

    def test_the_rule_makes_the_tree_clean(self, repo: Path) -> None:
        (repo / ".claude" / "Dev10x" / "new-record.md").write_text("x\n", encoding="utf-8")
        assert _status(repo) != ""

        ensure_ignored(repo_root=repo)

        assert _status(repo) == ""

    def test_tracked_claude_content_is_untouched(self, repo: Path) -> None:
        # The rule must scope to Dev10x/, not swallow the checked-in
        # .claude/rules/ the project deliberately tracks.
        ensure_ignored(repo_root=repo)

        assert "essentials.md" in _git("ls-files", ".claude", cwd=repo)


class TestIdempotence:
    def test_a_second_run_appends_nothing(self, repo: Path) -> None:
        first = ensure_ignored(repo_root=repo)
        second = ensure_ignored(repo_root=repo)

        assert first.status == "appended"
        assert second.status == "already-ignored"

    def test_the_rule_is_written_once(self, repo: Path) -> None:
        ensure_ignored(repo_root=repo)
        ensure_ignored(repo_root=repo)

        exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")

        assert exclude.count(IGNORE_PATTERN) == 1

    def test_existing_exclude_entries_survive(self, repo: Path) -> None:
        # "Append the line if the file exists without it; never rewrite or
        # reorder existing entries."
        exclude = repo / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("*.swp\nbuild/\n", encoding="utf-8")

        ensure_ignored(repo_root=repo)

        content = exclude.read_text(encoding="utf-8")
        assert content.startswith("*.swp\nbuild/\n")
        assert IGNORE_PATTERN in content


class TestItDefersToAnyExistingRule:
    def test_a_committed_gitignore_is_respected(self, repo: Path) -> None:
        # The scenario the suggestion points at: a teammate committed the
        # tracked rule, so the pass must not add a second, redundant one.
        (repo / ".claude" / ".gitignore").write_text(
            f"{SUGGESTED_TRACKED_PATTERN}\n", encoding="utf-8"
        )
        _git("add", ".claude/.gitignore", cwd=repo)
        _git("commit", "-q", "-m", "ignore Dev10x state", cwd=repo)

        outcome = ensure_ignored(repo_root=repo)

        assert outcome.status == "already-ignored"

    def test_an_uncommitted_gitignore_is_respected_too(self, repo: Path) -> None:
        # git reads an untracked .gitignore, so the rule counts before
        # anyone commits it. Asserted separately so the committed case
        # above cannot pass for the wrong reason.
        (repo / ".claude" / ".gitignore").write_text(
            f"{SUGGESTED_TRACKED_PATTERN}\n", encoding="utf-8"
        )

        assert ensure_ignored(repo_root=repo).status == "already-ignored"

    def test_is_already_ignored_reports_false_on_a_bare_repo(self, repo: Path) -> None:
        assert is_already_ignored(repo_root=repo) is False


class TestOneWriteCoversEveryWorktree:
    def test_a_worktree_inherits_the_rule(self, repo: Path, tmp_path: Path) -> None:
        # The common git dir is why this holds: a per-worktree gitdir's
        # info/exclude is not consulted by git at all.
        ensure_ignored(repo_root=repo)
        worktree = tmp_path / "wt"
        _git("worktree", "add", "-q", str(worktree), "-b", "feature", cwd=repo)
        state = worktree / ".claude" / "Dev10x"
        state.mkdir(parents=True, exist_ok=True)
        (state / "records.md").write_text("state\n", encoding="utf-8")

        assert _status(worktree) == ""

    def test_running_from_inside_a_worktree_writes_the_shared_dir(
        self, repo: Path, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "wt2"
        _git("worktree", "add", "-q", str(worktree), "-b", "other", cwd=repo)

        outcome = ensure_ignored(repo_root=worktree)

        assert outcome.exclude_path == repo / ".git" / "info" / "exclude"


class TestNonRepositories:
    def test_a_plain_directory_is_skipped(self, tmp_path: Path) -> None:
        outcome = ensure_ignored(repo_root=tmp_path)

        assert outcome.status == "not-a-repo"
        assert outcome.exclude_path is None

    def test_it_does_not_create_anything(self, tmp_path: Path) -> None:
        ensure_ignored(repo_root=tmp_path)

        assert not (tmp_path / ".git").exists()


class TestReporting:
    def test_each_repo_is_visited_once(self, repo: Path) -> None:
        outcomes = ensure_ignored_for_roots(repo_roots=[repo, repo, repo])

        assert len(outcomes) == 1

    def test_the_tracked_rule_is_suggested_after_a_write(self, repo: Path) -> None:
        outcome = ensure_ignored(repo_root=repo)

        suggestion = suggestion_for(outcome)

        assert suggestion is not None
        assert SUGGESTED_TRACKED_PATTERN in suggestion

    def test_no_suggestion_when_nothing_was_written(self, repo: Path) -> None:
        ensure_ignored(repo_root=repo)

        assert suggestion_for(ensure_ignored(repo_root=repo)) is None

    def test_the_summary_names_the_repo(self, repo: Path) -> None:
        assert str(repo) in ensure_ignored(repo_root=repo).summary()

    def test_the_summary_says_when_nothing_was_needed(self, repo: Path) -> None:
        ensure_ignored(repo_root=repo)

        assert "already ignored" in ensure_ignored(repo_root=repo).summary()

    def test_the_summary_says_when_it_skipped_a_non_repo(self, tmp_path: Path) -> None:
        assert "not a git repository" in ensure_ignored(repo_root=tmp_path).summary()


class TestDryRun:
    def test_it_writes_nothing(self, repo: Path) -> None:
        exclude = repo / ".git" / "info" / "exclude"
        before = exclude.read_text(encoding="utf-8") if exclude.exists() else ""

        ensure_ignored(repo_root=repo, dry_run=True)

        after = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        assert after == before

    def test_the_repo_stays_dirty(self, repo: Path) -> None:
        # The point of the preview is that it changes nothing — if the
        # state dir stopped showing, the dry run had written the rule.
        ensure_ignored(repo_root=repo, dry_run=True)

        assert ".claude/Dev10x/" in _status(repo)

    def test_it_names_the_file_it_would_write(self, repo: Path) -> None:
        outcome = ensure_ignored(repo_root=repo, dry_run=True)

        assert outcome.status == "would-append"
        assert outcome.exclude_path == repo / ".git" / "info" / "exclude"

    def test_it_still_suggests_the_tracked_rule(self, repo: Path) -> None:
        # `changed` means "this repo needed a rule", so the preview and the
        # real run print the same suggestion.
        outcome = ensure_ignored(repo_root=repo, dry_run=True)

        assert suggestion_for(outcome) is not None

    def test_an_already_ignored_repo_is_unchanged_either_way(self, repo: Path) -> None:
        ensure_ignored(repo_root=repo)

        outcome = ensure_ignored(repo_root=repo, dry_run=True)

        assert outcome.status == "already-ignored"
        assert suggestion_for(outcome) is None

    def test_the_summary_reads_as_a_preview(self, repo: Path) -> None:
        assert "would add" in ensure_ignored(repo_root=repo, dry_run=True).summary()

    def test_it_reaches_every_root(self, repo: Path) -> None:
        outcomes = ensure_ignored_for_roots(repo_roots=[repo], dry_run=True)

        assert [outcome.status for outcome in outcomes] == ["would-append"]
