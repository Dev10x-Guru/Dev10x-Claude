"""Check 1d's deterministic half (GH-1241).

The judgment pass Check 1d already documented could not be relied on for
the easy case: PR #1228 declared six ``Fixes:`` links, carried commits
for five, and closed GH-1221 with nothing behind it. These pin the set
diff that decides that case without reasoning.
"""

from __future__ import annotations

import json

import pytest

from dev10x.skills.merge.fixes_scope import (
    commit_ticket_ids,
    fixes_links,
    main,
    reconcile_fixes_links,
)

# The shape of PR #1228: six declared links, five backed by commits.
PR_1228_BODY = """\
**When** a maintainer bundles a milestone, **the maintainer wants to**
land every constituent in one review cycle **so the team can** ship the
milestone without six separate merges.

Fixes: GH-1218
Fixes: GH-1219
Fixes: GH-1220
Fixes: GH-1221
Fixes: GH-1222
Fixes: GH-1225
"""

PR_1228_COMMITS = [
    "\U0001f41b GH-1218 Keep a declared beat from vanishing silently\n",
    "\U0001f41b GH-1219 Name the run that produced an artifact\n",
    "\U0001f41b GH-1220 Let a caption survive its own navigation\n",
    "\U0001f41b GH-1222 Stop flagging an intentional guardrail\n",
    "\U0001f4dd GH-1225 Record the voice a walkthrough narrated in\n",
]


class TestFixesLinks:
    def test_reads_every_closing_keyword_form(self):
        body = "Fixes: GH-1\nCloses #2\nresolved: GH-3\n"
        assert fixes_links(body) == (1, 2, 3)

    def test_reads_a_full_issue_url(self):
        body = "Fixes: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1241\n"
        assert fixes_links(body) == (1241,)

    def test_reads_a_link_written_without_a_space(self):
        # GitHub honours `Fixes:GH-1221`. Failing to parse it would let the
        # check pass a PR whose link it never saw — a false negative in the
        # direction this module exists to prevent.
        assert fixes_links("Fixes:GH-1221\n") == (1221,)
        assert fixes_links("Closes#42\n") == (42,)

    def test_a_bare_reference_is_not_a_link(self):
        # Mentioning an issue in prose must not be read as a closing link,
        # or the check blocks on cross-references it should ignore.
        assert fixes_links("Follows on from GH-1234 and #99.\n") == ()

    def test_duplicate_links_collapse(self):
        assert fixes_links("Fixes: GH-7\nFixes: GH-7\n") == (7,)

    def test_an_empty_body_has_no_links(self):
        assert fixes_links("") == ()


class TestCommitTicketIds:
    def test_reads_the_subject_ticket(self):
        assert commit_ticket_ids(["\U0001f41b GH-42 Do the thing\n"]) == (42,)

    def test_reads_members_named_only_in_the_body(self):
        # A batched commit names its non-canonical members in the body;
        # scanning subjects alone would call them undelivered and block
        # exactly the multi-issue commit the bundle convention asks for.
        batched = "♻️ GH-12 Tighten timeout handling\n\nFixes: GH-12\nFixes: GH-14\n"
        assert commit_ticket_ids([batched]) == (12, 14)

    def test_deduplicates_across_commits(self):
        assert commit_ticket_ids(["GH-5 one", "GH-5 two"]) == (5,)


class TestReconciliation:
    def test_pr_1228_is_caught(self):
        verdict = reconcile_fixes_links(body=PR_1228_BODY, commit_messages=PR_1228_COMMITS)

        assert verdict.ok is False
        assert verdict.unbacked == (1221,)
        assert "GH-1221" in verdict.summary()

    def test_a_fully_backed_pr_passes(self):
        body = "Fixes: GH-1\nFixes: GH-2\n"
        commits = ["GH-1 first", "GH-2 second"]
        assert reconcile_fixes_links(body=body, commit_messages=commits).ok

    def test_a_batched_commit_backs_every_member(self):
        body = "Fixes: GH-12\nFixes: GH-14\n"
        commits = ["♻️ GH-12 One change\n\nFixes: GH-12\nFixes: GH-14\n"]
        assert reconcile_fixes_links(body=body, commit_messages=commits).ok

    def test_an_acknowledged_link_is_waived(self):
        verdict = reconcile_fixes_links(
            body=PR_1228_BODY,
            commit_messages=PR_1228_COMMITS,
            acknowledged={1221},
        )
        assert verdict.ok is True
        assert verdict.unbacked == ()

    def test_a_pr_with_no_links_passes(self):
        verdict = reconcile_fixes_links(body="no links here", commit_messages=[])
        assert verdict.ok is True
        assert verdict.summary() == "no Fixes:/Closes: links to reconcile"

    def test_delivered_lists_only_backed_links(self):
        verdict = reconcile_fixes_links(body=PR_1228_BODY, commit_messages=PR_1228_COMMITS)
        assert verdict.delivered == (1218, 1219, 1220, 1222, 1225)

    def test_a_commit_for_an_unlinked_issue_is_not_an_error(self):
        # Extra work in the branch is a scope question for the reviewer,
        # not something that can wrongly close an issue.
        verdict = reconcile_fixes_links(body="Fixes: GH-1\n", commit_messages=["GH-1 a", "GH-9 b"])
        assert verdict.ok is True


class TestCli:
    def _write_body(self, tmp_path, body: str):
        path = tmp_path / "body.txt"
        path.write_text(body, encoding="utf-8")
        return path

    def test_exits_non_zero_and_names_the_unbacked_link(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(
            "dev10x.skills.merge.fixes_scope.read_commit_messages",
            lambda **kwargs: PR_1228_COMMITS,
        )
        body = self._write_body(tmp_path, PR_1228_BODY)

        code = main(["--body-file", str(body), "--base", "origin/develop"])

        payload = json.loads(capsys.readouterr().out)
        assert code == 1
        assert payload["unbacked"] == [1221]

    def test_exits_zero_when_every_link_is_backed(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(
            "dev10x.skills.merge.fixes_scope.read_commit_messages",
            lambda **kwargs: ["GH-1 done"],
        )
        body = self._write_body(tmp_path, "Fixes: GH-1\n")

        code = main(["--body-file", str(body), "--base", "origin/develop"])

        assert code == 0
        assert json.loads(capsys.readouterr().out)["ok"] is True

    def test_acknowledge_flag_waives_a_link(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(
            "dev10x.skills.merge.fixes_scope.read_commit_messages",
            lambda **kwargs: PR_1228_COMMITS,
        )
        body = self._write_body(tmp_path, PR_1228_BODY)

        code = main(
            ["--body-file", str(body), "--base", "origin/develop", "--acknowledge", "1221"]
        )

        assert code == 0

    def test_an_error_is_json_on_stdout_not_an_empty_channel(self, tmp_path, capsys):
        # The caller parses stdout; an error only on stderr leaves it with
        # nothing to read (script-domain-boundaries.md single-channel rule).
        code = main(["--body-file", str(tmp_path / "absent.txt"), "--base", "origin/develop"])

        payload = json.loads(capsys.readouterr().out)
        assert code == 2
        assert "error" in payload


class TestReadCommitMessages:
    def test_surfaces_a_git_failure(self, monkeypatch):
        from dev10x.skills.merge import fixes_scope

        class _Result:
            returncode = 128
            stdout = ""
            stderr = "fatal: bad revision"

        monkeypatch.setattr(fixes_scope.subprocess, "run", lambda *a, **k: _Result())
        with pytest.raises(RuntimeError, match="bad revision"):
            fixes_scope.read_commit_messages(base="origin/nope")

    def test_splits_commits_on_the_null_separator(self, monkeypatch):
        from dev10x.skills.merge import fixes_scope

        class _Result:
            returncode = 0
            stdout = "GH-1 one\n\0GH-2 two\n\0"
            stderr = ""

        monkeypatch.setattr(fixes_scope.subprocess, "run", lambda *a, **k: _Result())
        assert fixes_scope.read_commit_messages(base="origin/develop") == [
            "GH-1 one\n",
            "GH-2 two\n",
        ]
