"""Tests for pr-notify.py formatting functions."""

import importlib.util
from pathlib import Path

import pytest  # type: ignore[import-not-found]

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "pr_notify",
    _repo_root / "skills" / "gh-pr-monitor" / "scripts" / "pr-notify.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

extract_jtbd = _mod.extract_jtbd
format_ci_table = _mod.format_ci_table
format_comments_section = _mod.format_comments_section
format_reviewers_section = _mod.format_reviewers_section
format_slack_message = _mod.format_slack_message
format_status_report = _mod.format_status_report
md_to_slack_bold = _mod.md_to_slack_bold
split_title_jtbd = _mod.split_title_jtbd


class TestSplitTitleJtbd:
    def test_splits_at_em_dash(self):
        title = (
            ":bug: PAY-646 Fix payment routing \u2014 When reconciling payments, I want routing"
        )
        short, jtbd = split_title_jtbd(pr_title=title)
        assert short == ":bug: PAY-646 Fix payment routing"
        assert jtbd == "When reconciling payments, I want routing"

    def test_no_em_dash_returns_full_title(self):
        title = ":bug: PAY-646 Fix payment routing"
        short, jtbd = split_title_jtbd(pr_title=title)
        assert short == ":bug: PAY-646 Fix payment routing"
        assert jtbd is None

    def test_multiple_em_dashes_splits_at_first(self):
        title = "Title \u2014 first part \u2014 second part"
        short, jtbd = split_title_jtbd(pr_title=title)
        assert short == "Title"
        assert jtbd == "first part \u2014 second part"

    def test_em_dash_without_spaces_not_split(self):
        title = "Title\u2014no spaces around dash"
        short, jtbd = split_title_jtbd(pr_title=title)
        assert short == "Title\u2014no spaces around dash"
        assert jtbd is None


class TestFormatSlackMessage:
    @pytest.fixture()
    def base_args(self):
        return {
            "pr_number": 1354,
            "repo": "example-org/app-pos",
            "pr_url": "https://github.com/example-org/app-pos/pull/1354",
        }

    def test_title_with_embedded_jtbd(self, base_args):
        result = format_slack_message(
            **base_args,
            pr_title=":bug: PAY-646 Fix routing \u2014 When reconciling payments, I want routing",
            jtbd=None,
        )
        assert result == (
            "Please review <https://github.com/example-org/app-pos/pull/1354|app-pos#1354>\n"
            ":bug: PAY-646 Fix routing\n"
            "> When reconciling payments, I want routing"
        )

    def test_body_jtbd_takes_precedence_over_title_jtbd(self, base_args):
        result = format_slack_message(
            **base_args,
            pr_title=":bug: PAY-646 Fix routing \u2014 embedded jtbd",
            jtbd="**When** reconciling, **wants to** see order number",
        )
        assert "> *When* reconciling, *wants to* see order number" in result
        assert "embedded jtbd" not in result

    def test_short_title_no_jtbd(self, base_args):
        result = format_slack_message(
            **base_args,
            pr_title=":bug: PAY-646 Fix routing",
            jtbd=None,
        )
        assert result == (
            "Please review <https://github.com/example-org/app-pos/pull/1354|app-pos#1354>\n"
            ":bug: PAY-646 Fix routing"
        )

    def test_body_jtbd_with_short_title(self, base_args):
        result = format_slack_message(
            **base_args,
            pr_title=":bug: PAY-646 Fix routing",
            jtbd="**When** reconciling payments, I **want to** see the order number",
        )
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[2] == "> *When* reconciling payments, I *want to* see the order number"


class TestExtractJtbd:
    def test_extracts_when_block(self):
        body = (
            "## Summary\n\n**When** reconciling payments\n"
            "**wants to** see order number\n\n## Details"
        )
        assert (
            extract_jtbd(body=body)
            == "**When** reconciling payments **wants to** see order number"
        )

    def test_returns_none_when_no_jtbd(self):
        body = "## Summary\n\nJust a regular PR body."
        assert extract_jtbd(body=body) is None


class TestMdToSlackBold:
    def test_converts_markdown_bold_to_slack(self):
        assert md_to_slack_bold(text="**When** I do **this**") == "*When* I do *this*"

    def test_no_bold_unchanged(self):
        assert md_to_slack_bold(text="plain text") == "plain text"


class TestFormatCiTable:
    def test_empty_checks(self):
        assert format_ci_table(checks=[]) == "No CI checks found."

    def test_passing_check_with_duration(self):
        checks = [
            {
                "name": "ruff",
                "state": "COMPLETED",
                "conclusion": "SUCCESS",
                "startedAt": "2026-03-23T10:00:00Z",
                "completedAt": "2026-03-23T10:00:45Z",
            }
        ]
        result = format_ci_table(checks=checks)
        assert "| ruff | ✅ success | 45s |" in result

    def test_failing_check(self):
        checks = [
            {
                "name": "pytest",
                "state": "COMPLETED",
                "conclusion": "FAILURE",
                "startedAt": "2026-03-23T10:00:00Z",
                "completedAt": "2026-03-23T10:02:30Z",
            }
        ]
        result = format_ci_table(checks=checks)
        assert "| pytest | ❌ failure | 2m 30s |" in result

    def test_in_progress_check(self):
        checks = [
            {
                "name": "build",
                "state": "IN_PROGRESS",
                "conclusion": "",
                "startedAt": "2026-03-23T10:00:00Z",
                "completedAt": None,
            }
        ]
        result = format_ci_table(checks=checks)
        assert "| build | ⏳ running | ... |" in result

    def test_table_has_header(self):
        checks = [
            {
                "name": "lint",
                "state": "COMPLETED",
                "conclusion": "SUCCESS",
                "startedAt": None,
                "completedAt": None,
            }
        ]
        result = format_ci_table(checks=checks)
        assert "| Check | Status | Duration |" in result
        assert "| --- | --- | --- |" in result


class TestFormatCommentsSection:
    def test_no_comments(self):
        result = format_comments_section(comments=[])
        assert result == "No unhandled review comments."

    def test_all_resolved(self):
        comments = [{"resolved": True, "user": "alice", "path": "a.py", "line": 1, "body": "ok"}]
        result = format_comments_section(comments=comments)
        assert result == "No unhandled review comments."

    def test_unresolved_comments(self):
        comments = [
            {
                "resolved": False,
                "user": "bob",
                "path": "server.py",
                "line": 42,
                "body": "This should use --pr instead",
            },
            {
                "resolved": True,
                "user": "alice",
                "path": "other.py",
                "line": 10,
                "body": "Looks good",
            },
        ]
        result = format_comments_section(comments=comments)
        assert "1 unhandled comment(s)" in result
        assert "**bob**" in result
        assert "`server.py:42`" in result


class TestFormatReviewersSection:
    def test_no_reviewers(self):
        data = {"reviewRequests": [], "reviews": [], "latestReviews": []}
        assert format_reviewers_section(data=data) == "No reviewers assigned."

    def test_approved_reviewer(self):
        data = {
            "reviewRequests": [],
            "reviews": [],
            "latestReviews": [{"author": {"login": "alice"}, "state": "APPROVED"}],
        }
        result = format_reviewers_section(data=data)
        assert "| @alice | ✅ approved |" in result

    def test_changes_requested_reviewer(self):
        data = {
            "reviewRequests": [],
            "reviews": [],
            "latestReviews": [{"author": {"login": "bob"}, "state": "CHANGES_REQUESTED"}],
        }
        result = format_reviewers_section(data=data)
        assert "| @bob | 🔄 changes_requested |" in result

    def test_pending_reviewer(self):
        data = {
            "reviewRequests": [{"login": "carol"}],
            "reviews": [],
            "latestReviews": [],
        }
        result = format_reviewers_section(data=data)
        assert "| @carol | ⏳ requested |" in result

    def test_reviewer_table_has_header(self):
        data = {
            "reviewRequests": [{"login": "dev"}],
            "reviews": [],
            "latestReviews": [],
        }
        result = format_reviewers_section(data=data)
        assert "| Reviewer | Status |" in result


class TestFormatStatusReport:
    def test_combines_all_sections(self):
        result = format_status_report(
            checks=[],
            comments=[],
            reviewers={"reviewRequests": [], "reviews": [], "latestReviews": []},
        )
        assert "## CI Check Status" in result
        assert "## Review Comments" in result
        assert "## Reviewers" in result
        assert "No CI checks found." in result
        assert "No unhandled review comments." in result
        assert "No reviewers assigned." in result
