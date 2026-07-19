"""Concurrency-safe file primitives: exclusive locks + atomic writes.

Background: shared state files under ``~/.claude/`` and
``<repo>/.claude/session/`` are written by multiple worktrees and
parallel agents. Plain ``Path.write_text()`` truncate-writes lose
data when two writers race; load→mutate→save cycles also lose data
even with atomic writes because the second writer reads stale state.

This module exposes three layers:

1. ``file_lock(path)`` — bare exclusive flock on a ``.lock`` sidecar
2. ``atomic_write_text`` / ``atomic_write_bytes`` — durable writes
   via ``mkstemp`` + ``os.rename`` (no lock; safe for non-mutating
   overwrites such as cache files); ``atomic_append_line`` — a single
   ``O_APPEND`` ``os.write`` for interleave-safe log/sink appends
3. ``locked_json_update`` / ``locked_yaml_update`` — full
   load→mutate→save cycle under a lock, with atomic durable write

Sidecar naming convention:

* ``file_lock`` and ``locked_yaml_update`` **append** ``.lock`` to the
  target's full name via :func:`_lock_path_for` — e.g. ``plan.yaml``
  → ``plan.yaml.lock``. New code should follow this convention.
* ``locked_json_update`` **replaces** the target's suffix with
  ``.lock`` — e.g. ``settings.local.json`` → ``settings.local.lock``.
  This is preserved deliberately for backward compatibility with the
  existing :mod:`dev10x.skills.permission` call sites and the test
  in ``tests/skills/upgrade-cleanup/test_file_lock.py``; switching
  it now would orphan on-disk sidecars across the upgrade boundary.

The two functions must not be used against the same target path
because their sidecars resolve to different files. New code MUST use
``file_lock`` (append-``.lock`` convention); ``locked_json_update``
is frozen for its existing :mod:`dev10x.skills.permission` call sites.
See ADR-0011 for the rationale.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

#: Default seconds to wait for an exclusive lock before giving up.
LOCK_TIMEOUT_SECONDS = 10.0

#: Poll interval while waiting on a contended lock.
_LOCK_RETRY_INTERVAL = 0.05


class LockTimeoutError(OSError):
    """Raised when an exclusive file lock cannot be acquired in time.

    Subclasses :class:`OSError` so existing ``except OSError`` handlers
    still catch it, while call sites that want an actionable retry
    message can match it specifically.
    """


def _lock_path_for(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock") if path.suffix else path.with_suffix(".lock")


def _acquire_exclusive(lock_fd: int, target: Path, timeout: float) -> None:
    """Acquire an exclusive ``flock``, raising after ``timeout`` seconds.

    Uses non-blocking ``LOCK_NB`` attempts in a poll loop so a crashed or
    wedged lock-holder cannot freeze the caller (and, for the MCP daemon,
    its async event loop) indefinitely. A non-positive ``timeout`` falls
    back to a single blocking acquire — callers can opt out of the guard
    when an unbounded wait is genuinely desired.
    """
    if timeout <= 0:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise LockTimeoutError(
                    f"{target} is locked by another process — could not acquire "
                    f"the lock within {timeout:g}s. Please try again."
                ) from None
            time.sleep(_LOCK_RETRY_INTERVAL)


@contextmanager
def file_lock(path: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS) -> Generator[None, None, None]:
    """Acquire exclusive ``flock`` on ``<path>.lock`` for the duration.

    Sidecar naming follows the module convention: ``.lock`` is
    *appended* to the full target name via :func:`_lock_path_for`
    (e.g. ``plan.yaml`` → ``plan.yaml.lock``). See the module docstring
    for the reason this differs from :func:`locked_json_update`.

    Raises :class:`LockTimeoutError` when the lock cannot be acquired
    within ``timeout`` seconds (default :data:`LOCK_TIMEOUT_SECONDS`),
    so a crashed or wedged holder cannot block the caller forever. Pass
    ``timeout=0`` for the legacy unbounded blocking behaviour.

    The sidecar lock file is deliberately not unlinked on release.
    Unlinking is unsafe: a third writer arriving between ``unlink`` and
    the next ``open(O_CREAT)`` would get a fresh inode and acquire its
    own independent flock, breaking mutual exclusion.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(_lock_path_for(path)), os.O_CREAT | os.O_RDWR)
    try:
        _acquire_exclusive(lock_fd, path, timeout)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path`` via ``mkstemp`` + ``os.rename``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, content)
        os.fsync(fd)
        os.close(fd)
        os.rename(tmp, str(path))
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` (UTF-8) to ``path`` atomically."""
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_append_line(path: Path, line: str) -> None:
    """Append ``line`` to ``path`` as a single atomic write.

    Uses ``os.open(O_APPEND|O_WRONLY|O_CREAT)`` + a single ``os.write`` so
    concurrent appenders never interleave partial lines — the exact
    guarantee a buffered ``TextIOWrapper.write`` (``open(path, "a")``)
    fails to provide, since it may split one logical write across several
    syscalls. POSIX guarantees a single ``write()`` to an ``O_APPEND`` fd
    is atomic up to ``PIPE_BUF`` bytes, so keep appended lines short (the
    doubt-sink / audit records this serves are well under that limit).

    A trailing newline is appended when ``line`` lacks one so callers pass
    the bare record text.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = line if line.endswith("\n") else line + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)


@contextmanager
def locked_json_update(
    path: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS
) -> Generator[dict[str, Any], None, None]:
    """Lock ``path``, yield its JSON content as a dict, atomically write back.

    Uses a ``.lock`` sidecar that replaces the path's suffix (e.g.
    ``settings.local.json`` → ``settings.local.lock``), preserving
    the historical naming used by the permission-skill call sites.

    Raises :class:`LockTimeoutError` when the lock cannot be acquired
    within ``timeout`` seconds. Pass ``timeout=0`` for unbounded waits.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(path.with_suffix(".lock")), os.O_CREAT | os.O_RDWR)
    try:
        _acquire_exclusive(lock_fd, path, timeout)
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = {}
        yield data
        atomic_write_text(path, json.dumps(data, indent=2) + "\n")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


@contextmanager
def locked_yaml_update(
    path: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS
) -> Generator[dict[str, Any], None, None]:
    """Lock ``path``, yield its YAML content as a dict, atomically write back.

    Sidecar naming follows the module convention: ``.lock`` is
    *appended* to the full target name via :func:`_lock_path_for`
    (e.g. ``plan.yaml`` → ``plan.yaml.lock``). See the module
    docstring for the reason this differs from
    :func:`locked_json_update`.

    Raises :class:`LockTimeoutError` when the lock cannot be acquired
    within ``timeout`` seconds. Pass ``timeout=0`` for unbounded waits.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(_lock_path_for(path)), os.O_CREAT | os.O_RDWR)
    try:
        _acquire_exclusive(lock_fd, path, timeout)
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text()) or {}
            except yaml.YAMLError:
                data = {}
        else:
            data = {}
        yield data
        atomic_write_text(
            path,
            yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
