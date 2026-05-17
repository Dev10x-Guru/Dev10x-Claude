"""Canonical Claude Code filesystem paths.

Centralizes every `Path.home() / ".claude" / ...` reference in the codebase
to eliminate duplicated home-dir resolution and to support a single
test/CI override via `DEV10X_CLAUDE_HOME`.

Path resolution is cached per `(override, segments)` tuple via
`functools.cache`. Tests that mutate `DEV10X_CLAUDE_HOME` between
calls automatically hit a different cache key, so caching does not
defeat the override. Call :func:`ClaudeDir.reset_cache` after tearing
down a temp home to release the cached `Path` objects.

`Path.home()` resolves cross-platform (Linux/macOS/Windows) without
hardcoded prefixes, so callers can rely on these accessors regardless
of OS.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

CLAUDE_HOME_ENV_VAR = "DEV10X_CLAUDE_HOME"


@functools.cache
def _resolve_path(*, override: str | None, segments: tuple[str, ...]) -> Path:
    base = Path(override).expanduser() if override else Path.home() / ".claude"
    return base.joinpath(*segments) if segments else base


class ClaudeDir:
    """Cached accessors for canonical paths under `~/.claude`.

    `DEV10X_CLAUDE_HOME` overrides the root — useful in tests and CI.
    """

    @classmethod
    def _resolve(cls, *segments: str) -> Path:
        return _resolve_path(
            override=os.environ.get(CLAUDE_HOME_ENV_VAR),
            segments=segments,
        )

    @classmethod
    def reset_cache(cls) -> None:
        """Clear the path resolution cache. Call in test teardown."""
        _resolve_path.cache_clear()

    @classmethod
    def home(cls) -> Path:
        return cls._resolve()

    @classmethod
    def settings_json(cls) -> Path:
        return cls._resolve("settings.json")

    @classmethod
    def settings_local_json(cls) -> Path:
        return cls._resolve("settings.local.json")

    @classmethod
    def skills_dir(cls) -> Path:
        return cls._resolve("skills")

    @classmethod
    def tools_dir(cls) -> Path:
        return cls._resolve("tools")

    @classmethod
    def hooks_dir(cls) -> Path:
        return cls._resolve("hooks")

    @classmethod
    def projects_dir(cls) -> Path:
        return cls._resolve("projects")

    @classmethod
    def session_state_dir(cls) -> Path:
        return cls._resolve("projects", "_session_state")

    @classmethod
    def metrics_dir(cls) -> Path:
        return cls._resolve("projects", "_metrics")

    @classmethod
    def memory_dir(cls) -> Path:
        return cls._resolve("memory")

    @classmethod
    def memory_dev10x_dir(cls) -> Path:
        return cls._resolve("memory", "Dev10x")

    @classmethod
    def memory_projects_yaml(cls) -> Path:
        return cls._resolve("memory", "Dev10x", "projects.yaml")

    @classmethod
    def dev10x_config_dir(cls) -> Path:
        return cls._resolve("Dev10x")

    @classmethod
    def dev10x_version_yaml(cls) -> Path:
        return cls._resolve("Dev10x", "version.yml")

    @classmethod
    def github_bot_dir(cls) -> Path:
        return cls._resolve("Dev10x", "github-bot")

    @classmethod
    def github_app_yaml(cls) -> Path:
        return cls._resolve("Dev10x", "github-bot", "github-app.yaml")

    @classmethod
    def upgrade_cleanup_projects_yaml(cls) -> Path:
        """Userspace projects config used by upgrade-cleanup and plugin-maintenance."""
        return cls._resolve("skills", "Dev10x:upgrade-cleanup", "projects.yaml")

    @classmethod
    def plugins_cache_dir(cls) -> Path:
        return cls._resolve("plugins", "cache")

    @classmethod
    def platforms_yaml(cls) -> Path:
        return cls._resolve("memory", "Dev10x", "platforms.yaml")

    @classmethod
    def slack_config_yaml(cls) -> Path:
        return cls._resolve("memory", "slack-config.yaml")

    @classmethod
    def slack_review_config_yaml(cls) -> Path:
        return cls._resolve("memory", "slack-config-code-review-requests.yaml")


__all__ = ["ClaudeDir", "CLAUDE_HOME_ENV_VAR"]
