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


class GitContext:
    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd

    def _resolved_cwd(self) -> str | None:
        return self._cwd if self._cwd is not None else resolve_cwd()

    @cached_property
    def toplevel(self) -> str | None:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                stderr=subprocess.DEVNULL,
                text=True,
                cwd=self._resolved_cwd(),
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    @cached_property
    def branch(self) -> str:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
                cwd=self._resolved_cwd(),
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return "unknown"

    def run(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", *args],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=self._resolved_cwd(),
        ).strip()
