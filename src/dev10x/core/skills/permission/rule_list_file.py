"""A Dev10x-owned YAML file that holds one list of permission rules (GH-1800).

``granted-permissions.yaml`` (rules remembered from a grant, GH-1677) and
``declined-permissions.yaml`` (rules kept out of worktree spread, GH-1790)
had the same locked read-append-write written twice. One copy keeps the
lock discipline and the error wording in one place; each caller decides
only whether a broken file is fatal to it.

Dev10x owns the whole file, so rewriting it with ``safe_dump`` loses
nothing — unlike appending to the hand-edited ``projects.yaml``, which
would strip the user's comments.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.file_locks import LockTimeoutError, locked_yaml_update


class _NotAMappingError(ValueError):
    """The file parsed, but not as a mapping."""


@dataclass(frozen=True)
class RuleListFile:
    """The ``key:`` list of rules in the YAML file at ``path``."""

    path: Path
    key: str

    def read(self) -> Result[list[str]]:
        """Every rule; an error when the file exists but cannot be used.

        An absent or empty file holds no rules. Whether an error is fatal
        is the caller's call: a writer that spreads rules must stop, a
        report-only reader may degrade.
        """
        if not self.path.is_file():
            return ok([])
        try:
            document = yaml.safe_load(self.path.read_text())
        except (OSError, yaml.YAMLError) as error:
            return err(f"{self.path} is unreadable: {error}", path=str(self.path))
        if document is None:
            return ok([])
        rules = document.get(self.key) if isinstance(document, dict) else None
        if not isinstance(rules, list):
            return err(
                f"{self.path} has no `{self.key}:` list; fix or remove the file, then retry",
                path=str(self.path),
            )
        return ok([rule for rule in rules if isinstance(rule, str) and rule])

    def append(self, *, rules: list[str]) -> Result[list[str]]:
        """Add ``rules`` under a file lock; returns the ones not present before.

        Idempotent. The write is a request, not a receipt (GH-1099): the
        result reports what the locked re-read found.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with locked_yaml_update(self.path) as document:
                if not isinstance(document, dict):
                    raise _NotAMappingError(str(self.path))
                existing = document.get(self.key)
                present = list(existing) if isinstance(existing, list) else []
                added = [rule for rule in dict.fromkeys(rules) if rule not in present]
                document[self.key] = [*present, *added]
        except LockTimeoutError as error:
            return err(
                f"{self.path} is locked by another writer; please try again ({error})",
                path=str(self.path),
            )
        except _NotAMappingError:
            return err(
                f"{self.path} is not a mapping, so nothing was written; "
                "inspect or remove the file, then retry",
                path=str(self.path),
            )
        except OSError as error:
            return err(f"cannot write {self.path}: {error}", path=str(self.path))
        return ok(added)


__all__ = ["RuleListFile"]
