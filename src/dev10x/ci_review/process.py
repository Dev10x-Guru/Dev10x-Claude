from __future__ import annotations

import subprocess
from pathlib import Path

from dev10x.core import subprocess_utils
from dev10x.core.domain.common.result import Result, err, ok

DEFAULT_TIMEOUT_SECONDS: float = 300


def run_checked(
    *,
    args: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Result[str]:
    try:
        completed = subprocess_utils.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return err(f"`{_render(args=args)}` timed out after {timeout:g}s. Please try again.")
    except OSError as exc:
        return err(f"`{_render(args=args)}` could not start: {exc}")
    if completed.returncode != 0:
        return err(
            f"`{_render(args=args)}` exited {completed.returncode}",
            stderr=completed.stderr.strip(),
        )
    return ok(completed.stdout)


def _render(*, args: list[str]) -> str:
    return " ".join(args[:4]) + (" …" if len(args) > 4 else "")
