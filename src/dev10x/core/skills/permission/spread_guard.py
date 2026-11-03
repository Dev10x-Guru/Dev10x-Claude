"""Which allow rules may travel between checkouts of one repo (GH-1790).

``merge-worktree`` and ``sync-worktrees`` copy rules sideways: from a
worktree to its main checkout, and from there into every sibling. A rule
an old session approved by accident therefore spread to the whole family.
Observed on one repo: ``Bash(psql:*)`` and ``Edit(~/.claude/**)`` from
eleven worktrees at once, next to ``Bash(bash:*)``, ``Bash(curl:*)`` and
``Bash(python3:*)`` that had already landed.

A rule is held back when any of these says so:

1. ``rule_risk.blanket_problem`` — it grants a whole arbitrary-code, egress or
   settings-write primitive.
2. A plugin hook denies the command it allows. ``Bash(psql:*)`` contradicts
   DX004, which blocks direct ``psql``; an allow the hook overrides on
   every call is dead weight that only makes the settings lie.
3. The supervisor declined it (``declined_catalog``), so a rule removed by
   hand stays removed.

Held rules are reported, never written. The supervisor can still grant one
deliberately with ``permission_grant``, which triages it first.
"""

from __future__ import annotations

from dataclasses import dataclass

from dev10x.domain import HookInput, HookResult
from dev10x.skills.permission.rule_risk import bash_prefix, blanket_problem, comparable_rule
from dev10x.validators import get_chain


@dataclass(frozen=True)
class HeldRule:
    """A rule kept out of a spread, and why."""

    rule: str
    reason: str


def hook_denial(*, rule: str) -> str | None:
    """The message a plugin hook blocks ``rule``'s command with, or None.

    The rule's literal prefix stands in for the command. That is enough
    for the deny shapes a whole-tool rule collides with (DX004 on
    ``psql``, DX006 on a routed ``gh pr edit``); a validator that needs
    arguments to object says nothing, and the rule is not held for it.
    """
    command = bash_prefix(rule=rule)
    if not command:
        return None
    probe = HookInput(
        tool_name="Bash",
        command=command,
        raw={"tool_name": "Bash", "tool_input": {"command": command}},
    )
    for result in get_chain().run(probe):
        if isinstance(result, HookResult):
            return result.message.splitlines()[0]
    return None


def hold_reason(*, rule: str, declined: frozenset[str]) -> str | None:
    """Why ``rule`` must not be copied to another checkout, or None."""
    if comparable_rule(rule=rule) in {comparable_rule(rule=item) for item in declined}:
        return "declined by the supervisor (declined-permissions.yaml)"
    blanket = blanket_problem(rule=rule)
    if blanket:
        return blanket
    denial = hook_denial(rule=rule)
    if denial:
        return f"a plugin hook denies it: {denial}"
    return None


def partition_spreadable(
    *, rules: list[str], declined: frozenset[str]
) -> tuple[list[str], list[HeldRule]]:
    """Split ``rules`` into those safe to copy and those held back."""
    spreadable: list[str] = []
    held: list[HeldRule] = []
    for rule in rules:
        reason = hold_reason(rule=rule, declined=declined)
        if reason is None:
            spreadable.append(rule)
        else:
            held.append(HeldRule(rule=rule, reason=reason))
    return spreadable, held


def render_held(*, held: list[HeldRule]) -> list[str]:
    """Report lines for the rules a spread left behind."""
    if not held:
        return []
    lines = [f"  held back {len(held)} rule(s) — not copied:"]
    for item in held:
        lines.append(f"    ! {item.rule}")
        lines.append(f"      {item.reason}")
    return lines


__all__ = [
    "HeldRule",
    "hold_reason",
    "hook_denial",
    "partition_spreadable",
    "render_held",
]
