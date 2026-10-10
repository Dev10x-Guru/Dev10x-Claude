"""Strategy: read-deny-phantom (GH-1321, class P).

A recursive search hit a ``Read()`` deny for an absolute path that could
not exist beneath the search root. The permission engine appears to
re-root an absolute deny path relative to the root being searched, so
the deny matches a path that is not there — a prompt with no file behind
it, and nothing in the prompt naming the deny as the cause.

So every absolute-path ``Read()`` deny is a latent prompt generator for
any recursive *Read-based* tool. The remediation is emphatically **not**
to remove the deny: an absolute deny on ``~/.ssh`` or ``~/.aws`` is
doing exactly its job, and a strategy that told users to delete those
would be asking them to dismantle a guardrail — the failure mode GH-1222
recorded for ``ask-shadows-allow``. The remediation is to route
recursive content search through the Grep tool, which the re-rooting
does not affect.

**Shape of the finding.** One finding per settings file, aggregating
every absolute-path ``Read()`` deny it carries, graded ``suggestion``.
Per-deny findings would be the noise this strategy must avoid: a machine
with ten sensible secret denies would produce ten reports all concluding
"this is correct, prefer Grep". One advisory line per file states the
consequence once, and a ``suggestion`` never blocks
``dev10x doctor run`` at its default threshold.

**What a true positive looks like.** A settings file whose ``deny`` list
contains at least one ``Read(...)`` rule whose pattern is absolute
(``/...``) or home-anchored (``~/...``, ``$HOME/...``), on a machine
where someone runs recursive Read-based search. **What would make it
fire wrongly.** Nothing about the rule itself is wrong, so the finding
is advisory by construction — it can only be *unhelpful*, never
*mistaken*, and it is unhelpful for a user who never searches
recursively. A relative-path deny is out of scope: it is not re-rooted,
because it was never rooted anywhere else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRule
from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    Strategy,
)

STRATEGY_ID = "read-deny-phantom"

_ABSOLUTE_PREFIXES = ("/", "~/", "$HOME/", "${HOME}/")


@dataclass(frozen=True)
class ReadDenyPhantomRemediation:
    """Remediation payload: a steer, not an edit to the deny list."""

    settings_path: str
    deny_rules: tuple[str, ...]

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="file_issue",
            target="recursive-read-search",
            action={
                "operation": "prefer-grep-for-recursive-search",
                "settings_path": self.settings_path,
                "deny_rules": list(self.deny_rules),
                "reason": (
                    "Keep these denies. The engine re-roots an absolute deny "
                    "path relative to the root being searched, so a recursive "
                    "Read-based search prompts on a path that does not exist "
                    "under that root. Route recursive content search through "
                    "the Grep tool, which the re-rooting does not affect."
                ),
            },
        )


def _absolute_read_denies(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        return []
    denies = permissions.get("deny")
    if not isinstance(denies, list):
        return []
    return [raw for raw in denies if isinstance(raw, str) and _is_absolute_read(raw)]


def _is_absolute_read(raw: str) -> bool:
    rule = AllowRule.parse(raw)
    return rule.tool == "Read" and rule.pattern.startswith(_ABSOLUTE_PREFIXES)


def detect(context: Context) -> list[Finding]:
    """One advisory finding per settings file carrying absolute Read denies."""
    findings: list[Finding] = []
    for path in context.settings_paths:
        rules = _absolute_read_denies(path)
        if not rules:
            continue
        findings.append(_finding(path=path, rules=tuple(rules)))
    return findings


def _finding(*, path: Path, rules: tuple[str, ...]) -> Finding:
    listed = ", ".join(f"``{rule}``" for rule in rules)
    return Finding(
        strategy_id=STRATEGY_ID,
        severity="suggestion",
        location=str(path),
        evidence=(
            f"{len(rules)} absolute-path Read() deny rule(s) — {listed} — are "
            "re-rooted relative to whatever root a recursive search walks, so "
            "they can match a path that does not exist there and raise a "
            "prompt that names no cause"
        ),
        proposed_fix=(
            "Leave the denies alone; they are doing their job. Use the Grep "
            "tool for recursive content search — it is not affected by the "
            "re-rooting — and reach for a Read-based recursive walk only "
            "against a root you know these patterns cannot shadow."
        ),
        data=ReadDenyPhantomRemediation(settings_path=str(path), deny_rules=rules),
    )


def remediate(finding: Finding) -> Remediation:
    """Propose the Grep steer that sidesteps the phantom match."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id=STRATEGY_ID,
    description=(
        "Name absolute-path Read() denies as the hidden cause of prompts "
        "during recursive search. The engine re-roots them under the search "
        "root, matching a path that is not there; the fix is to prefer the "
        "Grep tool, never to drop the deny (GH-1321)."
    ),
    detect=detect,
    remediate=remediate,
)
