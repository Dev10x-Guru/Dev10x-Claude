"""Queryable rule provenance for seeded permission settings (GH-602).

Once safe defaults are seeded fleet-wide, a settings file mixes three
origins: rules from the Dev10x base catalog (``default``), rules a user
promoted to their global ``~/.claude/settings.json`` (``user``), and
rules local to this one project/worktree (``project``). Provenance makes
that origin queryable so a maintainer can tell which rules a re-seed
would re-establish and which are bespoke to a single directory.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from enum import StrEnum
from pathlib import Path

from dev10x.domain.common.result import Result, err, ok
from dev10x.skills.permission.update_paths import _load_global_allow_rules

log = logging.getLogger(__name__)


class RuleProvenance(StrEnum):
    """Where a permission rule in a settings file came from."""

    DEFAULT = "default"  # shipped in the Dev10x base catalog (projects.yaml)
    USER = "user"  # present in the user-global ~/.claude/settings.json
    PROJECT = "project"  # local to this settings file only


def classify_provenance(
    rule: str,
    *,
    base_rules: set[str],
    global_rules: set[str],
) -> RuleProvenance:
    """Resolve a rule's origin (catalog default → user-global → project-local)."""
    if rule in base_rules:
        return RuleProvenance.DEFAULT
    if rule in global_rules:
        return RuleProvenance.USER
    return RuleProvenance.PROJECT


def build_provenance(
    *,
    settings_path: Path,
    config: dict,
    global_rules: set[str] | None = None,
) -> Result[dict]:
    """Tag every allow/deny rule in a settings file with its provenance.

    ``global_rules`` is injectable for testing; when omitted it is read from
    the live user-global settings. Denies are classified against the base
    deny catalog only — Claude Code does not inherit denies globally.
    """
    if not settings_path.is_file():
        return err("settings file not found", path=str(settings_path))
    try:
        data = json.loads(settings_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return err(f"cannot read settings file: {error}", path=str(settings_path))

    base_allow = set(config.get("base_permissions", []))
    base_deny = set(config.get("base_denies", []))
    user_rules = global_rules if global_rules is not None else _load_global_allow_rules()[0]

    permissions = data.get("permissions", {})
    rules: list[dict[str, str]] = []
    for rule in permissions.get("allow", []):
        if isinstance(rule, str):
            rules.append(
                {
                    "rule": rule,
                    "kind": "allow",
                    "provenance": classify_provenance(
                        rule, base_rules=base_allow, global_rules=user_rules
                    ).value,
                }
            )
    for rule in permissions.get("deny", []):
        if isinstance(rule, str):
            # Denies are not inherited globally: catalog-default or project-local.
            origin = RuleProvenance.DEFAULT if rule in base_deny else RuleProvenance.PROJECT
            rules.append({"rule": rule, "kind": "deny", "provenance": origin.value})

    counts = Counter(entry["provenance"] for entry in rules)
    return ok(
        {
            "path": str(settings_path),
            "rules": rules,
            "counts": {
                provenance.value: counts.get(provenance.value, 0) for provenance in RuleProvenance
            },
        }
    )
