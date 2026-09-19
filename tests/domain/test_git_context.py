"""GitContext bounds its own subprocesses (GH-1412) and owns the
common-dir lookup three modules used to hand-roll (GH-1445)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from dev10x.domain.git_context import GIT_TIMEOUT_SECONDS, GitContext


class _Recorder:
    """Stand in for ``subprocess.check_output`` and capture how it was called."""

    def __init__(self, *, result: str = "/repo", raises: BaseException | None = None) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append((args, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.result + "\n"

    @property
    def timeout(self) -> float | None:
        return self.calls[-1][1]["timeout"]

    @property
    def argv(self) -> list[str]:
        return list(self.calls[-1][0][0])


def _patch(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> None:
    monkeypatch.setattr(subprocess, "check_output", recorder)


def _timed_out() -> subprocess.TimeoutExpired:
    return subprocess.TimeoutExpired(cmd=["git"], timeout=GIT_TIMEOUT_SECONDS)


class TestDefaultTimeout:
    """Every accessor is bounded, including for callers that pass nothing.

    Fifteen call sites read ``toplevel``/``branch`` without opinions about
    timeouts; bounding the default is what makes them safe without edits.
    """

    def test_constant_is_bounded(self) -> None:
        assert GIT_TIMEOUT_SECONDS is not None
        assert GIT_TIMEOUT_SECONDS > 0

    def test_toplevel_passes_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder()
        _patch(monkeypatch, recorder)
        GitContext(cwd="/repo").toplevel
        assert recorder.timeout == GIT_TIMEOUT_SECONDS

    def test_branch_passes_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder(result="main")
        _patch(monkeypatch, recorder)
        GitContext(cwd="/repo").branch
        assert recorder.timeout == GIT_TIMEOUT_SECONDS

    def test_common_dir_passes_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder(result="/repo/.git")
        _patch(monkeypatch, recorder)
        GitContext(cwd="/repo").common_dir
        assert recorder.timeout == GIT_TIMEOUT_SECONDS

    def test_run_still_defaults_to_unbounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # run()'s signature is a documented contract; GH-1412 is about the
        # accessors that could not take a timeout at all.
        recorder = _Recorder()
        _patch(monkeypatch, recorder)
        GitContext(cwd="/repo").run("status")
        assert recorder.timeout is None


class TestExplicitTimeout:
    def test_instance_timeout_overrides_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder()
        _patch(monkeypatch, recorder)
        GitContext(cwd="/repo", timeout=0.25).toplevel
        assert recorder.timeout == 0.25

    def test_applies_to_every_accessor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder(result="main")
        _patch(monkeypatch, recorder)
        ctx = GitContext(cwd="/repo", timeout=0.25)
        ctx.branch
        ctx.common_dir
        assert [call[1]["timeout"] for call in recorder.calls] == [0.25, 0.25]


class TestTimeoutIsSurvivable:
    """A wedged git degrades to the documented fallback, it does not propagate."""

    def test_toplevel_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _Recorder(raises=_timed_out()))
        assert GitContext(cwd="/repo").toplevel is None

    def test_branch_returns_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _Recorder(raises=_timed_out()))
        assert GitContext(cwd="/repo").branch == "unknown"

    def test_common_dir_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _Recorder(raises=_timed_out()))
        assert GitContext(cwd="/repo").common_dir is None


class TestCommonDir:
    """GH-1445: one lookup, absolute, replacing three divergent hand-rolls."""

    def test_asks_for_an_absolute_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder(result="/repo/.git")
        _patch(monkeypatch, recorder)
        GitContext(cwd="/repo").common_dir
        assert "--path-format=absolute" in recorder.argv
        assert "--git-common-dir" in recorder.argv

    def test_returns_the_stripped_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _Recorder(result="/repo/.git"))
        assert GitContext(cwd="/repo").common_dir == "/repo/.git"

    def test_none_when_not_a_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        failure = subprocess.CalledProcessError(returncode=128, cmd=["git"])
        _patch(monkeypatch, _Recorder(raises=failure))
        assert GitContext(cwd="/tmp").common_dir is None

    def test_none_when_git_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _Recorder(raises=FileNotFoundError()))
        assert GitContext(cwd="/tmp").common_dir is None

    def test_cached_like_the_other_accessors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder(result="/repo/.git")
        _patch(monkeypatch, recorder)
        ctx = GitContext(cwd="/repo")
        ctx.common_dir
        ctx.common_dir
        assert len(recorder.calls) == 1

    def test_resolves_a_worktree_to_the_main_repo(self, tmp_path: Path) -> None:
        # Integration: in a real worktree the common dir is the MAIN repo's
        # .git, which is the whole reason preset_pin keys pins on it.
        main = tmp_path / "main"
        main.mkdir()
        subprocess.run(["git", "init", "-q", str(main)], check=True)
        # Identity via -c rather than env=, which would REPLACE the
        # environment and strand PATH at whatever this file hardcoded.
        subprocess.run(
            [
                "git",
                "-C",
                str(main),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "x",
            ],
            check=True,
        )
        linked = tmp_path / "wt"
        subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(linked)], check=True)
        assert GitContext(cwd=str(linked)).common_dir == str((main / ".git").resolve())
