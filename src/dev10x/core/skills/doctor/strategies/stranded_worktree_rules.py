"""Strategy: stranded-worktree-rules (GH-1709).

"Don't ask again" writes the literal path of the checkout where the
prompt was answered. When that settings file is later copied — by a
seed, a merge, or by hand — into another checkout, the rule still names
the first one: ``Bash(~/.herdr/worktrees/<repo>/<other-wt>/skills/x.sh …)``
in a sibling. It is dead everywhere except the checkout it points at,
and dead there too once that worktree is retired. PR #1708 taught the
merge path to re-anchor such rules (GH-1666), but rules already sitting
in a file were never looked at.

Report only. A rule whose worktree still exists is offered re-anchored
onto the file's own checkout; one whose worktree is gone is offered for
removal. Nothing is rewritten without the supervisor's confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRuleLoader
from dev10x.domain.common.workspace import worktree_roots_in
from dev10x.skills.doctor.strategy import Context, Finding, Remediation, Strategy
from dev10x.skills.permission.merge_worktree_permissions import reanchor_worktree_paths


@dataclass(frozen=True)
class StrandedRuleRemediation:
    """Remediation payload for a rule pinned to another worktree."""

    rule: str
    settings_path: str
    replacement: str | None

    def to_remediation(self, *, finding: Finding) -> Remediation:
        action: dict[str, str] = {"bucket": "permissions.allow", "remove": self.rule}
        if self.replacement is not None:
            action["add"] = self.replacement
        return Remediation(kind="edit_settings", target=self.settings_path, action=action)


def own_checkout(settings_path: Path) -> Path | None:
    """The checkout a project settings file belongs to; None for user scope."""
    if settings_path.parent.name != ".claude":
        return None
    checkout = settings_path.parent.parent
    return None if checkout == Path.home() else checkout


def _as_path(root: str) -> Path:
    return Path(root[1:] if root.startswith("//") else root).expanduser()


def _same(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def detect(context: Context) -> list[Finding]:
    """Flag allow rules naming a worktree other than the file's own checkout."""
    findings: list[Finding] = []
    for path in context.settings_paths:
        checkout = own_checkout(path)
        if checkout is None:
            continue
        for rule in AllowRuleLoader.load(path):
            stranded = [
                _as_path(root)
                for root in worktree_roots_in(rule)
                if not _same(_as_path(root), checkout)
            ]
            if stranded:
                findings.append(_finding(rule=rule, path=path, checkout=checkout, roots=stranded))
    return findings


def _finding(*, rule: str, path: Path, checkout: Path, roots: list[Path]) -> Finding:
    gone = [root for root in roots if not root.is_dir()]
    replacement = (
        None
        if gone
        else reanchor_worktree_paths(rule, main_project=checkout, worktree_roots=roots)
    )
    names = ", ".join(str(root) for root in roots)
    fix = (
        f"Remove it: {', '.join(str(root) for root in gone)} no longer exists."
        if replacement is None
        else f"Re-anchor it onto this checkout: ``{replacement}``."
    )
    return Finding(
        strategy_id="stranded-worktree-rules",
        # A dead allow grants nothing, so it must not gate `doctor run`.
        severity="suggestion",
        location=str(path),
        evidence=(
            f"``{rule}`` names {names}, not {checkout}; it never matches a "
            "command run in this checkout"
        ),
        proposed_fix=fix,
        data=StrandedRuleRemediation(rule=rule, settings_path=str(path), replacement=replacement),
    )


def remediate(finding: Finding) -> Remediation:
    """Propose re-anchoring the rule, or removing it when its worktree is gone."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id="stranded-worktree-rules",
    description=(
        "Flag allow rules pinned to an absolute path inside a different "
        "worktree than the settings file's own checkout. Such a rule is dead "
        "here, and dead everywhere once that worktree is retired (GH-1709)."
    ),
    detect=detect,
    remediate=remediate,
)
