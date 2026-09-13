"""A leased force-push must not overwrite a base it has not seen (GH-1270).

``--force-with-lease`` reads as the safe spelling and is allowed on every
branch, but the lease compares the remote against the LOCAL
remote-tracking ref. A ``develop`` last fetched hours ago therefore
leases cleanly against its own stale copy and overwrites every merge
landed since — seven PRs were erased that way in eleven minutes, with
git reporting success and ``git diff`` showing nothing because the two
tips shared a tree.

These tests drive the real script against real repositories: the defect
lives in how git resolves a lease, so a mock of git would assert only
that the mock was written to agree with the fix.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).parents[2] / "skills" / "git" / "scripts" / "git-push-safe.sh"
_GROOM = Path(__file__).parents[2] / "skills" / "git" / "scripts" / "git-rebase-groom.sh"
_TIMEOUT_SECONDS = 30

# Ignore the developer's own git config. Without this the suite passes on
# any machine carrying a global identity and fails on a CI runner without
# one — putting the failure where it cannot be reproduced. Repo-local
# config is unaffected, so the identity these fixtures set still applies.
_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        env=_ENV,
        timeout=_TIMEOUT_SECONDS,
    ).stdout.strip()


def _init_repo(path: Path, *, branch: str, bare: bool = False) -> Path:
    """Create a repo carrying its own committer identity.

    The identity is repo-local rather than a `-c` prefix on each call:
    these tests also run the groom script as a subprocess, which commits
    during its rebase and inherits nothing from the caller's argv. A CI
    runner has no global identity, so a `-c` prefix passes locally and
    fails there with "empty ident name".
    """
    subprocess.run(
        ["git", "init", "-q", *(["--bare"] if bare else []), "-b", branch, str(path)],
        check=True,
        env=_ENV,
        timeout=_TIMEOUT_SECONDS,
    )
    if not bare:
        _git("config", "user.name", "test", cwd=path)
        _git("config", "user.email", "test@example.com", cwd=path)
    return path


def _clone(remote: Path, into: Path) -> Path:
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(into)],
        check=True,
        env=_ENV,
        timeout=_TIMEOUT_SECONDS,
    )
    _git("config", "user.name", "test", cwd=into)
    _git("config", "user.email", "test@example.com", cwd=into)
    return into


def _commit(message: str, *, cwd: Path) -> None:
    """Commit a file unique to `message`.

    Deliberately not `--allow-empty`: empty commits all share one
    patch-id, so `git rev-list --cherry-pick` reads any two of them as
    the same change and the groom's base-moved guard drops a commit the
    base never contained.
    """
    slug = re.sub(r"\W+", "-", message).strip("-")[:40]
    (cwd / f"{slug}.txt").write_text(message, encoding="utf-8")
    _git("add", "-A", cwd=cwd)
    _git("commit", "-q", "-m", message, cwd=cwd)


@pytest.fixture()
def stale_clone(tmp_path: Path) -> tuple[Path, str]:
    """A checkout whose `main` is behind origin without knowing it.

    `peer` pushes a commit that `work` never fetches, so `work`'s
    remote-tracking ref still names the old tip — the exact state in
    which a lease is satisfied while the push destroys the peer's commit.
    Rewriting `work`'s own tip is what makes the push a force at all.
    """
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    peer = tmp_path / "peer"

    _init_repo(remote, branch="main", bare=True)
    _init_repo(work, branch="main")
    _commit("root", cwd=work)
    _git("remote", "add", "origin", str(remote), cwd=work)
    _git("push", "-q", "-u", "origin", "main", cwd=work)

    _clone(remote, peer)
    _commit("peer work nobody has fetched", cwd=peer)
    _git("push", "-q", "origin", "main", cwd=peer)

    _git("commit", "-q", "--amend", "-m", "rewritten root", cwd=work)
    return work, _git("rev-parse", "HEAD", cwd=peer)


def _payload(*args: str, cwd: Path) -> dict[str, Any]:
    """Run the script and parse its JSON verdict.

    Parsed with ``json.loads`` rather than a regex over quoted pairs:
    ``pushed`` is an unquoted boolean, so a string-only pattern drops it
    and every assertion about it silently reads ``None``.
    """
    result = subprocess.run(
        [str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_ENV,
        timeout=_TIMEOUT_SECONDS,
    )
    payload = json.loads(result.stdout.strip())
    payload["stderr"] = result.stderr
    return payload


class TestLeasedForcePushToAProtectedBranch:
    def test_a_lease_against_a_stale_ref_is_refused(self, stale_clone) -> None:
        work, _ = stale_clone

        payload = _payload("--force-with-lease", "origin", "main", cwd=work)

        assert payload.get("blocked_reason") == "base_behind_remote"

    def test_the_refusal_names_the_commits_that_would_be_lost(self, stale_clone) -> None:
        # A bare refusal is not actionable: the whole failure mode is that
        # the loss is invisible, so the message has to make it visible.
        work, _ = stale_clone

        payload = _payload("--force-with-lease", "origin", "main", cwd=work)

        assert "peer work nobody has fetched" in payload["stderr"]

    def test_the_peer_commit_survives_the_refusal(self, stale_clone) -> None:
        work, peer_sha = stale_clone

        _payload("--force-with-lease", "origin", "main", cwd=work)

        assert peer_sha in _git("ls-remote", "origin", "refs/heads/main", cwd=work)

    def test_a_lease_that_contains_the_remote_tip_still_pushes(self, stale_clone) -> None:
        # The gate refuses a push that DROPS commits, not every rewrite —
        # a groom rebased onto the current remote tip must still land.
        work, _ = stale_clone
        _git("fetch", "-q", "origin", "main", cwd=work)
        _git("reset", "-q", "--hard", "origin/main", cwd=work)
        _commit("work rebased onto the real tip", cwd=work)

        payload = _payload("--force-with-lease", "origin", "main", cwd=work)

        assert payload["pushed"] is True
        assert payload["ref"] == "main"

    def test_an_unprotected_branch_is_left_alone(self, stale_clone) -> None:
        # Feature branches are force-pushed constantly and deliberately;
        # widening the gate to them would break the everyday groom.
        work, _ = stale_clone
        _git("checkout", "-q", "-b", "feature", cwd=work)

        payload = _payload("--force-with-lease", "origin", "feature", cwd=work)

        assert payload["pushed"] is True

    def test_a_plain_push_is_never_gated(self, stale_clone) -> None:
        # Without a force spelling git rejects a non-fast-forward itself,
        # and that rejection is the honest one — the gate must not
        # pre-empt it with a different reason.
        work, _ = stale_clone

        payload = _payload("origin", "main", cwd=work)

        assert payload["blocked_reason"] == "push_failed"


class TestTheGateWhenTheRemoteCannotBeRead:
    """An unverifiable force-push is refused, not waved through.

    This is the branch where the gate can fail open, so it is the one
    most worth exercising: reading empty `ls-remote` output as "the
    branch does not exist" would allow exactly the push the gate exists
    to stop, on precisely the runs where the remote is broken.
    """

    def test_an_unreachable_remote_refuses_the_push(self, stale_clone, tmp_path) -> None:
        work, _ = stale_clone
        _git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=work)

        payload = _payload("--force-with-lease", "origin", "main", cwd=work)

        assert payload["blocked_reason"] == "base_fetch_failed"

    def test_a_branch_absent_from_the_remote_has_nothing_to_lose(self, stale_clone) -> None:
        # `main` exists remotely, but a protected branch that has never
        # been pushed cannot drop anything, so the gate must not block it.
        work, _ = stale_clone
        _git("checkout", "-q", "-b", "staging", cwd=work)

        payload = _payload("--force-with-lease", "origin", "staging", cwd=work)

        assert payload["pushed"] is True


class TestGroomRefusesAStaleLocalBase:
    """The rewrite half of the same incident (GH-1270).

    The push is what destroys the commits, but the groom is what builds
    the branch that drops them: rebasing onto a local `develop` fetched
    the previous evening replays every commit over a base that never
    contained the day's merges, and still prints "Successfully rebased".
    """

    @pytest.fixture()
    def repo_with_stale_local_base(self, tmp_path: Path) -> tuple[Path, Path]:
        remote = tmp_path / "remote.git"
        work = tmp_path / "work"
        peer = tmp_path / "peer"

        _init_repo(remote, branch="develop", bare=True)
        _init_repo(work, branch="develop")
        _commit("root", cwd=work)
        _git("remote", "add", "origin", str(remote), cwd=work)
        _git("push", "-q", "-u", "origin", "develop", cwd=work)

        _clone(remote, peer)
        _commit("merge that landed this morning", cwd=peer)
        _git("push", "-q", "origin", "develop", cwd=peer)

        _git("checkout", "-q", "-b", "feature", cwd=work)
        _commit("feature work", cwd=work)

        seq_file = tmp_path / "seq.txt"
        sha = _git("rev-parse", "--short", "HEAD", cwd=work)
        seq_file.write_text(f"pick {sha} feature work\n", encoding="utf-8")
        return work, seq_file

    def _groom(self, base_ref: str, *, work: Path, seq_file: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(_GROOM), str(seq_file), base_ref],
            capture_output=True,
            text=True,
            cwd=work,
            env=_ENV,
            timeout=_TIMEOUT_SECONDS,
        )

    def test_a_stale_local_base_is_refused(self, repo_with_stale_local_base) -> None:
        work, seq_file = repo_with_stale_local_base

        result = self._groom("develop", work=work, seq_file=seq_file)

        assert result.returncode == 1
        assert "is behind" in result.stderr

    def test_the_refusal_names_the_missing_merge(self, repo_with_stale_local_base) -> None:
        work, seq_file = repo_with_stale_local_base

        result = self._groom("develop", work=work, seq_file=seq_file)

        assert "merge that landed this morning" in result.stderr

    def test_the_remote_tracking_ref_is_accepted(self, repo_with_stale_local_base) -> None:
        # `origin/develop` is the spelling the refusal recommends, so it
        # must actually work — otherwise the guidance is a dead end.
        work, seq_file = repo_with_stale_local_base
        _git("fetch", "-q", "origin", "develop", cwd=work)

        result = self._groom("origin/develop", work=work, seq_file=seq_file)

        # returncode, not just the absence of the refusal string: "is
        # behind" is missing before the fix too, and missing for any
        # other failure, so on its own it pins nothing.
        assert result.returncode == 0, result.stderr


class TestDocumentedBlockedReasonsMatchTheScript:
    """The payload contract is what callers branch on, so pin it."""

    def test_the_script_emits_both_new_reasons(self) -> None:
        source = _SCRIPT.read_text(encoding="utf-8")

        assert '"blocked_reason":"base_behind_remote"' in source
        assert '"blocked_reason":"base_fetch_failed"' in source

    def test_the_skill_documents_the_new_reason(self) -> None:
        skill = (Path(__file__).parents[2] / "skills" / "git" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        assert "base_behind_remote" in skill

    def test_the_refusal_exits_non_zero(self, stale_clone) -> None:
        # Shell callers branch on the exit code, not the payload.
        work, _ = stale_clone
        result = subprocess.run(
            [str(_SCRIPT), "--force-with-lease", "origin", "main"],
            capture_output=True,
            text=True,
            cwd=work,
            env=_ENV,
            timeout=_TIMEOUT_SECONDS,
        )

        assert result.returncode == 2
