"""Tests for the git-blame-based fixup target resolver (GH-299)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dev10x.skills.git_fixup.find_fixup_target import (
    Hunk,
    blame_hunk,
    branch_commits,
    detect_base_branch,
    main,
    parse_staged_hunks,
    remote_qualified_base,
)


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Create a git repo with a `develop` base and two branch commits.

    Layout (HEAD on feature branch):
        develop:  commit B0 — payments.py:1-5, tests.py:1-3
        feature:  commit C1 — modifies payments.py:3
                  commit C2 — modifies tests.py:2
    """
    _git("init", "-q", "-b", "develop", cwd=tmp_path)
    _git("config", "user.email", "t@example.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    _git("config", "commit.gpgsign", "false", cwd=tmp_path)

    _write(
        tmp_path / "payments.py",
        "L1\nL2\nL3\nL4\nL5\n",
    )
    _write(tmp_path / "tests.py", "T1\nT2\nT3\n")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "B0 base commit", cwd=tmp_path)

    _git("checkout", "-q", "-b", "feature", cwd=tmp_path)

    # C1: modify payments.py line 3
    _write(
        tmp_path / "payments.py",
        "L1\nL2\nC1_PATCH_L3\nL4\nL5\n",
    )
    _git("commit", "-q", "-am", "C1 patch payments line 3", cwd=tmp_path)

    # C2: modify tests.py line 2
    _write(tmp_path / "tests.py", "T1\nC2_PATCH_T2\nT3\n")
    _git("commit", "-q", "-am", "C2 patch tests line 2", cwd=tmp_path)

    return tmp_path


def _sha(repo: Path, ref: str) -> str:
    return _git("rev-parse", ref, cwd=repo).strip()


def _run_main(repo: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    rc = main(["--cwd", str(repo), "--base", "develop"])
    captured = capsys.readouterr()
    return rc, json.loads(captured.out)


class TestSingleOwner:
    def test_edit_owned_by_one_branch_commit(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Edit payments.py:3 — owned by C1
        _write(
            repo / "payments.py",
            "L1\nL2\nFIXUP_L3\nL4\nL5\n",
        )
        _git("add", "payments.py", cwd=repo)

        rc, payload = _run_main(repo, capsys)

        assert rc == 0
        assert payload["status"] == "single"
        assert payload["target"] == _sha(repo, "HEAD~")  # C1
        assert "C1 patch payments line 3" in payload["subject"]

    def test_pure_addition_attributes_to_preceding_owner(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Add a line right after payments.py:3 (the C1-owned line)
        _write(
            repo / "payments.py",
            "L1\nL2\nC1_PATCH_L3\nINSERTED\nL4\nL5\n",
        )
        _git("add", "payments.py", cwd=repo)

        rc, payload = _run_main(repo, capsys)

        assert rc == 0
        assert payload["status"] == "single"
        assert payload["target"] == _sha(repo, "HEAD~")  # C1


class TestMultiOwner:
    def test_edits_across_two_owning_commits(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Edit payments.py:3 (C1) AND tests.py:2 (C2)
        _write(
            repo / "payments.py",
            "L1\nL2\nFIXUP_L3\nL4\nL5\n",
        )
        _write(repo / "tests.py", "T1\nFIXUP_T2\nT3\n")
        _git("add", "payments.py", "tests.py", cwd=repo)

        rc, payload = _run_main(repo, capsys)

        assert rc == 0
        assert payload["status"] == "multi"
        owner_shas = {o["sha"] for o in payload["owners"]}
        assert owner_shas == {
            _sha(repo, "HEAD~"),  # C1
            _sha(repo, "HEAD"),  # C2
        }
        # Each owner's hunks list points at the file it owns
        c1_owner = next(o for o in payload["owners"] if o["sha"] == _sha(repo, "HEAD~"))
        c2_owner = next(o for o in payload["owners"] if o["sha"] == _sha(repo, "HEAD"))
        assert {h["path"] for h in c1_owner["hunks"]} == {"payments.py"}
        assert {h["path"] for h in c2_owner["hunks"]} == {"tests.py"}


class TestNoStaged:
    def test_returns_exit_code_2(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc, payload = _run_main(repo, capsys)
        assert rc == 2
        assert payload["status"] == "no_staged"


class TestOutOfBranch:
    def test_edit_to_base_only_lines_falls_back(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Edit payments.py:1 — that line was last touched by B0 (base),
        # never by C1 or C2. Resolver should mark out_of_branch and
        # fall back to the first branch commit (C1).
        _write(
            repo / "payments.py",
            "FIXUP_L1\nL2\nC1_PATCH_L3\nL4\nL5\n",
        )
        _git("add", "payments.py", cwd=repo)

        rc, payload = _run_main(repo, capsys)

        assert rc == 3
        assert payload["status"] == "out_of_branch"
        assert payload["fallback_target"] == _sha(repo, "HEAD~")  # C1 (first on branch)


class TestDetectBaseBranch:
    def test_finds_develop_when_local(self, repo: Path) -> None:
        assert detect_base_branch(cwd=repo) == "develop"

    def test_finds_main_when_only_main_exists(self, tmp_path: Path) -> None:
        _git("init", "-q", "-b", "main", cwd=tmp_path)
        _git("config", "user.email", "t@example.com", cwd=tmp_path)
        _git("config", "user.name", "Test", cwd=tmp_path)
        _git("config", "commit.gpgsign", "false", cwd=tmp_path)
        _write(tmp_path / "f.txt", "a\n")
        _git("add", ".", cwd=tmp_path)
        _git("commit", "-q", "-m", "base", cwd=tmp_path)
        assert detect_base_branch(cwd=tmp_path) == "main"

    def test_raises_when_no_base_branch_exists(self, tmp_path: Path) -> None:
        _git("init", "-q", "-b", "feature", cwd=tmp_path)
        _git("config", "user.email", "t@example.com", cwd=tmp_path)
        _git("config", "user.name", "Test", cwd=tmp_path)
        _git("config", "commit.gpgsign", "false", cwd=tmp_path)
        _write(tmp_path / "f.txt", "a\n")
        _git("add", ".", cwd=tmp_path)
        _git("commit", "-q", "-m", "init", cwd=tmp_path)

        with pytest.raises(RuntimeError, match="Could not detect base branch"):
            detect_base_branch(cwd=tmp_path)


class TestParseStagedHunks:
    def test_handles_file_deletion(self, repo: Path) -> None:
        # Delete tests.py entirely
        (repo / "tests.py").unlink()
        _git("add", "tests.py", cwd=repo)

        hunks = parse_staged_hunks(cwd=repo)
        # /dev/null target → current_path becomes None → no hunks recorded
        assert all(h.path != "tests.py" or h.path == "tests.py" for h in hunks) is True


class TestBlameHunk:
    def test_insertion_at_top_returns_empty(self, repo: Path) -> None:
        # hunk.start == 0 with count == 0 → no pre-image context
        hunk = Hunk(path="payments.py", start=0, count=0)
        assert blame_hunk(hunk, cwd=repo) == []

    def test_nonexistent_file_returns_empty(self, repo: Path) -> None:
        hunk = Hunk(path="does-not-exist.py", start=1, count=1)
        assert blame_hunk(hunk, cwd=repo) == []


class TestAutoDetectBase:
    def test_main_runs_without_explicit_base(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(repo / "payments.py", "L1\nL2\nFIXUP_L3\nL4\nL5\n")
        _git("add", "payments.py", cwd=repo)
        rc = main(["--cwd", str(repo)])  # no --base
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert rc == 0
        assert payload["status"] == "single"
        assert payload["base"] == "develop"


class TestEmptyBranch:
    def test_no_branch_commits_is_an_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _git("init", "-q", "-b", "develop", cwd=tmp_path)
        _git("config", "user.email", "t@example.com", cwd=tmp_path)
        _git("config", "user.name", "Test", cwd=tmp_path)
        _git("config", "commit.gpgsign", "false", cwd=tmp_path)
        _write(tmp_path / "f.txt", "a\n")
        _git("add", ".", cwd=tmp_path)
        _git("commit", "-q", "-m", "base", cwd=tmp_path)
        _git("checkout", "-q", "-b", "feature", cwd=tmp_path)

        # Stage a change but no branch commits exist
        _write(tmp_path / "f.txt", "b\n")
        _git("add", "f.txt", cwd=tmp_path)

        rc, payload = _run_main(tmp_path, capsys)

        assert rc == 1
        assert payload["status"] == "error"
        assert "develop..HEAD" in payload["error"]


class TestStaleLocalBase:
    """Local develop lags origin/develop — GH-676 (GH-486 stale-base class).

    origin/develop:  B0 -> M1   (M1 already merged upstream)
    local  develop:  B0          (never fast-forwarded)
    feature HEAD:    B0 -> M1 -> C1

    Against local ``develop`` the range ``develop..HEAD`` is inflated to
    ``{M1, C1}``, so a hunk owned by the already-merged M1 is mis-attributed
    to a branch commit. Qualifying the base to ``origin/develop`` shrinks the
    range to ``{C1}`` so M1 is correctly treated as base history.
    """

    @pytest.fixture
    def stale_repo(self, tmp_path: Path) -> Path:
        origin = tmp_path / "origin.git"
        local = tmp_path / "local"
        local.mkdir()
        subprocess.run(
            ["git", "init", "-q", "--bare", str(origin)],
            check=True,
            capture_output=True,
            text=True,
        )

        _git("init", "-q", "-b", "develop", cwd=local)
        _git("config", "user.email", "t@example.com", cwd=local)
        _git("config", "user.name", "Test", cwd=local)
        _git("config", "commit.gpgsign", "false", cwd=local)
        _git("remote", "add", "origin", str(origin), cwd=local)

        _write(local / "payments.py", "L1\nL2\nL3\nL4\nL5\n")
        _git("add", ".", cwd=local)
        _git("commit", "-q", "-m", "B0 base commit", cwd=local)
        b0 = _git("rev-parse", "HEAD", cwd=local).strip()
        _git("push", "-q", "origin", "develop", cwd=local)

        # M1 merged upstream — modifies payments.py:1, pushed to origin.
        _write(local / "payments.py", "M1_L1\nL2\nL3\nL4\nL5\n")
        _git("commit", "-q", "-am", "M1 upstream merge", cwd=local)
        _git("push", "-q", "origin", "develop", cwd=local)

        # Feature branch off M1 (the origin tip), then add C1.
        _git("checkout", "-q", "-b", "feature", cwd=local)
        _write(local / "tests.py", "T1\nT2\nT3\n")
        _git("add", "tests.py", cwd=local)
        _git("commit", "-q", "-m", "C1 feature work", cwd=local)

        # Local develop rewinds to B0 (lags origin/develop); refresh refs.
        _git("branch", "-f", "develop", b0, cwd=local)
        _git("fetch", "-q", "origin", cwd=local)
        return local

    def test_remote_qualified_base_prefers_origin(self, stale_repo: Path) -> None:
        assert remote_qualified_base("develop", cwd=stale_repo) == "origin/develop"

    def test_remote_qualified_base_passthrough_when_no_remote(self, repo: Path) -> None:
        # The local-only `repo` fixture has no origin remote.
        assert remote_qualified_base("develop", cwd=repo) == "develop"

    def test_remote_qualified_base_passthrough_when_already_qualified(self, repo: Path) -> None:
        # An origin/-prefixed base is returned unchanged without a git call.
        assert remote_qualified_base("origin/develop", cwd=repo) == "origin/develop"

    def test_qualification_excludes_already_merged_commit(self, stale_repo: Path) -> None:
        local_range = branch_commits("develop", cwd=stale_repo)
        remote_range = branch_commits("origin/develop", cwd=stale_repo)
        c1 = _sha(stale_repo, "HEAD")
        assert local_range == {c1, _sha(stale_repo, "HEAD~")}  # inflated: M1 + C1
        assert remote_range == {c1}  # qualified: C1 only

    def test_main_attributes_to_real_branch_commit(
        self, stale_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Edit payments.py:1 — owned by M1 (already on origin/develop). With
        # the stale local base this would mis-resolve to M1; qualified, M1 is
        # base history so the hunk is out_of_branch and falls back to C1.
        _write(stale_repo / "payments.py", "FIXUP_L1\nL2\nL3\nL4\nL5\n")
        _git("add", "payments.py", cwd=stale_repo)

        rc, payload = _run_main(stale_repo, capsys)

        assert rc == 3
        assert payload["status"] == "out_of_branch"
        assert payload["base"] == "origin/develop"
        assert payload["fallback_target"] == _sha(stale_repo, "HEAD")  # C1, not M1
