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

**The rule.** A turn that ends on an *unanswered decision* hands the
supervisor nothing to answer. That is the block condition. It is
deliberately broader than the conjunction the issue first proposed
("prose block ending in ``?``"): the issue's own third instance
disproved the narrower test, since a plan-approval gate held in prose
as "say go and I'll run 4.1 through 4.11" contains no question mark at
all and cost two extra round trips.

**But a pause is not a decision (GH-1339).** The condition was first
written as "this turn used no widget", which made a block the gate's
single most common outcome — 106 of 224 audit records — and told
sessions holding a pending task to ask the supervisor about work they
had already been told to do. The rule that replaces it comes from the
friction ladder this repo has since collapsed, where ``guided`` meant
"block **with a recommendation**" and ``adaptive`` merely auto-selected
that recommendation:

    A gate fires only where there is no recommended next action.

Open work *is* the recommended next action, so it auto-advances. Two
states are not open work and still do not block:

  - a **deferral in prose** — "shall I push?" is a true question, asked
    badly, and reformulating it as a widget is the gate working;
  - an **absent task list** is not a depleted one (GH-1055). The task
    tools ship by default only on older models, so a session without
    them never populates ``plan.tasks``; ``essentials.md`` says that
    emptiness "must not be treated as evidence of anything else".
    Conflating the two would block every turn of every such session,
    which is the very over-firing this rule ends.

That leaves one blocking state on the no-decision side: a task list
that exists and is wholly completed. There the next move genuinely is
the supervisor's, and the steer asks to stand down — carrying its own
recommended option rather than an open-ended "reformulate something".

**The loop guard is not optional.** A hook that always blocks, without
one, never lets a turn finish. Two independent guards, because the
harness contract is only documented and nothing in this repo exercised
it before (the ``[Verify]`` the issue flags): ``stop_hook_active`` in
the payload, and a per-session marker so a block happens at most once
per turn even if that field is absent or named differently.

**Who the rule is for (GH-1314).** "A turn always ends on a widget"
presumes a supervisor on the other end of it, and two cases have none:

  - a **subagent**, whose final message is its report to whoever
    dispatched it. One was observed echoing the no-open-work steer back
    as a status question — complying with a block it should never have
    received;
  - a session the supervisor has put **on standby**. "Are we done?" had
    no terminal answer, so confirming it only re-armed the gate next
    turn. Standby is that answer, scoped to the supervisor's next
    message rather than forever.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dev10x.domain.file_locks import atomic_write_text


def _diagnose(*, what: str, error: OSError | ValueError) -> None:
    """Note a filesystem or decode failure without changing the verdict.

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

#: The terminal answer that parks the gate (GH-1314). Matched against the
#: widget answer that opens the turn, so the option label the steer asks
#: for must contain this phrase.
_STANDBY_RE = re.compile(r"\bon standby\b", re.IGNORECASE)

#: Payload fields that would mark a Stop as belonging to a subagent
#: (GH-1314). ``hook_event_name`` is the documented one — the harness
#: fires ``SubagentStop`` for a subagent — and the rest are defensive:
#: the event reached subagent sessions despite this repo registering the
#: orchestrator under ``Stop`` alone, so the field that actually arrives
#: is not something to assume. ``StopSignal.SUBAGENT`` in the audit log
#: is what turns the guess into evidence.
_SUBAGENT_EVENT = "SubagentStop"
_SUBAGENT_KEYS = ("is_subagent", "subagent", "subagent_id", "agent_id", "parent_session_id")


class StopSignal(StrEnum):
    """Which branch of :func:`decide` produced a verdict (GH-1257).

    ``STOP_HOOK_ACTIVE`` is the load-bearing member: seeing it in the
    audit log is the evidence that retiring the cooldown marker needs,
    and until it appears the marker is the only guard known to work.

    ``SUBAGENT`` and ``STANDBY`` are named for the same reason (GH-1314):
    each is a new way for a turn to end legitimately, and a branch nobody
    can observe is a branch nobody can retire or trust.

    ``OPEN_WORK`` and ``NO_TASK_LIST`` are the two GH-1339 advances, kept
    apart because they answer different questions: the first says the
    plan named a next action, the second says there was no plan to read.
    Collapsing them would hide exactly the population GH-1055 is about.
    """

    STOP_HOOK_ACTIVE = "stop_hook_active"
    OPEN_WORK = "open_work"
    NO_TASK_LIST = "no_task_list"
    SUBAGENT = "subagent"
    STANDBY = "standby"
    COOLDOWN = "cooldown_marker"
    NO_TRANSCRIPT = "no_transcript"
    ASKED = "asked"
    BLOCKED = "blocked"

    def __repr__(self) -> str:
        return f"StopSignal.{self.name}"


def is_subagent(*, data: dict) -> bool:
    """Whether this Stop belongs to a subagent rather than the session.

    A subagent has no supervisor to hand a widget to. Its final message
    is its report to whoever dispatched it, so blocking that message
    both corrupts the report — the observed subagent echoed this
    module's own steer text back as a status question — and risks
    hanging an unattended run that cannot answer.

    Degrades toward **not** blocking only on positive evidence: an
    absent discriminator leaves the session treated as a main session,
    which is the pre-GH-1314 behaviour. Guessing the other way would
    silently disable the gate everywhere the payload shape surprises us.
    """
    if data.get("hook_event_name") == _SUBAGENT_EVENT:
        return True
    return any(data.get(key) for key in _SUBAGENT_KEYS)


@dataclass(frozen=True)
class StopVerdict:
    """Whether to block the Stop, and the steer to hand back if so."""

    block: bool
    reason: str = ""
    #: Which branch of :func:`decide` produced this verdict (GH-1257).
    #: Four of the five mean "let the turn end", and the caller needs to
    #: tell them apart: retiring the cooldown marker is only safe with
    #: positive evidence that ``stop_hook_active`` arrives set, and the
    #: audit log recorded nothing but wrap-phase timing, so the
    #: question could not be answered from the field at all.
    signal: StopSignal = StopSignal.BLOCKED

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
        atomic_write_text(path=marker, content=str(time.time()))
    except OSError as error:
        _diagnose(what="writing the cooldown marker", error=error)


def _standby_path(*, session_id: str) -> Path:
    return Path("/tmp/Dev10x/stop-verdict") / f"{session_id or 'unknown'}.standby"


def standby_holds(*, session_id: str, entries: list[dict], boundary: dict | None) -> bool:
    """Whether the supervisor has parked this gate and not yet spoken again.

    "Are we done?" has no terminal answer — confirming it just re-arms
    the same gate on the next turn, which is what made the widget feel
    inescapable rather than useful. Standby is that missing answer, and
    it is deliberately **not** a disable: it lasts exactly until the
    supervisor's next message.

    The answer is looked for across the whole turn rather than in the
    boundary entry alone. A widget answer arrives as a ``tool_result``,
    and GH-1334 stopped treating those as boundaries — so the answer now
    sits *inside* the turn, and reading only the boundary would find the
    supervisor's typed message instead and never see it.

    The lifetime is still read off the transcript rather than a clock,
    and now off a genuine message: a marker naming the same boundary
    means nothing has been said since, a different one means they have
    spoken and the marker is dropped. Scoping it to a typed message is
    what stops a tool result from silently clearing a park the
    supervisor set.
    """
    marker = _standby_path(session_id=session_id)
    boundary_id = _entry_id(entry=boundary)

    if _STANDBY_RE.search(_turn_answers(entries=entries, boundary=boundary)):
        _record_standby(marker=marker, boundary_id=boundary_id)
        return True

    try:
        parked_id = json.loads(marker.read_text(encoding="utf-8")).get("boundary_id")
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as error:
        _diagnose(what="reading the standby marker", error=error)
        return False

    if parked_id == boundary_id:
        return True

    # The supervisor has spoken since. Clearing here rather than on
    # their message is what keeps standby free of a second writer.
    marker.unlink(missing_ok=True)
    return False


def _record_standby(*, marker: Path, boundary_id: str) -> None:
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            path=marker,
            content=json.dumps({"boundary_id": boundary_id, "at": time.time()}),
        )
    except OSError as error:
        _diagnose(what="writing the standby marker", error=error)


def _entry_id(*, entry: dict | None) -> str:
    """A stable identity for one transcript entry.

    ``uuid`` is what the harness writes; the timestamp is a fallback for
    a transcript shape that carries no id, and an empty string means the
    two cannot be told apart — in which case standby simply does not
    persist past the turn that set it, which is the safe direction.
    """
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("uuid") or entry.get("timestamp") or "")


def _answer_text(*, entry: dict | None) -> str:
    """The text of any tool results in a user entry, joined.

    A widget answer comes back as a ``tool_result`` block whose content
    is either a plain string or a list of text blocks, so both shapes
    are flattened here.
    """
    if not isinstance(entry, dict):
        return ""

    parts: list[str] = []
    for block in _content_blocks(entry=entry):
        if block.get("type") != "tool_result":
            continue
        content = block.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(
                inner.get("text", "")
                for inner in content
                if isinstance(inner, dict) and inner.get("type") == "text"
            )
    return "\n".join(part for part in parts if part)


def _turn_answers(*, entries: list[dict], boundary: dict | None) -> str:
    """Every widget answer given since the supervisor last spoke, joined.

    The boundary is included because a supervisor who types alongside a
    tool result keeps that entry as the boundary — the answer would
    otherwise be dropped on exactly the entry that carries it.
    """
    return "\n".join(
        text for text in (_answer_text(entry=entry) for entry in (*entries, boundary)) if text
    )


def _read_turn(*, transcript_path: str) -> list[dict]:
    """The current turn, without the user message that opens it."""
    return _read_turn_and_boundary(transcript_path=transcript_path)[0]


def _read_turn_and_boundary(*, transcript_path: str) -> tuple[list[dict], dict | None]:
    """Read the current turn out of a JSONL transcript, oldest first.

    Only the turn matters, and the turn is always a suffix — the file is
    append-only and the turn starts after the last human message. So the
    lines are walked from the end and parsing stops at that message,
    which keeps the cost proportional to one turn rather than to the
    whole session. Parsing every line instead would make turn N pay for
    the N-1 turns before it, on a file that grows all session.

    That invariant was false until GH-1334: ``_is_user`` matched tool
    results too, so the walk stopped at the last tool *call* and the
    "turn" was only whatever the assistant emitted after it. The repair
    is in the predicate, not here — widening the scan would have bought
    the same correctness at the cost this docstring exists to avoid.

    A malformed or truncated line is not a reason to block a turn, so
    every read failure degrades to "no evidence" rather than raising.

    The boundary user message is returned alongside the turn rather than
    discarded: it carries the supervisor's last word, which is what
    standby is scoped to (GH-1314).
    """
    if not transcript_path:
        return [], None
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8")
    except OSError as error:
        _diagnose(what="reading the transcript", error=error)
        return [], None
    except UnicodeDecodeError:
        # A ValueError, not an OSError — a corrupt or binary transcript
        # would otherwise escape this function and only be caught three
        # frames up, making the promise above true by accident.
        return [], None

    turn: list[dict] = []
    boundary: dict | None = None
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
            boundary = entry
            break
        turn.append(entry)
    turn.reverse()
    return turn, boundary


def _is_user(*, entry: dict) -> bool:
    """Whether this entry is the supervisor speaking, not a tool answering.

    A tool result is written as a ``user`` entry, so matching on the type
    alone made every tool call a turn boundary (GH-1334): 36 of the 38
    user entries in a captured transcript were ``tool_result`` blocks and
    2 were typed messages. ``_read_turn`` therefore stopped at the last
    tool call, and since an ``AskUserQuestion`` is always followed by its
    own result, the call it looks for was always outside the window —
    ``asked`` fired 0 times in 159 records against 76 blocks.

    Content that is nothing but tool results is the tool answering.
    Anything else — a typed string, prose blocks, a result the supervisor
    typed alongside — is the boundary. Content that is absent or not a
    list reads as a plain message, which is what a typed one looks like.
    """
    if entry.get("type") != "user" and entry.get("role") != "user":
        return False
    blocks = _content_blocks(entry=entry)
    return not blocks or any(block.get("type") != "tool_result" for block in blocks)


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
    #: Whether a task list was found at all (GH-1055, GH-1339). The
    #: default is ``False`` so that "no evidence" is what an unset signal
    #: means, rather than "the work is finished".
    has_task_list: bool = False

    @property
    def has_open_work(self) -> bool:
        return bool(self.open_subjects)

    @property
    def is_depleted(self) -> bool:
        """A list that exists and holds nothing open — the one asking state."""
        return self.has_task_list and not self.has_open_work


def _plan_tasks(*, plan: dict) -> list[dict]:
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict)]


def task_signal(*, plan: dict | None) -> TaskSignal:
    """Read the open-work signal out of a persisted plan.

    GH-1251 also detected a **phase boundary** — a completed phase parent
    followed by a pending one — as the point `Dev10x:work-on` requires a
    gate. GH-1339 retires it: a pending phase *is* an open task, so the
    boundary strictly implies open work and could never reach a block
    again. Keeping it would leave an unreachable branch asserting a
    second opinion about plan gates that ``resolve_gate`` already owns.
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

    return TaskSignal(open_subjects=open_subjects, has_task_list=bool(tasks))


def auto_advances(*, signal: TaskSignal, closing: str) -> bool:
    """Whether this turn may simply end, with no widget (GH-1339).

    The pure rule, kept separate from :func:`decide` so it can be read
    and tested as one sentence: a turn advances unless it is holding a
    decision back, or the plan says the work is done.
    """
    if _DEFERRAL_RE.search(closing):
        return False
    return not signal.is_depleted


def _reason(*, signal: TaskSignal, closing: str) -> str:
    """The steer for a turn that really is ending on a decision.

    Both branches name a recommended option. Pre-collapse ``guided``
    blocked *with* a recommendation and ``adaptive`` auto-selected it;
    an open-ended "reformulate the open decision" is what produced
    manufactured questions rather than progress (GH-1339).
    """
    head = "⛔  This turn is ending on an unanswered decision.\n\n"

    if signal.has_open_work:
        nxt = signal.open_subjects[0]
        return (
            head + "The closing sentence defers a decision in prose, so it "
            "never reached the supervisor as something answerable. Open "
            f"work remains — {nxt!r} is next — so the decision is that "
            "deferral alone, not whether to carry on.\n\n"
            "Call `Dev10x:ask` to put it in an `AskUserQuestion`, with "
            "proceeding as the `(Recommended)` option."
        )

    if not signal.has_task_list:
        # Reached only via a deferral: without a list there is nothing to
        # call depleted, so the agent's own question is the whole gate.
        return (
            head + "The closing sentence defers a decision in prose. There is "
            "no task list to say what comes next, so nothing else can "
            "answer it.\n\n"
            "Call `Dev10x:ask` to put that decision in an "
            "`AskUserQuestion` with a `(Recommended)` option."
        )

    return (
        head + "Every task on the list is complete, so the next move is the "
        "supervisor's rather than yours.\n\n"
        "Call `Dev10x:ask` to ask whether to stand down, offering "
        '"Stand down — the work is complete" as the `(Recommended)` '
        'option and "On standby — not waiting on you" alongside it. '
        "Standby parks this gate until the supervisor speaks again; it "
        "is not a permanent disable (GH-1314)."
    )


def decide(*, data: dict, plan: dict | None, now: float | None = None) -> StopVerdict:
    """Return the Stop verdict for one hook invocation.

    ``data`` is the Stop payload; ``plan`` is the persisted plan-sync
    document (or ``None`` when there is none).
    """
    if data.get("stop_hook_active"):
        return StopVerdict(block=False, signal=StopSignal.STOP_HOOK_ACTIVE)

    if is_subagent(data=data):
        # A subagent's last message is its report, not an unanswered
        # question — there is nobody on the other end of a widget.
        return StopVerdict(block=False, signal=StopSignal.SUBAGENT)

    session_id = str(data.get("session_id") or "")
    if blocked_recently(session_id=session_id, now=now):
        return StopVerdict(block=False, signal=StopSignal.COOLDOWN)

    entries, boundary = _read_turn_and_boundary(
        transcript_path=str(data.get("transcript_path") or "")
    )
    if not entries:
        # No readable transcript is no evidence. Blocking on an absent
        # file would fire on every session whose transcript moved.
        return StopVerdict(block=False, signal=StopSignal.NO_TRANSCRIPT)

    if standby_holds(session_id=session_id, entries=entries, boundary=boundary):
        return StopVerdict(block=False, signal=StopSignal.STANDBY)

    if asked_a_question(entries=entries):
        return StopVerdict(block=False, signal=StopSignal.ASKED)

    signal = task_signal(plan=plan)
    closing = final_text(entries=entries)

    if auto_advances(signal=signal, closing=closing):
        # Two ways to advance, kept apart so the audit log can tell a
        # plan that named a next action from one that was never there.
        return StopVerdict(
            block=False,
            signal=StopSignal.OPEN_WORK if signal.has_open_work else StopSignal.NO_TASK_LIST,
        )

    return StopVerdict(
        block=True,
        reason=_reason(signal=signal, closing=closing),
        signal=StopSignal.BLOCKED,
    )
