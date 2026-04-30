"""Utility MCP tool implementations.

Extracted from cli_server.py — general-purpose utility tools
(mktmp, etc.) that don't belong to GitHub or Git domains.
All public functions are async to avoid blocking the MCP event loop.
"""

from __future__ import annotations

from typing import Any

from dev10x.subprocess_utils import async_run_script


async def mktmp(
    *,
    namespace: str,
    prefix: str,
    ext: str = "",
    directory: bool = False,
    create: bool = False,
) -> dict[str, Any]:
    """Generate a unique temp path under /tmp/Dev10x/<namespace>/.

    By default returns a path without creating the file so callers
    using the Write tool don't trigger its overwrite gate (GH-39).
    Pass create=True to pre-create an empty file (legacy behavior).
    Directories are always created (directory=True).
    """
    mk_args: list[str] = []
    if directory:
        mk_args.append("-d")
    elif create:
        mk_args.append("--create")
    mk_args.extend([namespace, prefix])
    if ext and not directory:
        mk_args.append(ext)

    result = await async_run_script("bin/mktmp.sh", *mk_args)

    if result.returncode != 0:
        return {"error": result.stderr.strip()}

    return {"path": result.stdout.strip()}
