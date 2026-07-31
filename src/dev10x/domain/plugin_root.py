"""Resolve the active plugin root across checkout and installed layouts (GH-919).

Several commands need the directory that holds ``skills/``, ``src/``, and
``.claude-plugin/plugin.json``. Each grew its own resolution walk, and the
walk-up-from-``__file__`` variants silently return a non-plugin directory
when the CLI runs from an installed wheel (``uvx dev10x``) instead of a
repo checkout. Callers then saw an empty result that was indistinguishable
from "nothing to do".

This module is the single resolver. It tries, in order:

1. An explicit ``override`` (the ``--plugin-root`` CLI option).
2. The walk-up from this package — correct, and the fastest answer, when
   the CLI runs from a repo checkout or an editable install.
3. ``$CLAUDE_PLUGIN_ROOT`` — set by Claude Code for the running session.
4. The newest version directory under the installed plugin cache
   (``~/.claude/plugins/cache/<publisher>/<plugin>/<version>/``).

Every candidate must carry the ``.claude-plugin/plugin.json`` manifest, so
a stale env var or an empty cache directory is rejected rather than
returned as a plausible-looking wrong answer. ``None`` means no plugin
root exists on this machine — a hard error for callers, never a no-op.
"""

from __future__ import annotations

import os
from pathlib import Path

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.plugin_version import PluginVersion

PLUGIN_MANIFEST_RELPATH = Path(".claude-plugin") / "plugin.json"

# Marketplace installs have used both directory names over time.
KNOWN_PLUGIN_DIRS: tuple[str, ...] = ("Dev10x", "dev10x-claude")


def is_plugin_root(path: Path) -> bool:
    """True when ``path`` carries the plugin manifest."""
    return (path / PLUGIN_MANIFEST_RELPATH).is_file()


def resolve_plugin_root(
    *,
    override: Path | None = None,
    environ: dict[str, str] | None = None,
    cache_dir: Path | None = None,
) -> Path | None:
    """Return the active plugin root, or ``None`` when none can be found.

    Args:
        override: Explicit root supplied by the caller (``--plugin-root``).
            Returned verbatim, without the manifest check — an operator
            who names a root wants that root, and falling through to a
            different one is the silent-wrong-answer failure this
            resolver exists to remove. A bogus override surfaces as the
            caller's own "nothing found under <root>" error.
        environ: Environment mapping to read ``CLAUDE_PLUGIN_ROOT`` from.
            Defaults to ``os.environ``.
        cache_dir: Root of the installed plugin cache. Defaults to
            ``~/.claude/plugins/cache``.
    """
    env = os.environ if environ is None else environ

    if override is not None:
        return override

    checkout = _checkout_root()
    if checkout is not None:
        return checkout

    env_root = env.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        candidate = Path(env_root)
        if is_plugin_root(candidate):
            return candidate

    return latest_installed_root(cache_dir=cache_dir)


def latest_installed_root(*, cache_dir: Path | None = None) -> Path | None:
    """Return the newest installed plugin version directory, if any.

    Scans ``<cache_dir>/<publisher>/<plugin>/<version>/`` for every known
    plugin directory name and returns the highest semver that carries the
    plugin manifest.
    """
    root = cache_dir if cache_dir is not None else ClaudeDir.plugins_cache_dir()
    if not root.is_dir():
        return None

    candidates: list[Path] = []
    for publisher_dir in sorted(root.iterdir()):
        if not publisher_dir.is_dir():
            continue
        for plugin_name in KNOWN_PLUGIN_DIRS:
            plugin_dir = publisher_dir / plugin_name
            if not plugin_dir.is_dir():
                continue
            candidates.extend(d for d in plugin_dir.iterdir() if is_plugin_root(d))

    if not candidates:
        return None
    return max(candidates, key=lambda d: PluginVersion.sort_key(d.name))


def _checkout_root() -> Path | None:
    """Walk up from this module to a repo checkout or editable install."""
    candidate = Path(__file__).resolve().parents[3]
    return candidate if is_plugin_root(candidate) else None


__all__ = [
    "KNOWN_PLUGIN_DIRS",
    "PLUGIN_MANIFEST_RELPATH",
    "is_plugin_root",
    "latest_installed_root",
    "resolve_plugin_root",
]
