"""GitContext — lazy-cached git subprocess state.

Replaces duplicated get_toplevel(), get_branch(), _run_git()
calls scattered across session.py, task_plan_sync.py, and plan.py
with a single utility.

GH-979: Each instance pins its own CWD. Module-level singletons
must not be reused across MCP calls — the cached toplevel would
otherwise lock in whichever directory the first call happened to
hit. Callers either construct a fresh instance per call, or pass
`cwd=` explicitly. When `cwd` is None, the subprocess inherits the
ContextVar bound by `subprocess_utils.use_cwd` (set by MCP entry
points after EnterWorktree).

GH-584 (audit N21): this module resolves the effective CWD through
the domain-owned `cwd_resolver` seam rather than importing the
`subprocess_utils` infra module directly — ADR-0008 Rule #1 keeps
`domain/` free of outward dependencies. The infra layer wires the
concrete `effective_cwd` resolver into that seam at import time.
"""

from __future__ import annotations

import subprocess
from functools import cached_property

from dev10x.domain.cwd_resolver import resolve_cwd

#: Default bound on an accessor's git subprocess (GH-1412).
#:
#: The accessors are read as attributes by fifteen call sites that have no
#: opinion about timeouts, three of them synchronously inside ``async def``
#: MCP handlers. A default of ``None`` would leave every one of those
#: unbounded, so the bound lives here rather than at the call sites: a
#: wedged git — a stale ``index.lock``, an unreachable network remote —
#: then costs one caller this many seconds instead of freezing every
#: worktree sharing the long-lived daemon. Callers that genuinely need
#: longer pass ``timeout=`` to the constructor.
GIT_TIMEOUT_SECONDS = 5.0

#: Every way a git lookup can fail without the caller wanting a raise.
#:
#: ``OSError`` rather than just ``FileNotFoundError``: a repo on an
#: unreadable mount raises ``PermissionError``, and an accessor whose
#: documented contract is "any failure degrades to the fallback" must not
#: make the caller's choice for it on the basis of which errno it was.
_GIT_FAILURES = (
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
    OSError,
)


class GitContext:
    def __init__(self, cwd: str | None = None, *, timeout: float | None = None) -> None:
        self._cwd = cwd
        self._timeout = GIT_TIMEOUT_SECONDS if timeout is None else timeout

    def _resolved_cwd(self) -> str | None:
        return self._cwd if self._cwd is not None else resolve_cwd()

    def _read(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", *args],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=self._resolved_cwd(),
            timeout=self._timeout,
        ).strip()

    @cached_property
    def toplevel(self) -> str | None:
        try:
            return self._read("rev-parse", "--show-toplevel")
        except _GIT_FAILURES:
            return None

    @cached_property
    def branch(self) -> str:
        try:
            return self._read("rev-parse", "--abbrev-ref", "HEAD")
        except _GIT_FAILURES:
            return "unknown"

    @cached_property
    def common_dir(self) -> str | None:
        """Absolute path to the repo's git common dir, or ``None`` (GH-1445).

        From inside a linked worktree this is the *main* repo's ``.git``, so
        it — not ``toplevel`` — is what keys anything shared by a repo and
        all its worktrees. ``--path-format=absolute`` is part of the
        contract: the bare flag returns a working-tree-relative path that
        every caller then re-resolves by hand.
        """
        try:
            return self._read("rev-parse", "--path-format=absolute", "--git-common-dir")
        except _GIT_FAILURES:
            return None

    def run(self, *args: str, timeout: float | None = None) -> str:
        """Run a git command and return its stripped stdout.

        ``timeout`` bounds the call so a wedged git (a stale index.lock, an
        unreachable network remote) cannot hang a request served by the
        long-lived MCP daemon (`.claude/rules/mcp-tools.md` § concurrency
        conventions). Callers on a request path MUST pass one; it defaults to
        ``None`` so existing call sites keep their prior behavior.
        """
        return subprocess.check_output(
            ["git", *args],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=self._resolved_cwd(),
            timeout=timeout,
        ).strip()
