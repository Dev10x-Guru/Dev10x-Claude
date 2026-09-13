"""A derived `Fixes:` trailer is not a landed one (GH-1274).

GH-1256 taught `create_pr` to derive a reference from `issue_id`, but
nothing asserted one reached the created PR. `has_fixes_trailer` existed
and was referenced only by its own tests. A body without the trailer is
rejected by the hygiene bot and closes no issue on merge, and the caller
had to know to re-read the body by hand.

The check is a genuine read-back rather than a local assertion on the
text we sent: the MCP transport can drop a write and return nothing to
say so, so only a fresh `pr_get` proves what GitHub holds.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x import github as gh
from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok
from dev10x.skills.merge.fixes_scope import reconcile_link_closure

_JOB_STORY = (
    "**When** a PR is opened, **the maintainer wants** the trailer to be "
    "there, **so the reviewer can** trust the link."
)


def _created() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="https://github.com/owner/repo/pull/42\n42",
        stderr="",
    )


@pytest.mark.usefixtures("stub_feature_branch")
class TestCreatePrFixesTrailerReadback:
    @pytest.mark.asyncio
    @patch("dev10x.github.pr_get", new_callable=AsyncMock)
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_a_body_without_a_trailer_is_refused(
        self, mock_run: AsyncMock, mock_pr_get: AsyncMock
    ) -> None:
        mock_run.return_value = _created()
        mock_pr_get.return_value = ok({"body": "Just a story, no trailer"})

        result = await gh.create_pr(title="t", job_story=_JOB_STORY, issue_id="GH-1")

        assert isinstance(result, ErrorResult)

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_get", new_callable=AsyncMock)
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_the_refusal_names_the_pr_it_already_opened(
        self, mock_run: AsyncMock, mock_pr_get: AsyncMock
    ) -> None:
        # The PR exists by the time the check runs. An error that does
        # not identify it strands it — and invites a duplicate.
        mock_run.return_value = _created()
        mock_pr_get.return_value = ok({"body": "Just a story, no trailer"})

        result = await gh.create_pr(title="t", job_story=_JOB_STORY, issue_id="GH-1")

        assert isinstance(result, ErrorResult)
        assert "42" in result.error
        assert "https://github.com/owner/repo/pull/42" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_get", new_callable=AsyncMock)
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_the_refusal_points_at_the_repair(
        self, mock_run: AsyncMock, mock_pr_get: AsyncMock
    ) -> None:
        mock_run.return_value = _created()
        mock_pr_get.return_value = ok({"body": "Just a story, no trailer"})

        result = await gh.create_pr(title="t", job_story=_JOB_STORY, issue_id="GH-1")

        assert isinstance(result, ErrorResult)
        assert "update_pr" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_get", new_callable=AsyncMock)
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_a_landed_trailer_is_reported_verified(
        self, mock_run: AsyncMock, mock_pr_get: AsyncMock
    ) -> None:
        mock_run.return_value = _created()
        mock_pr_get.return_value = ok({"body": "Story\n\nFixes: #1"})

        result = await gh.create_pr(title="t", job_story=_JOB_STORY, issue_id="GH-1")

        assert isinstance(result, SuccessResult)
        assert result.value["fixes_trailer_verified"] is True

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_get", new_callable=AsyncMock)
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_an_explicit_repo_reaches_the_read_back(
        self, mock_run: AsyncMock, mock_pr_get: AsyncMock
    ) -> None:
        # The read-back must resolve the same repository the PR was
        # opened in; dropping `repo` would silently read a same-numbered
        # PR in whichever repo the CWD happens to name.
        mock_run.return_value = _created()
        mock_pr_get.return_value = ok({"body": "Story\n\nFixes: #1"})

        await gh.create_pr(
            title="t",
            job_story=_JOB_STORY,
            issue_id="GH-1",
            repo="owner/repo",
        )

        mock_pr_get.assert_awaited_once_with(number=42, repo="owner/repo")

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_get", new_callable=AsyncMock)
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_the_check_reads_github_not_the_text_we_sent(
        self, mock_run: AsyncMock, mock_pr_get: AsyncMock
    ) -> None:
        # A local assertion would pass here: the arguments carry a
        # reference. Only the read-back sees that GitHub does not.
        mock_run.return_value = _created()
        mock_pr_get.return_value = ok({"body": "no trailer"})

        result = await gh.create_pr(
            title="t",
            job_story=_JOB_STORY,
            issue_id="GH-1",
            fixes_url="https://github.com/owner/repo/issues/1",
        )

        assert isinstance(result, ErrorResult)
        # Pin WHICH PR was read, not just that a read happened: a
        # read-back aimed at the wrong number would verify a body that
        # was never this call's, and pass every other assertion here.
        mock_pr_get.assert_awaited_once_with(number=42, repo=None)

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_get", new_callable=AsyncMock)
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_an_unreadable_readback_warns_instead_of_failing(
        self, mock_run: AsyncMock, mock_pr_get: AsyncMock
    ) -> None:
        # Failing to read the body is not evidence that the body is bad,
        # and the PR is open either way.
        mock_run.return_value = _created()
        mock_pr_get.return_value = err("gh: connection reset")

        result = await gh.create_pr(title="t", job_story=_JOB_STORY, issue_id="GH-1")

        assert isinstance(result, SuccessResult)
        assert result.value["fixes_trailer_verified"] is False
        assert "connection reset" in result.value["warning"]


class TestPostMergeLinkClosure:
    """Did the trailer actually close anything (GH-1274)?

    Observed: one merge closed two of three identical trailers, a later
    session recorded 0 of 7 across two merges, and a third closed two of
    three. Both spellings failed in the 0-of-7 run, so the form is not
    the variable — which is why this reports rather than predicts.
    """

    def test_every_closed_link_is_reported_ok(self) -> None:
        verdict = reconcile_link_closure(
            body="Fixes: #12\nFixes: #14",
            issue_states={12: "CLOSED", 14: "CLOSED"},
        )

        assert verdict.ok
        assert verdict.closed == (12, 14)

    def test_a_straggler_is_named(self) -> None:
        verdict = reconcile_link_closure(
            body="Fixes: #12\nFixes: #14\nFixes: #16",
            issue_states={12: "CLOSED", 14: "CLOSED", 16: "OPEN"},
        )

        assert not verdict.ok
        assert verdict.still_open == (16,)
        assert "GH-16" in verdict.summary()

    def test_an_unread_state_is_never_counted_as_closed(self) -> None:
        # Quietly folding an unread issue into `closed` would recreate
        # the exact silence this check exists to break.
        verdict = reconcile_link_closure(body="Fixes: #12", issue_states={})

        assert verdict.unknown == (12,)
        assert verdict.closed == ()
        assert not verdict.ok

    def test_a_body_with_no_links_is_ok_and_says_so(self) -> None:
        verdict = reconcile_link_closure(body="A story with no trailer", issue_states={})

        assert verdict.ok
        assert "no Fixes:/Closes: links" in verdict.summary()

    @pytest.mark.parametrize("state", ["closed", "Closed", " CLOSED "])
    def test_state_matching_is_case_and_space_insensitive(self, state: str) -> None:
        verdict = reconcile_link_closure(body="Fixes: #12", issue_states={12: state})

        assert verdict.closed == (12,)

    def test_both_trailer_spellings_are_reconciled(self) -> None:
        # The 0-of-7 run used a full URL and a bare #N; missing either
        # would under-report the stragglers.
        verdict = reconcile_link_closure(
            body="Fixes: https://github.com/o/r/issues/12\nFixes: #14",
            issue_states={12: "OPEN", 14: "OPEN"},
        )

        assert verdict.still_open == (12, 14)

    def test_the_summary_counts_against_the_links_found(self) -> None:
        verdict = reconcile_link_closure(
            body="Fixes: #12\nFixes: #14",
            issue_states={12: "CLOSED", 14: "OPEN"},
        )

        assert "of 2 linked issue(s)" in verdict.summary()
