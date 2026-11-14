#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Refuse a review video that predates the branch's last UI change.

A review round that changes the UI leaves the pack's video showing a
screen the branch no longer has, and a reviewer approves footage of
behaviour that is gone (GH-1828). This compares two timestamps:

  - the newest **author date** among the commits in ``<base>..HEAD``
    that touch the UI globs, and
  - the newest capture time among the videos given.

Author dates, not committer dates: a rebase or groom rewrites every
committer date on the branch, which would make each video look stale
after any history cleanup. Known gap: a fixup folded into an older
commit keeps that commit's older author date, so a UI change made by
the fixup can hide behind it.

A video's capture time is, in order of preference: an explicit
``--recorded-at`` value, the container's ``creation_time`` tag read with
ffprobe, or the file's modification time. The source used is reported,
because a file mtime from a fresh clone of the evidence repo is the
clone time, not the capture time.

Output: one JSON report on stdout. Exit 0 when the evidence is current
(or there is nothing to compare, or a stated override was given), 1
when the newest video predates the newest UI commit, 2 on a usage or
tooling error. Errors are emitted as JSON on stdout too, so a caller
parses exactly one channel.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

DEFAULT_UI_GLOBS = (
    "**/*.tsx",
    "**/*.jsx",
    "**/*.vue",
    "**/*.svelte",
    "**/*.astro",
    "**/*.html",
    "**/*.css",
    "**/*.scss",
    "**/*.sass",
    "**/*.less",
)

_FIELD_SEPARATOR = "\x1f"
_SUBPROCESS_TIMEOUT_SECONDS = 60


class ToolingError(RuntimeError):
    """A required external tool is missing or failed, or input is unusable."""


class UiCommit(NamedTuple):
    sha: str
    author_date: datetime
    subject: str


class Recording(NamedTuple):
    label: str
    recorded_at: datetime
    source: str


def _run(argv: list[str]) -> str:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise ToolingError(f"{argv[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolingError(
            f"{argv[0]} timed out after {_SUBPROCESS_TIMEOUT_SECONDS}s; please try again"
        ) from exc
    if completed.returncode != 0:
        raise ToolingError(f"{' '.join(argv[:3])} failed: {completed.stderr.strip()}")
    return completed.stdout


def parse_timestamp(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ToolingError(f"not an ISO-8601 timestamp: {raw!r}") from exc
    if parsed.tzinfo is None:
        raise ToolingError(f"timestamp {raw!r} has no UTC offset; add one (e.g. Z or +00:00)")
    return parsed.astimezone(UTC)


def pathspecs(globs: list[str]) -> list[str]:
    return [glob if glob.startswith(":") else f":(glob){glob}" for glob in globs]


def parse_log(output: str) -> list[UiCommit]:
    commits = []
    for line in output.splitlines():
        if not line.strip():
            continue
        sha, author_date, subject = line.split(_FIELD_SEPARATOR, 2)
        commits.append(
            UiCommit(sha=sha, author_date=parse_timestamp(author_date), subject=subject)
        )
    return commits


def ui_commits(*, repo: Path, base: str, globs: list[str]) -> list[UiCommit]:
    output = _run(
        [
            "git",
            "-C",
            str(repo),
            "log",
            f"--format=%H{_FIELD_SEPARATOR}%aI{_FIELD_SEPARATOR}%s",
            f"{base}..HEAD",
            "--",
            *pathspecs(globs),
        ]
    )
    return parse_log(output)


def newest_commit(commits: list[UiCommit]) -> UiCommit | None:
    return max(commits, key=lambda commit: commit.author_date, default=None)


def container_creation_time(path: Path) -> datetime | None:
    try:
        raw = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format_tags=creation_time",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
        )
    except ToolingError:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return parse_timestamp(raw)
    except ToolingError:
        return None


def video_recording(path: Path) -> Recording:
    if not path.exists():
        raise ToolingError(f"video not found: {path}")
    created = container_creation_time(path)
    if created is not None:
        return Recording(label=str(path), recorded_at=created, source="creation_time")
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return Recording(label=str(path), recorded_at=modified, source="mtime")


def stated_recording(raw: str) -> Recording:
    return Recording(label=raw, recorded_at=parse_timestamp(raw), source="recorded-at")


def newest_recording(recordings: list[Recording]) -> Recording | None:
    return max(recordings, key=lambda recording: recording.recorded_at, default=None)


def _commit_dict(commit: UiCommit | None) -> dict | None:
    if commit is None:
        return None
    return {
        "sha": commit.sha,
        "author_date": commit.author_date.isoformat(),
        "subject": commit.subject,
    }


def _recording_dict(recording: Recording | None) -> dict | None:
    if recording is None:
        return None
    return {
        "label": recording.label,
        "recorded_at": recording.recorded_at.isoformat(),
        "source": recording.source,
    }


def judge(
    *,
    commit: UiCommit | None,
    recording: Recording | None,
    override: str | None,
) -> dict:
    report = {
        "newest_ui_commit": _commit_dict(commit),
        "newest_video": _recording_dict(recording),
        "override": None,
    }
    if recording is None:
        return report | {
            "verdict": "no-video",
            "ok": True,
            "message": "No video to compare; freshness does not apply.",
        }
    if commit is None:
        return report | {
            "verdict": "no-ui-change",
            "ok": True,
            "message": "No commit on the branch touches the UI globs; evidence still current.",
        }
    if recording.recorded_at >= commit.author_date:
        return report | {
            "verdict": "fresh",
            "ok": True,
            "message": "Evidence still current: the newest video post-dates the last UI change.",
        }
    message = (
        f"Re-record: the newest video ({recording.recorded_at.isoformat()}) predates "
        f"UI commit {commit.sha[:8]} '{commit.subject}' "
        f"({commit.author_date.isoformat()}). "
        "Re-record before sending, or override with a stated reason."
    )
    if override:
        return report | {
            "verdict": "stale",
            "ok": True,
            "override": override,
            "message": f"{message} Overridden: {override}",
        }
    return report | {"verdict": "stale", "ok": False, "message": message}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base", required=True, help="Base ref the branch is compared to (origin/develop)"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Checkout of the PR branch")
    parser.add_argument(
        "--ui-glob",
        action="append",
        default=[],
        help="UI path glob (repeatable); defaults to front-end file extensions",
    )
    parser.add_argument(
        "--video", action="append", default=[], type=Path, help="Recorded video file (repeatable)"
    )
    parser.add_argument(
        "--recorded-at",
        action="append",
        default=[],
        help="Capture time of a video not on disk, ISO-8601 with offset (repeatable)",
    )
    parser.add_argument(
        "--override", help="Reason for sending a stale video anyway; reported, never silent"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    globs = args.ui_glob or list(DEFAULT_UI_GLOBS)
    try:
        commit = newest_commit(ui_commits(repo=args.repo, base=args.base, globs=globs))
        recordings = [video_recording(path) for path in args.video]
        recordings += [stated_recording(raw) for raw in args.recorded_at]
    except ToolingError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    report = judge(commit=commit, recording=newest_recording(recordings), override=args.override)
    report["ui_globs"] = globs
    report["ui_globs_source"] = "argument" if args.ui_glob else "default"
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
