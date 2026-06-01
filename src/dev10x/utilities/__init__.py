"""Utility MCP tool implementations.

Extracted from cli_server.py — general-purpose utility tools
(mktmp, etc.) that don't belong to GitHub or Git domains.
All public functions are async to avoid blocking the MCP event loop.
"""

from __future__ import annotations

from typing import Any

from dev10x.domain.common.result import Result, err, ok
from dev10x.subprocess_utils import async_run_script


async def mktmp(
    *,
    namespace: str,
    prefix: str,
    ext: str = "",
    directory: bool = False,
    create: bool = False,
    cwd: str | None = None,
) -> Result[dict[str, Any]]:
    """Generate a unique temp path under /tmp/Dev10x/<namespace>/.

    By default returns a path without creating the file so callers
    using the Write tool don't trigger its overwrite gate (GH-39).
    Pass create=True to pre-create an empty file (legacy behavior).
    Directories are always created (directory=True).

    Args:
        namespace: Subdirectory under /tmp/Dev10x/ (e.g. "git", "skill-audit")
        prefix: Filename prefix (e.g. "commit-msg", "pr-review")
        ext: File extension including dot (e.g. ".txt", ".json"). Ignored for directories.
        directory: If True, create a directory instead of a file.
        create: If True (and directory=False), pre-create an empty file.
        cwd: Effective working directory for the subprocess (GH-410). The
            mktmp.sh script writes to /tmp so the CWD does not affect the
            output path, but passing a valid directory avoids the ENOENT
            that occurs when the previously-bound worktree was deleted.
            When omitted, ``safe_effective_cwd()`` provides the fallback.
    """
    mk_args: list[str] = []
    if directory:
        mk_args.append("-d")
    elif create:
        mk_args.append("--create")
    mk_args.extend([namespace, prefix])
    if ext and not directory:
        mk_args.append(ext)

    result = await async_run_script("bin/mktmp.sh", *mk_args, cwd=cwd)

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"path": result.stdout.strip()})
