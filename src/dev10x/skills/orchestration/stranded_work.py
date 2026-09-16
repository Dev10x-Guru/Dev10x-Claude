"""Detect work an agent left uncommitted in its ephemeral worktree (GH-1363).

An `isolation="worktree"` agent's worktree is reclaimed after the
orchestrator collects its result. Anything still uncommitted at that
point is unreachable: the shared object store holds no SHA to
cherry-pick, which is the whole reason GH-427 made the commit the
durable checkpoint.

Prose alone does not hold the line. GH-1173 rewrote the anti-stall
contract from an activity list into a reason class naming this exact
case, and four agents in one swarm still ended their turns mid-run with
work uncommitted "while waiting for the test suite" — with that wording,
and in two cases its rationale, verbatim in their briefs. So the
orchestrator stops depending on the agent having read it, and looks.

The decision is a pure function over `git status --porcelain` output and
the agent's status token; `inspect_worktree` is the wiring that runs git
(hook-patterns.md, the `stop_verdict` / `build_stop_verdict` split).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dev10x.skills.orchestration.subagent_protocol import SubagentStatus

_PORCELAIN_STATUS_WIDTH = 3
_RENAME_ARROW = " -> "


class StrandedSignal(StrEnum):
    """Which branch produced the verdict, so each one is observable."""

    CLEAN = "clean"
    UNREACHABLE = "unreachable"
    STRANDED = "stranded"


@dataclass(frozen=True)
class StrandedVerdict:
    """What the orchestrator must do before reclaiming a worktree."""

    signal: StrandedSignal
    paths: tuple[str, ...] = ()
    reason: str = ""

    @property
    def resume_required(self) -> bool:
        return self.signal is StrandedSignal.STRANDED

    @property
    def teardown_allowed(self) -> bool:
        return self.signal is StrandedSignal.CLEAN

    def to_dict(self) -> dict[str, object]:
        return {
            "signal": self.signal.value,
            "paths": list(self.paths),
            "reason": self.reason,
            "resume_required": self.resume_required,
            "teardown_allowed": self.teardown_allowed,
        }


def parse_porcelain(*, porcelain: str) -> tuple[str, ...]:
    """Extract the paths from `git status --porcelain` output.

    Untracked entries (`??`) count: the GH-1363 evidence includes a whole
    new test file that existed only as an untracked path. Ignored files
    do not appear unless `--ignored` is passed, which this never does.
    """
    paths: list[str] = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        path = line[_PORCELAIN_STATUS_WIDTH:].strip()
        if _RENAME_ARROW in path:
            path = path.split(_RENAME_ARROW, maxsplit=1)[1].strip()
        if path:
            paths.append(path)
    return tuple(paths)


def decide_stranded_work(
    *,
    porcelain: str,
    status: SubagentStatus,
    worktree_exists: bool = True,
) -> StrandedVerdict:
    """Decide whether an agent's worktree still holds unsalvageable work.

    A `DONE` token does not exempt a dirty worktree — it is the most
    dangerous combination, because `DONE` is what lets Phase 4 proceed to
    teardown.
    """
    if not worktree_exists:
        return StrandedVerdict(
            signal=StrandedSignal.UNREACHABLE,
            reason="worktree path does not exist; nothing left to inspect",
        )

    paths = parse_porcelain(porcelain=porcelain)
    if not paths:
        return StrandedVerdict(
            signal=StrandedSignal.CLEAN,
            reason=f"worktree clean after {status.value}",
        )

    return StrandedVerdict(
        signal=StrandedSignal.STRANDED,
        paths=paths,
        reason=(
            f"{len(paths)} uncommitted path(s) after {status.value}; "
            "resume the agent to commit and push before teardown"
        ),
    )


def resume_prompt(*, verdict: StrandedVerdict) -> str:
    """The continuation to SendMessage to a stranded agent."""
    if not verdict.resume_required:
        return ""
    listed = ", ".join(verdict.paths)
    return (
        "Your worktree still holds uncommitted work and is about to be "
        f"reclaimed, which would lose it: {listed}. Commit and push it now, "
        "before any verification step, then finish the lifecycle through to "
        "PR merge."
    )


def inspect_worktree(*, worktree: Path, status: SubagentStatus) -> StrandedVerdict:
    """Run `git status --porcelain` in an agent worktree and decide."""
    from dev10x import subprocess_utils

    if not worktree.is_dir():
        return decide_stranded_work(porcelain="", status=status, worktree_exists=False)

    completed = subprocess_utils.run(
        ["git", "status", "--porcelain"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return StrandedVerdict(
            signal=StrandedSignal.UNREACHABLE,
            reason=(completed.stderr or "git status failed").strip(),
        )

    return decide_stranded_work(porcelain=completed.stdout, status=status)
