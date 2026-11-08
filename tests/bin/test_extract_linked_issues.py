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
        ],
    )
    def test_body_without_explicit_none_reports_nothing(self, body: str) -> None:
        assert explicit_none_reason(body=body) is None

    def test_partial_delivery_body_closes_nothing(self) -> None:
        # The parent named after `part of` must stay open -- that is the
        # trailer's whole purpose.
        assert extract(body=_PARTIAL_DELIVERY_BODY, repo=REPO) == []


class TestCli:
    @pytest.mark.parametrize(
        ("argv", "body", "expected"),
        [
            (["--repo", REPO], "Fixes: GH-7\n", f"{REPO}#7\n"),
            (["--repo", REPO], _PARTIAL_DELIVERY_BODY, ""),
            (["--explicit-none"], _PARTIAL_DELIVERY_BODY, "part of #909\n"),
            (["--explicit-none"], "Fixes: GH-7\n", ""),
        ],
    )
    def test_main_prints_one_mode_per_flag(
        self,
        argv: list[str],
        body: str,
        expected: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.argv", ["extract-linked-issues.py", *argv])
        monkeypatch.setattr("sys.stdin", io.StringIO(body))

        assert extract_linked_issues.main() == 0
        assert capsys.readouterr().out == expected

    def test_main_requires_repo_unless_explicit_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.argv", ["extract-linked-issues.py"])
        monkeypatch.setattr("sys.stdin", io.StringIO("Fixes: GH-7\n"))

        with pytest.raises(SystemExit):
            extract_linked_issues.main()


class TestWorkflowWiring:
    """The workflow must consult the explicit-none mode before failing."""

    @pytest.fixture
    def empty_refs_block(self) -> str:
        text = _WORKFLOW.read_text(encoding="utf-8")
        start = text.index('if [ -z "$refs" ]; then')
        end = text.index("\n          fi\n", start)
        return text[start:end]

    def test_only_a_declared_reason_exits_green_before_the_loud_failure(
        self,
        empty_refs_block: str,
    ) -> None:
        markers = [
            "--explicit-none",
            'if [ -n "$reason" ]; then',
            "exit 0",
            "\n            fi\n",
            "::error::",
            "exit 1",
        ]

        positions = [empty_refs_block.index(marker) for marker in markers]

        assert positions == sorted(positions)
