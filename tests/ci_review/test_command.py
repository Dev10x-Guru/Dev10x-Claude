from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from dev10x.ci_review import replay
from dev10x.ci_review.replay import ReplayOptions, ReplayOutcome
from dev10x.commands.ci_review import ci_review
from dev10x.core.domain.common.result import Result as DomainResult
from dev10x.core.domain.common.result import err, ok


class Replays:
    def __init__(self) -> None:
        self.options: list[ReplayOptions] = []
        self.result: DomainResult[ReplayOutcome] | None = None
        self.report: str | None = None
        self.trigger_warning: str | None = None
        self.posted_url: str | None = None

    def __call__(self, *, options: ReplayOptions) -> DomainResult[ReplayOutcome]:
        self.options.append(options)
        return self.result or ok(self._outcome(options=options))

    def _outcome(self, *, options: ReplayOptions) -> ReplayOutcome:
        return ReplayOutcome(
            workflow=options.workflow,
            run_dir=Path("/runs") / options.workflow,
            failed_guards=[],
            cli_version="2.1.0",
            argv=["claude", "-p", "<prompt: 3 lines>"],
            prompt_path=Path("/runs") / options.workflow / "prompt.md",
            report=self.report,
            trigger_warning=self.trigger_warning,
            posted_url=self.posted_url,
        )


@pytest.fixture
def replays(monkeypatch: pytest.MonkeyPatch) -> Replays:
    fake = Replays()
    monkeypatch.setattr(replay, "run_replay", fake)
    monkeypatch.setattr("dev10x.ci_review.run_replay", fake)
    monkeypatch.setattr(replay, "detect_repo_root", lambda: ok(Path("/repo")))
    monkeypatch.setattr(replay, "detect_repo", lambda: ok("owner/name"))
    return fake


def _invoke(*args: str) -> Result:
    return CliRunner().invoke(ci_review, list(args))


class TestRenderOnly:
    @pytest.fixture
    def result(self, replays: Replays) -> Result:
        return _invoke("--pr", "7", "--render-only")

    def test_exits_zero(self, result: Result) -> None:
        assert result.exit_code == 0, result.output

    def test_prints_the_resolved_inputs(self, result: Result) -> None:
        assert "claude cli: 2.1.0" in result.output
        assert "prompt: /runs/code-review/prompt.md" in result.output

    def test_passes_the_options(self, result: Result, replays: Replays) -> None:
        (options,) = replays.options

        assert (options.pr, options.repo, options.repo_root, options.render_only) == (
            7,
            "owner/name",
            Path("/repo"),
            True,
        )


def test_all_runs_hygiene_then_code_review(replays: Replays) -> None:
    _invoke("--pr", "7", "--workflow", "all")

    assert [options.workflow for options in replays.options] == ["hygiene", "code-review"]


def test_explicit_repo_skips_detection(replays: Replays, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replay, "detect_repo", lambda: err("must not be called"))

    result = _invoke("--pr", "7", "--repo", "other/repo")

    assert result.exit_code == 0
    assert replays.options[0].repo == "other/repo"


def test_prints_the_report(replays: Replays) -> None:
    replays.report = "### Claude usage"

    result = _invoke("--pr", "7")

    assert "### Claude usage" in result.output


class TestPostAndCompare:
    def test_passes_the_flags(self, replays: Replays) -> None:
        result = _invoke("--pr", "7", "--post", "--compare-ci", "42")

        assert result.exit_code == 0, result.output
        assert (replays.options[0].post, replays.options[0].compare_ci) == (True, 42)

    def test_defaults_keep_it_local(self, replays: Replays) -> None:
        _invoke("--pr", "7")

        assert (replays.options[0].post, replays.options[0].compare_ci) == (False, None)

    def test_prints_the_posted_url(self, replays: Replays) -> None:
        replays.posted_url = "https://github.com/owner/name/pull/7#issuecomment-1"

        result = _invoke("--pr", "7", "--post")

        assert "posted: https://github.com/owner/name/pull/7#issuecomment-1" in result.output

    def test_prints_the_trigger_warning(self, replays: Replays) -> None:
        replays.trigger_warning = "CI would never have triggered it"

        result = _invoke("--pr", "7", "--render-only")

        assert "⚠️ CI would never have triggered it" in result.output

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (("--render-only", "--post"), "need a model run"),
            (("--render-only", "--compare-ci", "42"), "need a model run"),
            (("--workflow", "hygiene", "--compare-ci", "42"), "use --workflow code-review"),
            (("--workflow", "all", "--compare-ci", "42"), "use --workflow code-review"),
        ],
        ids=["render-post", "render-compare", "hygiene-compare", "all-compare"],
    )
    def test_refuses_combinations(
        self, replays: Replays, args: tuple[str, ...], message: str
    ) -> None:
        result = _invoke("--pr", "7", *args)

        assert result.exit_code == 2
        assert message in result.output
        assert replays.options == []


class TestFailures:
    @pytest.mark.parametrize("target", ["detect_repo_root", "detect_repo"])
    def test_detection_failure_exits_one(
        self, replays: Replays, monkeypatch: pytest.MonkeyPatch, target: str
    ) -> None:
        monkeypatch.setattr(replay, target, lambda: err(f"{target} failed"))

        result = _invoke("--pr", "7")

        assert result.exit_code == 1
        assert f"{target} failed" in result.output

    def test_replay_failure_prints_details(self, replays: Replays) -> None:
        replays.result = err("CI would skip", run_dir="/runs/x", stderr="boom")

        result = _invoke("--pr", "7")

        assert result.exit_code == 1
        assert "run_dir: /runs/x" in result.output
        assert "stderr: boom" in result.output
