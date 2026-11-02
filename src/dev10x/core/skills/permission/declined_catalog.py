"""Rules the supervisor excluded from worktree permission spread (GH-1790).

Removing a rule from a main checkout's ``settings.local.json`` did not
stick: the worktrees that granted it still held it, so the next
``merge-worktree`` run copied it straight back. ``declined-permissions.yaml``
records the answer once, and both directions of spread —
``merge-worktree`` and ``sync-worktrees`` — skip every rule listed there.

The file shares its locked read-append-write with ``granted_catalog``
through ``RuleListFile`` (GH-1800).
"""

from __future__ import annotations

import logging
from pathlib import Path

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.skills.permission.rule_list_file import RuleListFile

DECLINED_KEY = "declined"

log = logging.getLogger(__name__)


def declined_path() -> Path:
    return Dev10xConfigDir.declined_permissions_yaml()


def _store(*, path: Path | None) -> RuleListFile:
    return RuleListFile(path=path if path is not None else declined_path(), key=DECLINED_KEY)


def read_declined_rules(*, path: Path | None = None) -> Result[frozenset[str]]:
    """Every declined rule; an error when the file exists but cannot be read.

    A spread must not run on a broken file: the supervisor's exclusions
    would silently stop applying and the rules they removed would come
    back. An absent or empty file declines nothing.
    """
    result = _store(path=path).read()
    if isinstance(result, ErrorResult):
        return err(f"declined rules cannot be honoured: {result.error}")
    return ok(frozenset(result.value))


def load_declined_rules(*, path: Path | None = None) -> frozenset[str]:
    """Every declined rule, degrading to none with a warning on a bad file.

    For report-only readers (plugin-doctor). Writers that spread rules use
    :func:`read_declined_rules` and stop on an error instead.
    """
    result = read_declined_rules(path=path)
    if isinstance(result, ErrorResult):
        log.warning("Declined rules skipped: %s", result.error)
        return frozenset()
    return result.value


def decline_rules(*, rules: list[str], path: Path | None = None) -> Result[dict[str, object]]:
    """Record ``rules`` as declined under a file lock; idempotent.

    Returns ``{"path", "added"}`` where ``added`` lists the rules that were
    not declined before this call.
    """
    candidates = [rule.strip() for rule in rules if rule.strip()]
    if not candidates:
        return err("no rule to decline")
    store = _store(path=path)
    result = store.append(rules=candidates)
    if isinstance(result, ErrorResult):
        return result
    return ok({"path": str(store.path), "added": result.value})


__all__ = [
    "DECLINED_KEY",
    "decline_rules",
    "declined_path",
    "load_declined_rules",
    "read_declined_rules",
]
