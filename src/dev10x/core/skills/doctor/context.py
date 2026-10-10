"""Build a doctor :class:`Context` from the filesystem (GH-1321).

The interactive skill has an agent to decide which settings files are in
play. A CI runner has nobody, so the discovery has to be written down:
the two user-scope settings files plus the project-scope pair under the
checkout being examined.

Only existing files are listed. A strategy that abstains on a missing
path would behave the same either way, but reporting a location that
does not exist makes the payload unreadable — and
``retired_session_yaml`` derives its candidate paths from a settings
file's *parent*, so a phantom entry would have it probe a directory
nobody has.
"""

from __future__ import annotations

import os
from pathlib import Path

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.skills.doctor.strategy import Context
from dev10x.subprocess_utils import effective_cwd

_PROJECT_SETTINGS_NAMES = ("settings.json", "settings.local.json")


def build_context(*, project_root: Path | None = None) -> Context:
    """Settings and memory locations the shipped strategies read."""
    root = project_root or Path(effective_cwd() or os.getcwd())
    project_claude = root / ".claude"
    candidates = [
        ClaudeDir.settings_json(),
        ClaudeDir.settings_local_json(),
        *(project_claude / name for name in _PROJECT_SETTINGS_NAMES),
    ]
    memory_root = ClaudeDir.home() / "memory"
    return Context(
        settings_paths=tuple(path for path in candidates if path.is_file()),
        memory_roots=(memory_root,) if memory_root.is_dir() else (),
        plugin_cache_root=(
            ClaudeDir.plugins_cache_dir() if ClaudeDir.plugins_cache_dir().is_dir() else None
        ),
    )


__all__ = ["build_context"]
