"""Decide whether a Stop event should be blocked and steered (GH-1251).

Every mechanism that enforced "do not end a turn on a decision question"
was model-side instruction, and therefore skippable. `Dev10x:ask` owns
the reformulation but is invoked by hand; the GH-149 task-list invariant
is prose in `essentials.md`; `Dev10x:session-wrap-up` runs after the
fact. A Stop hook was already wired and could enforce none of it,
because the orchestrator discarded every feature's return value.

This module is the decision half. It reads the payload and the
transcript and returns a :class:`StopVerdict`; the orchestrator owns
the envelope. Keeping the two apart is what makes the rule testable
without a subprocess — the separation `dev10x.hooks.format_scope` got
under GH-1143.

**The rule.** A turn that ends without an ``AskUserQuestion`` hands the
supervisor nothing to answer. That is the block condition, and it is
deliberately broader than the conjunction the issue first proposed
("prose block ending in ``?``"). The issue's own third instance
disproved the narrower test: a plan-approval gate held in prose as
"say go and I'll run 4.1 through 4.11" contains no question mark at
all, and cost two extra round trips. The supervisor's ruling is that a
turn always ends on a widget — when there is genuinely nothing open,
the widget confirms that ("No open loops. Are we done?") rather than a
closing sentence asserting it.

**What varies is the steer, not the verdict.** The reason text is
graded by what the task list shows, because that is structural rather
than a guess about English (the ordering the GH-1251 comment
recommends):

  - a phase boundary — one phase parent complete, the next still
    pending — names the skipped gate outright;
  - open tasks name the next open loop;
  - nothing open asks for confirmation that the work is done.

**The loop guard is not optional.** A hook that always blocks, without
one, never lets a turn finish. Two independent guards, because the
harness contract is only documented and nothing in this repo exercised
it before (the ``[Verify]`` the issue flags): ``stop_hook_active`` in
the payload, and a per-session marker so a block happens at most once
per turn even if that field is absent or named differently.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dev10x.domain.file_locks import atomic_write_text


def _diagnose(*, what: str, error: OSError) -> None:
    """Note a filesystem failure without changing the verdict.

    Every degradation in this module points the same way — toward
    letting the turn end — which is right and also invisible. A marker
    directory that has become unwritable disables the cooldown guard,
    and the symptom is a hook that re-blocks every turn with nothing
    anywhere naming the cause. One stderr line keeps that discoverable;
    the orchestrator's ``audit_hook`` wrapper picks stderr up.
    """
    print(f"stop-verdict: {what} failed ({error})", file=sys.stderr)


#: A block is allowed again once this many seconds have passed since the
#: last one. Long enough that a single continued turn cannot re-block,
#: short enough that a later turn in the same session is still guarded.
_REBLOCK_COOLDOWN_SECONDS = 90

#: Closing shapes that defer a decision without asking one. Secondary to
#: the task-list signal — used only to sharpen the steer, never to
#: decide the verdict.
_DEFERRAL_RE = re.compile(
    r"\b(say go|let me know|shall i|want me to|should i|"
    r"if you(?:'d| woul)d like|do you want)\b",
    re.IGNORECASE,
)

_ASK_TOOL = "AskUserQuestion"


@dataclass(frozen=True)
class StopVerdict:
    """Whether to block the Stop, and the steer to hand back if so."""

    block: bool
    reason: str = ""

    def to_envelope(self) -> dict:
        """Render the Claude Code Stop-hook decision payload."""
        return {"decision": "block", "reason": self.reason}


def _marker_path(*, session_id: str) -> Path:
    return Path("/tmp/Dev10x/stop-verdict") / f"{session_id or 'unknown'}.marker"


def blocked_recently(*, session_id: str, now: float | None = None) -> bool:
    """True when this session was already blocked inside the cooldown.

    Belt-and-braces companion to ``stop_hook_active``: it holds even if
    that field is absent, renamed, or not set on a continuation.
    """
    marker = _marker_path(session_id=session_id)
    try:
        last = marker.stat().st_mtime
    except FileNotFoundError:
        # No marker yet — the expected state for a first block.
        return False
    except OSError as error:
        _diagnose(what="reading the cooldown marker", error=error)
        return False
    current = time.time() if now is None else now
    return (current - last) < _REBLOCK_COOLDOWN_SECONDS


def record_block(*, session_id: str) -> None:
    """Note that this session has just been blocked.

    A failure here must not turn into a second block, so the marker is
    written best-effort — the caller has already decided to block.
    """
    marker = _marker_path(session_id=session_id)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(marker, str(time.time()))
    except OSError as error:
        _diagnose(what="writing the cooldown marker", error=error)


def _read_turn(*, transcript_path: str) -> list[dict]:
    """Read the current turn out of a JSONL transcript, oldest first.

    Only the turn matters, and the turn is always a suffix — the file is
    append-only and the turn starts after the last human message. So the
    lines are walked from the end and parsing stops at that message,
    which keeps the cost proportional to one turn rather than to the
    whole session. Parsing every line instead would make turn N pay for
    the N-1 turns before it, on a file that grows all session.

    A malformed or truncated line is not a reason to block a turn, so
    every read failure degrades to "no evidence" rather than raising.
    """
    if not transcript_path:
        return []
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8")
    except OSError as error:
        _diagnose(what="reading the transcript", error=error)
        return []
    except UnicodeDecodeError:
        # A ValueError, not an OSError — a corrupt or binary transcript
        # would otherwise escape this function and only be caught three
        # frames up, making the promise above true by accident.
        return []

    turn: list[dict] = []
    for line in reversed(raw.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if _is_user(entry=entry):
            break
        turn.append(entry)
    turn.reverse()
    return turn


def _is_user(*, entry: dict) -> bool:
    return entry.get("type") == "user" or entry.get("role") == "user"


def _content_blocks(*, entry: dict) -> list[dict]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else entry.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def asked_a_question(*, entries: list[dict]) -> bool:
    """True when this turn used ``AskUserQuestion``."""
    for entry in entries:
        for block in _content_blocks(entry=entry):
            if block.get("type") == "tool_use" and block.get("name") == _ASK_TOOL:
                return True
    return False


def final_text(*, entries: list[dict]) -> str:
    """The last assistant prose in the turn, or ``""`` if there is none."""
    for entry in reversed(entries):
        texts = [
            block.get("text", "")
            for block in _content_blocks(entry=entry)
            if block.get("type") == "text"
        ]
        joined = "\n".join(text for text in texts if text).strip()
        if joined:
            return joined
    return ""


@dataclass(frozen=True)
class TaskSignal:
    """What the task list says about open work."""

    open_subjects: tuple[str, ...] = ()
    at_phase_boundary: bool = False

    @property
    def has_open_work(self) -> bool:
        return bool(self.open_subjects)


def _plan_tasks(*, plan: dict) -> list[dict]:
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict)]


def task_signal(*, plan: dict | None) -> TaskSignal:
    """Read the open-work signal out of a persisted plan.

    ``at_phase_boundary`` is the GH-1251 comment's primary detector: a
    completed phase parent followed by a pending one is the point where
    `Dev10x:work-on` requires a gate, whatever shape the closing
    sentence took.
    """
    if not isinstance(plan, dict):
        return TaskSignal()

    tasks = _plan_tasks(plan=plan)
    open_subjects = tuple(
        str(task.get("subject", "")).strip()
        for task in tasks
        if task.get("status") in ("pending", "in_progress")
        and str(task.get("subject", "")).strip()
    )

    phases = [task for task in tasks if str(task.get("subject", "")).startswith("Phase ")]
    at_boundary = any(
        earlier.get("status") == "completed" and later.get("status") == "pending"
        for earlier, later in zip(phases, phases[1:], strict=False)
    )

    return TaskSignal(open_subjects=open_subjects, at_phase_boundary=at_boundary)


def _reason(*, signal: TaskSignal, closing: str) -> str:
    head = (
        "⛔  This turn is ending without an `AskUserQuestion`.\n\n"
        "Call `Dev10x:ask` to reformulate the open decision as a widget "
        "before finishing.\n\n"
    )

    if signal.at_phase_boundary:
        body = (
            "A phase completed while the next phase is still pending — "
            "that is a plan gate, and the skill contract requires a "
            "widget there. Ask which way to proceed instead of "
            "describing the plan and waiting."
        )
    elif signal.has_open_work:
        nxt = signal.open_subjects[0]
        body = (
            f"Open work remains — the next open loop is {nxt!r}. Either "
            "hand the supervisor a choice about it, or confirm it is the "
            "right thing to pick up next."
        )
    else:
        body = (
            "Nothing is open. That still ends on a widget rather than a "
            'closing sentence — ask "No open loops. Are we done?", or '
            "present what was done for confirmation."
        )

    tail = ""
    if _DEFERRAL_RE.search(closing):
        tail = (
            "\n\nThe closing sentence defers a decision in prose. A "
            "deferral is a gate whether or not it ends in a question "
            "mark — GH-1251 instance 3."
        )

    return head + body + tail


def decide(*, data: dict, plan: dict | None, now: float | None = None) -> StopVerdict:
    """Return the Stop verdict for one hook invocation.

    ``data`` is the Stop payload; ``plan`` is the persisted plan-sync
    document (or ``None`` when there is none).
    """
    if data.get("stop_hook_active"):
        return StopVerdict(block=False)

    session_id = str(data.get("session_id") or "")
    if blocked_recently(session_id=session_id, now=now):
        return StopVerdict(block=False)

    entries = _read_turn(transcript_path=str(data.get("transcript_path") or ""))
    if not entries:
        # No readable transcript is no evidence. Blocking on an absent
        # file would fire on every session whose transcript moved.
        return StopVerdict(block=False)

    if asked_a_question(entries=entries):
        return StopVerdict(block=False)

    signal = task_signal(plan=plan)
    return StopVerdict(
        block=True, reason=_reason(signal=signal, closing=final_text(entries=entries))
    )
