from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dev10x.ci_review import cli_pin, compare, gh_shim, post_steps, replay, runner, workspace
from dev10x.ci_review.compare import CiPosted
from dev10x.ci_review.render import RenderedInputs
from dev10x.ci_review.replay import ReplayOptions, ReplayOutcome, run_replay
from dev10x.ci_review.report import LOCAL_REPLICA_MARKER
from dev10x.ci_review.workflow import ReviewJob
from dev10x.core.domain.common.result import ErrorResult, Result, SuccessResult, err, ok

_NOW: datetime = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
_REFS: workspace.Refs = workspace.Refs(base_sha="base1", merge_sha="merge1")
_JOB: ReviewJob = ReviewJob(
    job_id="claude-review",
    build_inputs=("args/code-review.txt", "prompts/code-review.core.md"),
    action_ref="a26b07d8",
    guards=("draft", "fork"),
    keep_pr_head=True,
)
_PROMPT: str = "Review the PR.\nRUN CONTEXT:\n- PR: 7\n"
_REAL_FETCH_CI_POSTED = compare.fetch_ci_posted


@dataclass
class Pipeline:
    """Fakes for every side-effecting call the replay makes."""

    tmp_path: Path
    calls: list[str] = field(default_factory=list)
    failures: dict[str, ErrorResult] = field(default_factory=dict)
    blobs: dict[str, str] = field(default_factory=lambda: {"base1": "base", "merge1": "base"})
    pr: dict[str, Any] = field(
        default_factory=lambda: {"baseRefName": "develop", "isDraft": False, "state": "OPEN"}
    )
    failed_guards: list[str] = field(default_factory=list)
    prior_comment_id: int | None = 41
    real_gh: str | None = "/usr/bin/gh"
    job: ReviewJob = _JOB
    changed: list[str] = field(default_factory=lambda: ["src/a.py"])
    ci: CiPosted = field(default_factory=lambda: CiPosted(run_id=42, findings=[], verdicts=[]))

    def result(self, *, name: str, value: Any) -> Result[Any]:
        self.calls.append(name)
        return self.failures.get(name) or ok(value)

    @property
    def run_dir(self) -> Path:
        return self.tmp_path / "run"

    @property
    def space(self) -> workspace.Workspace:
        return workspace.Workspace(
            repo_root=self.tmp_path,
            run_dir=self.run_dir,
            checkout=self.run_dir / "checkout",
            scripts=self.run_dir / "scripts",
            base_sha="base1",
        )


@pytest.fixture
def pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Pipeline:
    fake = Pipeline(tmp_path=tmp_path)
    fake.run_dir.mkdir()

    def read_blob(*, repo_root: Path, sha: str, path: str) -> Result[str]:
        return fake.result(name=f"read_blob:{sha}", value=fake.blobs[sha])

    def hygiene(**_: Any) -> Result[str]:
        return fake.result(name="hygiene_post_step", value="patched")

    def code_review(**_: Any) -> list[dict[str, Any]]:
        fake.calls.append("code_review_post_steps")
        return []

    def write_shim(**_: Any) -> Path:
        fake.calls.append("write_shim")
        return fake.run_dir / "bin" / "gh"

    def write_mcp(**_: Any) -> Path:
        fake.calls.append("write_mcp_config")
        return fake.run_dir / "mcp.json"

    def remove(**_: Any) -> Result[None]:
        return fake.result(name="remove_workspace", value=None)

    patches: dict[tuple[Any, str], Any] = {
        (replay, "fetch_pr"): lambda **_: fake.result(name="fetch_pr", value=fake.pr),
        (replay, "evaluate_guards"): lambda **_: fake.failed_guards,
        (replay, "load_review_job"): lambda **_: fake.result(
            name="load_review_job", value=fake.job
        ),
        (workspace, "fetch_refs"): lambda **_: fake.result(name="fetch_refs", value=_REFS),
        (workspace, "changed_files"): lambda **_: fake.result(
            name="changed_files", value=fake.changed
        ),
        (compare, "fetch_ci_posted"): lambda **_: fake.result(
            name="fetch_ci_posted", value=fake.ci
        ),
        (post_steps, "post_replica"): lambda **_: fake.result(
            name="post_replica", value="https://github.com/owner/name/pull/7#issuecomment-1"
        ),
        (workspace, "read_blob"): read_blob,
        (workspace, "require_base_scripts"): lambda **_: fake.result(
            name="require_base_scripts", value=None
        ),
        (workspace, "run_dir_for"): lambda **_: fake.run_dir,
        (workspace, "create_workspace"): lambda **_: fake.result(
            name="create_workspace", value=fake.space
        ),
        (workspace, "apply_rules"): lambda **_: fake.result(name="apply_rules", value=None),
        (workspace, "gather_context"): lambda **_: fake.result(name="gather_context", value=None),
        (workspace, "write_prior_hygiene_comment"): lambda **_: fake.result(
            name="write_prior_hygiene_comment", value=fake.prior_comment_id
        ),
        (workspace, "remove_workspace"): remove,
        (replay, "render_inputs"): lambda **_: fake.result(
            name="render_inputs",
            value=RenderedInputs(prompt=_PROMPT, claude_args=["--model", "sonnet"]),
        ),
        (cli_pin, "resolve_cli_version"): lambda **_: fake.result(
            name="resolve_cli_version", value="2.1.0"
        ),
        (cli_pin, "ensure_cli"): lambda **_: fake.result(
            name="ensure_cli", value=Path("/cli/claude")
        ),
        (replay.shutil, "which"): lambda _name: fake.real_gh,
        (gh_shim, "write_shim"): write_shim,
        (runner, "write_mcp_config"): write_mcp,
        (runner, "node_dir"): lambda: None,
        (runner, "resolve_auth"): lambda **_: fake.result(
            name="resolve_auth", value=runner.Auth(env={}, notional=True)
        ),
        (runner, "run_claude"): lambda **_: fake.result(
            name="run_claude", value=[{"type": "result", "total_cost_usd": 0.5, "num_turns": 3}]
        ),
        (post_steps, "hygiene_post_step"): hygiene,
        (post_steps, "code_review_post_steps"): code_review,
    }
    for (target, name), value in patches.items():
        monkeypatch.setattr(target, name, value)
    return fake


def _options(**overrides: Any) -> ReplayOptions:
    values: dict[str, Any] = {
        "pr": 7,
        "workflow": "code-review",
        "repo": "owner/name",
        "repo_root": Path("/repo"),
    }
    return ReplayOptions(**{**values, **overrides})


def _replay(**overrides: Any) -> Result[ReplayOutcome]:
    return run_replay(options=_options(**overrides), now=_NOW)


class TestRenderOnly:
    @pytest.fixture
    def outcome(self, pipeline: Pipeline) -> ReplayOutcome:
        result = _replay(render_only=True)
        assert isinstance(result, SuccessResult), result
        return result.value

    def test_writes_the_prompt(self, outcome: ReplayOutcome) -> None:
        assert outcome.prompt_path.read_text(encoding="utf-8") == _PROMPT

    def test_reports_the_pinned_version(self, outcome: ReplayOutcome) -> None:
        assert outcome.cli_version == "2.1.0"

    def test_elides_the_prompt_in_argv(self, outcome: ReplayOutcome) -> None:
        assert _PROMPT not in outcome.argv

    def test_makes_no_model_call(self, outcome: ReplayOutcome, pipeline: Pipeline) -> None:
        assert "run_claude" not in pipeline.calls

    def test_removes_the_workspace(self, outcome: ReplayOutcome, pipeline: Pipeline) -> None:
        assert "remove_workspace" in pipeline.calls

    def test_reports_failed_guards_instead_of_refusing(self, pipeline: Pipeline) -> None:
        pipeline.failed_guards = ["draft"]

        result = _replay(render_only=True)

        assert isinstance(result, SuccessResult)
        assert result.value.failed_guards == ["draft"]


class TestModelRun:
    @pytest.fixture
    def outcome(self, pipeline: Pipeline) -> ReplayOutcome:
        result = _replay()
        assert isinstance(result, SuccessResult), result
        return result.value

    def test_runs_the_code_review_post_steps(
        self, outcome: ReplayOutcome, pipeline: Pipeline
    ) -> None:
        assert "code_review_post_steps" in pipeline.calls

    def test_writes_the_report(self, outcome: ReplayOutcome, pipeline: Pipeline) -> None:
        assert (pipeline.run_dir / "report.md").read_text(encoding="utf-8") == outcome.report

    def test_labels_subscription_cost_notional(self, outcome: ReplayOutcome) -> None:
        assert outcome.notional is True

    def test_installs_the_shim_and_mcp_config(
        self, outcome: ReplayOutcome, pipeline: Pipeline
    ) -> None:
        assert {"write_shim", "write_mcp_config"} <= set(pipeline.calls)


class TestTriggerFilter:
    @pytest.fixture
    def filtered(self, pipeline: Pipeline) -> Pipeline:
        pipeline.job = replace(_JOB, paths=("**/*.py",))
        return pipeline

    def test_unfiltered_workflow_lists_no_files(self, pipeline: Pipeline) -> None:
        result = _replay(render_only=True)

        assert isinstance(result, SuccessResult)
        assert result.value.trigger_warning is None
        assert "changed_files" not in pipeline.calls

    def test_matching_file_raises_no_warning(self, filtered: Pipeline) -> None:
        result = _replay(render_only=True)

        assert isinstance(result, SuccessResult)
        assert result.value.trigger_warning is None

    def test_warns_when_ci_would_not_trigger(self, filtered: Pipeline) -> None:
        filtered.changed = ["README.md", "docs/a.md"]

        result = _replay()

        assert isinstance(result, SuccessResult)
        assert result.value.trigger_warning == (
            "none of PR #7's 2 changed files match the code-review workflow's paths filter; "
            "CI would never have triggered it"
        )
        assert "run_claude" in filtered.calls

    def test_unlisted_files_only_log(
        self, filtered: Pipeline, caplog: pytest.LogCaptureFixture
    ) -> None:
        filtered.failures["changed_files"] = err("diff broke")

        with caplog.at_level(logging.WARNING, logger=replay.__name__):
            result = _replay(render_only=True)

        assert isinstance(result, SuccessResult)
        assert result.value.trigger_warning is None
        assert "could not list PR #7's changed files: diff broke" in caplog.text


class TestPost:
    def test_dry_run_posts_nothing(self, pipeline: Pipeline) -> None:
        result = _replay()

        assert isinstance(result, SuccessResult)
        assert result.value.posted_url is None
        assert "post_replica" not in pipeline.calls

    def test_posts_the_marked_replica(self, pipeline: Pipeline) -> None:
        result = _replay(post=True)

        assert isinstance(result, SuccessResult)
        assert result.value.posted_url == "https://github.com/owner/name/pull/7#issuecomment-1"
        body = (pipeline.run_dir / "replica-comment.md").read_text(encoding="utf-8")
        assert body.endswith(f"{LOCAL_REPLICA_MARKER}\n")

    def test_failed_post_names_the_run_dir(self, pipeline: Pipeline) -> None:
        pipeline.failures["post_replica"] = err("forbidden")

        result = _replay(post=True)

        assert isinstance(result, ErrorResult)
        assert (result.error, result.details["run_dir"]) == ("forbidden", str(pipeline.run_dir))
        assert (pipeline.run_dir / "report.md").is_file()


class TestCompareCi:
    def test_appends_the_comparison(self, pipeline: Pipeline) -> None:
        result = _replay(compare_ci=42)

        assert isinstance(result, SuccessResult)
        assert "### Compared with CI run 42" in (result.value.report or "")
        assert "| (no inline findings on either side) | | |" in (result.value.report or "")

    def test_failed_fetch_keeps_the_report(self, pipeline: Pipeline) -> None:
        pipeline.failures["fetch_ci_posted"] = err("run not found")

        result = _replay(compare_ci=42)

        assert isinstance(result, SuccessResult)
        assert "- Comparison unavailable: run not found" in (result.value.report or "")

    def test_report_is_on_disk_with_the_comparison(self, pipeline: Pipeline) -> None:
        result = _replay(compare_ci=42)

        assert isinstance(result, SuccessResult)
        assert (pipeline.run_dir / "report.md").read_text(encoding="utf-8") == result.value.report

    def test_not_fetched_without_the_flag(self, pipeline: Pipeline) -> None:
        _replay()

        assert "fetch_ci_posted" not in pipeline.calls


_CI_RUN: str = json.dumps(
    {
        "head_sha": "head1",
        "run_started_at": "2026-10-31T12:00:00Z",
        "updated_at": "2026-10-31T12:10:00Z",
    }
)


class TestMalformedCiData:
    @pytest.fixture(
        params=[
            {"line": "three", "created_at": "2026-10-31T12:05:00Z"},
            {"line": 3, "created_at": "yesterday"},
        ],
        ids=["line", "timestamp"],
    )
    def result(
        self,
        request: pytest.FixtureRequest,
        pipeline: Pipeline,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Result[ReplayOutcome]:
        comment = {"path": "a.py", "body": "WARNING", "commit": "head1", "bot": True}
        replies = {
            "runs": _CI_RUN,
            "comments": json.dumps({**comment, **request.param}) + "\n",
            "reviews": "",
        }

        def fake_run(*, args: list[str], timeout: float) -> Result[str]:
            url = next(arg for arg in args if arg.startswith("repos/"))
            return ok(next(reply for key, reply in replies.items() if key in url))

        monkeypatch.setattr(compare, "fetch_ci_posted", _REAL_FETCH_CI_POSTED)
        monkeypatch.setattr(compare, "run_checked", fake_run)
        return _replay(compare_ci=42)

    def test_reports_the_comparison_unavailable(self, result: Result[ReplayOutcome]) -> None:
        assert isinstance(result, SuccessResult)
        assert "- Comparison unavailable: CI run 42 posted" in (result.value.report or "")

    def test_keeps_the_report_on_disk(
        self, result: Result[ReplayOutcome], pipeline: Pipeline
    ) -> None:
        assert isinstance(result, SuccessResult)
        assert (pipeline.run_dir / "report.md").read_text(encoding="utf-8") == result.value.report


class TestHygiene:
    def test_replays_the_posting_step(self, pipeline: Pipeline) -> None:
        result = _replay(workflow="hygiene")

        assert isinstance(result, SuccessResult)
        assert "hygiene_post_step" in pipeline.calls

    def test_skips_the_code_review_post_steps(self, pipeline: Pipeline) -> None:
        _replay(workflow="hygiene")

        assert "code_review_post_steps" not in pipeline.calls


class TestWorkflowSource:
    @pytest.fixture
    def differing(self, pipeline: Pipeline) -> Pipeline:
        pipeline.blobs["merge1"] = "pr"
        return pipeline

    @pytest.mark.parametrize(("rules", "expected"), [("base", "base"), ("head", "pr")])
    def test_rules_pick_the_workflow_copy(
        self,
        differing: Pipeline,
        monkeypatch: pytest.MonkeyPatch,
        rules: str,
        expected: str,
    ) -> None:
        seen: list[str] = []

        def load(*, workflow_text: str) -> Result[ReviewJob]:
            seen.append(workflow_text)
            return ok(_JOB)

        monkeypatch.setattr(replay, "load_review_job", load)

        _replay(render_only=True, rules=rules)

        assert seen == [expected]

    def test_warns_when_the_pr_edits_its_workflow(
        self, differing: Pipeline, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=replay.__name__):
            _replay(render_only=True)

        assert "differs from the base branch" in caplog.text


class TestRefusals:
    def test_failed_guard_refuses_a_model_run(self, pipeline: Pipeline) -> None:
        pipeline.failed_guards = ["fork"]

        result = _replay()

        assert isinstance(result, ErrorResult)
        assert result.details["failed_guards"] == ["fork"]

    def test_missing_gh_refuses(self, pipeline: Pipeline) -> None:
        pipeline.real_gh = None

        result = _replay()

        assert isinstance(result, ErrorResult)
        assert "gh is not on PATH" in result.error

    @pytest.mark.parametrize(
        "step",
        [
            "fetch_pr",
            "fetch_refs",
            "read_blob:base1",
            "read_blob:merge1",
            "load_review_job",
            "require_base_scripts",
        ],
    )
    def test_early_failure_returns_before_a_workspace_exists(
        self, pipeline: Pipeline, step: str
    ) -> None:
        pipeline.failures[step] = err(f"{step} broke")

        result = _replay()

        assert isinstance(result, ErrorResult)
        assert result.error == f"{step} broke"
        assert "create_workspace" not in pipeline.calls

    def test_workspace_failure_names_the_run_dir(self, pipeline: Pipeline) -> None:
        pipeline.failures["create_workspace"] = err("worktree add failed")

        result = _replay()

        assert isinstance(result, ErrorResult)
        assert result.details["run_dir"] == str(pipeline.run_dir)

    @pytest.mark.parametrize(
        ("step", "workflow"),
        [
            ("apply_rules", "code-review"),
            ("gather_context", "code-review"),
            ("write_prior_hygiene_comment", "hygiene"),
            ("render_inputs", "code-review"),
            ("resolve_cli_version", "code-review"),
            ("ensure_cli", "code-review"),
            ("resolve_auth", "code-review"),
            ("run_claude", "code-review"),
            ("hygiene_post_step", "hygiene"),
        ],
    )
    def test_failure_inside_the_workspace_names_the_run_dir_and_cleans_up(
        self, pipeline: Pipeline, step: str, workflow: str
    ) -> None:
        pipeline.failures[step] = err(f"{step} broke")

        result = _replay(workflow=workflow)

        assert isinstance(result, ErrorResult)
        assert (result.error, result.details["run_dir"]) == (
            f"{step} broke",
            str(pipeline.run_dir),
        )
        assert pipeline.calls[-1] == "remove_workspace"


class TestCleanup:
    def test_keep_workspace_leaves_the_checkout(self, pipeline: Pipeline) -> None:
        _replay(render_only=True, keep_workspace=True)

        assert "remove_workspace" not in pipeline.calls

    def test_failed_removal_only_warns(
        self, pipeline: Pipeline, caplog: pytest.LogCaptureFixture
    ) -> None:
        pipeline.failures["remove_workspace"] = err("busy")

        with caplog.at_level(logging.WARNING, logger=replay.__name__):
            result = _replay(render_only=True)

        assert isinstance(result, SuccessResult)
        assert "could not remove" in caplog.text


class TestDetection:
    @pytest.fixture
    def answers(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Result[str]]:
        answers: dict[str, Result[str]] = {
            "gh": ok("owner/name\n"),
            "git": ok("/repo\n"),
        }
        monkeypatch.setattr(replay, "run_checked", lambda *, args, **_: answers[args[0]])
        return answers

    def test_detect_repo(self, answers: dict[str, Result[str]]) -> None:
        result = replay.detect_repo()

        assert isinstance(result, SuccessResult)
        assert result.value == "owner/name"

    def test_detect_repo_root(self, answers: dict[str, Result[str]]) -> None:
        result = replay.detect_repo_root()

        assert isinstance(result, SuccessResult)
        assert result.value == Path("/repo")

    @pytest.mark.parametrize(
        ("tool", "detect"),
        [("gh", replay.detect_repo), ("git", replay.detect_repo_root)],
        ids=["repo", "repo-root"],
    )
    def test_detection_failure_passes_through(
        self, answers: dict[str, Result[str]], tool: str, detect: Any
    ) -> None:
        answers[tool] = err(f"{tool} failed")

        result = detect()

        assert isinstance(result, ErrorResult)
        assert result.error == f"{tool} failed"
