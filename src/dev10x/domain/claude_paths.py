"""Canonical Claude Code filesystem paths.

Centralizes every `Path.home() / ".claude" / ...` reference in the codebase
to eliminate the triplicated USERSPACE_CONFIG constant and to support a
single test/CI override via `DEV10X_CLAUDE_HOME`.

Paths are resolved lazily on each access so tests can mutate
`DEV10X_CLAUDE_HOME` between calls without re-importing the module.
"""

from __future__ import annotations

import os
from pathlib import Path

CLAUDE_HOME_ENV_VAR = "DEV10X_CLAUDE_HOME"


class ClaudeDir:
    """Lazy accessors for canonical paths under `~/.claude`.

    `DEV10X_CLAUDE_HOME` overrides the root — useful in tests and CI.
    """

    @classmethod
    def home(cls) -> Path:
        override = os.environ.get(CLAUDE_HOME_ENV_VAR)
        if override:
            return Path(override).expanduser()
        return Path.home() / ".claude"

    @classmethod
    def settings_json(cls) -> Path:
        return cls.home() / "settings.json"

    @classmethod
    def skills_dir(cls) -> Path:
        return cls.home() / "skills"

    @classmethod
    def projects_dir(cls) -> Path:
        return cls.home() / "projects"

    @classmethod
    def session_state_dir(cls) -> Path:
        return cls.projects_dir() / "_session_state"

    @classmethod
    def metrics_dir(cls) -> Path:
        return cls.projects_dir() / "_metrics"

    @classmethod
    def memory_dir(cls) -> Path:
        return cls.home() / "memory"

    @classmethod
    def memory_dev10x_dir(cls) -> Path:
        return cls.memory_dir() / "Dev10x"

    @classmethod
    def memory_projects_yaml(cls) -> Path:
        return cls.memory_dev10x_dir() / "projects.yaml"

    @classmethod
    def dev10x_config_dir(cls) -> Path:
        return cls.home() / "Dev10x"

    @classmethod
    def github_bot_dir(cls) -> Path:
        return cls.dev10x_config_dir() / "github-bot"

    @classmethod
    def github_app_yaml(cls) -> Path:
        return cls.github_bot_dir() / "github-app.yaml"

    @classmethod
    def upgrade_cleanup_projects_yaml(cls) -> Path:
        """Userspace projects config used by upgrade-cleanup and plugin-maintenance."""
        return cls.skills_dir() / "Dev10x:upgrade-cleanup" / "projects.yaml"

    @classmethod
    def plugins_cache_dir(cls) -> Path:
        return cls.home() / "plugins" / "cache"

    @classmethod
    def platforms_yaml(cls) -> Path:
        return cls.memory_dev10x_dir() / "platforms.yaml"

    @classmethod
    def slack_config_yaml(cls) -> Path:
        return cls.memory_dir() / "slack-config.yaml"

    @classmethod
    def slack_review_config_yaml(cls) -> Path:
        return cls.memory_dir() / "slack-config-code-review-requests.yaml"


__all__ = ["ClaudeDir", "CLAUDE_HOME_ENV_VAR"]
