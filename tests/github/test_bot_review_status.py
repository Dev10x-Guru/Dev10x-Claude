"""bot_review_status: per-bot reviewed SHA vs PR head (GH-1832)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult, err

from dev10x.coding.github import bot_reviews
from dev10x.coding.github.bot_review_config import normalize_login, resolve_blocking_bots
from dev10x.core.github import _gateway
from dev10x.mcp import server_cli as cli_server
from tests.github.graphql_doubles import completed, write_merge_settings

FIXTURES = Path(__file__).parents[1] / "fixtures" / "bot_review_status"


def _payload(*, name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _pr(*, name: str) -> dict[str, Any]:
    return _payload(name=name)["data"]["repository"]["pullRequest"]


def _author(*, login: str, typename: str = "Bot") -> dict[str, str]:
    return {"__typename": typename, "login": login}


def _bot(*, report: dict[str, Any], login: str) -> dict[str, Any]:
    return next(b for b in report["bots"] if b["login"] == login)


class TestDraftSkip:
    @pytest.fixture
    def report(self) -> dict[str, Any]:
        return bot_reviews.summarize(pr=_pr(name="draft_skip"), blocking_globs=("claude",))

    def test_reports_no_bots(self, report: dict[str, Any]) -> None:
        assert report["bots"] == []

    def test_blocking_bot_is_missing(self, report: dict[str, Any]) -> None:
        assert report["missing_blocking_bots"] == ["claude"]

    def test_is_not_ready(self, report: dict[str, Any]) -> None:
        assert report["ready"] is False

    def test_reason_names_the_draft(self, report: dict[str, Any]) -> None:
        assert "review bots skip drafts" in report["reasons"][0]


class TestEmptyBodyWithInlineFindings:
    @pytest.fixture
    def report(self) -> dict[str, Any]:
        return bot_reviews.summarize(pr=_pr(name="empty_body_inline"), blocking_globs=("claude",))

    @pytest.fixture
    def claude(self, report: dict[str, Any]) -> dict[str, Any]:
        return _bot(report=report, login="claude")

    def test_is_at_head_by_sha(self, claude: dict[str, Any]) -> None:
        assert (claude["at_head"], claude["at_head_basis"]) == (True, "sha")

    def test_counts_only_unresolved_threads(self, claude: dict[str, Any]) -> None:
        assert claude["open_inline_comments"] == 2

    def test_flags_findings_hidden_under_empty_body(self, claude: dict[str, Any]) -> None:
        assert claude["empty_body_with_inline"] is True

    def test_last_activity_includes_thread_replies(self, claude: dict[str, Any]) -> None:
        assert claude["last_activity"] == "2026-11-05T10:31:00Z"

    def test_open_inline_findings_block(self, report: dict[str, Any]) -> None:
        assert report["reasons"] == ["claude: 2 open inline comment(s)"]


class TestStaleSha:
    @pytest.fixture
    def report(self) -> dict[str, Any]:
        return bot_reviews.summarize(
            pr=_pr(name="stale_sha"), blocking_globs=("claude", "copilot*")
        )

    def test_uses_latest_review_of_each_bot(self, report: dict[str, Any]) -> None:
        claude = _bot(report=report, login="claude")

        assert (claude["reviewed_sha"], claude["review_state"]) == ("b" * 40, "APPROVED")

    def test_stale_bot_is_not_at_head(self, report: dict[str, Any]) -> None:
        assert _bot(report=report, login="claude")["at_head"] is False

    def test_fresh_bot_is_at_head(self, report: dict[str, Any]) -> None:
        assert _bot(report=report, login="copilot-pull-request-reviewer")["at_head"] is True

    def test_human_reviews_are_not_bots(self, report: dict[str, Any]) -> None:
        assert [b["login"] for b in report["bots"]] == [
            "claude",
            "copilot-pull-request-reviewer",
        ]

    def test_only_the_stale_bot_blocks(self, report: dict[str, Any]) -> None:
        assert report["reasons"] == ["claude: last review is not at the PR head"]


class TestCommentOnlyBots:
    @pytest.fixture
    def report(self) -> dict[str, Any]:
        return bot_reviews.summarize(
            pr=_pr(name="comment_only"), blocking_globs=("hygiene-review", "github-actions")
        )

    @pytest.mark.parametrize(
        ("login", "expected"),
        [
            ("hygiene-review", True),
            ("github-actions", False),
        ],
    )
    def test_at_head_compares_activity_with_head_commit_time(
        self, report: dict[str, Any], login: str, expected: bool
    ) -> None:
        bot = _bot(report=report, login=login)

        assert (bot["kind"], bot["at_head"], bot["at_head_basis"]) == (
            "comment",
            expected,
            "timestamp",
        )

    def test_has_no_reviewed_sha(self, report: dict[str, Any]) -> None:
        assert _bot(report=report, login="hygiene-review")["reviewed_sha"] is None

    def test_push_time_defaults_to_the_commit_date(self, report: dict[str, Any]) -> None:
        assert report["head_pushed_at"] == report["head_committed_at"]


LATER = "2999-01-01T00:00:00Z"


class TestHeadPushTime:
    """A comment-only bot is judged against the push, not the commit (GH-1857)."""

    def _hygiene(self, *, pr: dict[str, Any]) -> dict[str, Any]:
        report = bot_reviews.summarize(pr=pr, blocking_globs=("hygiene-review",))
        return _bot(report=report, login="hygiene-review") | {
            "head_pushed_at": report["head_pushed_at"]
        }

    @pytest.mark.parametrize(("onto_head", "at_head"), [(True, False), (False, True)])
    def test_a_force_push_onto_the_head_moves_the_basis(
        self, onto_head: bool, at_head: bool
    ) -> None:
        pr = _pr(name="comment_only")
        oid = pr["headRefOid"] if onto_head else "0" * 40
        pr["timelineItems"] = {"nodes": [{"createdAt": LATER, "afterCommit": {"oid": oid}}]}

        assert self._hygiene(pr=pr)["at_head"] is at_head

    def test_a_check_suite_created_after_the_comment_moves_the_basis(self) -> None:
        pr = _pr(name="comment_only")
        pr["commits"]["nodes"][0]["commit"]["checkSuites"] = {
            "nodes": [{"createdAt": LATER}, {"createdAt": None}]
        }

        bot = self._hygiene(pr=pr)

        assert (bot["at_head"], bot["head_pushed_at"]) == (False, LATER)

    def test_a_check_suite_older_than_the_commit_does_not_move_it_back(self) -> None:
        pr = _pr(name="comment_only")
        committed = pr["commits"]["nodes"][0]["commit"]["committedDate"]
        pr["commits"]["nodes"][0]["commit"]["checkSuites"] = {
            "nodes": [{"createdAt": "1999-01-01T00:00:00Z"}]
        }

        assert self._hygiene(pr=pr)["head_pushed_at"] == committed


class TestSummarizeEdges:
    def test_no_blocking_bots_is_ready(self) -> None:
        report = bot_reviews.summarize(pr=_pr(name="stale_sha"), blocking_globs=())

        assert (report["ready"], report["reasons"]) == (True, [])

    @pytest.mark.parametrize(
        ("connection", "flag"),
        [
            ("reviews", "hasPreviousPage"),
            ("reviewThreads", "hasNextPage"),
            ("comments", "hasPreviousPage"),
        ],
    )
    def test_incomplete_window_blocks(self, connection: str, flag: str) -> None:
        pr = _pr(name="stale_sha")
        pr[connection]["pageInfo"] = {flag: True}

        report = bot_reviews.summarize(pr=pr, blocking_globs=())

        assert (report["truncated"], report["ready"]) == ([connection], False)

    def test_complete_windows_are_not_truncated(self) -> None:
        pr = _pr(name="stale_sha")
        pr["reviewThreads"]["pageInfo"] = {"hasNextPage": False}

        assert bot_reviews.summarize(pr=pr, blocking_globs=())["truncated"] == []

    def test_comment_bot_without_head_time_is_unknown(self) -> None:
        pr = _pr(name="comment_only")
        pr["commits"] = {"nodes": []}

        report = bot_reviews.summarize(pr=pr, blocking_globs=("hygiene-review",))

        assert report["reasons"] == ["hygiene-review: cannot tell whether it reviewed the PR head"]

    def test_pending_reviews_are_ignored(self) -> None:
        pr = _pr(name="stale_sha")
        pr["reviews"]["nodes"].append(
            {
                "author": {"__typename": "Bot", "login": "claude"},
                "state": "PENDING",
                "body": "",
                "submittedAt": None,
                "commit": {"oid": "3" * 40},
            }
        )

        report = bot_reviews.summarize(pr=pr, blocking_globs=("claude",))

        assert _bot(report=report, login="claude")["at_head"] is False

    @pytest.mark.parametrize(
        "overrides",
        [
            {
                "reviews": {
                    "nodes": [
                        {
                            "author": _author(login="claude"),
                            "state": "PENDING",
                            "submittedAt": None,
                        }
                    ]
                }
            },
            {"reviewThreads": {"nodes": [{"isResolved": False, "first": {"nodes": []}}]}},
            {
                "reviewThreads": {
                    "nodes": [
                        {
                            "isResolved": False,
                            "first": {
                                "nodes": [
                                    {
                                        "author": _author(login="octo-dev", typename="User"),
                                        "createdAt": "x",
                                    }
                                ]
                            },
                        }
                    ]
                }
            },
            {"reviews": None, "comments": {"nodes": [{"author": None, "createdAt": "x"}]}},
            {"comments": {"nodes": [{"author": _author(login=""), "createdAt": "x"}]}},
        ],
        ids=[
            "pending-only-review",
            "thread-without-comments",
            "human-inline-thread",
            "ghost-author-and-missing-connection",
            "bot-without-login",
        ],
    )
    def test_creates_no_bot_row(self, overrides: dict[str, Any]) -> None:
        pr = {**_pr(name="draft_skip"), **overrides}

        assert bot_reviews.summarize(pr=pr, blocking_globs=())["bots"] == []

    def test_missing_head_sha_is_unknown_not_stale(self) -> None:
        pr = _pr(name="stale_sha")
        pr["headRefOid"] = None

        report = bot_reviews.summarize(pr=pr, blocking_globs=("claude",))

        assert report["reasons"] == ["claude: cannot tell whether it reviewed the PR head"]

    def test_older_review_listed_last_does_not_win(self) -> None:
        pr = _pr(name="stale_sha")
        pr["reviews"]["nodes"].reverse()

        report = bot_reviews.summarize(pr=pr, blocking_globs=())

        assert _bot(report=report, login="claude")["review_state"] == "APPROVED"

    def test_changes_requested_at_head_blocks(self) -> None:
        pr = _pr(name="stale_sha")
        pr["reviews"]["nodes"][2]["state"] = "CHANGES_REQUESTED"

        report = bot_reviews.summarize(pr=pr, blocking_globs=("copilot*",))

        assert report["reasons"] == [
            "copilot-pull-request-reviewer: requested changes at the PR head"
        ]

    def test_human_login_that_looks_like_a_bot_is_not_a_bot(self) -> None:
        pr = _pr(name="draft_skip")
        pr["comments"] = {
            "nodes": [{"author": _author(login="claude-fan", typename="User"), "createdAt": "x"}]
        }

        report = bot_reviews.summarize(pr=pr, blocking_globs=("claude*",))

        assert (report["bots"], report["missing_blocking_bots"]) == ([], ["claude*"])


class TestResolveBlockingBots:
    def test_absent_file_blocks_nothing(self) -> None:
        result = resolve_blocking_bots(repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value.globs == ()

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (
                "blocking_bots: [claude]\nprojects:\n  - match_repo: 'owner/*'\n"
                "    blocking_bots: [hygiene-review, copilot*]\n",
                ("hygiene-review", "copilot*"),
            ),
            ("blocking_bots: ['claude[bot]', 'copilot*[bot]']\n", ("claude", "copilot*")),
            ("blocking_bots: [claude]\nprojects:\n  - match_repo: 'owner/*'\n", ("claude",)),
            (
                "blocking_bots: [claude]\nprojects:\n  - match_repo: 'owner/*'\n"
                "    blocking_bots: []\n",
                (),
            ),
            ("# nothing yet\n", ()),
        ],
        ids=[
            "project-entry-overrides-default",
            "bot-suffix-dropped",
            "entry-without-key-keeps-default",
            "explicit-empty-list-blocks-nothing",
            "empty-file-blocks-nothing",
        ],
    )
    def test_resolves_globs(self, text: str, expected: tuple[str, ...]) -> None:
        write_merge_settings(text=text)

        assert resolve_blocking_bots(repo="owner/repo").value.globs == expected

    @pytest.mark.parametrize(
        ("login", "expected"),
        [
            ("claude[bot]", "claude"),
            ("Claude[BOT]", "Claude"),
            ("octo", "octo"),
            (None, ""),
        ],
    )
    def test_normalize_login(self, login: str | None, expected: str) -> None:
        assert normalize_login(login) == expected

    def test_suffixed_glob_matches_the_graphql_login(self) -> None:
        write_merge_settings(text="blocking_bots: ['claude[bot]']\n")
        globs = resolve_blocking_bots(repo="owner/repo").value.globs

        report = bot_reviews.summarize(pr=_pr(name="empty_body_inline"), blocking_globs=globs)

        assert report["missing_blocking_bots"] == []

    def test_unmatched_repo_uses_default(self) -> None:
        write_merge_settings(
            text=(
                "blocking_bots: claude\n"
                "projects:\n"
                "  - match_repo: 'other/*'\n"
                "    blocking_bots: [hygiene-review]\n"
            )
        )

        result = resolve_blocking_bots(repo="owner/repo")

        assert (result.value.globs, result.value.project_status) == (("claude",), "no_match")

    @pytest.mark.parametrize(
        "text",
        [
            "blocking_bots: {claude: true}\n",
            "blocking_bots: ['']\n",
            "- just\n- a list\n",
            "blocking_bots: [unclosed\n",
            "blocking_bots:\n",
            "blocking_bots: [claude]\nprojects:\n  - match_repo: 'owner/*'\n    blocking_bots:\n",
        ],
        ids=[
            "mapping",
            "blank-glob",
            "top-level-list",
            "invalid-yaml",
            "null-default",
            "null-project-entry",
        ],
    )
    def test_malformed_config_fails_loud(self, text: str) -> None:
        write_merge_settings(text=text)

        assert isinstance(resolve_blocking_bots(repo="owner/repo"), ErrorResult)

    def test_unreadable_file_fails_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "settings-pr-merge.yaml"
        path.write_bytes(b"\xff\xfe\x00")

        assert isinstance(resolve_blocking_bots(repo="owner/repo", path=path), ErrorResult)


class TestConfigFoundSignal:
    """Say why nothing blocks when that was not a stated choice (GH-1857)."""

    def test_an_absent_file_is_named(self) -> None:
        config = resolve_blocking_bots(repo="owner/repo").value

        assert config.found is False
        assert "not found" in config.notes()[0]

    @pytest.mark.parametrize(
        ("text", "note"),
        [
            (
                "projects:\n  - match_repo: 'other/*'\n    blocking_bots: [claude]\n",
                "matched this repo",
            ),
            ("merge_strategy: rebase\n", "sets no `blocking_bots:`"),
            ("# nothing yet\n", "sets no `blocking_bots:`"),
        ],
        ids=["unmatched-no-default", "file-without-key", "empty-file"],
    )
    def test_an_unstated_list_is_noted(self, text: str, note: str) -> None:
        write_merge_settings(text=text)

        config = resolve_blocking_bots(repo="owner/repo").value

        assert (config.found, config.stated) == (True, False)
        assert note in config.notes()[0]

    @pytest.mark.parametrize(
        "text",
        [
            "blocking_bots: [claude]\nprojects:\n  - match_repo: 'other/*'\n",
            "blocking_bots: []\nprojects:\n  - match_repo: 'other/*'\n",
            "blocking_bots: []\n",
            "projects:\n  - match_repo: 'owner/*'\n    blocking_bots: []\n",
        ],
        ids=[
            "unmatched-with-default",
            "unmatched-with-explicit-empty-default",
            "explicit-empty",
            "matched-explicit-empty",
        ],
    )
    def test_a_stated_list_is_not_noted(self, text: str) -> None:
        write_merge_settings(text=text)

        config = resolve_blocking_bots(repo="owner/repo").value

        assert (config.stated, config.notes()) == (True, [])


@pytest.mark.usefixtures("mock_resolve_repo")
class TestBotReviewStatusTool:
    @pytest.mark.asyncio
    async def test_reports_blocking_status_from_config(self, mock_graphql: AsyncMock) -> None:
        write_merge_settings(text="blocking_bots: [claude]\n")
        mock_graphql.return_value = completed(
            stdout=json.dumps(_payload(name="empty_body_inline"))
        )

        result = await cli_server.bot_review_status(pr_number=7)

        assert (result["repo"], result["pr_number"], result["ready"]) == (
            "owner/repo",
            7,
            False,
        )
        assert result["blocking_bots"] == ["claude"]
        assert (result["config_found"], result["notes"]) == (True, [])

    @pytest.mark.asyncio
    async def test_reports_a_missing_config_without_blocking(
        self, mock_graphql: AsyncMock
    ) -> None:
        mock_graphql.return_value = completed(
            stdout=json.dumps(_payload(name="empty_body_inline"))
        )

        result = await cli_server.bot_review_status(pr_number=7)

        assert (result["config_found"], result["ready"]) == (False, True)
        assert "not found" in result["notes"][0]

    @pytest.mark.asyncio
    async def test_queries_the_requested_pr(self, mock_graphql: AsyncMock) -> None:
        mock_graphql.return_value = completed(stdout=json.dumps(_payload(name="draft_skip")))

        await bot_reviews.bot_review_status(pr_number=7)

        query = mock_graphql.call_args.kwargs["fields"]["query"]
        assert 'repository(owner: "owner", name: "repo")' in query
        assert "pullRequest(number: 7)" in query

    @pytest.mark.parametrize(
        ("response", "message"),
        [
            (completed(returncode=1, stderr="HTTP 502"), "HTTP 502"),
            (completed(returncode=1), "GitHub GraphQL call failed"),
            (completed(stdout="not json"), "Invalid JSON"),
            (
                completed(stdout=json.dumps({"errors": [{"message": "bad field"}]})),
                "bad field",
            ),
            (completed(stdout=json.dumps({"errors": ["plain text"]})), "plain text"),
            (completed(stdout=json.dumps({"errors": {"message": "lone"}})), "lone"),
            (completed(stdout=json.dumps([1, 2])), "not an object"),
            (
                completed(stdout=json.dumps({"data": {"repository": {"pullRequest": None}}})),
                "PR #7 not found",
            ),
            (
                completed(stdout=json.dumps({"data": {"repository": None}})),
                "PR #7 not found",
            ),
        ],
        ids=[
            "gh-failure",
            "gh-silent-failure",
            "bad-json",
            "graphql-error",
            "graphql-error-string",
            "graphql-error-object",
            "non-object-payload",
            "no-pr",
            "no-repository",
        ],
    )
    @pytest.mark.asyncio
    async def test_failures_are_errors(
        self,
        mock_graphql: AsyncMock,
        response: subprocess.CompletedProcess[str],
        message: str,
    ) -> None:
        mock_graphql.return_value = response

        result = await bot_reviews.bot_review_status(pr_number=7)

        assert isinstance(result, ErrorResult)
        assert message in result.error

    @pytest.mark.asyncio
    async def test_malformed_config_stops_before_the_api(self, mock_graphql: AsyncMock) -> None:
        write_merge_settings(text="blocking_bots: {claude: true}\n")

        result = await bot_reviews.bot_review_status(pr_number=7)

        assert isinstance(result, ErrorResult)
        mock_graphql.assert_not_called()


@pytest.mark.asyncio
async def test_unresolvable_repo_is_an_error() -> None:
    with patch.object(
        _gateway, "_resolve_repo", new_callable=AsyncMock, return_value=err("no repo")
    ):
        result = await bot_reviews.bot_review_status(pr_number=7)

    assert isinstance(result, ErrorResult)
