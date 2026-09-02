"""End-to-end tests for ``skills/git/scripts/git-rebase-groom.sh`` (GH-1103).

The base-moved guard protects against silent history corruption: when the
base already contains a branch's commits, ``git rebase -i`` drops the
``pick`` as already-applied and replays the trailing ``fixup`` onto
whatever sits at the base tip — fusing the fix into a foreign commit and
losing the feature commit. Only a real repository exercises that path, so
these tests build one rather than mocking the script away.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

GROOM_SCRIPT = (
    Path(__file__).resolve().parents[2] / "skills" / "git" / "scripts" / "git-rebase-groom.sh"
)

_SUBPROCESS_TIMEOUT_SECONDS = 60


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )
    return result.stdout.strip()


def _commit(repo: Path, filename: str, contents: str, message: str) -> str:
    (repo / filename).write_text(contents)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "--short", "HEAD")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repo with `main`, a `feature` branch carrying one commit + a fixup."""
    _git(tmp_path, "init", "-q", "-b", "main", ".")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "tester")
    _commit(tmp_path, "base.txt", "base\n", "base")
    return tmp_path


@pytest.fixture()
def feature_with_fixup(repo: Path) -> tuple[Path, str, str]:
    _git(repo, "checkout", "-qb", "feature")
    feature_sha = _commit(repo, "feature.txt", "feature\n", "feat: the work")
    fixup_sha = _commit(repo, "feature.txt", "feature\ntweak\n", "fixup! feat: the work")
    return repo, feature_sha, fixup_sha


def _write_seq(repo: Path, feature_sha: str, fixup_sha: str) -> Path:
    seq = repo / "seq.txt"
    seq.write_text(f"pick {feature_sha} feat: the work\nfixup {fixup_sha} fixup! feat: the work\n")
    return seq


def _run_groom(repo: Path, seq: Path, base_ref: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(GROOM_SCRIPT), str(seq), base_ref],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )


class TestBaseMovedGuard:
    def test_refuses_when_base_already_contains_the_picked_commit(
        self,
        feature_with_fixup: tuple[Path, str, str],
    ) -> None:
        repo, feature_sha, fixup_sha = feature_with_fixup

        # Reproduce a rebase-merged PR: main advances first, THEN absorbs
        # the branch's patch — so the replayed commit has a different SHA
        # and only patch-id matching can detect the duplication.
        _git(repo, "checkout", "-q", "main")
        _commit(repo, "other.txt", "other\n", "unrelated main commit")
        _git(repo, "cherry-pick", feature_sha)
        _git(repo, "checkout", "-q", "feature")

        tip_before = _git(repo, "rev-parse", "HEAD")
        seq = _write_seq(repo, feature_sha, fixup_sha)

        result = _run_groom(repo, seq, "main")

        assert result.returncode != 0
        assert "refusing to groom" in result.stderr
        assert feature_sha in result.stderr
        assert _git(repo, "rev-parse", "HEAD") == tip_before

    def test_ordinary_groom_still_squashes_the_fixup(
        self,
        feature_with_fixup: tuple[Path, str, str],
    ) -> None:
        repo, feature_sha, fixup_sha = feature_with_fixup
        seq = _write_seq(repo, feature_sha, fixup_sha)

        result = _run_groom(repo, seq, "main")

        assert result.returncode == 0
        assert _git(repo, "rev-list", "--count", "main..HEAD") == "1"
        assert (repo / "feature.txt").read_text() == "feature\ntweak\n"
