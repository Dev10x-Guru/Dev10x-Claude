"""Maintain Dev10x plugin permission settings across all projects.

Modes:
  - (default) Update versioned plugin cache paths to the latest version
  - ensure-base: Add missing base permissions from projects.yaml
  - generalize: Replace session-specific args with wildcard patterns

CLI entry point: ``dev10x permission update-paths`` (and siblings).

This module was 2,308 lines holding ten catalog operations (GH-1432).
Each operation now lives in the module it belongs to, and this module
re-exports them so ``from dev10x.skills.permission.update_paths import
...`` and ``update_paths.<name>`` keep resolving:

- :mod:`~dev10x.skills.permission.catalog_load` — config lookup and
  loading, settings-file discovery, userspace-config bootstrap
- :mod:`~dev10x.skills.permission.catalog_rules` — computing the rules
  the catalog expects (script/Read builders, coverage checks,
  generalization, legacy-rule collapse); no writes
- :mod:`~dev10x.skills.permission.catalog_write` — the ``ensure_*``
  fixers, ``generalize``, ``seed_worktree`` and the git-tracked guard
- :mod:`~dev10x.skills.permission.catalog_version` — versioned
  plugin-cache path rewriting
- :mod:`~dev10x.skills.permission.catalog_backup` — ``--restore``
- :mod:`~dev10x.skills.permission.catalog_result` — the result-dict
  shape every operation returns

``doctor.py`` stays the diagnose-only layer it already was. A patch
aimed at code that moved must target the owning module: patching a
name here rebinds only this facade.
"""

from dev10x.skills.permission.catalog_backup import _restore
from dev10x.skills.permission.catalog_load import (
    KNOWN_PLUGIN_DIRS,
    MEMORY_CONFIG,
    PLUGIN_CONFIG,
    USERSPACE_CONFIG,
    _detect_plugin_cache,
    detect_latest_version,
    extract_cache_publisher,
    find_config,
    find_settings_files,
    init_userspace_config,
    load_config,
    load_effective_config,
    load_shipped_config,
)
from dev10x.skills.permission.catalog_result import _result
from dev10x.skills.permission.catalog_rules import (
    _CREDENTIALED_EXEC_RE,
    _DUP_SLASH_RE,
    _LEGACY_UPGRADE_CLEANUP_RULE_PATTERN,
    _LEGACY_UPGRADE_CLEANUP_SCRIPTS,
    _PASSTHROUGH_ARGV_RE,
    _RULE_ARG_TAIL,
    _RULE_SHAPE_RE,
    _VERB_ALLOWLIST_RE,
    GENERALIZE_PATTERNS,
    MCP_WILDCARD_PATTERN,
    READ_TOP_LEVEL_DIRS,
    SCRIPT_SCAN_GLOBS,
    USER_SKILL_SCRIPT_GLOBS,
    _entry_covers_script,
    _expand_stale_wildcards,
    _generalizations,
    _is_nonfunctional_mcp_wildcard,
    _unescaped_parens_balance,
    build_marketplaces_read_rules,
    build_marketplaces_script_rules,
    build_read_allow_rules,
    build_script_allow_rules,
    build_user_skill_script_rules,
    collapse_double_slashes,
    collapse_legacy_upgrade_cleanup_rule,
    generalize_permission,
    is_dead_glob_script_rule,
    is_verb_blind_credentialed_wrapper,
    is_well_formed_rule,
    scan_plugin_scripts,
    scan_skill_directories,
    scan_top_level_dirs,
    scan_user_skill_scripts,
    verify_read_coverage,
    verify_script_coverage,
)
from dev10x.skills.permission.catalog_version import (
    VERSION_PATTERN,
    _rewrite_plugin_version_match,
    update_file,
)
from dev10x.skills.permission.catalog_write import (
    _apply_ide_block,
    _apply_tracker_block,
    _catalog_drift_messages,
    _is_git_tracked,
    _load_global_allow_rules,
    _partition_writable,
    _residual_gap_errors,
    catalog_gap,
    collapse_legacy_upgrade_cleanup_rules,
    ensure_base,
    ensure_base_asks,
    ensure_base_denies,
    ensure_base_permissions,
    ensure_read_rules,
    ensure_reads,
    ensure_script_rules,
    ensure_scripts,
    ensure_user_skill_scripts,
    ensure_workspace,
    ensure_workspace_directories,
    generalize,
    generalize_permissions,
    partition_writable,
    purge_dead_glob_script_rules,
    seed_worktree,
)

__all__ = [
    "GENERALIZE_PATTERNS",
    "KNOWN_PLUGIN_DIRS",
    "MCP_WILDCARD_PATTERN",
    "MEMORY_CONFIG",
    "PLUGIN_CONFIG",
    "READ_TOP_LEVEL_DIRS",
    "SCRIPT_SCAN_GLOBS",
    "USERSPACE_CONFIG",
    "USER_SKILL_SCRIPT_GLOBS",
    "VERSION_PATTERN",
    "_CREDENTIALED_EXEC_RE",
    "_DUP_SLASH_RE",
    "_LEGACY_UPGRADE_CLEANUP_RULE_PATTERN",
    "_LEGACY_UPGRADE_CLEANUP_SCRIPTS",
    "_PASSTHROUGH_ARGV_RE",
    "_RULE_ARG_TAIL",
    "_RULE_SHAPE_RE",
    "_VERB_ALLOWLIST_RE",
    "_apply_ide_block",
    "_apply_tracker_block",
    "_catalog_drift_messages",
    "_detect_plugin_cache",
    "_entry_covers_script",
    "_expand_stale_wildcards",
    "_generalizations",
    "_is_git_tracked",
    "_is_nonfunctional_mcp_wildcard",
    "_load_global_allow_rules",
    "_partition_writable",
    "_residual_gap_errors",
    "_restore",
    "_result",
    "_rewrite_plugin_version_match",
    "_unescaped_parens_balance",
    "build_marketplaces_read_rules",
    "build_marketplaces_script_rules",
    "build_read_allow_rules",
    "build_script_allow_rules",
    "build_user_skill_script_rules",
    "catalog_gap",
    "collapse_double_slashes",
    "collapse_legacy_upgrade_cleanup_rule",
    "collapse_legacy_upgrade_cleanup_rules",
    "detect_latest_version",
    "ensure_base",
    "ensure_base_asks",
    "ensure_base_denies",
    "ensure_base_permissions",
    "ensure_read_rules",
    "ensure_reads",
    "ensure_script_rules",
    "ensure_scripts",
    "ensure_user_skill_scripts",
    "ensure_workspace",
    "ensure_workspace_directories",
    "extract_cache_publisher",
    "find_config",
    "find_settings_files",
    "generalize",
    "generalize_permission",
    "generalize_permissions",
    "init_userspace_config",
    "is_dead_glob_script_rule",
    "is_verb_blind_credentialed_wrapper",
    "is_well_formed_rule",
    "load_config",
    "load_effective_config",
    "load_shipped_config",
    "partition_writable",
    "purge_dead_glob_script_rules",
    "scan_plugin_scripts",
    "scan_skill_directories",
    "scan_top_level_dirs",
    "scan_user_skill_scripts",
    "seed_worktree",
    "update_file",
    "verify_read_coverage",
    "verify_script_coverage",
]
