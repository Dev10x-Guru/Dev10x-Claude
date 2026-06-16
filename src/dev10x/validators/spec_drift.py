"""Validator: block spec-governed edits when the spec is untouched (DX015).

Implements the spec-first Golden Rule as action backpressure on
``PreToolUse Edit|Write``: if the branch carries a ticket ID that
maps to an active ``docs/specs/<TICKET-ID>.md``, and that spec file
is **not** in the current git working set (staged or unstaged
changes), warn before any source edit is applied.

This moves the Golden Rule from "skill-if-invoked" (output
backpressure via ``Dev10x:spec-update``) to "hook-always" (action
backpressure that fires whenever the spec is untouched).

Spawned from GH-430 recommendation P2. Full spec: GH-434.

Design notes
------------
* ``should_run`` returns False for non-Edit/Write tools, for edits to
  the spec file itself, and when no active spec can be found.
* ``validate`` runs ``git diff --name-only HEAD`` to get the working
  set, then checks whether the spec path is present.
* Git failures (no repo, git not installed) silently pass — the hook
  must not block CI runners or fresh checkouts.
* The validator is ``experimental=True`` on first ship so users who
  do not use SPDD can opt out with ``DEV10X_HOOK_EXPERIMENTAL=0``.
  Once the adoption rate is confirmed, flip to ``experimental=False``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from dev10x import subprocess_utils
from dev10x.domain import HookInput, HookResult
from dev10x.domain.common.ticket_id import TicketId
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

_SPECS_SUBDIR = "docs/specs"

_WARN_MSG_TEMPLATE = """\
⚠️  Spec-drift gate (DX015): spec exists but is untouched in the working set.

Editing:   {file_path}
Spec:      {spec_path}
Ticket:    {ticket_id}

The Golden Rule (ADR-0005) says: fix the prompt first, then regenerate.
You are about to edit a source file while the canonical spec at
``{spec_path}`` has not been touched in the current working set.

Options:
  1. Run ``Dev10x:spec-update`` first to update the spec, then regenerate.
  2. Edit the spec file directly (``{spec_path}``) before this file.
  3. Disable this check for the session: ``DEV10X_HOOK_DISABLE=DX015``.

See ``.claude/rules/hook-patterns.md`` — DX015 / spec-drift — for details.
"""


def _branch_ticket_id(*, cwd: str) -> str | None:
    """Return the first ticket-id found in the current branch name, or None."""
    try:
        result = subprocess_utils.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    branch = result.stdout.strip()
    ticket = TicketId.find_first_in_branch_name(branch)
    return str(ticket) if ticket is not None else None


def _repo_toplevel(*, cwd: str) -> str | None:
    """Return the git repository toplevel, or None if not a git repo."""
    try:
        result = subprocess_utils.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return result.stdout.strip()


def _working_set_paths(*, cwd: str) -> set[str]:
    """Return file paths present in staged + unstaged working set.

    Uses ``git status --porcelain`` so the result includes both
    index-staged (A/M) and working-tree-changed (??/M) entries.
    Returns an empty set on any git error.
    """
    try:
        result = subprocess_utils.run(
            ["git", "status", "--porcelain"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return set()
    output = result.stdout
    paths: set[str] = set()
    for line in output.splitlines():
        # porcelain format: "XY filename" or "XY old -> new" for renames
        if len(line) < 4:
            continue
        rest = line[3:].strip()
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        paths.add(rest.strip())
    return paths


@dataclass
class SpecDriftValidator(ValidatorBase):
    """Warn before editing a source file when the active spec is untouched.

    Checks:
    1. Tool is Edit or Write (skips Bash).
    2. Branch carries a ticket ID (e.g. GH-434 in
       ``janusz/GH-434/feature-name``).
    3. A canonical spec ``docs/specs/<TICKET-ID>.md`` exists in the repo.
    4. The spec file is NOT in the current git working set.

    When all four conditions hold the validator emits a blocking
    ``HookResult`` with remediation guidance.

    Git errors (not a repo, git not installed, bare clone) are silently
    swallowed so the hook never interferes with CI or non-git contexts.
    """

    name: ClassVar[str] = "spec-drift"
    rule_id: ClassVar[str] = "DX015"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
    experimental: ClassVar[bool] = True

    _cwd_override: str | None = field(default=None, repr=False)

    def should_run(self, inp: HookInput) -> bool:
        """Fast skip: only fires for Edit/Write, never for the spec file itself."""
        if inp.tool_name not in ("Edit", "Write"):
            return False
        file_path = inp.raw.get("tool_input", {}).get("file_path", "")
        if not file_path:
            return False
        if _SPECS_SUBDIR in file_path:
            return False
        return True

    def validate(self, inp: HookInput) -> HookResult | None:
        """Return a HookResult if the spec exists but is untouched."""
        cwd = self._cwd_override or inp.cwd or ""
        file_path: str = inp.raw.get("tool_input", {}).get("file_path", "")

        ticket_id = _branch_ticket_id(cwd=cwd)
        if not ticket_id:
            return None

        toplevel = _repo_toplevel(cwd=cwd)
        if not toplevel:
            return None

        spec_rel = f"{_SPECS_SUBDIR}/{ticket_id}.md"
        spec_path = Path(toplevel) / spec_rel
        if not spec_path.exists():
            return None

        working_set = _working_set_paths(cwd=cwd)
        if spec_rel in working_set:
            return None

        return HookResult(
            message=_WARN_MSG_TEMPLATE.format(
                file_path=file_path,
                spec_path=spec_rel,
                ticket_id=ticket_id,
            )
        )
