"""Tests for bin/extract-linked-issues.py (GH-1196).

The bug this covers: PR #1193 merged with eight `Fixes: GH-N` lines and
`close-issues.yml` closed none of them, reporting success. The extractor
required a full URL; the bare-ID form the repo's own commit convention
uses matched nothing. Every shape below is one a real PR body has used.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT = _REPO_ROOT / "bin" / "extract-linked-issues.py"

_spec = importlib.util.spec_from_file_location("extract_linked_issues", _SCRIPT)
assert _spec is not None and _spec.loader is not None
extract_linked_issues = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_linked_issues)

extract = extract_linked_issues.extract
explicit_none_reason = extract_linked_issues.explicit_none_reason
verdict = extract_linked_issues.verdict
workflow_data = extract_linked_issues.workflow_data
EXIT_REFS = extract_linked_issues.EXIT_REFS
EXIT_MISSING = extract_linked_issues.EXIT_MISSING
EXIT_DECLARED_NONE = extract_linked_issues.EXIT_DECLARED_NONE

REPO = "Dev10x-Guru/Dev10x-Claude"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "close-issues.yml"


class TestBareForms:
    """The shapes that silently matched nothing before GH-1196."""

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ("Fixes: GH-1149", [f"{REPO}#1149"]),
            ("Fixes: #1149", [f"{REPO}#1149"]),
            ("Fixes GH-1149", [f"{REPO}#1149"]),
            ("Closes #1149", [f"{REPO}#1149"]),
            ("Resolves #1149", [f"{REPO}#1149"]),
            ("fixes: gh-1149", [f"{REPO}#1149"]),
        ],
    )
    def test_bare_reference_resolves_against_current_repo(
        self,
        body: str,
        expected: list[str],
    ) -> None:
        assert extract(body=body, repo=REPO) == expected

    def test_pr_1193_body_shape_yields_every_constituent(self) -> None:
        body = "\n".join(
            [
                "Some job story.",
                "",
                *(f"Fixes: GH-{n}" for n in (1149, 1150, 1151, 1152, 1153, 1154, 1155, 1173)),
            ]
        )
        assert extract(body=body, repo=REPO) == [
            f"{REPO}#{n}" for n in (1149, 1150, 1151, 1152, 1153, 1154, 1155, 1173)
        ]


class TestUrlForm:
    def test_full_url_still_recognised(self) -> None:
        body = f"Fixes: https://github.com/{REPO}/issues/42"
        assert extract(body=body, repo=REPO) == [f"{REPO}#42"]

    def test_url_keeps_its_own_repo_not_the_current_one(self) -> None:
        body = "Fixes: https://github.com/other-org/other-repo/issues/7"
        assert extract(body=body, repo=REPO) == ["other-org/other-repo#7"]

    def test_url_is_not_double_counted_as_a_bare_reference(self) -> None:
        body = f"Fixes: https://github.com/{REPO}/issues/42"
        assert extract(body=body, repo=REPO) == [f"{REPO}#42"]


class TestMixedAndDegenerate:
    def test_mixed_url_and_bare_forms_both_land(self) -> None:
        body = "\n".join(
            [
                f"Fixes: https://github.com/{REPO}/issues/42",
                "Fixes: GH-1149",
                "Closes #7",
            ]
        )
        assert extract(body=body, repo=REPO) == [
            f"{REPO}#42",
            f"{REPO}#1149",
            f"{REPO}#7",
        ]

    def test_duplicates_collapse_to_first_occurrence(self) -> None:
        body = "Fixes: GH-42\nCloses #42\n"
        assert extract(body=body, repo=REPO) == [f"{REPO}#42"]

    @pytest.mark.parametrize(
        "body",
        [
            "",
            "A body with no references at all.",
            "Mentions GH-42 without a closing keyword.",
            "See #42 for context.",
        ],
    )
    def test_bodies_without_closing_keywords_yield_nothing(self, body: str) -> None:
        # The caller treats an empty result as a failure, not a no-op --
        # a bare mention must not be enough to close someone's issue.
        assert extract(body=body, repo=REPO) == []


_PARTIAL_DELIVERY_BODY = "\n".join(
    [
        "**When** a maintainer lands one slice of #909 ...",
        "",
        "Fixes: none — part of #909",
    ]
)


class TestExplicitNone:
    """GH-1819: `Fixes: none — <reason>` is a deliberate no-op, not a gap."""

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (_PARTIAL_DELIVERY_BODY, "part of #909"),
            ("Fixes: none — self-motivated", "self-motivated"),
            ("Fixes: none -- self-motivated", "self-motivated"),
            ("Fixes: none - self-motivated", "self-motivated"),
            ("fixes: NONE – part of #12", "part of #12"),
            ("Fixes: none—part of #12", "part of #12"),
            ("Story.\n\n  Fixes: none — part of #909  \n", "part of #909"),
            ("Story.\r\n\r\nFixes: none — part of #909\r\n", "part of #909"),
            ("Fixes: none —\nFixes: none — part of #909", "part of #909"),
            ("```\nFixes: none — x\n```\nFixes: none — part of #909", "part of #909"),
            ("<!-- note -->\nFixes: none — part of #909", "part of #909"),
            ("<!-- a\nb -->Fixes: none — part of #909", "part of #909"),
            ("Fixes: none — <b>bold</b> reason", "<b>bold</b> reason"),
        ],
        ids=[
            "partial-delivery-body",
            "em-dash",
            "double-hyphen",
            "single-hyphen",
            "case-insensitive-en-dash",
            "no-space-before-reason",
            "indented-with-trailing-space",
            "crlf",
            "first-usable-line-wins",
            "after-closed-fence",
            "after-inline-comment",
            "after-multi-line-comment",
            "html-inside-a-real-reason",
        ],
    )
    def test_explicit_none_trailer_reports_its_reason(
        self,
        body: str,
        expected: str,
    ) -> None:
        assert explicit_none_reason(body=body) == expected

    @pytest.mark.parametrize(
        "body",
        [
            "",
            "A body with no references at all.",
            "Fixes: GH-42",
            "Fixes: nonexistent-thing",
            "Fixes: none-yet",
            "Fixes: none of the above",
            "Fixes: none",
            "Fixes: none —",
            "Story.\r\n\r\nFixes: none\r\n",
            "Fixes: none —   \r\n",
            "We considered Fixes: none — but rejected it.",
            "Fixes: none" + " " * 60_000 + "x",
            "Fixes: none — —",
            "Fixes: none — ...",
            "Fixes: none — __",
            "Fixes: none — <reason>",
            "Fixes: none — < why >",
            "```\nFixes: none — part of #909\n```",
            "~~~md\nFixes: none — part of #909",
            "<!-- Fixes: none — part of #909 -->",
            "<!--\nFixes: none — part of #909\n-->",
            "<!--" * 20_000 + "\nFixes: none — part of #909",
        ],
        ids=[
            "empty",
            "no-references",
            "real-reference",
            "none-prefix-word",
            "none-yet",
            "none-of-the-above",
            "bare-none",
            "dash-without-reason",
            "bare-none-crlf",
            "dash-with-blank-reason-crlf",
            "quoted-in-prose",
            "hostile-whitespace",
            "punctuation-only-reason",
            "ellipsis-reason",
            "underscore-only-reason",
            "unfilled-placeholder",
            "spaced-placeholder",
            "inside-backtick-fence",
            "inside-unclosed-tilde-fence",
            "inside-inline-comment",
            "inside-multi-line-comment",
            "inside-unclosed-comment-flood",
        ],
    )
    def test_body_without_explicit_none_reports_nothing(self, body: str) -> None:
        assert explicit_none_reason(body=body) is None

    def test_partial_delivery_body_closes_nothing(self) -> None:
        # The parent named after `part of` must stay open -- that is the
        # trailer's whole purpose.
        assert extract(body=_PARTIAL_DELIVERY_BODY, repo=REPO) == []


class TestVerdict:
    """GH-1873: one call decides refs / declared-none / missing."""

    def test_references_win_over_a_none_trailer(self) -> None:
        body = "Fixes: GH-7\nFixes: none — part of #909"

        assert verdict(body=body, repo=REPO) == (EXIT_REFS, [f"{REPO}#7"])

    def test_declared_none_is_a_notice(self) -> None:
        assert verdict(body=_PARTIAL_DELIVERY_BODY, repo=REPO) == (
            EXIT_DECLARED_NONE,
            ["::notice::PR declares 'Fixes: none' (part of #909); nothing to close."],
        )

    @pytest.mark.parametrize(
        ("body", "expected_errors"),
        [
            ("Just a story.", 1),
            ("Story.\n\nFixes: none", 2),
            ("Story.\n\nFixes: none — <reason>", 2),
        ],
        ids=["no-trailer", "bare-none", "placeholder-none"],
    )
    def test_missing_fails_and_names_a_malformed_none_trailer(
        self,
        body: str,
        expected_errors: int,
    ) -> None:
        code, lines = verdict(body=body, repo=REPO)

        assert code == EXIT_MISSING
        assert sum(line.startswith("::error::") for line in lines) == expected_errors

    @pytest.mark.parametrize(
        "shape",
        extract_linked_issues.RECOGNIZED_SHAPES,
        ids=extract_linked_issues.RECOGNIZED_SHAPES,
    )
    def test_every_advertised_shape_is_one_the_extractor_closes(self, shape: str) -> None:
        body = shape.replace("<owner>/<repo>", "owner/repo")

        assert extract(body=body, repo=REPO) != []

    def test_the_hint_lists_every_advertised_shape(self) -> None:
        _, lines = verdict(body="Just a story.", repo=REPO)
        hint = next(line for line in lines if line.startswith("Recognized shapes:"))

        assert all(f"'{shape}'" in hint for shape in extract_linked_issues.RECOGNIZED_SHAPES)


class TestWorkflowData:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("part of #909", "part of #909"),
            ("100%0A::error::forged", "100%250A::error::forged"),
            ("tab\there\x1b[31m", "tabhere[31m"),
        ],
        ids=["plain", "runner-escape", "control-characters"],
    )
    def test_author_text_cannot_steer_the_runner(self, text: str, expected: str) -> None:
        assert workflow_data(text=text) == expected

    def test_a_reason_is_escaped_inside_the_notice(self) -> None:
        _, lines = verdict(body="Fixes: none — 50%0A done", repo=REPO)

        assert lines == ["::notice::PR declares 'Fixes: none' (50%250A done); nothing to close."]


class TestCli:
    @pytest.mark.parametrize(
        ("body", "expected_code", "expected_out"),
        [
            ("Fixes: GH-7\n", EXIT_REFS, f"{REPO}#7\n"),
            (
                _PARTIAL_DELIVERY_BODY,
                EXIT_DECLARED_NONE,
                "::notice::PR declares 'Fixes: none' (part of #909); nothing to close.\n",
            ),
        ],
        ids=["refs", "declared-none"],
    )
    def test_main_prints_exactly_the_verdict_and_exits_with_its_code(
        self,
        body: str,
        expected_code: int,
        expected_out: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.argv", ["extract-linked-issues.py", "--repo", REPO])
        monkeypatch.setattr("sys.stdin", io.StringIO(body))

        assert extract_linked_issues.main() == expected_code
        assert capsys.readouterr().out == expected_out

    def test_main_fails_a_bare_none_with_the_verdict_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.argv", ["extract-linked-issues.py", "--repo", REPO])
        monkeypatch.setattr("sys.stdin", io.StringIO("Fixes: none\n"))
        _, expected_lines = verdict(body="Fixes: none\n", repo=REPO)

        assert extract_linked_issues.main() == EXIT_MISSING
        assert capsys.readouterr().out.splitlines() == expected_lines

    def test_main_requires_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["extract-linked-issues.py"])
        monkeypatch.setattr("sys.stdin", io.StringIO("Fixes: GH-7\n"))

        with pytest.raises(SystemExit) as raised:
            extract_linked_issues.main()

        assert raised.value.code == 2


class TestWorkflowWiring:
    """close-issues.yml makes one call and branches only on its exit code."""

    @pytest.fixture
    def workflow_text(self) -> str:
        return _WORKFLOW.read_text(encoding="utf-8")

    def test_the_extractor_is_called_once(self, workflow_text: str) -> None:
        assert workflow_text.count("./bin/extract-linked-issues.py") == 1

    def test_exit_three_reaches_the_case_under_set_e(self, workflow_text: str) -> None:
        wrapped = workflow_text[workflow_text.index("set +e") :]
        markers = ["set +e", "verdict=$(", "status=$?", "set -e\n", 'case "$status" in']

        positions = [wrapped.index(marker) for marker in markers]

        assert positions == sorted(positions)

    @pytest.mark.parametrize(
        "arm",
        [
            f"{EXIT_REFS}) refs=$verdict ;;",
            f"{EXIT_DECLARED_NONE}) printf '%s\\n' \"$verdict\"; exit 0 ;;",
            "*) printf '%s\\n' \"$verdict\"; exit 1 ;;",
        ],
        ids=["refs", "declared-none", "anything-else-fails"],
    )
    def test_each_exit_code_maps_to_its_outcome(self, workflow_text: str, arm: str) -> None:
        assert arm in workflow_text
