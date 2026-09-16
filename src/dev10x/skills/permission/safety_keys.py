"""Enforce disableAutoMode / disableBypassPermissionsMode as a floor (GH-1320).

Both keys are top-level ``settings.json`` entries (siblings of
``permissions``) that take ONLY the literal string ``"disable"``. A JSON
boolean ``true`` is silently ignored by the Claude Code harness — the key
reads as configured while enforcing nothing. That is the whole defect
class this module closes: a compliance control that looks set but is
inert must fail LOUD at write time, never coerce or ignore a wrong value.

These keys restrict behaviour rather than grant it, which is a different
judgement from the allow/deny/ask rule catalog in ``projects.yaml``. PR
#1338's ``UNTRIAGED_BACKLOG`` ratchet (``test_backlog_only_shrinks``)
deliberately declined to auto-seed 189 uncatalogued *permission* rules —
seeding an allow rule expands what a session can do without a prompt.
Seeding these two keys does the opposite: it can only narrow behaviour
(auto mode / bypass-permissions mode off), so seeding them additively
here does not fight that ratchet — it is not part of the same catalog and
carries the opposite risk profile.

Global ``~/.claude/settings.json`` alone is not a floor (GH-47): a
project's ``settings.local.json`` wins outright, so global-only values
never merge in. Every writer/check here must therefore be run against
each settings file individually, not just the global one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok

REQUIRED_VALUE = "disable"
SAFETY_KEYS: tuple[str, str] = ("disableAutoMode", "disableBypassPermissionsMode")


def validate_safety_key_value(key: str, value: Any) -> Result[str]:
    """Reject anything but the literal string ``"disable"`` (GH-1320).

    A JSON boolean ``true`` is the documented failure mode: Claude Code
    silently ignores it, so a writer that accepted it would produce a
    settings file that looks configured while enforcing nothing. This
    function is the single choke point every writer routes through —
    fail loud instead of coercing ``true``/``"true"``/``1`` to the
    required string.
    """
    if key not in SAFETY_KEYS:
        return err(f"{key!r} is not a recognized safety key (expected one of {SAFETY_KEYS}).")
    if isinstance(value, str) and value == REQUIRED_VALUE:
        return ok(value)
    return err(
        f"{key} must be the literal string {REQUIRED_VALUE!r}, got "
        f"{value!r} ({type(value).__name__}). A boolean here is silently "
        "ignored by Claude Code -- the control would look configured "
        "while providing no protection."
    )


@dataclass(frozen=True)
class SafetyKeyFinding:
    """One safety-key problem found in a settings file."""

    key: str
    issue: str  # "missing" | "invalid"
    detail: str


def check_safety_keys(settings: dict[str, Any]) -> list[SafetyKeyFinding]:
    """Doctor check: report every safety key that is absent or wrong (GH-1320).

    Read-only and pure — an empty finding list means both keys are
    present and hold the literal string ``"disable"``.
    """
    findings: list[SafetyKeyFinding] = []
    for key in SAFETY_KEYS:
        if key not in settings:
            findings.append(SafetyKeyFinding(key=key, issue="missing", detail="key is absent"))
            continue
        result = validate_safety_key_value(key, settings[key])
        if isinstance(result, ErrorResult):
            findings.append(SafetyKeyFinding(key=key, issue="invalid", detail=result.error))
    return findings


def seed_safety_keys(settings: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Add any missing safety key to ``settings``, set to ``"disable"``.

    Additive only — an existing value (even an invalid one) is left
    untouched here; ``check_safety_keys`` is what flags an invalid
    existing value, and a human decides whether to overwrite it. Returns
    the (possibly mutated) dict and the list of keys that were added.
    """
    added: list[str] = []
    for key in SAFETY_KEYS:
        if key not in settings:
            settings[key] = REQUIRED_VALUE
            added.append(key)
    return settings, added


def write_safety_keys_to_file(path: Path, *, dry_run: bool = False) -> tuple[int, list[str]]:
    """Seed any missing safety key into one settings file. Returns (count, messages).

    Per-file writer counterpart to ``ensure_workspace_directories`` —
    called directly by ``ensure_base`` against its own already-guarded
    ``writable_files`` list, and by :func:`ensure_safety_keys` for the
    standalone ``dev10x permission ensure-safety-keys`` command. Callers
    own the git-tracked guard (GH-1155); this function only ever writes
    to the path it is given.
    """
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return 0, [f"  SKIP (invalid JSON): {exc}"]

    _, added = seed_safety_keys(dict(data))
    if not added:
        return 0, []

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live_data:
            seed_safety_keys(live_data)

    messages = [f"  + {key}: {REQUIRED_VALUE!r}" for key in added]
    return len(added), messages


def _result(
    *,
    exit_code: int,
    messages: list[str],
    errors: list[str],
    total_added: int = 0,
    files_changed: int = 0,
) -> dict[str, object]:
    return {
        "exit_code": exit_code,
        "messages": messages,
        "errors": errors,
        "total_added": total_added,
        "files_changed": files_changed,
    }


def ensure_safety_keys(
    *,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
    allow_tracked: bool = False,
) -> dict[str, object]:
    """Seed both safety keys into every settings file that lacks them.

    Writer counterpart to :func:`safety_keys_gap`. Uses the same
    lock+backup pattern as ``ensure_workspace_directories`` so a
    concurrent writer (another worktree's maintenance pass) cannot lose
    an update, and consults the GH-1155 git-tracked guard so a tracked
    `settings.json` is never rewritten in place — the rules redirect to
    its `settings.local.json` sibling instead, same as `ensure_workspace`.
    """
    from dev10x.skills.permission.update_paths import partition_writable

    messages: list[str] = []
    errors: list[str] = []
    total_added = 0
    files_changed = 0

    if dry_run and not quiet:
        messages.append("(dry run — no files will be modified)\n")

    writable_files, skip_messages = partition_writable(
        sorted(settings_files),
        redirect_tracked=True,
        allow_tracked=allow_tracked,
    )
    if not quiet:
        messages.extend(skip_messages)

    for path in writable_files:
        count, file_messages = write_safety_keys_to_file(path, dry_run=dry_run)
        if count == 0:
            if file_messages:  # invalid JSON — surface it, don't drop it silently
                errors.append(f"{path}:")
                errors.extend(file_messages)
            continue
        if not quiet:
            messages.append(f"\n{path}")
            messages.extend(file_messages)
        total_added += count
        files_changed += 1

    if total_added == 0:
        messages.append("All settings files already carry both safety keys.")
    else:
        verb = "Would add" if dry_run else "Added"
        messages.append(f"{verb} {total_added} safety-key entries across {files_changed} files.")

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


def safety_keys_gap(
    *,
    settings_files: list[Path],
    quiet: bool = False,
) -> dict[str, object]:
    """Report missing/invalid safety keys per settings file (GH-1320).

    Read-only. Exits non-zero (via the returned ``exit_code``) when any
    settings file has a finding, so post-upgrade verification is a
    command rather than a reading of a maintenance log.
    """
    messages: list[str] = []
    errors: list[str] = []
    total_findings = 0
    files_with_findings = 0

    for path in sorted(settings_files):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: SKIP (invalid JSON): {exc}")
            continue

        findings = check_safety_keys(data)
        if not findings:
            continue

        files_with_findings += 1
        total_findings += len(findings)
        if not quiet:
            messages.append(f"\n{path}")
            messages.extend(f"  - {f.key}: {f.issue} ({f.detail})" for f in findings)

    if total_findings == 0:
        messages.append("0 missing / 0 invalid safety keys across all settings files.")
    else:
        errors.append(
            f"{total_findings} safety-key finding(s) across {files_with_findings} file(s)."
        )

    return _result(
        exit_code=0 if total_findings == 0 else 1,
        messages=messages,
        errors=errors,
        total_added=0,
        files_changed=0,
    )
