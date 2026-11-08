"""Shared ``subprocess.CompletedProcess`` factory for tests (GH-1857)."""

import subprocess


def completed(
    *,
    stdout: str = "",
    returncode: int = 0,
    stderr: str = "",
    args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=args or [],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
