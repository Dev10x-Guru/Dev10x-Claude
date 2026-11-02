"""A switched-off Claude review reads as disabled, not skipped (GH-1764)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import pytest

from dev10x.coding.skills.monitor import ci_check_status as impl

_LABELS = "pr view 7 --repo o/r --json labels"
_REPO_VAR = "api repos/o/r/actions/variables/CLAUDE_REVIEW_ENABLED"
_ORG_VARS = "api repos/o/r/actions/organization-variables?per_page=100"


@dataclass
class FakeGh:
    """Answers keyed by the gh argv (without `--jq`); unknown argv fails with `failure`."""

    answers: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    failure: str = "HTTP 404: Not Found"

    def __call__(self, argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        key = " ".join(argv[1 : argv.index("--jq")])
        self.calls.append(key)
        stdout = self.answers.get(key)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0 if stdout is not None else 1,
            stdout=stdout or "",
            stderr="" if stdout is not None else self.failure,
        )


@pytest.fixture
def gh(monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    fake = FakeGh()
    monkeypatch.setattr(impl.subprocess, "run", fake)
    return fake


class TestClaudeReviewSwitch:
    @pytest.mark.parametrize(
        ("answers", "expected"),
        [
            ({_LABELS: "bug\nskip-claude-review\n"}, "label:skip-claude-review"),
            (
                {_LABELS: "bug\n", _REPO_VAR: "false\n"},
                "repo-variable:CLAUDE_REVIEW_ENABLED=false",
            ),
            ({_LABELS: "", _ORG_VARS: "false\n"}, "org-variable:CLAUDE_REVIEW_ENABLED=false"),
            ({_LABELS: "", _REPO_VAR: "true\n", _ORG_VARS: "false\n"}, None),
            ({_LABELS: "", _ORG_VARS: "true\n"}, None),
            ({_LABELS: ""}, None),
            ({}, None),
        ],
        ids=[
            "label",
            "repo-variable",
            "org-variable",
            "repo-value-wins-over-org",
            "org-enabled",
            "unset",
            "unreadable",
        ],
    )
    def test_resolves_the_switch(
        self, gh: FakeGh, answers: dict[str, str], expected: str | None
    ) -> None:
        gh.answers = answers

        assert impl.claude_review_switch(pr_number=7, repo="o/r") == expected

    @pytest.mark.parametrize(
        "failure",
        [subprocess.TimeoutExpired(cmd="gh", timeout=30), FileNotFoundError("gh")],
        ids=["timeout", "no-gh"],
    )
    def test_a_gh_that_cannot_run_reads_as_unknown(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        failure: Exception,
    ) -> None:
        def raise_failure(argv: list[str], **_: object) -> None:
            raise failure

        monkeypatch.setattr(impl.subprocess, "run", raise_failure)

        assert impl.claude_review_switch(pr_number=7, repo="o/r") is None
        assert "[review-switch]" in capsys.readouterr().err

    def test_an_unset_variable_404_is_silent(
        self, gh: FakeGh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gh.answers = {_LABELS: ""}

        impl.claude_review_switch(pr_number=7, repo="o/r")

        assert capsys.readouterr().err == ""

    def test_a_forbidden_read_is_reported(
        self, gh: FakeGh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gh.failure = "HTTP 403: Forbidden"

        assert impl.claude_review_switch(pr_number=7, repo="o/r") is None
        assert "HTTP 403" in capsys.readouterr().err

    def test_the_label_short_circuits_the_variable_reads(self, gh: FakeGh) -> None:
        gh.answers = {_LABELS: "skip-claude-review\n"}

        impl.claude_review_switch(pr_number=7, repo="o/r")

        assert gh.calls == [_LABELS]


class TestMarkDisabledReviews:
    _RESULT: dict = {"skipping_checks": ["claude-review", "hygiene-review", "deploy"]}

    def test_names_only_the_review_checks(self) -> None:
        result = impl.mark_disabled_reviews(result=self._RESULT, reason="label:skip-claude-review")

        assert result["disabled_checks"] == ["claude-review", "hygiene-review"]
        assert result["review_disabled_reason"] == "label:skip-claude-review"
        assert result["skipping_checks"] == self._RESULT["skipping_checks"]

    def test_no_switch_leaves_them_skipped(self) -> None:
        result = impl.mark_disabled_reviews(result=self._RESULT, reason=None)

        assert result["disabled_checks"] == []
        assert "review_disabled_reason" not in result

    def test_a_switch_without_a_skipped_review_names_nothing(self) -> None:
        result = impl.mark_disabled_reviews(
            result={"skipping_checks": ["deploy"]}, reason="label:skip-claude-review"
        )

        assert result["disabled_checks"] == []
        assert "review_disabled_reason" not in result


class TestProbeOnce:
    @pytest.fixture(autouse=True)
    def _pr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(impl, "get_pr_state", lambda **_: impl.PrState(mergeable="MERGEABLE"))
        monkeypatch.setattr(impl, "runs_running_at_head", lambda **_: [])

    def _checks(self, monkeypatch: pytest.MonkeyPatch, *, review_bucket: str) -> None:
        checks = [
            {"name": "build", "bucket": "pass", "required": True},
            {"name": "claude-review", "bucket": review_bucket, "required": False},
        ]
        monkeypatch.setattr(
            impl,
            "get_annotated_checks",
            lambda **_: impl.ChecksRead(checks=checks, source=impl.SOURCE_GH_CLI),
        )

    def test_a_skipped_review_is_checked_against_the_switch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._checks(monkeypatch, review_bucket="skipping")
        monkeypatch.setattr(impl, "claude_review_switch", lambda **_: "label:skip-claude-review")

        result = impl.probe_once(pr_number=7, repo="o/r")

        assert result["disabled_checks"] == ["claude-review"]
        assert result["review_disabled_reason"] == "label:skip-claude-review"

    def test_a_review_that_ran_costs_no_switch_lookup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._checks(monkeypatch, review_bucket="pass")
        monkeypatch.setattr(
            impl, "claude_review_switch", lambda **_: pytest.fail("switch must not be read")
        )

        result = impl.probe_once(pr_number=7, repo="o/r")

        assert result["disabled_checks"] == []
