"""Shared lock-contention helpers for tests that exercise file_locks."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def hold_sidecar(sidecar: Path) -> Iterator[None]:
    """Hold an exclusive ``flock`` on ``sidecar``, standing in for another writer.

    flock is associated with the open file description, so a second
    ``os.open`` of the same sidecar inside the same process contends exactly
    as a separate process — or another worktree — would.
    """
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(sidecar), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
