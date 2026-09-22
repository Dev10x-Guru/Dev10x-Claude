"""End-to-end tests for check-top-level-comments.sh (GH-1468).

The script handed each surface's raw rows to jq as a command-line
argument (`--argjson extra "${COMMENTS_RAW}"`). Linux caps a single
argument at 128 KiB (MAX_ARG_STRLEN), so a PR whose top-level comments
added up past that made jq fail with "Argument list too long" — and
Check 1b, which treats a check that cannot run as a reason not to merge,
failed closed on exactly the busy PRs it exists for.

The filter tests cannot see this: the argv hand-off lives in the script,
so these drive the script itself against a stub `gh`.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "gh-pr-merge"
    / "scripts"
    / "check-top-level-comments.sh"
)

# Linux's per-argument ceiling: MAX_ARG_STRLEN is 32 pages of 4 KiB.
ARG_STRLEN_LIMIT = 128 * 1024

STUB_GH = (
    "#!/usr/bin/env bash\n"
    "# Serve each endpoint's fixture the way `gh api` would print it.\n"
    'case "$2" in\n'
    '  */comments) cat "${FAKE_GH_DIR}/comments.json" ;;\n'
    '  */reviews)  cat "${FAKE_GH_DIR}/reviews.json" ;;\n'
    '  *)          cat "${FAKE_GH_DIR}/pr_body.txt" ;;\n'
    "esac\n"
)

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not on PATH")


def _bot_row(cid: int, body: str, **fields: str) -> dict:
    return {"id": cid, "user": {"login": "review-bot", "type": "Bot"}, "body": body, **fields}


# Twenty 8 KiB bot comments with no severity token: history that is never
# a finding, only volume — the shape of a PR a review bot has been
# re-reviewing round after round.
BULK = [_bot_row(5000000000 + i, "x" * 8192) for i in range(20)]

FINDING = _bot_row(4900000001, "REQUIRED: add the missing timeout")


def _run_script(
    tmp_path: Path,
    *,
    comments: list[dict],
    reviews: list[dict],
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(STUB_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "comments.json").write_text(json.dumps(comments))
    (tmp_path / "reviews.json").write_text(json.dumps(reviews))
    (tmp_path / "pr_body.txt").write_text("")
    return subprocess.run(
        [str(SCRIPT), "owner", "repo", "1"],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_GH_DIR": str(tmp_path),
        },
    )


def test_bulk_history_is_past_the_per_argument_limit() -> None:
    """The premise, kept live so a shrunken fixture cannot pass vacuously."""
    assert len(json.dumps(BULK).encode()) > ARG_STRLEN_LIMIT


class TestLongHistoryDoesNotOverflowArgv:
    @pytest.mark.parametrize("bulky", ["comments", "reviews"])
    def test_findings_still_surface_behind_a_long_history(
        self, bulky: str, tmp_path: Path
    ) -> None:
        """Each surface is the other invocation's `$extra`, so both
        directions have to survive the volume."""
        surfaces: dict[str, list[dict]] = {"comments": [], "reviews": []}
        surfaces[bulky] = [*BULK, FINDING]
        result = _run_script(tmp_path, **surfaces)
        assert result.returncode == 0, result.stderr
        assert [row["id"] for row in json.loads(result.stdout)] == [FINDING["id"]]

    def test_keyed_reply_buried_in_a_long_history_still_disposes(self, tmp_path: Path) -> None:
        """The field shape: the reply sits among the bulky issue comments and
        the finding on the review surface, so the whole comment history
        reaches the review scan as `$extra` — the argument that overflowed.
        An empty result is only reachable if that history was actually read:
        ignored, the finding would still be reported."""
        review_finding = _bot_row(4839278701, "CRITICAL: the retry loop is unbounded")
        reply = {
            "id": 5159664533,
            "user": {"login": "maintainer", "type": "User"},
            "body": "Re: comment 4839278701 — fixed.",
        }
        result = _run_script(tmp_path, comments=[*BULK, reply], reviews=[review_finding])
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == []


class TestOutputShape:
    """`check_top_level_comments` buckets findings by `severity` and reports
    `source`; moving the payloads off argv must not change what it parses."""

    def test_findings_from_both_surfaces_concatenate_comments_first(self, tmp_path: Path) -> None:
        comment = _bot_row(101, "REQUIRED: add the guard")
        review = _bot_row(202, "INFO: consider a helper", state="COMMENTED")
        result = _run_script(tmp_path, comments=[comment], reviews=[review])
        assert json.loads(result.stdout) == [
            {
                "id": 101,
                "user": "review-bot",
                "snippet": "REQUIRED: add the guard",
                "source": "comment",
                "severity": "blocking",
            },
            {
                "id": 202,
                "user": "review-bot",
                "snippet": "INFO: consider a helper",
                "source": "review",
                "severity": "info",
            },
        ]

    def test_no_findings_is_an_empty_array(self, tmp_path: Path) -> None:
        result = _run_script(tmp_path, comments=[], reviews=[])
        assert json.loads(result.stdout) == []
