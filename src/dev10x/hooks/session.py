"""Session hook logic — reload prior state and compact context.

SessionReloader: reads persisted state file and plan file, produces
additionalContext for the agent on session start.

ContextCompactor: injects structured context summary before compaction
so the agent recovers gracefully after context window compression.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.file_locks import atomic_write_text, file_lock
from dev10x.domain.git_context import GitContext

_git = GitContext()


def _get_toplevel() -> str | None:
    return _git.toplevel


def _get_branch() -> str:
    return _git.branch


def _run_git(*args: str) -> str:
    try:
        return GitContext().run(*args)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return {}


def _claim_state_file(path: Path) -> dict[str, Any]:
    claimed = path.with_suffix(f".{os.getpid()}.claimed")
    try:
        os.rename(path, claimed)
    except FileNotFoundError:
        return {}
    try:
        return _read_json(path=claimed)
    finally:
        claimed.unlink(missing_ok=True)


def _read_plan_summary(*, toplevel: str) -> dict[str, Any]:
    from dev10x.hooks.task_plan_sync import get_plan_path, read_plan

    plan_path = get_plan_path(toplevel=toplevel)
    return read_plan(plan_path=plan_path)


def _escape_for_json(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _format_session_state(state: dict[str, Any]) -> str:
    from dev10x.domain.session_state import SessionState

    return SessionState.from_dict(data=state).format_for_display()


def _format_plan_summary(plan: dict[str, Any]) -> str:
    from dev10x.domain.session_state import PlanSummary

    return PlanSummary.from_dict(data=plan).format_for_display()


def _read_friction_level(*, toplevel: str) -> str:
    session_yaml = Path(toplevel) / ".claude" / "Dev10x" / "session.yaml"
    if not session_yaml.exists():
        return ""
    try:
        import yaml

        with open(session_yaml) as f:
            data = yaml.safe_load(f) or {}
        return data.get("friction_level", "")
    except Exception:
        return ""


def _format_decision_guidance(
    *,
    plan: dict[str, Any],
    friction_level: str,
) -> str:
    from dev10x.domain.session_state import PlanSummary

    summary = PlanSummary.from_dict(data=plan)
    decisions = summary.pending_decisions
    if not decisions:
        has_remaining = any(t.get("status") not in ("completed", "deleted") for t in summary.tasks)
        if has_remaining:
            return "Session resumed with tasks remaining. Auto-advance through the task list."
        return ""

    if friction_level == "adaptive":
        return (
            "Session resumed with pending decisions. Friction level is adaptive — "
            "auto-select recommended options for all queued decisions and continue "
            "advancing through the task list without calling AskUserQuestion."
        )
    return (
        "Session resumed with pending decisions. "
        "Re-ask each pending decision using AskUserQuestion — "
        "invoke Dev10x:ask before advancing."
    )


def build_reload_context() -> str:
    """Build the session-reload additionalContext string. Empty when no state."""
    toplevel = _get_toplevel()
    if not toplevel:
        return ""

    project_hash = hashlib.md5(toplevel.encode()).hexdigest()
    state_dir = ClaudeDir.session_state_dir()
    state_file = state_dir / f"{project_hash}.json"
    plan_file = Path(toplevel) / ".claude" / "session" / "plan.yaml"

    state = _claim_state_file(path=state_file)
    has_plan = plan_file.exists()

    if not state and not has_plan:
        return ""

    parts: list[str] = []

    if state:
        state_text = _format_session_state(state=state)
        if state_text:
            parts.append(state_text)

    if has_plan:
        plan = _read_plan_summary(toplevel=toplevel)
        plan_text = _format_plan_summary(plan=plan)
        if plan_text:
            parts.append(plan_text)
        friction_level = _read_friction_level(toplevel=toplevel)
        guidance = _format_decision_guidance(plan=plan, friction_level=friction_level)
        if guidance:
            parts.append(guidance)

    return "\n\n".join(parts)


def session_reload() -> None:
    context = build_reload_context()
    if not context:
        sys.exit(0)

    escaped = _escape_for_json(s=context)
    output = (
        '{"hookSpecificOutput":{"hookEventName":"SessionStart",'
        f'"additionalContext":"{escaped}"}}}}'
    )
    print(output)


def context_compact() -> None:
    toplevel = _get_toplevel()
    if not toplevel:
        sys.exit(0)

    branch = _get_branch()
    worktree_name = ""
    git_file = Path(toplevel) / ".git"
    if git_file.is_file():
        worktree_name = Path(toplevel).name

    modified = _run_git("diff", "--name-only").splitlines()[:20]
    staged = _run_git("diff", "--cached", "--name-only").splitlines()[:20]
    untracked = _run_git("ls-files", "--others", "--exclude-standard").splitlines()[:10]
    recent_commits = _run_git("log", "--oneline", "-5")

    plugin_root = Path(__file__).parents[3]
    essentials_file = plugin_root / ".claude" / "rules" / "essentials.md"
    essentials = ""
    if essentials_file.exists():
        essentials = essentials_file.read_text()

    summary = f"# Post-Compaction Context Recovery\n\n## Git State\n- **Branch:** {branch}"
    if worktree_name:
        summary += f"\n- **Worktree:** {worktree_name}"
    summary += f"\n- **Working directory:** {toplevel}"

    def format_files(files: list[str]) -> str:
        return "\n".join(f"- {f}" for f in files if f)

    if modified:
        summary += f"\n\n### Modified files (unstaged)\n{format_files(modified)}"
    if staged:
        summary += f"\n\n### Staged files\n{format_files(staged)}"
    if untracked:
        summary += f"\n\n### Untracked files\n{format_files(untracked)}"
    if recent_commits:
        summary += f"\n\n### Recent commits\n```\n{recent_commits}\n```"
    if essentials:
        summary += f"\n\n## Essential Conventions (from essentials.md)\n{essentials}"

    plan_file = Path(toplevel) / ".claude" / "session" / "plan.yaml"
    if plan_file.exists():
        from dev10x.domain.session_state import PlanSummary

        plan_data = _read_plan_summary(toplevel=toplevel)
        plan = PlanSummary.from_dict(data=plan_data)

        summary += "\n\n" + plan.format_for_compaction()

        if not plan.context.routing_table:
            recovery_file = plugin_root / "references" / "compaction-recovery.md"
            if recovery_file.exists():
                summary += f"\n\n{recovery_file.read_text()}"

        friction_level = _read_friction_level(toplevel=toplevel)
        guidance = _format_decision_guidance(
            plan=plan_data,
            friction_level=friction_level,
        )
        if guidance:
            summary += f"\n\n### Resume Guidance\n{guidance}"

        summary += (
            "\n\n> Reconstructed from persisted plan file. Use TaskList to verify\n"
            "> current session state. If tasks are missing, recreate them from\n"
            "> this list. Use the routing table above for all shipping actions."
        )

    escaped = _escape_for_json(s=summary)
    print(f'{{"hookSpecificOutput":{{"systemMessage":"{escaped}"}}}}')


def session_tmpdir(data: dict | None = None) -> None:
    """Create session scratch directory and install mktmp.sh (SessionStart hook)."""
    if data is None:
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            sys.exit(0)

    session_id = data.get("session_id") or ""
    if not session_id:
        return

    Path(f"/tmp/Dev10x/{session_id}").mkdir(parents=True, exist_ok=True)

    plugin_root = Path(__file__).parents[3]
    mktmp_src = plugin_root / "bin" / "mktmp.sh"
    dest_bin = Path("/tmp/Dev10x/bin")
    dest_bin.mkdir(parents=True, exist_ok=True)

    if mktmp_src.exists():
        dest = dest_bin / "mktmp.sh"
        shutil.copy2(src=mktmp_src, dst=dest)
        dest.chmod(0o755)


def build_guidance_context() -> str:
    """Return the session-guidance.md contents, or empty string if missing."""
    plugin_root = Path(__file__).parents[3]
    guidance_file = plugin_root / "hooks" / "scripts" / "session-guidance.md"
    if not guidance_file.exists():
        return ""
    return guidance_file.read_text()


def session_guidance() -> None:
    """Output session-guidance.md as additionalContext (SessionStart hook)."""
    content = build_guidance_context()
    if not content:
        sys.exit(0)

    escaped = _escape_for_json(s=content)
    print(
        '{"hookSpecificOutput":{"hookEventName":"SessionStart",'
        f'"additionalContext":"{escaped}"}}}}'
    )


def session_git_aliases() -> None:
    """Check git branch-comparison aliases and report status (SessionStart hook)."""
    aliases = [
        "develop-log",
        "develop-diff",
        "develop-rebase",
        "autosquash-develop",
        "development-log",
        "development-diff",
        "development-rebase",
        "autosquash-development",
        "trunk-log",
        "trunk-diff",
        "trunk-rebase",
        "autosquash-trunk",
        "main-log",
        "main-diff",
        "main-rebase",
        "autosquash-main",
        "master-log",
        "master-diff",
        "master-rebase",
        "autosquash-master",
    ]

    missing = []
    present = []
    for alias in aliases:
        if _run_git("config", "--get", f"alias.{alias}"):
            present.append(alias)
        else:
            missing.append(alias)

    if not missing:
        print(f"Git aliases available: {' '.join(present)}")
        print("Use `git {base}-log`, `git {base}-diff`, `git {base}-rebase`")
        print("instead of $(git merge-base ...) to avoid permission prompts.")
    else:
        print(f"Git aliases missing: {' '.join(missing)}")
        if present:
            print(f"Git aliases available: {' '.join(present)}")
        print("Run the git-alias-setup skill (/Dev10x:git-alias-setup) to configure them.")


def _build_migration_replacements(
    *,
    plugin_root: Path,
    home: str,
) -> list[tuple[str, str]]:
    version_parent = plugin_root.parent
    current_abs = str(plugin_root) + "/"
    current_tilde = current_abs.replace(home, "~")

    replacements: list[tuple[str, str]] = []
    try:
        children = sorted(version_parent.iterdir())
    except OSError:
        return replacements

    for child in children:
        if not child.is_dir() or child == plugin_root:
            continue
        old_abs = str(child) + "/"
        old_tilde = old_abs.replace(home, "~")
        replacements.append((old_abs, current_abs))
        replacements.append((old_tilde, current_tilde))

    return replacements


def _migrate_rules(
    *,
    rules: list[str],
    replacements: list[tuple[str, str]],
) -> tuple[list[str], int]:
    migrated = 0
    result = []
    for rule in rules:
        new_rule = rule
        for old, new in replacements:
            if old in rule:
                new_rule = rule.replace(old, new)
                migrated += 1
                break
        result.append(new_rule)
    return result, migrated


def _deduplicate_rules(rules: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for rule in rules:
        if rule not in seen:
            seen.add(rule)
            deduped.append(rule)
    return deduped


def session_migrate_permissions() -> None:
    """Migrate stale plugin permission rules to current version (SessionStart hook).

    Only runs when installed via plugin cache (not --plugin-dir).
    """
    plugin_root = Path(__file__).parents[3]

    if "plugins/cache/" not in str(plugin_root):
        sys.exit(0)

    home_path = Path.home()
    home = str(home_path)
    replacements = _build_migration_replacements(plugin_root=plugin_root, home=home)
    if not replacements:
        sys.exit(0)

    settings_files = [
        f
        for f in [
            home_path / ".claude" / "settings.json",
            home_path / ".claude" / "settings.local.json",
        ]
        if f.exists()
    ]

    total_migrated = 0
    files_changed: list[str] = []

    for settings_file in settings_files:
        try:
            with file_lock(settings_file):
                settings = json.loads(settings_file.read_text())
                permissions = settings.get("permissions", {})
                changed = False
                for key in ("allow", "deny"):
                    raw = permissions.get(key, [])
                    if not raw:
                        continue
                    new_rules, count = _migrate_rules(rules=raw, replacements=replacements)
                    new_rules = _deduplicate_rules(rules=new_rules)
                    total_migrated += count
                    if count:
                        permissions[key] = new_rules
                        changed = True
                if not changed:
                    continue
                atomic_write_text(settings_file, json.dumps(settings, indent=2) + "\n")
            files_changed.append(settings_file.name)
        except (json.JSONDecodeError, OSError):
            continue

    if total_migrated > 0:
        files_str = ", ".join(files_changed)
        print(
            f"Migrated {total_migrated} stale permission rule(s) "
            f"to current plugin version in {files_str}"
        )


def session_persist(data: dict | None = None) -> None:
    """Persist session state to disk for next-session reload (SessionStop hook)."""
    if data is None:
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            sys.exit(0)

    session_id = data.get("session_id") or ""
    if not session_id:
        return

    toplevel = _get_toplevel()
    if not toplevel:
        return

    project_hash = hashlib.md5(toplevel.encode()).hexdigest()
    state_dir = ClaudeDir.session_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    state_file = state_dir / f"{project_hash}.json"

    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"

    worktree_name = ""
    git_file = Path(toplevel) / ".git"
    if git_file.is_file():
        worktree_name = Path(toplevel).name

    modified = _run_git("diff", "--name-only").splitlines()[:20]
    staged = _run_git("diff", "--cached", "--name-only").splitlines()[:20]
    recent_commits = _run_git("log", "--oneline", "-5").splitlines()

    has_plan = (Path(toplevel) / ".claude" / "session" / "plan.yaml").exists()

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    state: dict[str, Any] = {
        "session_id": session_id,
        "branch": branch,
        "worktree": worktree_name,
        "working_directory": toplevel,
        "timestamp": timestamp,
        "modified_files": modified,
        "staged_files": staged,
        "recent_commits": recent_commits,
        "has_plan": has_plan,
    }
    state_file.write_text(json.dumps(state, indent=2))


def session_goodbye(data: dict | None = None) -> None:
    """Output goodbye message with community link and resume hint (SessionStop hook)."""
    if data is None:
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            data = {}

    session_id = data.get("session_id") or ""

    url = "https://www.skool.com/Dev10x-1892"
    print()
    print("Thank you for using Dev10x. Join the community to get the most out of the plugin:")
    print(f"\033]8;;{url}\033\\{url}\033]8;;\033\\")

    if session_id:
        print()
        print("Resume this session with:")
        print(f"  claude --resume {session_id}")
