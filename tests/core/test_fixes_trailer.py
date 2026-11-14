from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from dev10x.domain.pr_body import has_fixes_trailer

from dev10x.core.fixes_trailer import EXIT_MISSING, verdict

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
_PROBE_TIMEOUT_SECONDS = 30
_IMPORT_PROBE = """
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
before = set(sys.modules)
importlib.import_module(sys.argv[2])
loaded = {name.split(".")[0] for name in set(sys.modules) - before}
print(json.dumps(sorted(loaded - set(sys.stdlib_module_names) - {"dev10x"})))
"""


@pytest.fixture(scope="module")
def third_party_imports() -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-I", "-c", _IMPORT_PROBE, str(_SRC_ROOT), "dev10x.core.fixes_trailer"],
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_SECONDS,
        check=True,
    )
    return json.loads(completed.stdout)


class TestStdlibOnly:
    def test_close_issues_shim_can_import_the_grammar_without_dependencies(
        self,
        third_party_imports: list[str],
    ) -> None:
        assert third_party_imports == []


_REPO = "Dev10x-Guru/Dev10x-Claude"
_TRAILERS = {
    "em-dash-reason": ("Fixes: none — part of #909", True),
    "hyphen-reason": ("Fixes: none - self-motivated", True),
    "uppercase": ("FIXES: NONE — self-motivated", True),
    "crlf-reason": ("Fixes: none — part of #909\r\n", True),
    "reference-beside-bare": ("Fixes: GH-7\nFixes: none", True),
    "reference-above-separate-bare": ("Fixes: #7\n\nFixes: none", True),
    "bare": ("Fixes: none", False),
    "dash-only": ("Fixes: none —", False),
    "punctuation-only": ("Fixes: none — —", False),
    "underscore-only": ("Fixes: none — _", False),
    "placeholder": ("Fixes: none — <reason>", False),
    "no-dash": ("Fixes: none of the above", False),
    "fenced-example-then-bare": ("```\nFixes: none — part of #909\n```\nFixes: none", False),
    "commented-example-then-bare": ("<!-- Fixes: none — part of #909 -->\nFixes: none", False),
    "unclosed-fence": ("```\nFixes: none — part of #909", False),
    "indented-reason": ("  Fixes: none — part of #909", True),
    "indented-bare": ("  Fixes: none", False),
    "commented-reason-only": ("<!-- Fixes: none — part of #909 -->", False),
    "reference": ("Fixes: #123", True),
    "indented-reference": ("  Fixes: #123", True),
    "commented-reference-only": ("<!-- Fixes: #123 -->", False),
    "fenced-reference-only": ("```\nFixes: #123\n```", False),
    "commented-reference-then-bare": ("<!-- Fixes: #123 -->\nFixes: none", False),
    "non-ascii-number": ("Fixes: #١٢٣", False),
    "number-glued-to-a-word-character": ("Fixes: GH-12_", False),
    "url": (f"Fixes: https://github.com/{_REPO}/issues/123", True),
    "closes-url-beside-fixes": (
        f"Closes https://github.com/{_REPO}/issues/9\nFixes: #123",
        True,
    ),
    "refs-url-only": (f"Refs: https://github.com/{_REPO}/issues/123", False),
    "url-glued-to-the-colon": (f"Fixes:https://github.com/{_REPO}/issues/123", False),
}


class TestCreationAndMergeAgree:
    """GH-1873, GH-1896: a trailer create_pr accepts is one close-issues accepts."""

    @pytest.fixture(params=_TRAILERS.values(), ids=list(_TRAILERS))
    def case(self, request: pytest.FixtureRequest) -> tuple[str, bool]:
        trailer, expected = request.param
        return f"**When** a slice lands, **a maintainer wants** it.\n\n{trailer}", expected

    def test_create_pr_accepts_exactly_the_expected_bodies(self, case: tuple[str, bool]) -> None:
        body, expected = case

        assert has_fixes_trailer(body=body) is expected

    def test_close_issues_passes_exactly_the_expected_bodies(
        self,
        case: tuple[str, bool],
    ) -> None:
        body, expected = case
        code, _ = verdict(body=body, repo=_REPO)

        assert (code != EXIT_MISSING) is expected
