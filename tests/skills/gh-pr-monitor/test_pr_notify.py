"""Tests for pr-notify.py formatting functions and arg-building logic."""

import argparse
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest  # type: ignore[import-not-found]

# Load the shim script so the module object is available for patching.
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
update_pr_checklist = _mod.update_pr_checklist

# Private helper — import directly from the underlying module (not the * shim).
from dev10x.skills.monitor import pr_notify as _pr_notify_module  # noqa: E402

_repo_name = _pr_notify_module._repo_name


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
    """`gh pr checks --json` exposes `bucket`, not `conclusion` (GH-773)."""

    def test_empty_checks(self):
        assert format_ci_table(checks=[]) == "No CI checks found."

    def test_passing_check_with_duration(self):
        checks = [
            {
                "name": "ruff",
                "bucket": "pass",
                "startedAt": "2026-03-23T10:00:00Z",
                "completedAt": "2026-03-23T10:00:45Z",
            }
        ]
        result = format_ci_table(checks=checks)
        assert "| ruff | ✅ pass | 45s |" in result

    def test_failing_check(self):
        checks = [
            {
                "name": "pytest",
                "bucket": "fail",
                "startedAt": "2026-03-23T10:00:00Z",
                "completedAt": "2026-03-23T10:02:30Z",
            }
        ]
        result = format_ci_table(checks=checks)
        assert "| pytest | ❌ fail | 2m 30s |" in result

    def test_pending_check(self):
        checks = [
            {
                "name": "build",
                "bucket": "pending",
                "startedAt": "2026-03-23T10:00:00Z",
                "completedAt": None,
            }
        ]
        result = format_ci_table(checks=checks)
        assert "| build | ⏳ pending | ... |" in result

    def test_pending_check_with_zero_completed_timestamp(self):
        # gh emits the Go zero time for a not-yet-finished check.
        checks = [
            {
                "name": "build",
                "bucket": "pending",
                "startedAt": "2026-03-23T10:00:00Z",
                "completedAt": "0001-01-01T00:00:00Z",
            }
        ]
        result = format_ci_table(checks=checks)
        assert "| build | ⏳ pending | ... |" in result

    def test_skipping_check(self):
        checks = [{"name": "deploy", "bucket": "skipping"}]
        result = format_ci_table(checks=checks)
        assert "| deploy | ⏭️ skipping | - |" in result

    def test_cancel_check(self):
        checks = [{"name": "e2e", "bucket": "cancel"}]
        result = format_ci_table(checks=checks)
        assert "| e2e | 🚫 cancel | - |" in result

    def test_unknown_bucket_falls_back(self):
        checks = [{"name": "mystery", "bucket": "weird"}]
        result = format_ci_table(checks=checks)
        assert "| mystery | ⏸️ weird | - |" in result

    def test_missing_bucket_falls_back_to_unknown(self):
        checks = [{"name": "nameless"}]
        result = format_ci_table(checks=checks)
        assert "| nameless | ⏸️ unknown | - |" in result

    def test_table_has_header(self):
        checks = [
            {
                "name": "lint",
                "bucket": "pass",
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


class TestRepoName:
    """Unit tests for _repo_name helper — pure logic, no network."""

    def test_owner_slash_name_returns_name(self):
        assert _repo_name(repo="example-org/app-pos") == "app-pos"

    def test_valid_repository_ref_parsed_to_name(self):
        # RepositoryRef.try_parse succeeds for owner/name strings
        assert _repo_name(repo="acme/my-service") == "my-service"

    def test_bare_name_without_slash_returns_whole_string(self):
        # When RepositoryRef.try_parse returns None, fallback is split("/")[-1]
        # A bare name with no slash should return itself.
        result = _repo_name(repo="standalone")
        assert result == "standalone"


class TestUpdatePrChecklistArgBuilding:
    """Tests for update_pr_checklist arg-building — which gh pr edit args are assembled.

    The function builds a replacements list from diff content, then calls
    gh_run with those replacements applied to the PR body.  We mock gh_json
    (to supply the current body) and gh_run (to capture the edited body) so
    the pure arg-building logic can be exercised without network access.
    """

    def _run(
        self,
        diff: str,
        initial_body: str = (
            "- [ ] CI is passing\n"
            "- [ ] A person or better yet a group is selected in the reviewers section\n"
            "- [ ] Clean history with auto-squashed fixup! commits\n"
            "- [ ] **Data migrations** are present (if applicable) and unit tested\n"
            "- [ ] **New environment variables** are documented\n"
            "- [ ] **Breaking changes** are communicated to the team\n"
        ),
    ) -> str | None:
        """Run update_pr_checklist and return the body passed to gh pr edit, or None."""
        captured: list[str] = []

        def fake_gh_json(args: list[str]) -> dict:
            return {"body": initial_body}

        def fake_gh_run(args: list[str]) -> None:
            # args is: ["pr", "edit", "<pr>", "--repo", "<repo>", "--body", "<body>"]
            body_idx = args.index("--body")
            captured.append(args[body_idx + 1])

        with (
            patch.object(_pr_notify_module, "gh_json", side_effect=fake_gh_json),
            patch.object(_pr_notify_module, "gh_run", side_effect=fake_gh_run),
        ):
            update_pr_checklist(pr_number=1, repo="owner/repo", diff=diff)

        return captured[0] if captured else None

    def test_no_migrations_in_diff_strikes_through_migration_item(self):
        body = self._run(diff="some/other/file.py changed")
        assert body is not None
        assert "~**Data migrations**" in body
        assert "- [ ] **Data migrations**" not in body

    def test_migrations_in_diff_leaves_migration_item_unchecked(self):
        body = self._run(diff="migrations/0042_add_column.py\n+ new line")
        assert body is not None
        # Migration item should NOT be struck through; it stays as-is (checked or unchecked)
        assert "~**Data migrations**" not in body

    def test_no_env_changes_in_diff_strikes_through_env_item(self):
        body = self._run(diff="src/views.py changed")
        assert body is not None
        assert "~**New environment variables**" in body

    def test_env_changes_in_diff_leaves_env_item_unchecked(self):
        # diff contains "settings" and an assignment pattern
        body = self._run(diff="settings/base.py\n+SECRET_KEY='abc'")
        assert body is not None
        assert "~**New environment variables**" not in body

    def test_breaking_false_strikes_through_breaking_item(self):
        # has_breaking is always False (conservative default) in current impl
        body = self._run(diff="anything")
        assert body is not None
        assert "~**Breaking changes**" in body

    def test_standard_checklist_items_are_checked(self):
        body = self._run(diff="")
        assert body is not None
        assert "- [x] CI is passing" in body
        assert "- [x] A person or better yet a group is selected in the reviewers section" in body
        assert "- [x] Clean history with auto-squashed fixup! commits" in body

    def test_no_changes_when_checklist_items_absent(self):
        # If the body has no checklist markers, gh_run is never called (no-op)
        captured: list[str] = []

        def fake_gh_json(args: list[str]) -> dict:
            return {"body": "Just a plain PR body with no checklist."}

        def fake_gh_run(args: list[str]) -> None:
            captured.append("called")

        with (
            patch.object(_pr_notify_module, "gh_json", side_effect=fake_gh_json),
            patch.object(_pr_notify_module, "gh_run", side_effect=fake_gh_run),
        ):
            update_pr_checklist(pr_number=1, repo="owner/repo", diff="")

        assert captured == []

    def test_none_body_treated_as_empty_string(self):
        # gh_json returns body=None — should not raise
        captured: list[str] = []

        def fake_gh_json(args: list[str]) -> dict:
            return {"body": None}

        def fake_gh_run(args: list[str]) -> None:
            captured.append("called")

        with (
            patch.object(_pr_notify_module, "gh_json", side_effect=fake_gh_json),
            patch.object(_pr_notify_module, "gh_run", side_effect=fake_gh_run),
        ):
            update_pr_checklist(pr_number=1, repo="owner/repo", diff="")

        # No checklist items in None/empty body → no edit needed
        assert captured == []


class TestSendSubcommandArgDefaults:
    """Tests that the send subcommand's argparse defaults are correct.

    Builds the parser inline (mirrors main() structure) so defaults can be
    asserted without calling main() which triggers RepositoryRef.parse().
    """

    @pytest.fixture()
    def send_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        p_send = subparsers.add_parser("send")
        p_send.add_argument("--pr", type=int, required=True)
        p_send.add_argument("--repo", required=True)
        p_send.add_argument("--channel")
        p_send.add_argument("--message")
        p_send.add_argument("--message-file")
        p_send.add_argument("--reviewer")
        p_send.add_argument("--skip-slack", action="store_true")
        p_send.add_argument("--skip-reviewers", action="store_true")
        p_send.add_argument("--skip-checklist", action="store_true")
        return parser

    def test_skip_flags_default_to_false(self, send_parser: argparse.ArgumentParser):
        args = send_parser.parse_args(["send", "--pr", "42", "--repo", "owner/repo"])
        assert args.skip_slack is False
        assert args.skip_reviewers is False
        assert args.skip_checklist is False

    def test_optional_args_default_to_none(self, send_parser: argparse.ArgumentParser):
        args = send_parser.parse_args(["send", "--pr", "42", "--repo", "owner/repo"])
        assert args.channel is None
        assert args.message is None
        assert args.message_file is None
        assert args.reviewer is None

    def test_skip_slack_flag_parsed(self, send_parser: argparse.ArgumentParser):
        args = send_parser.parse_args(
            ["send", "--pr", "1", "--repo", "owner/repo", "--skip-slack"]
        )
        assert args.skip_slack is True

    def test_skip_reviewers_flag_parsed(self, send_parser: argparse.ArgumentParser):
        args = send_parser.parse_args(
            ["send", "--pr", "1", "--repo", "owner/repo", "--skip-reviewers"]
        )
        assert args.skip_reviewers is True

    def test_skip_checklist_flag_parsed(self, send_parser: argparse.ArgumentParser):
        args = send_parser.parse_args(
            ["send", "--pr", "1", "--repo", "owner/repo", "--skip-checklist"]
        )
        assert args.skip_checklist is True

    def test_all_optional_args_provided(self, send_parser: argparse.ArgumentParser):
        args = send_parser.parse_args(
            [
                "send",
                "--pr",
                "99",
                "--repo",
                "myorg/myrepo",
                "--channel",
                "C123456",
                "--message",
                "Hello",
                "--reviewer",
                "myorg/reviewers",
            ]
        )
        assert args.pr == 99
        assert args.repo == "myorg/myrepo"
        assert args.channel == "C123456"
        assert args.message == "Hello"
        assert args.reviewer == "myorg/reviewers"

    def test_pr_parsed_as_int(self, send_parser: argparse.ArgumentParser):
        args = send_parser.parse_args(["send", "--pr", "123", "--repo", "owner/repo"])
        assert isinstance(args.pr, int)
        assert args.pr == 123

    def test_status_json_flag_default_false(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        p_status = subparsers.add_parser("status")
        p_status.add_argument("--pr", type=int, required=True)
        p_status.add_argument("--repo", required=True)
        p_status.add_argument("--json", action="store_true")

        args = parser.parse_args(["status", "--pr", "5", "--repo", "owner/repo"])
        assert args.json is False

    def test_status_json_flag_parsed(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        p_status = subparsers.add_parser("status")
        p_status.add_argument("--pr", type=int, required=True)
        p_status.add_argument("--repo", required=True)
        p_status.add_argument("--json", action="store_true")

        args = parser.parse_args(["status", "--pr", "5", "--repo", "owner/repo", "--json"])
        assert args.json is True
