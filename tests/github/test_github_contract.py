"""Live GitHub API contract tests for dev10x.github (GH-398).

Contract class: contract
  These tests call the real GitHub API against a known fixture PR and assert
  the returned shape. They are gated on GITHUB_TOKEN — skipped locally
  without one, run in CI on a schedule.

  The static-lint tier (test_graphql_static.py) catches invalid GraphQL
  field selections without any live call. This tier additionally catches
  REST response-shape drift: fields removed from or renamed in the real
  GitHub API response.

Fixture:
  PR #394 in Dev10x-Guru/Dev10x-Claude — a merged PR that closed GH-386
  (Parts 2 & 3). It is stable (merged), public, and has review comments,
  making it suitable for exercising pr_get, pr_comments, and
  resolve_review_thread's read paths.

See docs/github-contract-test-boundary.md for the full boundary doc.
"""

from __future__ import annotations

import os

import pytest

# Skip the entire module when GITHUB_TOKEN is absent.
pytestmark = pytest.mark.skipif(
    not os.getenv("GITHUB_TOKEN"),
    reason="GITHUB_TOKEN not set — live contract tests skipped",
)

gh = pytest.importorskip("dev10x.github", reason="dev10x not installed")

# ---------------------------------------------------------------------------
# Fixture constants — stable merged PR in this repo (GH-386 Parts 2 & 3).
# Changing this PR requires updating the assertions below.
# ---------------------------------------------------------------------------
_FIXTURE_REPO = "Dev10x-Guru/Dev10x-Claude"
_FIXTURE_PR_NUMBER = 394


class TestPrGetContract:
    """contract-class: contract

    Calls pr_get against the fixture PR and asserts that the required fields
    are present and have the expected types/values.
    """

    @pytest.mark.asyncio
    async def test_pr_get_returns_success(self) -> None:
        """pr_get must succeed for a known-good merged PR."""
        result = await gh.pr_get(
            number=_FIXTURE_PR_NUMBER,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult), (
            f"pr_get({_FIXTURE_PR_NUMBER!r}, repo={_FIXTURE_REPO!r}) returned an error: {result}"
        )

    @pytest.mark.asyncio
    async def test_pr_get_required_fields_present(self) -> None:
        """pr_get response must contain all required top-level fields."""
        result = await gh.pr_get(
            number=_FIXTURE_PR_NUMBER,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult)
        payload = result.value
        required_fields = {
            "number",
            "title",
            "state",
            "url",
        }
        missing = required_fields - payload.keys()
        assert not missing, (
            f"pr_get response missing required fields: {sorted(missing)}. "
            f"Returned keys: {sorted(payload.keys())}"
        )

    @pytest.mark.asyncio
    async def test_pr_get_gh668_state_fields_present(self) -> None:
        """pr_get must expose isDraft/mergeable/reviewDecision/reviewRequests (GH-668).

        These let gh-pr-merge Checks 3/4/7 and verify-acc-dod read draft,
        mergeability, and approval state from the routed MCP tool instead
        of the hook-blocked raw ``gh pr view``.
        """
        result = await gh.pr_get(
            number=_FIXTURE_PR_NUMBER,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult)
        payload = result.value
        gh668_fields = {
            "isDraft",
            "mergeable",
            "reviewDecision",
            "reviewRequests",
        }
        missing = gh668_fields - payload.keys()
        assert not missing, (
            f"pr_get response missing GH-668 fields: {sorted(missing)}. "
            f"Returned keys: {sorted(payload.keys())}. "
            "gh-pr-get.sh must request these in its --json field list."
        )

    @pytest.mark.asyncio
    async def test_pr_get_number_matches_fixture(self) -> None:
        """pr_get response number must match the requested PR number."""
        result = await gh.pr_get(
            number=_FIXTURE_PR_NUMBER,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult)
        payload = result.value
        assert payload.get("number") == _FIXTURE_PR_NUMBER, (
            f"pr_get returned number {payload.get('number')!r}, "
            f"expected {_FIXTURE_PR_NUMBER!r}. "
            "Response-shape drift: 'number' field renamed or removed?"
        )

    @pytest.mark.asyncio
    async def test_pr_get_state_is_merged(self) -> None:
        """pr_get fixture PR #394 is merged — state must reflect that.

        GitHub returns state='CLOSED' (via gh pr view) or state='closed' (REST)
        for merged PRs, and sets mergedAt to a non-null value.
        """
        result = await gh.pr_get(
            number=_FIXTURE_PR_NUMBER,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult)
        payload = result.value
        state = str(payload.get("state", "")).upper()
        assert state in {"CLOSED", "MERGED"}, (
            f"Fixture PR #{_FIXTURE_PR_NUMBER} is merged but pr_get returned "
            f"state={payload.get('state')!r}. If the field was renamed, update "
            "the gh-pr-get.sh script and this assertion."
        )

    @pytest.mark.asyncio
    async def test_pr_get_merged_field_absent_or_falsy(self) -> None:
        """pr_get must NOT trigger an error via the invalid 'merged' field (GH-329).

        The GH-329 post-mortem found that 'merged' is not a valid
        'gh pr view --json' field. The fix uses 'mergedAt' instead.
        This live test confirms the command succeeds without the invalid field.
        """
        result = await gh.pr_get(
            number=_FIXTURE_PR_NUMBER,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult), (
            "pr_get returned an error. If the error message mentions 'merged' "
            "or 'unknown JSON field', the GH-329 regression has reappeared."
        )


class TestPrCommentsContract:
    """contract-class: contract

    Calls pr_comments(action='list') against the fixture PR and asserts the
    returned shape. The fixture PR is merged so its comment list is stable.
    """

    @pytest.mark.asyncio
    async def test_pr_comments_list_returns_success(self) -> None:
        """pr_comments list action must succeed for a known-good merged PR."""
        result = await gh.pr_comments(
            action="list",
            pr_number=_FIXTURE_PR_NUMBER,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult), (
            f"pr_comments(action='list', pr_number={_FIXTURE_PR_NUMBER!r}) "
            f"returned an error: {result}"
        )

    @pytest.mark.asyncio
    async def test_pr_comments_list_returns_value_key(self) -> None:
        """pr_comments list response must contain a 'value' key wrapping the list.

        The REST endpoint returns a JSON array; the implementation wraps it
        in {'value': [...]} to satisfy the Mapping contract (ADR-0009).
        """
        result = await gh.pr_comments(
            action="list",
            pr_number=_FIXTURE_PR_NUMBER,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult)
        payload = result.value
        assert "value" in payload, (
            f"pr_comments list response missing 'value' key. "
            f"Got keys: {sorted(payload.keys())}. "
            "If the wrapping contract changed, update ADR-0009 and this assertion."
        )
        assert isinstance(payload["value"], list), (
            f"pr_comments list 'value' must be a list, got {type(payload['value'])!r}."
        )

    @pytest.mark.asyncio
    async def test_pr_comments_list_items_have_expected_shape(self) -> None:
        """Each comment in the list must have the standard GitHub REST shape fields.

        The known-valid fields are those present in the GitHub REST API response
        for GET /repos/{owner}/{repo}/pulls/{pull_number}/comments.
        """
        result = await gh.pr_comments(
            action="list",
            pr_number=_FIXTURE_PR_NUMBER,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult)
        comments = result.value.get("value", [])
        if not comments:
            pytest.skip(
                f"PR #{_FIXTURE_PR_NUMBER} has no review comments — "
                "cannot assert comment shape. Choose a fixture PR with at least one comment."
            )
        first = comments[0]
        required_comment_fields = {"id", "body", "path", "url"}
        missing = required_comment_fields - first.keys()
        assert not missing, (
            f"First comment in pr_comments list is missing required fields: "
            f"{sorted(missing)}. Got keys: {sorted(first.keys())}. "
            "Response-shape drift from GitHub REST API?"
        )

    @pytest.mark.asyncio
    async def test_pr_comments_unresolved_threads_returns_success(self) -> None:
        """pr_comments with unresolved_only=True must succeed against the real API.

        This exercises the GraphQL _list_unresolved_threads path which was the
        site of the GH-329 pullRequestReviewThread bug.
        """
        result = await gh.pr_comments(
            action="list",
            pr_number=_FIXTURE_PR_NUMBER,
            unresolved_only=True,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult), (
            f"pr_comments(action='list', unresolved_only=True) returned an error: {result}. "
            "This exercises the GraphQL reviewThreads path (GH-329 fix)."
        )

    @pytest.mark.asyncio
    async def test_pr_comments_unresolved_threads_response_shape(self) -> None:
        """pr_comments unresolved_only response must have the normalized shape.

        The _list_unresolved_threads function returns
        {'unresolved_threads': [...], 'count': N}.
        """
        result = await gh.pr_comments(
            action="list",
            pr_number=_FIXTURE_PR_NUMBER,
            unresolved_only=True,
            repo=_FIXTURE_REPO,
        )
        from dev10x.domain.common.result import SuccessResult

        assert isinstance(result, SuccessResult)
        payload = result.value
        assert "unresolved_threads" in payload, (
            f"pr_comments unresolved_only response missing 'unresolved_threads' key. "
            f"Got keys: {sorted(payload.keys())}"
        )
        assert "count" in payload, (
            f"pr_comments unresolved_only response missing 'count' key. "
            f"Got keys: {sorted(payload.keys())}"
        )
        assert isinstance(payload["unresolved_threads"], list), (
            f"'unresolved_threads' must be a list, got {type(payload['unresolved_threads'])!r}."
        )
        assert payload["count"] == len(payload["unresolved_threads"]), (
            f"'count' ({payload['count']}) must equal len('unresolved_threads') "
            f"({len(payload['unresolved_threads'])})."
        )
