"""Tests for bin/extract-linked-issues.py (GH-1196).

The bug this covers: PR #1193 merged with eight `Fixes: GH-N` lines and
`close-issues.yml` closed none of them, reporting success. The extractor
required a full URL; the bare-ID form the repo's own commit convention
uses matched nothing. Every shape below is one a real PR body has used.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT = _REPO_ROOT / "bin" / "extract-linked-issues.py"

_spec = importlib.util.spec_from_file_location("extract_linked_issues", _SCRIPT)
assert _spec is not None and _spec.loader is not None
extract_linked_issues = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_linked_issues)

extract = extract_linked_issues.extract

REPO = "Dev10x-Guru/Dev10x-Claude"


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
