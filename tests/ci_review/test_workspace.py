from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dev10x.ci_review import workspace
from dev10x.ci_review.workspace import (
    SYMLINK_PLACEHOLDER,
    Refs,
    Workspace,
    apply_rules,
    cache_root,
    changed_files,
    create_workspace,
    fetch_refs,
    gather_context,
    read_blob,
    remove_workspace,
    require_base_scripts,
    restore_config_from_base,
    run_dir_for,
    write_prior_hygiene_comment,
)
from dev10x.core.domain.common.result import ErrorResult, Result, SuccessResult, err, ok
from tests.ci_review.conftest import PR_NUMBER, GitFixture, git


def test_cache_root_honors_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    assert cache_root() == tmp_path / "dev10x" / "ci-review"


def test_cache_root_defaults_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    assert cache_root() == Path.home() / ".cache" / "dev10x" / "ci-review"


def test_run_dir_for(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    path = run_dir_for(
        repo="own/name", pr=3, workflow="hygiene", now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    )

    assert (
        path
        == tmp_path / "dev10x" / "ci-review" / "own-name" / "pr-3" / "20260102T030405Z-hygiene"
    )


class TestRefs:
    def test_fetch_refs(self, git_repos: GitFixture) -> None:
        result = fetch_refs(repo_root=git_repos.clone, base="develop", pr=PR_NUMBER)

        assert result == SuccessResult(
            value=Refs(base_sha=git_repos.base_sha, merge_sha=git_repos.merge_sha)
        )

    def test_unknown_base(self, git_repos: GitFixture) -> None:
        result = fetch_refs(repo_root=git_repos.clone, base="nope", pr=PR_NUMBER)

        assert isinstance(result, ErrorResult)

    def test_missing_merge_ref(self, git_repos: GitFixture) -> None:
        result = fetch_refs(repo_root=git_repos.clone, base="develop", pr=99)

        assert isinstance(result, ErrorResult)
        assert "no merge ref" in result.error

    @pytest.mark.parametrize("failing_call", [2, 4], ids=["base-sha", "merge-sha"])
    def test_rev_parse_failure(self, monkeypatch: pytest.MonkeyPatch, failing_call: int) -> None:
        calls: list[int] = []

        def fake_git(*, repo_root: Path, args: list[str]) -> Result[str]:
            calls.append(1)
            return err("rev-parse") if len(calls) == failing_call else ok("sha\n")

        monkeypatch.setattr(workspace, "_git", fake_git)

        assert fetch_refs(repo_root=Path("/r"), base="b", pr=1) == err("rev-parse")

    def test_read_blob(self, git_repos: GitFixture) -> None:
        fetch_refs(repo_root=git_repos.clone, base="develop", pr=PR_NUMBER)

        result = read_blob(
            repo_root=git_repos.clone, sha=git_repos.merge_sha, path=".github/workflows/review.yml"
        )

        assert result == SuccessResult(value="name: pr\n")

    def test_changed_files_are_the_merge_commits_diff(self, git_repos: GitFixture) -> None:
        fetch_refs(repo_root=git_repos.clone, base="develop", pr=PR_NUMBER)

        result = changed_files(repo_root=git_repos.clone, merge_sha=git_repos.merge_sha)

        assert result == SuccessResult(
            value=[
                ".claude/link",
                ".claude/rules/a.md",
                ".claude/rules/b.md",
                ".github/claude/ci-system-prompt.md",
                ".github/workflows/review.yml",
                ".mcp.json",
                "CLAUDE.md",
            ]
        )

    def test_changed_files_failure(self, git_repos: GitFixture) -> None:
        result = changed_files(repo_root=git_repos.clone, merge_sha="0" * 40)

        assert isinstance(result, ErrorResult)

    def test_base_scripts_present(self, git_repos: GitFixture) -> None:
        result = require_base_scripts(
            repo_root=git_repos.clone, base="develop", base_sha=git_repos.base_sha
        )

        assert result == SuccessResult(value=None)

    def test_base_scripts_missing(self, git_repos: GitFixture) -> None:
        empty_tree_commit = git(
            "commit-tree",
            "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
            "-m",
            "empty",
            cwd=git_repos.clone,
        ).strip()

        result = require_base_scripts(
            repo_root=git_repos.clone, base="develop", base_sha=empty_tree_commit
        )

        assert isinstance(result, ErrorResult)
        assert "skipping rather than running this PR's own copy" in result.error


class TestWorkspace:
    @pytest.fixture
    def space(self, git_repos: GitFixture, tmp_path: Path) -> Workspace:
        refs = fetch_refs(repo_root=git_repos.clone, base="develop", pr=PR_NUMBER)
        assert isinstance(refs, SuccessResult)
        result = create_workspace(
            repo_root=git_repos.clone, run_dir=tmp_path / "run", refs=refs.value
        )
        assert isinstance(result, SuccessResult), result
        return result.value

    def test_checkout_is_the_merge_ref(self, space: Workspace) -> None:
        assert (space.checkout / "CLAUDE.md").read_text(encoding="utf-8") == "pr claude\n"

    def test_scripts_come_from_base(self, space: Workspace) -> None:
        assert sorted(path.name for path in space.scripts.iterdir()) == [
            "build-claude-inputs.sh",
            "gather-pr-context.sh",
            "stage-trusted.sh",
        ]

    def test_base_rules_stage_and_restore(self, space: Workspace) -> None:
        result = apply_rules(workspace=space, rules="base", keep_pr_head=True)

        checkout = space.checkout
        assert result == SuccessResult(value=None)
        assert (checkout / ".github/claude/ci-system-prompt.md").read_text(
            encoding="utf-8"
        ) == "base system prompt\n"
        assert (checkout / ".claude-ci/pr-head/.github/claude/ci-system-prompt.md").read_text(
            encoding="utf-8"
        ) == "pr system prompt\n"
        assert (checkout / ".claude/rules/a.md").read_text(encoding="utf-8") == "base rule\n"
        assert not (checkout / ".claude/rules/b.md").exists()
        assert not (checkout / ".mcp.json").exists()
        assert (checkout / "CLAUDE.md").read_text(encoding="utf-8") == "base claude\n"
        assert (checkout / ".claude-pr/.claude/rules/b.md").read_text(
            encoding="utf-8"
        ) == "pr-only rule\n"
        assert (checkout / ".claude-pr/.mcp.json").is_file()
        assert (checkout / ".claude-pr/.claude/link").read_text(
            encoding="utf-8"
        ) == SYMLINK_PLACEHOLDER
        assert git("status", "--porcelain", "--", ".claude-pr", cwd=checkout) == ""

    def test_base_rules_without_pr_head(self, space: Workspace) -> None:
        apply_rules(workspace=space, rules="base", keep_pr_head=False)

        assert not (space.checkout / ".claude-ci" / "pr-head").exists()

    def test_restore_is_idempotent_on_exclude(self, space: Workspace) -> None:
        restore_config_from_base(checkout=space.checkout, base_sha=space.base_sha)
        restore_config_from_base(checkout=space.checkout, base_sha=space.base_sha)

        exclude = Path(
            git(
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                "info/exclude",
                cwd=space.checkout,
            ).strip()
        )
        assert exclude.read_text(encoding="utf-8").splitlines().count("/.claude-pr/") == 1

    def test_head_rules_leave_the_pr_copy(
        self, space: Workspace, caplog: pytest.LogCaptureFixture
    ) -> None:
        result = apply_rules(workspace=space, rules="head", keep_pr_head=True)

        assert result == SuccessResult(value=None)
        assert (space.checkout / ".mcp.json").is_file()
        assert "CI reads the base" in caplog.text

    def test_remove_workspace(self, space: Workspace) -> None:
        assert remove_workspace(workspace=space) == SuccessResult(value=None)
        assert not space.checkout.exists()

    def test_remove_missing_workspace_fails(self, space: Workspace) -> None:
        remove_workspace(workspace=space)

        assert isinstance(remove_workspace(workspace=space), ErrorResult)


def test_create_workspace_fails_on_bad_sha(git_repos: GitFixture, tmp_path: Path) -> None:
    result = create_workspace(
        repo_root=git_repos.clone,
        run_dir=tmp_path / "run",
        refs=Refs(base_sha=git_repos.base_sha, merge_sha="0" * 40),
    )

    assert isinstance(result, ErrorResult)


def test_create_workspace_fails_on_archive(git_repos: GitFixture, tmp_path: Path) -> None:
    result = create_workspace(
        repo_root=git_repos.clone,
        run_dir=tmp_path / "run",
        refs=Refs(base_sha="f" * 40, merge_sha=git_repos.base_sha),
    )

    assert isinstance(result, ErrorResult)


class TestRestoreFailures:
    @pytest.fixture
    def checkout(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.mark.parametrize("failing", ["reset", "rev-parse"])
    def test_git_failures(
        self, monkeypatch: pytest.MonkeyPatch, checkout: Path, failing: str
    ) -> None:
        monkeypatch.setattr(
            workspace,
            "run_checked",
            lambda *, args, cwd, timeout: err(failing) if args[1] == failing else ok(""),
        )

        assert restore_config_from_base(checkout=checkout, base_sha="s") == err(failing)

    def test_exclude_without_trailing_newline(
        self, monkeypatch: pytest.MonkeyPatch, checkout: Path
    ) -> None:
        (checkout / "exclude").write_text("*.log", encoding="utf-8")
        monkeypatch.setattr(
            workspace, "run_checked", lambda *, args, cwd, timeout: ok("exclude\n")
        )

        restore_config_from_base(checkout=checkout, base_sha="s")

        assert (checkout / "exclude").read_text(encoding="utf-8") == "*.log\n/.claude-pr/\n"


def test_stage_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(workspace, "run_checked", lambda **_: err("stage"))
    space = Workspace(
        repo_root=tmp_path, run_dir=tmp_path, checkout=tmp_path, scripts=tmp_path, base_sha="s"
    )

    assert apply_rules(workspace=space, rules="base", keep_pr_head=False) == err("stage")


class TestGatherContext:
    @pytest.fixture
    def space(self, tmp_path: Path) -> Workspace:
        return Workspace(
            repo_root=tmp_path,
            run_dir=tmp_path,
            checkout=tmp_path / "checkout",
            scripts=tmp_path / "scripts",
            base_sha="s",
        )

    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        recorded: list[dict[str, Any]] = []
        monkeypatch.setenv("GH_TOKEN", "secret")
        monkeypatch.setenv("GITHUB_OUTPUT", "/tmp/out")

        def fake_run(**kwargs: Any) -> Result[str]:
            recorded.append(kwargs)
            return ok("")

        monkeypatch.setattr(workspace, "run_checked", fake_run)
        return recorded

    def test_runs_with_user_auth(self, space: Workspace, calls: list[dict[str, Any]]) -> None:
        assert gather_context(workspace=space, repo="o/r", pr=4) == SuccessResult(value=None)

        (call,) = calls
        assert call["args"] == [str(space.scripts / "gather-pr-context.sh")]
        assert call["cwd"] == space.checkout
        assert call["env"]["PR_NUMBER"] == "4"
        assert call["env"]["GITHUB_REPOSITORY"] == "o/r"
        assert "GH_TOKEN" not in call["env"]
        assert "GITHUB_OUTPUT" not in call["env"]

    def test_failure(self, space: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(workspace, "run_checked", lambda **_: err("gh down"))

        assert gather_context(workspace=space, repo="o/r", pr=4) == err("gh down")


class TestPriorHygieneComment:
    @pytest.fixture
    def context(self, tmp_path: Path) -> Path:
        path = tmp_path / ".claude-ci" / "pr-context"
        path.mkdir(parents=True)
        return path

    def _comments(self, *, context: Path, comments: list[dict[str, Any]]) -> None:
        (context / "issue-comments.json").write_text(json.dumps(comments), encoding="utf-8")

    def test_picks_the_last_bot_comment_with_marker(self, context: Path, tmp_path: Path) -> None:
        marker = "<!-- dev10x-pr-hygiene -->"
        self._comments(
            context=context,
            comments=[
                {"id": 1, "user": "github-actions[bot]", "body": f"old {marker}"},
                {"id": 2, "user": "human", "body": f"forged {marker}"},
                {"id": 3, "user": "github-actions[bot]", "body": f"new {marker}"},
                {"id": 4, "user": "github-actions[bot]", "body": "no marker"},
                {"id": 5, "user": "github-actions[bot]", "body": None},
            ],
        )

        result = write_prior_hygiene_comment(checkout=tmp_path)

        assert result == SuccessResult(value=3)
        assert json.loads((context / "prior-hygiene-comment.json").read_text())["id"] == 3

    def test_no_prior_comment_writes_empty_object(self, context: Path, tmp_path: Path) -> None:
        self._comments(context=context, comments=[])

        assert write_prior_hygiene_comment(checkout=tmp_path) == SuccessResult(value=None)
        assert json.loads((context / "prior-hygiene-comment.json").read_text()) == {}

    def test_missing_comments_file(self, tmp_path: Path) -> None:
        assert isinstance(write_prior_hygiene_comment(checkout=tmp_path), ErrorResult)
