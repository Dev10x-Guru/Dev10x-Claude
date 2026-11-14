"""Tests for the review-pack video freshness check (GH-1828)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "video_freshness",
    _repo_root / "plugins" / "qa" / "skills" / "review-pack" / "scripts" / "video-freshness.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

EARLY = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
LATE = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def _commit(when: datetime, sha: str = "a" * 40) -> object:
    return _mod.UiCommit(sha=sha, author_date=when, subject="Tweak button")


def _recording(when: datetime) -> object:
    return _mod.Recording(label="take.webm", recorded_at=when, source="recorded-at")


class TestParseTimestamp:
    def test_normalises_an_offset_to_utc(self):
        assert _mod.parse_timestamp("2026-11-01T12:00:00+02:00") == EARLY

    def test_accepts_a_zulu_suffix(self):
        assert _mod.parse_timestamp("2026-11-01T10:00:00Z") == EARLY

    def test_rejects_a_naive_timestamp(self):
        with pytest.raises(_mod.ToolingError, match="no UTC offset"):
            _mod.parse_timestamp("2026-11-01T10:00:00")

    def test_rejects_garbage(self):
        with pytest.raises(_mod.ToolingError, match="not an ISO-8601"):
            _mod.parse_timestamp("yesterday")


class TestPathspecs:
    def test_prefixes_glob_magic(self):
        assert _mod.pathspecs(["**/*.tsx"]) == [":(glob)**/*.tsx"]

    def test_keeps_an_explicit_magic_pathspec(self):
        assert _mod.pathspecs([":(glob)web/**"]) == [":(glob)web/**"]


class TestParseLog:
    def test_reads_sha_author_date_and_subject(self):
        output = f"{'b' * 40}\x1f2026-11-01T10:00:00+00:00\x1fFix: a\x1fb\n\n"

        (commit,) = _mod.parse_log(output)

        assert commit == _mod.UiCommit(sha="b" * 40, author_date=EARLY, subject="Fix: a\x1fb")

    def test_empty_output_yields_no_commits(self):
        assert _mod.parse_log("") == []


class TestNewestCommit:
    def test_picks_the_latest_author_date_not_the_first_listed(self):
        commits = [_commit(EARLY, sha="1" * 40), _commit(LATE, sha="2" * 40)]

        assert _mod.newest_commit(commits).sha == "2" * 40

    def test_no_commits_yields_none(self):
        assert _mod.newest_commit([]) is None


class TestJudge:
    def test_a_video_after_the_last_ui_change_is_fresh(self):
        report = _mod.judge(commit=_commit(EARLY), recording=_recording(LATE), override=None)

        assert (report["verdict"], report["ok"]) == ("fresh", True)

    def test_a_video_at_the_same_instant_is_fresh(self):
        report = _mod.judge(commit=_commit(EARLY), recording=_recording(EARLY), override=None)

        assert report["verdict"] == "fresh"

    def test_a_video_before_the_last_ui_change_is_refused(self):
        report = _mod.judge(commit=_commit(LATE), recording=_recording(EARLY), override=None)

        assert (report["verdict"], report["ok"]) == ("stale", False)
        assert report["message"].startswith("Re-record")
        assert "aaaaaaaa" in report["message"]

    def test_a_stated_override_sends_a_stale_video_and_reports_why(self):
        report = _mod.judge(
            commit=_commit(LATE), recording=_recording(EARLY), override="copy-only change"
        )

        assert (report["verdict"], report["ok"]) == ("stale", True)
        assert report["override"] == "copy-only change"
        assert "Overridden: copy-only change" in report["message"]

    def test_no_ui_commit_keeps_evidence_current(self):
        report = _mod.judge(commit=None, recording=_recording(EARLY), override=None)

        assert (report["verdict"], report["ok"]) == ("no-ui-change", True)

    def test_no_video_means_nothing_to_compare(self):
        report = _mod.judge(commit=_commit(LATE), recording=None, override=None)

        assert (report["verdict"], report["ok"]) == ("no-video", True)


class TestVideoRecording:
    def test_prefers_the_container_creation_time(self, tmp_path, monkeypatch):
        video = tmp_path / "take.webm"
        video.write_bytes(b"x")
        monkeypatch.setattr(_mod, "_run", lambda argv: "2026-11-01T10:00:00.000000Z\n")

        recording = _mod.video_recording(video)

        assert (recording.recorded_at, recording.source) == (EARLY, "creation_time")

    @pytest.mark.parametrize("probe_output", ["", "not-a-date"])
    def test_falls_back_to_mtime_without_a_usable_tag(self, tmp_path, monkeypatch, probe_output):
        video = tmp_path / "take.webm"
        video.write_bytes(b"x")
        os.utime(video, (LATE.timestamp(), LATE.timestamp()))
        monkeypatch.setattr(_mod, "_run", lambda argv: probe_output)

        recording = _mod.video_recording(video)

        assert (recording.recorded_at, recording.source) == (LATE, "mtime")

    def test_falls_back_to_mtime_without_ffprobe(self, tmp_path, monkeypatch):
        video = tmp_path / "take.webm"
        video.write_bytes(b"x")

        def missing(argv):
            raise _mod.ToolingError("ffprobe is not installed")

        monkeypatch.setattr(_mod, "_run", missing)

        assert _mod.video_recording(video).source == "mtime"

    def test_a_missing_video_is_an_error(self, tmp_path):
        with pytest.raises(_mod.ToolingError, match="video not found"):
            _mod.video_recording(tmp_path / "gone.webm")


class TestNewestRecording:
    def test_picks_the_latest_capture(self):
        newest = _mod.newest_recording([_recording(LATE), _recording(EARLY)])

        assert newest.recorded_at == LATE

    def test_no_recordings_yields_none(self):
        assert _mod.newest_recording([]) is None


class TestRun:
    def test_a_missing_binary_is_a_tooling_error(self):
        with pytest.raises(_mod.ToolingError, match="not installed"):
            _mod._run(["dev10x-no-such-binary-gh1828"])

    def test_a_failing_command_is_a_tooling_error(self, tmp_path):
        with pytest.raises(_mod.ToolingError, match="failed"):
            _mod._run(["git", "-C", str(tmp_path), "log"])

    def test_a_hung_command_is_a_tooling_error(self, monkeypatch):
        def hang(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=60)

        monkeypatch.setattr(_mod.subprocess, "run", hang)

        with pytest.raises(_mod.ToolingError, match="please try again"):
            _mod._run(["git", "log"])


def _git(repo: Path, *args: str, when: datetime | None = None) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    if when is not None:
        env |= {"GIT_AUTHOR_DATE": when.isoformat(), "GIT_COMMITTER_DATE": when.isoformat()}
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, env=env, capture_output=True, timeout=30
    )


@pytest.fixture
def branch_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "qa@example.com")
    _git(repo, "config", "user.name", "QA")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "Base", when=EARLY)
    _git(repo, "branch", "base")
    (repo / "web").mkdir()
    (repo / "web" / "Button.tsx").write_text("export {}\n")
    _git(repo, "add", "web/Button.tsx")
    _git(repo, "commit", "-q", "-m", "Restyle button", when=LATE)
    (repo / "api.py").write_text("x = 1\n")
    _git(repo, "add", "api.py")
    _git(repo, "commit", "-q", "-m", "Backend only", when=datetime(2026, 11, 3, tzinfo=UTC))
    return repo


class TestUiCommits:
    def test_finds_only_branch_commits_touching_the_globs(self, branch_repo):
        commits = _mod.ui_commits(repo=branch_repo, base="base", globs=["**/*.tsx"])

        assert [(c.subject, c.author_date) for c in commits] == [("Restyle button", LATE)]

    def test_globs_that_match_nothing_yield_no_commits(self, branch_repo):
        assert _mod.ui_commits(repo=branch_repo, base="base", globs=["**/*.vue"]) == []


class TestMain:
    def test_a_stale_video_exits_one_with_a_re_record_message(self, branch_repo, capsys):
        code = _mod.main(
            ["--base", "base", "--repo", str(branch_repo), "--recorded-at", EARLY.isoformat()]
        )

        report = json.loads(capsys.readouterr().out)
        assert (code, report["verdict"]) == (1, "stale")
        assert report["ui_globs_source"] == "default"

    def test_a_fresh_video_exits_zero(self, branch_repo, capsys):
        code = _mod.main(
            [
                "--base",
                "base",
                "--repo",
                str(branch_repo),
                "--recorded-at",
                "2026-11-02T11:00:00Z",
            ]
        )

        assert code == 0
        assert json.loads(capsys.readouterr().out)["verdict"] == "fresh"

    def test_configured_globs_replace_the_defaults(self, branch_repo, capsys):
        code = _mod.main(
            [
                "--base",
                "base",
                "--repo",
                str(branch_repo),
                "--ui-glob",
                "**/*.vue",
                "--recorded-at",
                EARLY.isoformat(),
            ]
        )

        report = json.loads(capsys.readouterr().out)
        assert (code, report["verdict"]) == (0, "no-ui-change")
        assert (report["ui_globs"], report["ui_globs_source"]) == (["**/*.vue"], "argument")

    def test_an_override_exits_zero_and_is_reported(self, branch_repo, capsys):
        code = _mod.main(
            [
                "--base",
                "base",
                "--repo",
                str(branch_repo),
                "--recorded-at",
                EARLY.isoformat(),
                "--override",
                "copy-only change",
            ]
        )

        assert code == 0
        assert json.loads(capsys.readouterr().out)["override"] == "copy-only change"

    def test_an_unknown_base_is_reported_as_json_and_exits_two(self, branch_repo, capsys):
        code = _mod.main(["--base", "no-such-ref", "--repo", str(branch_repo)])

        assert code == 2
        assert "error" in json.loads(capsys.readouterr().out)
