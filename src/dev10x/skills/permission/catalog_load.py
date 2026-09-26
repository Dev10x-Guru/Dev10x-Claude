"""Load the permission catalog and discover the settings files it governs (GH-1432).

Config lookup order (post-GH-215):
  1. ~/.config/Dev10x/projects.yaml (XDG; legacy ~/.claude/memory/Dev10x/)
  2. ~/.config/Dev10x/upgrade-cleanup-projects.yaml (XDG; legacy
     ~/.claude/skills/Dev10x:upgrade-cleanup/projects.yaml)
  3. ${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/projects.yaml (plugin default)

GH-315 Bug C (resolved, GH-577): ``merge-worktree`` and ``clean`` now
read ``~/.config/Dev10x/projects.yaml`` (MEMORY_CONFIG) like every
other subcommand, falling back to the legacy
``~/.config/Dev10x/upgrade-cleanup-projects.yaml`` (USERSPACE_CONFIG)
only when ``projects.yaml`` is absent. ``init-userspace-config``
migrates the legacy file into ``projects.yaml`` on first use, so the
two no longer drift.

Split out of ``update_paths.py`` by GH-1432.
"""

import logging
from pathlib import Path

import yaml

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.plugin_version import PluginVersion
from dev10x.domain.common.result import Result
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.skills.permission.catalog_merge import MergedCatalog, merge_catalogs
from dev10x.skills.permission.catalog_paths import shipped_projects_catalog
from dev10x.skills.permission.catalog_result import _result
from dev10x.skills.permission.config import parse_config, resolve_config

MEMORY_CONFIG = Dev10xConfigDir.projects_yaml()
USERSPACE_CONFIG = Dev10xConfigDir.upgrade_cleanup_projects_yaml()
PLUGIN_CONFIG = shipped_projects_catalog()

log = logging.getLogger(__name__)


def extract_cache_publisher(plugin_cache: str) -> str | None:
    path = Path(plugin_cache).expanduser()
    parts = list(path.parts)
    for i, part in enumerate(parts):
        if part == "cache" and i >= 2 and parts[i - 1] == "plugins":
            if i + 1 < len(parts):
                return parts[i + 1]
    return None


def find_config() -> Result[Path]:
    candidates = [MEMORY_CONFIG, USERSPACE_CONFIG]
    if PLUGIN_CONFIG is not None:
        candidates.append(PLUGIN_CONFIG)
    return resolve_config(candidates=candidates, create_path=MEMORY_CONFIG)


def load_config(config_path: Path) -> dict:
    return parse_config(config_path)


def load_shipped_config() -> dict | None:
    """Parse the plugin's shipped catalog, or ``None`` when unavailable.

    A missing or malformed shipped catalog degrades the merge to the
    userspace catalog alone rather than failing the command — the same
    tolerance :func:`load_policy_layers` applies to a partial install.
    """
    if PLUGIN_CONFIG is None:
        log.warning("Plugin root unresolvable, shipped catalog not loaded")
        return None
    if not PLUGIN_CONFIG.is_file():
        log.warning("Shipped catalog missing, merging skipped: %s", PLUGIN_CONFIG)
        return None
    try:
        return parse_config(PLUGIN_CONFIG)
    except (OSError, yaml.YAMLError):
        log.warning("Shipped catalog unreadable, merging skipped: %s", PLUGIN_CONFIG)
        return None


def load_effective_config(config_path: Path) -> MergedCatalog:
    """Load ``config_path`` merged with the shipped defaults (ADR-0021).

    When ``config_path`` IS the shipped catalog — the pre-``init`` case
    where no userspace copy exists — there is nothing to merge and the
    file is returned as-is.
    """
    user_config = load_config(config_path)
    if PLUGIN_CONFIG is not None and config_path == PLUGIN_CONFIG:
        return MergedCatalog(config=user_config)
    return merge_catalogs(shipped=load_shipped_config(), user=user_config)


def detect_latest_version(cache_dir: Path) -> str | None:
    if not cache_dir.is_dir():
        return None
    versions = sorted(
        cache_dir.iterdir(),
        key=lambda p: PluginVersion.sort_key(p.name),
    )
    return versions[-1].name if versions else None


def find_settings_files(
    roots: list[str],
    *,
    include_user: bool,
) -> list[Path]:
    files: list[Path] = []
    if include_user:
        user_dir = ClaudeDir.home()
        for name in ("settings.json", "settings.local.json"):
            candidate = user_dir / name
            if candidate.exists():
                files.append(candidate)

    project_settings_dir = ClaudeDir.projects_dir()
    if project_settings_dir.is_dir():
        for settings_file in project_settings_dir.rglob("settings.local.json"):
            files.append(settings_file)

    for root in roots:
        root_path = Path(root).expanduser()
        if not root_path.is_dir():
            continue
        for settings_file in root_path.rglob(".claude/settings.local.json"):
            files.append(settings_file)

    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


KNOWN_PLUGIN_DIRS = ("Dev10x", "dev10x-claude")


def _detect_plugin_cache() -> str:
    cache_root = ClaudeDir.plugins_cache_dir()
    if not cache_root.is_dir():
        return "~/.claude/plugins/cache/Dev10x-Guru/Dev10x"
    candidates: list[Path] = []
    for org_dir in cache_root.iterdir():
        if not org_dir.is_dir():
            continue
        for plugin_name in KNOWN_PLUGIN_DIRS:
            plugin_dir = org_dir / plugin_name
            if plugin_dir.is_dir():
                candidates.append(plugin_dir)
                break
    if len(candidates) == 1:
        return f"~/.claude/plugins/cache/{candidates[0].parent.name}/{candidates[0].name}"
    if len(candidates) > 1:
        names = ", ".join(f"{c.parent.name}/{c.name}" for c in candidates)
        print(f"Multiple plugin cache entries found: {names}")
        print(f"Using first match: {candidates[0].parent.name}/{candidates[0].name}")
        return f"~/.claude/plugins/cache/{candidates[0].parent.name}/{candidates[0].name}"
    return "~/.claude/plugins/cache/Dev10x-Guru/Dev10x"


def init_userspace_config() -> dict[str, object]:
    """Create or migrate the userspace projects config (GH-577).

    Consolidates on ``projects.yaml`` (MEMORY_CONFIG). When only the
    legacy ``upgrade-cleanup-projects.yaml`` (USERSPACE_CONFIG) exists,
    its content is migrated into ``projects.yaml`` so ``clean`` and
    ``merge-worktree`` — which now read ``projects.yaml`` — see the same
    roots as every other subcommand. The legacy file is left in place
    for downgrade safety; ``upgrade-cleanup``/``plugin-doctor`` remove
    it once parity is confirmed. Returns a result dict.
    """
    from dev10x.domain.file_locks import atomic_write_text, file_lock

    messages: list[str] = []
    errors: list[str] = []

    if MEMORY_CONFIG.is_file():
        messages.append(f"Config already exists: {MEMORY_CONFIG}")
        return _result(exit_code=0, messages=messages, errors=errors)

    MEMORY_CONFIG.parent.mkdir(parents=True, exist_ok=True)

    # Double-checked locking (GH-587): two worktrees/agents racing first-call
    # init must not both pass the exists-check and clobber each other's write.
    with file_lock(MEMORY_CONFIG):
        if MEMORY_CONFIG.is_file():
            messages.append(f"Config already exists: {MEMORY_CONFIG}")
            return _result(exit_code=0, messages=messages, errors=errors)

        if USERSPACE_CONFIG.is_file():
            atomic_write_text(MEMORY_CONFIG, USERSPACE_CONFIG.read_text())
            messages.append(f"Migrated {USERSPACE_CONFIG} -> {MEMORY_CONFIG}")
            messages.append(f"{USERSPACE_CONFIG} is deprecated; edit {MEMORY_CONFIG} from now on.")
            return _result(exit_code=0, messages=messages, errors=errors)

        if PLUGIN_CONFIG is None:
            errors.append(
                "ERROR: Could not resolve the Dev10x plugin root, so the "
                "shipped catalog could not be located. Set $CLAUDE_PLUGIN_ROOT "
                "or install the plugin."
            )
            return _result(exit_code=1, messages=messages, errors=errors)

        if not PLUGIN_CONFIG.is_file():
            errors.append(f"ERROR: Plugin default config not found: {PLUGIN_CONFIG}")
            return _result(exit_code=1, messages=messages, errors=errors)

        content = PLUGIN_CONFIG.read_text()
        detected_cache = _detect_plugin_cache()
        content = content.replace(
            "~/.claude/plugins/cache/Dev10x-Guru/dev10x-claude",
            detected_cache,
        )
        atomic_write_text(MEMORY_CONFIG, content)
        messages.append(f"Created: {MEMORY_CONFIG}")
        messages.append(f"Plugin cache: {detected_cache}")
        messages.append("Edit this file to add your project roots.")
        return _result(exit_code=0, messages=messages, errors=errors)
