"""Stub-binary harness shared by the dev10x:diagram-* render.sh tests (GH-1782).

Each render test puts stub binaries first on ``PATH``; the stubs record
their calls and read their behaviour from files in ``$FAKE_DIR``.
"""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Collection
from pathlib import Path

SYSTEM_PATH = "/usr/bin:/bin"


def install_stub(*, bin_dir: Path, name: str, body: str) -> Path:
    path = bin_dir / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def stub_path(*, bin_dir: Path) -> str:
    return f"{bin_dir}:{SYSTEM_PATH}"


def run_script(
    *,
    script: Path,
    args: list[str],
    path: str,
    fake_dir: Path,
    extra_env: dict[str, str] | None = None,
    strip_env: Collection[str] = (),
) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key not in strip_env}
    env.update({"PATH": path, "FAKE_DIR": str(fake_dir), **(extra_env or {})})
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
