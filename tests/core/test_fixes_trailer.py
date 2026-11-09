from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from dev10x.domain.pr_body import has_fixes_trailer

from dev10x.core.fixes_trailer import explicit_none_reason

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


_NONE_TRAILERS = {
    "em-dash-reason": "Fixes: none — part of #909",
    "hyphen-reason": "Fixes: none - self-motivated",
    "uppercase": "FIXES: NONE — self-motivated",
    "bare": "Fixes: none",
    "dash-only": "Fixes: none —",
    "punctuation-only": "Fixes: none — —",
    "placeholder": "Fixes: none — <reason>",
    "no-dash": "Fixes: none of the above",
    "fenced-example-then-bare": "```\nFixes: none — part of #909\n```\nFixes: none",
    "commented-example-then-bare": "<!-- Fixes: none — part of #909 -->\nFixes: none",
    "unclosed-fence": "```\nFixes: none — part of #909",
}


class TestCreationAndMergeAgree:
    """GH-1873: a none trailer create_pr accepts is one close-issues accepts."""

    @pytest.mark.parametrize("trailer", _NONE_TRAILERS.values(), ids=_NONE_TRAILERS.keys())
    def test_both_ends_reach_the_same_verdict(self, trailer: str) -> None:
        body = f"**When** a slice lands, **a maintainer wants** it.\n\n{trailer}"

        assert has_fixes_trailer(body=body) == (explicit_none_reason(body=body) is not None)
