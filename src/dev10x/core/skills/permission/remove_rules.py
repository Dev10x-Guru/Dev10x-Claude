"""Remove permission rules matching a glob from settings files (GH-1925).

The mechanical path for what no ``clean`` detector covers: the auditor's
``manual`` findings and the apply skill's deferred removals. The plugin's
own hook denies ``sed -i`` on settings files, so each rule used to be a
hand-made ``Edit``.

CLI entry point: ``dev10x permission remove``.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dev10x.skills.permission.backup import backed_up_write

PERMISSION_LISTS: tuple[str, ...] = ("allow", "ask", "deny")


@dataclass
class FileRemoval:
    path: Path
    removed: dict[str, list[str]] = field(default_factory=dict)
    skipped: str | None = None

    @property
    def count(self) -> int:
        return sum(len(rules) for rules in self.removed.values())


def match_rules(
    *,
    data: dict[str, Any],
    pattern: str,
    lists: tuple[str, ...],
) -> dict[str, list[str]]:
    permissions = data.get("permissions", {})
    matched: dict[str, list[str]] = {}
    for name in lists:
        rules = permissions.get(name, [])
        if not isinstance(rules, list):
            continue
        hits = [
            rule for rule in rules if isinstance(rule, str) and fnmatch.fnmatchcase(rule, pattern)
        ]
        if hits:
            matched[name] = hits
    return matched


def remove_from_file(
    path: Path,
    *,
    pattern: str,
    lists: tuple[str, ...] = PERMISSION_LISTS,
    dry_run: bool = False,
) -> FileRemoval:
    outcome = FileRemoval(path=path)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        outcome.skipped = f"SKIP (unreadable JSON): {e}"
        return outcome

    outcome.removed = match_rules(data=data, pattern=pattern, lists=lists)
    if dry_run or not outcome.removed:
        return outcome

    with backed_up_write(path) as live_data:
        # Re-matched against the live document so a concurrent writer's
        # rules survive and only what is still present is reported.
        outcome.removed = match_rules(data=live_data, pattern=pattern, lists=lists)
        for name, hits in outcome.removed.items():
            doomed = set(hits)
            live_data["permissions"][name] = [
                rule for rule in live_data["permissions"][name] if rule not in doomed
            ]
    return outcome


def format_removal(outcome: FileRemoval, *, dry_run: bool) -> list[str]:
    if outcome.skipped:
        return [f"  {outcome.skipped}"]
    verb = "would remove" if dry_run else "removed"
    return [
        f"  {verb} [{name}] {rule}" for name, rules in outcome.removed.items() for rule in rules
    ]
