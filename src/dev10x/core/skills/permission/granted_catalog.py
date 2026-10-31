"""Rules a supervisor granted, remembered for checkouts created later (GH-1677).

A grant written into the settings files that exist today never reaches a
worktree or project created tomorrow: those are seeded by ``ensure-base``
and ``seed-worktree`` from the catalog, and a grant never landed there.

``granted-permissions.yaml`` is that missing layer. It holds only
``base_permissions`` and is merged into the userspace catalog by
``catalog_load.load_effective_config``, so every existing seeding path
propagates a remembered rule with no new code of its own.

Dev10x owns the whole file, so rewriting it with ``safe_dump`` loses
nothing — unlike appending to the hand-edited ``projects.yaml``, which
would strip the user's comments. Callers are expected to have triaged
the rule already (``permission_grant``, GH-1676); this module refuses
only what can never be a working allow rule.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import LockTimeoutError, locked_yaml_update
from dev10x.skills.permission.star_prefix import is_unmatchable

GRANTED_KEY = "base_permissions"

log = logging.getLogger(__name__)


def granted_path() -> Path:
    return Dev10xConfigDir.granted_permissions_yaml()


def load_granted_rules(*, path: Path | None = None) -> list[str]:
    """Every remembered rule, or ``[]`` when the file is absent or unreadable.

    An unreadable file degrades to no remembered rules with a warning,
    the same tolerance the shipped-catalog loader applies: one bad layer
    must not stop ``ensure-base`` from seeding the rest of the catalog.
    """
    target = path if path is not None else granted_path()
    if not target.is_file():
        return []
    try:
        document = yaml.safe_load(target.read_text())
    except (OSError, yaml.YAMLError) as error:
        log.warning("Granted rules unreadable, skipped: %s (%s)", target, error)
        return []
    if not isinstance(document, dict):
        log.warning("Granted rules file is not a mapping, skipped: %s", target)
        return []
    rules = document.get(GRANTED_KEY)
    if not isinstance(rules, list):
        log.warning("Granted rules file has no %s list, skipped: %s", GRANTED_KEY, target)
        return []
    return [rule for rule in rules if isinstance(rule, str) and rule]


class _NotAMappingError(ValueError):
    """The remembered-rules file parsed, but not as a mapping."""


def remember_granted_rule(*, rule: str, path: Path | None = None) -> Result[dict[str, object]]:
    """Append ``rule`` to the remembered layer under a file lock; idempotent.

    Returns ``{"path", "rule", "added"}``; ``added`` is ``False`` when the
    rule was already remembered. The write is a request, not a receipt
    (GH-1099): the result reports what the locked re-read found.
    """
    candidate = rule.strip()
    if not candidate:
        return err("cannot remember an empty rule")
    if is_unmatchable(candidate):
        return err(
            f"cannot remember {candidate}: a `*` before `:*` never matches (GH-1472)",
            rule=candidate,
        )
    target = path if path is not None else granted_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with locked_yaml_update(target) as document:
            if not isinstance(document, dict):
                raise _NotAMappingError(str(target))
            existing = document.get(GRANTED_KEY)
            rules = list(existing) if isinstance(existing, list) else []
            added = candidate not in rules
            if added:
                rules.append(candidate)
            document[GRANTED_KEY] = rules
    except LockTimeoutError as error:
        return err(
            f"{target} is locked by another writer; please try again ({error})",
            path=str(target),
        )
    except _NotAMappingError:
        return err(
            f"{target} is not a mapping, so the rule was not remembered; "
            "inspect or remove the file, then retry",
            path=str(target),
        )
    except OSError as error:
        return err(f"cannot remember {candidate} in {target}: {error}", path=str(target))
    return ok({"path": str(target), "rule": candidate, "added": added})


def with_granted_rules(*, config: dict, granted: list[str]) -> dict:
    """``config`` with remembered rules appended to its allow tier, de-duplicated."""
    if not granted:
        return config
    existing = config.get(GRANTED_KEY)
    rules = list(existing) if isinstance(existing, list) else []
    rules.extend(rule for rule in granted if rule not in rules)
    return {**config, GRANTED_KEY: rules}


__all__ = [
    "GRANTED_KEY",
    "granted_path",
    "load_granted_rules",
    "remember_granted_rule",
    "with_granted_rules",
]
