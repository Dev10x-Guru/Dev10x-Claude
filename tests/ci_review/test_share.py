from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.ci_review import post_steps, share
from dev10x.ci_review.report import LOCAL_REPLICA_HEADER, LOCAL_REPLICA_MARKER
from dev10x.ci_review.share import post_finished_run, workflow_of
from dev10x.core.domain.common.result import ErrorResult, Result, SuccessResult, err, ok

_URL: str = "https://github.com/owner/name/pull/7#issuecomment-1"


class Posts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []
        self.result: Result[str] = ok(_URL)

    def __call__(self, *, repo: str, pr: int, body_path: Path) -> Result[str]:
        self.calls.append((repo, pr, body_path.read_text(encoding="utf-8")))
        return self.result


@pytest.fixture
def posts(monkeypatch: pytest.MonkeyPatch) -> Posts:
    fake = Posts()
    monkeypatch.setattr(post_steps, "post_replica", fake)
    return fake


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    path = tmp_path / "owner-name" / "pr-7" / "20261031T120000Z-code-review"
    path.mkdir(parents=True)
    (path / share.REPORT_FILE).write_text("## dev10x ci-review — code-review\n", encoding="utf-8")
    entry = {"kind": "post_step", "step": "summary", "branch": "x", "body": "Looks fine"}
    (path / share.OUTBOX_FILE).write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return path


class TestPostFinishedRun:
    @pytest.fixture
    def result(self, run_dir: Path, posts: Posts) -> Result[str]:
        return post_finished_run(run_dir=run_dir, repo="owner/name", pr=7)

    def test_returns_the_posted_url(self, result: Result[str]) -> None:
        assert result == SuccessResult(value=_URL)

    def test_posts_the_marked_replica_body(self, result: Result[str], posts: Posts) -> None:
        ((repo, pr, body),) = posts.calls

        assert (repo, pr) == ("owner/name", 7)
        assert f"## {LOCAL_REPLICA_HEADER} — code-review" in body
        assert body.rstrip("\n").endswith(LOCAL_REPLICA_MARKER)
        assert "Looks fine" in body

    def test_keeps_the_body_in_the_run_dir(self, result: Result[str], run_dir: Path) -> None:
        assert (run_dir / share.REPLICA_FILE).is_file()


def test_a_run_without_a_report_is_refused(run_dir: Path, posts: Posts) -> None:
    (run_dir / share.REPORT_FILE).unlink()

    result = post_finished_run(run_dir=run_dir, repo="owner/name", pr=7)

    assert isinstance(result, ErrorResult)
    assert "only a finished model run" in result.error
    assert posts.calls == []


def test_a_cut_off_outbox_is_refused(run_dir: Path, posts: Posts) -> None:
    (run_dir / share.OUTBOX_FILE).write_text('{"kind": "post_step", "bo\n', encoding="utf-8")

    result = post_finished_run(run_dir=run_dir, repo="owner/name", pr=7)

    assert isinstance(result, ErrorResult)
    assert "may have been cut off" in result.error
    assert posts.calls == []


def test_a_post_failure_is_returned(run_dir: Path, posts: Posts) -> None:
    posts.result = err("forbidden")

    result = post_finished_run(run_dir=run_dir, repo="owner/name", pr=7)

    assert result == err("forbidden")


class TestWorkflowOf:
    @pytest.mark.parametrize("workflow", ["code-review", "hygiene"])
    def test_reads_the_workflow_from_the_name(self, tmp_path: Path, workflow: str) -> None:
        run_dir = tmp_path / "pr-7" / f"20261031T120000Z-{workflow}"

        assert workflow_of(run_dir=run_dir, pr=7) == SuccessResult(value=workflow)

    @pytest.mark.parametrize(
        ("relative", "message"),
        [
            ("pr-7/checkout", "not a ci-review run directory"),
            ("pr-7/20261031T120000Z-other", "not a ci-review run directory"),
            ("pr-8/20261031T120000Z-hygiene", "not a run of PR #7"),
            ("misc/20261031T120000Z-hygiene", "not a run of PR #7"),
        ],
        ids=["no-stamp", "unknown-workflow", "other-pr", "no-pr-dir"],
    )
    def test_refuses_a_directory_it_cannot_place(
        self, tmp_path: Path, relative: str, message: str
    ) -> None:
        result = workflow_of(run_dir=tmp_path / relative, pr=7)

        assert isinstance(result, ErrorResult)
        assert message in result.error
