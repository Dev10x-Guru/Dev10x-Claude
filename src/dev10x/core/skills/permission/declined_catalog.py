"""Rules the supervisor excluded from worktree permission spread (GH-1790).

Removing a rule from a main checkout's ``settings.local.json`` did not
stick: the worktrees that granted it still held it, so the next
``merge-worktree`` run copied it straight back. ``declined-permissions.yaml``
records the answer once, and both directions of spread —
``merge-worktree`` and ``sync-worktrees`` — skip every rule listed there.

Dev10x owns the whole file, so it is rewritten under a lock with
``locked_yaml_update``, the same discipline ``granted_catalog`` follows.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import LockTimeoutError, locked_yaml_update

DECLINED_KEY = "declined"

log = logging.getLogger(__name__)


def declined_path() -> Path:
    return Dev10xConfigDir.declined_permissions_yaml()


def read_declined_rules(*, path: Path | None = None) -> Result[frozenset[str]]:
    """Every declined rule; an error when the file exists but cannot be read.

    A spread must not run on a broken file: the supervisor's exclusions
    would silently stop applying and the rules they removed would come
    back. An absent or empty file declines nothing.
    """
    target = path if path is not None else declined_path()
    if not target.is_file():
        return ok(frozenset())
    try:
        document = yaml.safe_load(target.read_text())
    except (OSError, yaml.YAMLError) as error:
        return err(f"{target} is unreadable, so declined rules cannot be honoured: {error}")
    if document is None:
        return ok(frozenset())
    rules = document.get(DECLINED_KEY) if isinstance(document, dict) else None
    if not isinstance(rules, list):
        return err(f"{target} has no `{DECLINED_KEY}:` list; fix or remove the file, then retry")
    return ok(frozenset(rule for rule in rules if isinstance(rule, str) and rule))


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


class _NotAMappingError(ValueError):
    """The declined-rules file parsed, but not as a mapping."""


def decline_rules(*, rules: list[str], path: Path | None = None) -> Result[dict[str, object]]:
    """Record ``rules`` as declined under a file lock; idempotent.

    Returns ``{"path", "added"}`` where ``added`` lists the rules that were
    not declined before this call.
    """
    candidates = [rule.strip() for rule in rules if rule.strip()]
    if not candidates:
        return err("no rule to decline")
    target = path if path is not None else declined_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with locked_yaml_update(target) as document:
            if not isinstance(document, dict):
                raise _NotAMappingError(str(target))
            existing = document.get(DECLINED_KEY)
            declined = list(existing) if isinstance(existing, list) else []
            added = [rule for rule in dict.fromkeys(candidates) if rule not in declined]
            document[DECLINED_KEY] = [*declined, *added]
    except LockTimeoutError as error:
        return err(
            f"{target} is locked by another writer; please try again ({error})",
            path=str(target),
        )
    except _NotAMappingError:
        return err(
            f"{target} is not a mapping, so nothing was declined; "
            "inspect or remove the file, then retry",
            path=str(target),
        )
    except OSError as error:
        return err(f"cannot write {target}: {error}", path=str(target))
    return ok({"path": str(target), "added": added})


__all__ = [
    "DECLINED_KEY",
    "decline_rules",
    "declined_path",
    "load_declined_rules",
    "read_declined_rules",
]
