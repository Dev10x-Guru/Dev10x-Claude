"""Write the permission catalog into settings files — the ``ensure_*`` fixers (GH-1432).

Every function here mutates a settings file, and every mutation goes
through :func:`dev10x.skills.permission.backup.backed_up_write` (GH-1429)
and — at the operation level — through :func:`partition_writable`, the
GH-1136/GH-1155 guard that keeps a git-tracked ``settings.json`` out of a
maintenance run. The rules being written are computed in
:mod:`dev10x.skills.permission.catalog_rules`; the catalog they come from
is loaded by :mod:`dev10x.skills.permission.catalog_load`. Split out of
``update_paths.py`` by GH-1432.
"""

import json
import subprocess
from pathlib import Path

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.result import Result, err, ok
from dev10x.skills.permission.backup import backed_up_write
from dev10x.skills.permission.catalog_load import detect_latest_version
from dev10x.skills.permission.catalog_merge import CatalogDrift
from dev10x.skills.permission.catalog_result import _result
from dev10x.skills.permission.catalog_rules import (
    _expand_stale_wildcards,
    _generalizations,
    _is_nonfunctional_mcp_wildcard,
    build_marketplaces_read_rules,
    build_marketplaces_script_rules,
    build_read_allow_rules,
    build_script_allow_rules,
    build_user_skill_script_rules,
    collapse_legacy_upgrade_cleanup_rule,
    is_dead_glob_script_rule,
    scan_plugin_scripts,
    scan_user_skill_scripts,
    verify_read_coverage,
    verify_script_coverage,
)
from dev10x.skills.permission.policy_catalog_migration import migrate_flat_config
from dev10x.skills.permission.policy_renderer import render_permissions


def ensure_base_permissions(
    path: Path,
    base_permissions: list[str],
    *,
    dry_run: bool = False,
    expand_mcp: bool = True,
    mcp_catalog: dict[str, list[str]] | None = None,
) -> tuple[int, list[str]]:
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, [f"  SKIP (invalid JSON): {e}"]

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    existing = {r for r in allow_list if not _is_nonfunctional_mcp_wildcard(r)}
    stale_wildcards = [r for r in allow_list if _is_nonfunctional_mcp_wildcard(r)]
    expanded_tools = _expand_stale_wildcards(
        stale_wildcards=stale_wildcards,
        existing=existing,
        enabled=expand_mcp,
        catalog=mcp_catalog,
    )
    if expanded_tools:
        existing.update(expanded_tools)

    # GH-1152: a rule this file's own `permissions.deny` names is a
    # deliberate local opt-out (e.g. denying mcp__claude_ai_Linear__* in
    # favour of mcp__linear-server__*). Re-adding it to `allow` does not
    # weaken anything — deny wins at evaluation time — but it accumulates
    # a contradictory pair on every upgrade and reads as the tool
    # fighting the user. Skip and report instead.
    denied = set(data.get("permissions", {}).get("deny", []))
    missing = [p for p in base_permissions if p not in existing and p not in denied]
    skipped_denied = [p for p in base_permissions if p not in existing and p in denied]

    if not missing and not stale_wildcards:
        if skipped_denied:
            return 0, [f"  skipped {len(skipped_denied)} denied by this file"]
        return 0, []

    if not dry_run:
        with backed_up_write(path=path) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            if "allow" not in live_data["permissions"]:
                live_data["permissions"]["allow"] = []
            if stale_wildcards:
                live_data["permissions"]["allow"] = [
                    r
                    for r in live_data["permissions"]["allow"]
                    if not _is_nonfunctional_mcp_wildcard(r)
                ]
            live_data["permissions"]["allow"].extend(expanded_tools)
            live_data["permissions"]["allow"].extend(missing)

    messages = [f"  - {wc}  (non-functional MCP wildcard removed)" for wc in stale_wildcards]
    messages.extend(f"  + {tool}  (expanded from MCP wildcard)" for tool in expanded_tools)
    messages.extend(f"  + {p}" for p in missing)
    if skipped_denied:
        messages.append(f"  skipped {len(skipped_denied)} denied by this file")
    return len(missing) + len(stale_wildcards) + len(expanded_tools), messages


def ensure_base_denies(
    path: Path,
    base_denies: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Add missing base deny rules to a settings file's `permissions.deny` list.

    Denies are stricter than allows — they must be enforced per project even
    when a global setting allows the same operation. The presence of a deny
    rule in global settings does NOT excuse adding it to project settings,
    so this helper skips the global-rules filter that `ensure_base_permissions`
    uses for allows.
    """
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, [f"  SKIP (invalid JSON): {e}"]

    deny_list: list[str] = data.get("permissions", {}).get("deny", [])
    existing = set(deny_list)
    missing = [d for d in base_denies if d not in existing]
    if not missing:
        return 0, []

    if not dry_run:
        with backed_up_write(path=path) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            if "deny" not in live_data["permissions"]:
                live_data["permissions"]["deny"] = []
            live_data["permissions"]["deny"].extend(missing)

    messages = [f"  + {d}  (deny)" for d in missing]
    return len(missing), messages


def ensure_base_asks(
    path: Path,
    base_asks: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Add missing base ask rules to a settings file's `permissions.ask` list.

    Asks share the per-project posture of denies, not of allows: a rule
    that prompts only in global settings prompts nowhere once a project
    `settings.local.json` exists (GH-47), so this helper skips the
    global-rules filter that `ensure_base_permissions` uses for allows.

    The ask tier exists because deny is the wrong instrument for a
    sensitive-but-legitimate operation (GH-1154). A hard deny drops the
    user into a manual `!` shell with no in-session recourse, which is
    exactly what DX014 avoids by emitting `ask`. A rule already denied by
    the target file is left alone — a deny is the stricter statement, and
    downgrading it to a prompt would silently weaken a deliberate choice.
    """
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, [f"  SKIP (invalid JSON): {e}"]

    permissions = data.get("permissions", {})
    existing = set(permissions.get("ask", []))
    denied = set(permissions.get("deny", []))
    missing = [a for a in base_asks if a not in existing and a not in denied]
    skipped_denied = [a for a in base_asks if a not in existing and a in denied]
    if not missing:
        if skipped_denied:
            return 0, [f"  skipped {len(skipped_denied)} already denied by this file"]
        return 0, []

    if not dry_run:
        with backed_up_write(path=path) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            if "ask" not in live_data["permissions"]:
                live_data["permissions"]["ask"] = []
            live_data["permissions"]["ask"].extend(missing)

    messages = [f"  + {a}  (ask)" for a in missing]
    if skipped_denied:
        messages.append(f"  skipped {len(skipped_denied)} already denied by this file")
    return len(missing), messages


def purge_dead_glob_script_rules(
    path: Path,
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Remove dead ``**`` cache-glob Bash rules from a settings file.

    Returns ``(count_removed, messages)``. Idempotent — a file with no
    dead globs returns ``(0, [])``.
    """
    try:
        content = path.read_text()
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        return 0, [f"  SKIP (unreadable JSON): {exc}"]

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    dead = [r for r in allow_list if is_dead_glob_script_rule(r)]
    if not dead:
        return 0, []

    if not dry_run:
        with backed_up_write(path=path) as live_data:
            allow = live_data.get("permissions", {}).get("allow", [])
            live_data["permissions"]["allow"] = [
                r for r in allow if not is_dead_glob_script_rule(r)
            ]

    messages = [f"  - {r}  (dead ** cache glob removed)" for r in dead]
    return len(dead), messages


def ensure_read_rules(
    settings_path: Path,
    missing_rules: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Append missing Read rules to ``settings_path``.

    Idempotent — only appends rules not already present. Backed up
    via :mod:`dev10x.skills.permission.backup`.
    """
    if not missing_rules:
        return 0, []

    if not dry_run:
        with backed_up_write(path=settings_path) as data:
            if "permissions" not in data:
                data["permissions"] = {}
            if "allow" not in data["permissions"]:
                data["permissions"]["allow"] = []
            existing = set(data["permissions"]["allow"])
            for rule in missing_rules:
                if rule not in existing:
                    data["permissions"]["allow"].append(rule)
                    existing.add(rule)

    messages = [f"  + {rule}" for rule in missing_rules]
    return len(missing_rules), messages


def ensure_script_rules(
    settings_path: Path,
    missing_rules: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    if not missing_rules:
        return 0, []

    if not dry_run:
        with backed_up_write(path=settings_path) as data:
            if "permissions" not in data:
                data["permissions"] = {}
            if "allow" not in data["permissions"]:
                data["permissions"]["allow"] = []
            data["permissions"]["allow"].extend(missing_rules)

    messages = [f"  + {rule}" for rule in missing_rules]
    return len(missing_rules), messages


def collapse_legacy_upgrade_cleanup_rules(
    path: Path,
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Rewrite legacy upgrade-cleanup script rules in a settings file."""

    try:
        content = path.read_text()
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        return 0, [f"  SKIP (unreadable JSON): {exc}"]

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    if not allow_list:
        return 0, []

    seen: set[str] = set()
    new_allow: list[str] = []
    replacements: list[tuple[str, str]] = []
    for entry in allow_list:
        collapsed = collapse_legacy_upgrade_cleanup_rule(entry)
        if collapsed is None:
            if entry not in seen:
                new_allow.append(entry)
                seen.add(entry)
            continue
        replacements.append((entry, collapsed))
        if collapsed not in seen:
            new_allow.append(collapsed)
            seen.add(collapsed)

    if not replacements:
        return 0, []

    if not dry_run:
        with backed_up_write(path=path) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            live_data["permissions"]["allow"] = new_allow

    messages = [f"  {old} → {new}" for old, new in replacements]
    return len(replacements), messages


def generalize_permissions(
    path: Path,
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, [f"  SKIP (invalid JSON): {e}"]

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    if not allow_list:
        return 0, []

    replacements, refused = _generalizations(allow_list)
    refusal_messages = [f"  REFUSED (would emit a malformed rule): {entry}" for entry in refused]

    if not replacements:
        return 0, refusal_messages

    if not dry_run:
        with backed_up_write(path=path) as live_data:
            live_allow = live_data.get("permissions", {}).get("allow", [])
            live_replacements, _live_refused = _generalizations(live_allow)
            for old, new in live_replacements:
                live_allow[live_allow.index(old)] = new

    messages = [f"  {old} → {new}" for old, new in replacements]
    messages.extend(refusal_messages)
    return len(replacements), messages


def _is_git_tracked(path: Path) -> bool:
    """True when `path` is tracked by git (GH-1136).

    A maintenance run must never write a git-tracked
    `.claude/settings.json`: doing so dirtied 16 working trees at once
    and rode into unrelated commits. Only `settings.local.json` — which
    projects gitignore — is a safe write target. An untracked file, a
    path outside any repo, and a missing `git` binary all answer False,
    so the check never blocks a legitimate write.
    """
    from dev10x import subprocess_utils

    try:
        completed = subprocess_utils.run(
            ["git", "ls-files", "--error-unmatch", path.name],
            cwd=str(path.parent),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def partition_writable(
    settings_files: list[Path],
    *,
    redirect_tracked: bool = False,
    allow_tracked: bool = False,
) -> tuple[list[Path], list[str]]:
    """Split settings files into writable ones and skip messages (GH-1136).

    For a long time this was the ONLY guard against writing a git-tracked
    `settings.json`, and it had exactly one caller — `ensure_base`. Its
    siblings (`ensure_scripts`, `ensure_reads`, the promote/update-paths
    writers) never consulted it, so a single maintenance run took one
    tracked file from 2 committed rules to 1495 allow / 51 ask / 82 deny
    in the working tree. The `SKIP (git-tracked)` line implied a safety
    property the tool set did not actually have (GH-1155).

    `redirect_tracked` sends those rules to the sibling
    `settings.local.json` instead of dropping them, which is what a
    caller wants when skipping would mean the rules reach no file at all.
    The redirect target is de-duplicated, so passing both spellings of a
    project's settings is safe.

    `allow_tracked` is the escape hatch for a user who genuinely intends
    to commit their settings; it disables the guard entirely and says so.
    """
    if allow_tracked:
        return list(settings_files), ["  (--allow-tracked: git-tracked guard disabled)"]

    writable: list[Path] = []
    messages: list[str] = []
    for path in settings_files:
        if path.name != "settings.json" or not _is_git_tracked(path):
            writable.append(path)
            continue
        if not redirect_tracked:
            messages.append(f"  SKIP (git-tracked): {path}")
            continue
        local_sibling = path.with_name("settings.local.json")
        if local_sibling in writable or local_sibling in settings_files:
            messages.append(f"  SKIP (git-tracked, sibling already targeted): {path}")
            continue
        if not local_sibling.is_file():
            # Redirecting to a file that does not exist would hand every
            # downstream writer a missing path to read. Creating it here
            # would invent a settings file the user never opted into, so
            # this reports the gap and writes nothing.
            messages.append(
                f"  SKIP (git-tracked, no {local_sibling.name} to redirect to): {path}"
            )
            continue
        messages.append(f"  REDIRECT (git-tracked): {path} -> {local_sibling.name}")
        writable.append(local_sibling)
    return writable, messages


# Retained so in-module callers and the existing monkeypatch-based tests
# keep working after the helper was promoted to the public surface for
# cross-module use by the `update-paths` and `promote-plan` commands.
_partition_writable = partition_writable


def _load_global_allow_rules() -> tuple[set[str], list[str]]:
    global_settings = ClaudeDir.settings_json()
    if not global_settings.is_file():
        return set(), []
    try:
        data = json.loads(global_settings.read_text())
        all_rules = data.get("permissions", {}).get("allow", [])
        wildcards = [r for r in all_rules if _is_nonfunctional_mcp_wildcard(r)]
        effective = {r for r in all_rules if not _is_nonfunctional_mcp_wildcard(r)}
        return effective, wildcards
    except (json.JSONDecodeError, OSError):
        return set(), []


def ensure_workspace_directories(
    path: Path,
    workspace_dirs: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Add missing entries to permissions.additionalDirectories.

    Allow-rules like Write(/tmp/Dev10x/**) don't cover paths outside
    the project root — Claude Code requires the directory to be
    registered as an additional working directory (GH-40). This
    function ensures the configured workspace dirs are present.

    Returns (count_added, messages).
    """
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, [f"  SKIP (invalid JSON): {e}"]

    permissions = data.get("permissions", {})
    existing = list(permissions.get("additionalDirectories", []))
    missing = [d for d in workspace_dirs if d not in existing]

    if not missing:
        return 0, []

    if not dry_run:
        with backed_up_write(path=path) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            current = live_data["permissions"].get("additionalDirectories", [])
            for d in workspace_dirs:
                if d not in current:
                    current.append(d)
            live_data["permissions"]["additionalDirectories"] = current

    messages = [f"  + additionalDirectories: {d}" for d in missing]
    return len(missing), messages


def ensure_workspace(
    *,
    config: dict,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
    allow_tracked: bool = False,
) -> dict[str, object]:
    """Add workspace directory registrations to settings files.

    Returns a result dict: ``{exit_code, messages, errors, total_added,
    files_changed}``. Callers print ``messages`` (stdout) and ``errors``
    (stderr) and act on ``exit_code``. No print() side effects.
    """
    messages: list[str] = []
    errors: list[str] = []

    workspace_dirs = config.get("workspace_directories", [])
    if not workspace_dirs:
        if not quiet:
            messages.append("No workspace_directories defined in config.")
        return _result(
            exit_code=0,
            messages=messages,
            errors=errors,
            total_added=0,
            files_changed=0,
        )

    if not quiet:
        messages.append(f"Workspace directories: {len(workspace_dirs)} entr(ies)")
        for d in workspace_dirs:
            messages.append(f"  - {d}")
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    # GH-1155: additionalDirectories entries are additive, so redirect a
    # tracked settings.json to its local sibling rather than skipping —
    # skipping would leave the workspace unregistered anywhere.
    writable_files, skip_messages = _partition_writable(
        sorted(settings_files),
        redirect_tracked=True,
        allow_tracked=allow_tracked,
    )
    if not quiet:
        messages.extend(skip_messages)

    total_added = 0
    files_changed = 0

    for path in writable_files:
        count, file_messages = ensure_workspace_directories(
            path,
            workspace_dirs,
            dry_run=dry_run,
        )
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_added += count
            files_changed += 1

    if total_added == 0:
        messages.append("All settings files already register the workspace directories.")
    else:
        verb = "Would add" if dry_run else "Added"
        messages.append(f"{verb} {total_added} workspace entries across {files_changed} files.")

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


def _catalog_drift_messages(*, drift: CatalogDrift | None, quiet: bool) -> list[str]:
    """Name shipped defaults the userspace catalog lacked (ADR-0021).

    The drift is computed once at load time and threaded in, so this
    stays a pure function of its arguments — re-reading the catalog
    here would make ``ensure_base`` depend on the caller's real home
    directory even when handed a synthetic config.

    The rules WILL be applied regardless; the message exists because
    the previous silence is what let five shipped defaults go missing
    unnoticed for months (GH-925 F1).
    """
    if quiet or drift is None or not drift.has_missing_defaults:
        return []
    missing = drift.missing_from_user + drift.denies_missing_from_user
    return [
        f"Catalog drift: {len(missing)} shipped rule(s) were absent from "
        f"the userspace catalog — merged in per ADR-0021. "
        f"Run `dev10x permission catalog-diff` for the full report."
    ]


def _apply_tracker_block(
    *,
    config: dict,
    toplevel: str | None,
    quiet: bool,
) -> tuple[dict, list[str]]:
    """Fold in only the project's tracker block, and say which (GH-768).

    Seeding is otherwise silent about omitting the other trackers' rules,
    and "my Jira tools still prompt" is indistinguishable from a bug
    unless the run states which tracker it seeded and where that came
    from. A catalog with no ``tracker_permissions:`` block at all is
    pre-GH-768 and passes through untouched.

    That pass-through is now a fallback rather than the pre-GH-768 norm
    (GH-1249): ``merge_catalogs`` supplies the shipped tracker block to a
    user catalog that lacks one, so a pre-GH-768 catalog reaches here
    already carrying it. The guard still fires when there is no shipped
    catalog to merge from — an unresolvable plugin root — where passing
    through untouched remains the right answer.
    """
    from dev10x.domain.common.tracker_choice import (
        TRACKER_ALLOW_KEY,
        TRACKER_DENY_KEY,
        apply_tracker_selection,
    )
    from dev10x.domain.git_context import GitContext
    from dev10x.skills.permission.tracker_resolve import resolve_tracker, tracker_source

    if not isinstance(config.get(TRACKER_ALLOW_KEY), dict) and not isinstance(
        config.get(TRACKER_DENY_KEY), dict
    ):
        return config, []

    resolved = toplevel if toplevel is not None else GitContext().toplevel
    tracker = resolve_tracker(toplevel=resolved)
    merged = apply_tracker_selection(config=config, tracker=tracker)
    if quiet:
        return merged, []
    source = tracker_source(toplevel=resolved)
    origin = {
        "project": "from this project's friction.yaml entry",
        "defaults": "from the friction.yaml defaults block",
        "default": "no tracker configured — using the default",
    }[source]
    return merged, [
        f"Issue tracker: {tracker.value} ({origin}). "
        f"Only {tracker.value} tracker rules are seeded; other trackers' "
        f"rules are left out. Change it with the `tracker:` key in "
        f"~/.config/Dev10x/friction.yaml."
    ]


def _apply_ide_block(
    *,
    config: dict,
    toplevel: str | None,
    quiet: bool,
) -> tuple[dict, list[str]]:
    """Fold in only the project's IDE block, and say which (GH-1261).

    Mirrors :func:`_apply_tracker_block`, with one difference that
    matters: the resolved default is ``none``, so an unpinned project
    folds nothing and the run stays silent. Announcing "IDE: none" on
    every seeding run in every repo without an IDE server would be noise
    about a non-event.
    """
    from dev10x.domain.common.ide_choice import (
        IDE_ALLOW_KEY,
        IDE_DENY_KEY,
        Ide,
        apply_ide_selection,
    )
    from dev10x.domain.git_context import GitContext
    from dev10x.skills.permission.ide_resolve import ide_source, resolve_ide

    if not isinstance(config.get(IDE_ALLOW_KEY), dict) and not isinstance(
        config.get(IDE_DENY_KEY), dict
    ):
        return config, []

    resolved = toplevel if toplevel is not None else GitContext().toplevel
    ide = resolve_ide(toplevel=resolved)
    merged = apply_ide_selection(config=config, ide=ide)
    if quiet or ide is Ide.NONE:
        return merged, []
    origin = {
        "project": "from this project's friction.yaml entry",
        "defaults": "from the friction.yaml defaults block",
        "default": "no IDE configured — using the default",
    }[ide_source(toplevel=resolved)]
    return merged, [
        f"IDE MCP server: {ide.value} ({origin}). Its read and edit tools "
        f"are seeded; its shell-equivalent tools stay denied. Change it "
        f"with the `ide:` key in ~/.config/Dev10x/friction.yaml."
    ]


def ensure_base(
    *,
    config: dict,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
    drift: CatalogDrift | None = None,
    toplevel: str | None = None,
    dedupe_global: bool = False,
) -> dict[str, object]:
    """Add missing base permissions to each settings file. Returns result dict.

    ``dedupe_global`` opts back into the pre-GH-1136 behaviour of skipping
    rules already present in ``~/.claude/settings.json``. It defaults off
    because the permission engine consults the *project* file when one
    exists (GH-47): a rule that lives only in global does not cover the
    project, so treating global as coverage wrote nothing to any project
    file for months while reporting success. Same opt-in posture as
    ``clean --aggressive``.
    """
    messages: list[str] = []
    errors: list[str] = []

    config, tracker_messages = _apply_tracker_block(
        config=config,
        toplevel=toplevel,
        quiet=quiet,
    )
    messages.extend(tracker_messages)

    config, ide_messages = _apply_ide_block(
        config=config,
        toplevel=toplevel,
        quiet=quiet,
    )
    messages.extend(ide_messages)

    policies = migrate_flat_config(config=config)
    rendered = render_permissions(policies=policies, home=str(Path.home()))
    base_permissions = rendered.get("allow", [])
    base_denies = rendered.get("deny", [])
    base_asks = rendered.get("ask", [])
    if not base_permissions and not base_denies and not base_asks:
        messages.append("No base_permissions, base_denies or base_asks defined in config.")
        return _result(exit_code=0, messages=messages, errors=errors)

    messages.extend(_catalog_drift_messages(drift=drift, quiet=quiet))

    global_rules, stale_wildcards = _load_global_allow_rules()
    if dedupe_global:
        filtered = [p for p in base_permissions if p not in global_rules]
        skipped = len(base_permissions) - len(filtered)
    else:
        filtered = list(base_permissions)
        skipped = 0

    writable_files, skip_messages = _partition_writable(sorted(settings_files))

    total_added = 0
    changed_files: set[Path] = set()
    per_file_added: dict[Path, int] = {}

    # GH-1320: disableAutoMode / disableBypassPermissionsMode are a
    # compliance floor, not part of the allow/deny/ask catalog below —
    # seeded here (same writable_files, same GH-1155 guard) so every
    # settings file ensure_base touches carries them regardless of
    # whether the catalog itself has anything left to add, per the
    # issue's acceptance criterion. Additive only; an invalid existing
    # value is left for `dev10x permission doctor safety-keys` to flag.
    from dev10x.skills.permission.safety_keys import write_safety_keys_to_file

    for path in writable_files:
        count, file_messages = write_safety_keys_to_file(path, dry_run=dry_run)
        if count == 0:
            continue
        if not quiet:
            messages.append(f"\n{path} (safety keys)")
            messages.extend(file_messages)
        total_added += count
        changed_files.add(path)
        per_file_added[path] = per_file_added.get(path, 0) + count

    if not quiet:
        messages.append(f"Base permissions: {len(base_permissions)} rules")
        if stale_wildcards:
            messages.append(
                f"  WARNING: {len(stale_wildcards)} non-functional MCP wildcard(s)"
                " in global settings.json:"
            )
            for wc in stale_wildcards:
                messages.append(f"    - {wc}  (Claude Code ignores MCP wildcards)")
        if skipped > 0:
            messages.append(
                f"  Skipping {skipped} already in global settings.json (--dedupe-global)"
            )
        messages.extend(skip_messages)
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    # Only the allow tier is dedupable against global; denies and asks are
    # enforced per project regardless (GH-47). Returning here whenever the
    # allow list came back empty would skip both of the other tiers, so the
    # early exit has to be conditional on all three (GH-1154).
    if not filtered and not base_denies and not base_asks:
        if not quiet:
            messages.append("All base permissions already covered by global settings.")
        return _result(
            exit_code=0,
            messages=messages,
            errors=errors,
            total_added=total_added,
            files_changed=len(changed_files),
        )

    from dev10x.skills.permission.enumerate_mcp import discover_mcp_tools

    mcp_catalog = discover_mcp_tools()

    for path in writable_files:
        count, file_messages = ensure_base_permissions(
            path,
            filtered,
            dry_run=dry_run,
            mcp_catalog=mcp_catalog,
        )
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_added += count
            changed_files.add(path)
            per_file_added[path] = per_file_added.get(path, 0) + count

    if base_denies:
        if not quiet:
            messages.append(f"\nBase denies: {len(base_denies)} rules")
        for path in writable_files:
            count, file_messages = ensure_base_denies(
                path,
                base_denies,
                dry_run=dry_run,
            )
            if count > 0:
                if not quiet:
                    messages.append(f"\n{path}")
                    messages.extend(file_messages)
                total_added += count
                changed_files.add(path)
                per_file_added[path] = per_file_added.get(path, 0) + count

    if base_asks:
        if not quiet:
            messages.append(f"\nBase asks: {len(base_asks)} rules")
        for path in writable_files:
            count, file_messages = ensure_base_asks(
                path,
                base_asks,
                dry_run=dry_run,
            )
            if count > 0:
                if not quiet:
                    messages.append(f"\n{path}")
                    messages.extend(file_messages)
                total_added += count
                changed_files.add(path)
                per_file_added[path] = per_file_added.get(path, 0) + count

    files_changed = len(changed_files)

    if total_added == 0:
        messages.append("All files already have base permissions.")
    else:
        verb = "Would add" if dry_run else "Added"
        messages.append(f"{verb} {total_added} permissions across {files_changed} files.")

    messages.append("\nPer-file added counts:")
    for path in writable_files:
        messages.append(f"  {per_file_added.get(path, 0):>4}  {path}")

    residual = _residual_gap_errors(
        settings_files=writable_files,
        base_permissions=filtered,
        base_denies=base_denies,
        base_asks=base_asks,
        dry_run=dry_run,
    )
    errors.extend(residual)

    return _result(
        exit_code=1 if residual else 0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


def _residual_gap_errors(
    *,
    settings_files: list[Path],
    base_permissions: list[str],
    base_denies: list[str],
    dry_run: bool,
    base_asks: list[str] | None = None,
) -> list[str]:
    """Name every file that still lacks catalog rules after a write (GH-1136).

    Silence was the original defect: the run reported success while
    leaving 137 of 285 rules out of every project file. A residual gap
    after a real write is a failure, so it exits non-zero and names the
    files. A dry run asserts nothing — it wrote nothing by design.
    """
    if dry_run:
        return []

    from dev10x.skills.permission.catalog_gap import compute_gap

    errors: list[str] = []
    for path in settings_files:
        gap = compute_gap(
            path=path,
            base_permissions=base_permissions,
            base_denies=base_denies,
            base_asks=base_asks,
        )
        if not gap.is_empty:
            errors.append(
                f"ERROR: {path} still missing {len(gap.missing_allow)} allow / "
                f"{len(gap.missing_deny)} deny / {len(gap.missing_ask)} ask "
                "catalog rules after ensure-base."
            )
    return errors


def catalog_gap(
    *,
    config: dict,
    settings_files: list[Path],
    quiet: bool = False,
    verbose: bool = False,
    toplevel: str | None = None,
) -> dict[str, object]:
    """Report which catalog rules each settings file is missing (GH-1136).

    Read-only counterpart to ``ensure_base``: it answers "does this file
    carry the catalog?" without writing anything, so post-upgrade
    verification is a command rather than a reading of a maintenance log.
    Exits non-zero when any file has a gap.
    """
    from dev10x.skills.permission.catalog_gap import compute_gap, format_gap_report

    messages: list[str] = []
    config, tracker_messages = _apply_tracker_block(
        config=config,
        toplevel=toplevel,
        quiet=quiet,
    )
    messages.extend(tracker_messages)

    config, ide_messages = _apply_ide_block(
        config=config,
        toplevel=toplevel,
        quiet=quiet,
    )
    messages.extend(ide_messages)

    policies = migrate_flat_config(config=config)
    rendered = render_permissions(policies=policies, home=str(Path.home()))
    base_permissions = rendered.get("allow", [])
    base_denies = rendered.get("deny", [])
    base_asks = rendered.get("ask", [])

    if not quiet:
        messages.append(
            f"Catalog: {len(base_permissions)} allow / {len(base_denies)} deny"
            f" / {len(base_asks)} ask rules\n"
        )

    total_missing = 0
    for path in sorted(settings_files):
        gap = compute_gap(
            path=path,
            base_permissions=base_permissions,
            base_denies=base_denies,
            base_asks=base_asks,
        )
        total_missing += gap.total_missing
        messages.extend(format_gap_report(gap, verbose=verbose))
        messages.append("")

    return _result(
        exit_code=1 if total_missing else 0,
        messages=messages,
        errors=[],
        total_added=total_missing,
        files_changed=len(settings_files),
    )


def seed_worktree(
    *,
    worktree_root: Path,
    config: dict,
    dry_run: bool = False,
    dedupe_global: bool = False,
) -> Result[dict[str, object]]:
    """Pre-seed a single worktree's settings.local.json with base defaults (GH-602).

    A read-only surface curated once should be honored in a freshly created
    worktree without a first prompt. This seeds the worktree's
    ``.claude/settings.local.json`` (creating it when absent) with the base
    catalog. Returns the count added so the worktree-creation caller can
    report it.

    ``dedupe_global`` defaults off for the reason given on ``ensure_base``:
    a rule present only in ``~/.claude/settings.json`` does not cover a
    worktree whose own settings file the engine reads instead, so skipping
    it left every freshly created worktree short of the catalog (GH-1136).

    The write itself is **delegated to** ``ensure_base`` (GH-1405). This
    function used to render the catalog and call two of the three tier
    writers itself, which made a new worktree structurally weaker than a
    checkout: no ``base_asks`` (so curated prompts reverted to raw
    prompts), no tracker or IDE block (so the IDE shell-equivalent denies
    — unconditional by GH-1261 — were simply absent), no safety keys
    (GH-1320), and no residual-gap check (GH-1136). Each omission was a
    separate line that had to be kept in step with ``ensure_base`` and
    none of them was; delegating removes the class rather than the four
    instances.
    """
    settings = Path(worktree_root) / ".claude" / "settings.local.json"

    created_fresh = not settings.exists()
    if dry_run:
        return ok(
            {
                "path": str(settings),
                "added": 0,
                "would_create": created_fresh,
                "dry_run": True,
            }
        )

    if created_fresh:
        try:
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text("{}\n")
        except OSError as error:
            return err(f"cannot create worktree settings: {error}", path=str(settings))

    result = ensure_base(
        config=config,
        settings_files=[settings],
        dry_run=False,
        quiet=True,
        toplevel=str(worktree_root),
        dedupe_global=dedupe_global,
    )

    raw_errors = result.get("errors")
    errors = raw_errors if isinstance(raw_errors, list) else []
    if errors:
        return err(
            f"worktree seeded with a residual catalog gap: {'; '.join(errors)}",
            path=str(settings),
            created_fresh=created_fresh,
            added=result.get("total_added", 0),
        )

    return ok(
        {
            "path": str(settings),
            "added": result.get("total_added", 0),
            "created_fresh": created_fresh,
        }
    )


def generalize(
    *,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
    allow_tracked: bool = False,
) -> dict[str, object]:
    """Replace session-specific permission args with wildcards. Returns result dict."""
    messages: list[str] = []
    errors: list[str] = []

    if dry_run and not quiet:
        messages.append("(dry run — no files will be modified)\n")

    # GH-1155: plain skip rather than redirect. Like the update-paths CLI,
    # this command rewrites rules that already exist in the target file,
    # so there is nothing to hand to a sibling — the sibling gets its own
    # pass from its own entry in settings_files.
    writable_files, skip_messages = _partition_writable(
        sorted(settings_files),
        allow_tracked=allow_tracked,
    )
    if not quiet:
        messages.extend(skip_messages)

    total_generalized = 0
    files_changed = 0

    for path in writable_files:
        count, file_messages = generalize_permissions(path, dry_run=dry_run)
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_generalized += count
            files_changed += 1
        elif file_messages and not quiet:
            # A zero count with messages means every candidate rule was
            # REFUSED as malformed (GH-1150). Dropping those messages here
            # would restore the silence that issue exists to remove — the
            # file looks untouched and nothing says a rule was skipped.
            messages.append(f"\n{path}")
            messages.extend(file_messages)

    if total_generalized == 0:
        messages.append("No session-specific permissions found.")
    else:
        verb = "Would generalize" if dry_run else "Generalized"
        messages.append(f"{verb} {total_generalized} permissions in {files_changed} files.")

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_generalized,
        files_changed=files_changed,
    )


def ensure_scripts(
    *,
    config: dict,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
    allow_tracked: bool = False,
) -> dict[str, object]:
    """Add missing per-script allow rules for plugin scripts. Returns result dict."""
    messages: list[str] = []
    errors: list[str] = []

    cache_dir = Path(config["plugin_cache"]).expanduser()
    target_version = detect_latest_version(cache_dir)
    if not target_version:
        errors.append(f"ERROR: No versions found in {cache_dir}")
        return _result(exit_code=1, messages=messages, errors=errors)

    plugin_root = cache_dir / target_version
    scripts = scan_plugin_scripts(plugin_root)
    if not scripts:
        messages.append(f"No callable scripts found in {plugin_root}")
        return _result(exit_code=0, messages=messages, errors=errors)

    expected_rules = build_script_allow_rules(
        scripts,
        plugin_root=plugin_root,
    )
    # GH-704: also seed the unversioned marketplace-root twins so a grant
    # matches whichever root family (cache vs marketplaces) dispatches the
    # script.
    expected_rules += build_marketplaces_script_rules(
        scripts,
        plugin_root=plugin_root,
        plugin_cache=config["plugin_cache"],
        user_home=Path.home(),
    )

    if not quiet:
        messages.append(f"Plugin root: {plugin_root}")
        messages.append(f"Scripts found: {len(scripts)}")
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    # GH-1155: this guard used to live only in ensure_base, so a tracked
    # settings.json collected every per-script rule this command emits.
    writable_files, skip_messages = _partition_writable(
        sorted(settings_files),
        redirect_tracked=True,
        allow_tracked=allow_tracked,
    )
    if not quiet:
        messages.extend(skip_messages)

    total_added = 0
    total_purged = 0
    files_changed = 0

    for path in writable_files:
        # GH-471: purge dead ** cache globs first so verify_script_coverage
        # reports the concrete version-pinned rules as missing and they get
        # added — replacing the non-functional globs rather than coexisting.
        purged, purge_messages = purge_dead_glob_script_rules(path, dry_run=dry_run)

        _covered, missing = verify_script_coverage(
            settings_path=path,
            expected_rules=expected_rules,
        )
        count = 0
        file_messages: list[str] = []
        if missing:
            count, file_messages = ensure_script_rules(
                settings_path=path,
                missing_rules=missing,
                dry_run=dry_run,
            )

        if purged > 0 or count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(purge_messages)
                messages.extend(file_messages)
            total_added += count
            total_purged += purged
            files_changed += 1

    if total_added == 0 and total_purged == 0:
        messages.append("All settings files have complete script coverage.")
    else:
        verb = "Would update" if dry_run else "Updated"
        messages.append(
            f"{verb} {files_changed} files "
            f"(+{total_added} concrete rules, -{total_purged} dead ** globs)."
        )

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


def ensure_user_skill_scripts(
    *,
    settings_files: list[Path],
    skills_root: Path | None = None,
    user_home: Path | None = None,
    dry_run: bool,
    quiet: bool = False,
    allow_tracked: bool = False,
) -> dict[str, object]:
    """Seed canonical allow rules for user-skill scripts (GH-606 AC2).

    Enumerates ``~/.claude/skills/<dir>/scripts/*.{sh,py}`` (colon-kept and
    prefix-stripped dirs alike), emits ``~/`` + ``/home/<user>/`` twin
    ``Bash(...:*)`` rules, and SKIPS verb-blind credentialed pass-through
    wrappers so they keep prompting. Matching is exact (like
    :func:`ensure_reads`), so re-runs are idempotent.
    """
    messages: list[str] = []
    errors: list[str] = []

    root = skills_root or (ClaudeDir.home() / "skills")
    home = user_home or Path.home()
    scripts = scan_user_skill_scripts(root)
    if not scripts:
        if not quiet:
            messages.append(f"No user-skill scripts found in {root}")
        return _result(exit_code=0, messages=messages, errors=errors)

    expected_rules, skipped = build_user_skill_script_rules(
        scripts, skills_root=root, user_home=home
    )

    if not quiet:
        messages.append(f"User-skill scripts root: {root}")
        messages.append(
            f"Scripts found: {len(scripts)} ({len(expected_rules)} rules, twins included)"
        )
        for wrapper in skipped:
            messages.append(f"  SKIP (verb-blind credentialed wrapper, no :* rule): {wrapper}")
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    # GH-1155: shares the `ensure-scripts` command with ensure_scripts, so
    # it needs the same git-tracked guard — guarding only its sibling would
    # leave the command still writing a tracked file.
    writable_files, skip_messages = _partition_writable(
        sorted(settings_files),
        redirect_tracked=True,
        allow_tracked=allow_tracked,
    )
    if not quiet:
        messages.extend(skip_messages)

    total_added = 0
    files_changed = 0

    for path in writable_files:
        _covered, missing = verify_read_coverage(
            settings_path=path,
            expected_rules=expected_rules,
        )
        if not missing:
            continue
        count, file_messages = ensure_read_rules(
            settings_path=path,
            missing_rules=missing,
            dry_run=dry_run,
        )
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_added += count
            files_changed += 1

    if total_added == 0:
        messages.append("All settings files already cover the user-skill scripts.")
    else:
        verb = "Would add" if dry_run else "Added"
        messages.append(
            f"{verb} {total_added} user-skill script rules across {files_changed} files."
        )

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


def ensure_reads(
    *,
    config: dict,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
    allow_tracked: bool = False,
) -> dict[str, object]:
    """Emit per-skill folder Read rules with ~/ + /home/<user>/ twins. Returns result dict."""
    messages: list[str] = []
    errors: list[str] = []

    cache_dir = Path(config["plugin_cache"]).expanduser()
    target_version = detect_latest_version(cache_dir)
    if not target_version:
        errors.append(f"ERROR: No versions found in {cache_dir}")
        return _result(exit_code=1, messages=messages, errors=errors)

    plugin_root = cache_dir / target_version
    expected_rules = build_read_allow_rules(
        plugin_root=plugin_root,
        user_home=Path.home(),
    )
    # GH-254: emit unversioned marketplaces Read rules alongside the
    # versioned cache rules. The runtime reads skills from the
    # marketplaces tree, which is unversioned — pinning to cache
    # versions guarantees the rule goes stale on every upgrade.
    expected_rules.extend(
        build_marketplaces_read_rules(
            plugin_cache=config["plugin_cache"],
            user_home=Path.home(),
        )
    )
    if not expected_rules:
        messages.append(f"No Read rules to emit for {plugin_root}")
        return _result(exit_code=0, messages=messages, errors=errors)

    if not quiet:
        messages.append(f"Plugin root: {plugin_root}")
        messages.append(f"Read rules expected: {len(expected_rules)} (twins included)")
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    # GH-1155: this guard used to live only in ensure_base, so a tracked
    # settings.json collected every Read rule this command emits.
    writable_files, skip_messages = _partition_writable(
        sorted(settings_files),
        redirect_tracked=True,
        allow_tracked=allow_tracked,
    )
    if not quiet:
        messages.extend(skip_messages)

    total_added = 0
    files_changed = 0

    for path in writable_files:
        _covered, missing = verify_read_coverage(
            settings_path=path,
            expected_rules=expected_rules,
        )
        if not missing:
            continue

        count, file_messages = ensure_read_rules(
            settings_path=path,
            missing_rules=missing,
            dry_run=dry_run,
        )
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_added += count
            files_changed += 1

    if total_added == 0:
        messages.append("All settings files have complete Read coverage.")
    else:
        verb = "Would add" if dry_run else "Added"
        messages.append(f"{verb} {total_added} Read rules across {files_changed} files.")

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )
