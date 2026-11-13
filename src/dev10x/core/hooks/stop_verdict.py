"""Decide whether a Stop event should be blocked and steered (GH-1251).

Every mechanism that enforced "do not end a turn on a decision question"
was model-side instruction, and therefore skippable. `dev10x:ask` owns
the reformulation but is invoked by hand; the GH-149 task-list invariant
is prose in `essentials.md`; `dev10x:session-wrap-up` runs after the
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

**Open work ends the turn quietly.** GH-1377 once blocked every turn
that stopped with actionable tasks, steering "the plan still has work
on it". The supervisor retired it: a block on every turn of a long
plan was noise, and auto-advance belongs to the skill and playbook
instructions that already say "complete a task, start the next" —
not to a hook re-asserting them after each turn.

The terminal ``Verify acceptance criteria`` task GH-149 keeps open
still matters, because it decides which quiet ending applies: work
besides that gate reads as ``OPEN_WORK``, the gate alone as
``AWAITING_SUPERVISOR``.

An **absent task list** is not a depleted one (GH-1055):
the task tools ship by default only on older models, so a session
without them never populates ``plan.tasks``, and ``essentials.md`` says
that emptiness "must not be treated as evidence of anything else".
Conflating the two would block every turn of every such session, which
is the very over-firing this rule ends.

That leaves one blocking state on the task list: a list that exists and
is wholly completed. There the next move genuinely is the supervisor's,
and the steer asks to stand down — carrying its own recommended option
rather than an open-ended "reformulate something". (GH-1365 adds the
dirty-tree block on that same finished list.)

**A deferral in prose is not a decision.** An earlier cut of this rule
also blocked on closing shapes like "shall I push?" / "want me to…",
reasoning that the agent had taken a decision out of the supervisor's
hands. The supervisor's ruling is that it had not: pushing is forward
and reversible, so the answer is always yes, and asking is the defect.
Blocking never made the agent push — it made it render a widget about
work it should have simply done. Removing that carve-out took the last
guess about English out of the gate; everything left is structural.

**A promise nothing kept is the one exception (GH-1829).** "Now I'll
run the tests" with no tool after it is not a deferral — it tells the
supervisor work is under way when nothing is. Detecting it needs
phrases, so they live in ``stop_intent_patterns.yaml`` rather than in
code, keyed by language, with exemptions for a wait, a promise
conditioned on the supervisor's word, and deliberate deferral. The
check runs after both loop guards, standby and an open widget, and
before the task list, so it fires with or without a plan — except
for a turn parked on dispatched subagents (GH-1464). A pattern file
that cannot be read disarms it rather than blocking.

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
    received. The branch GH-1314 added for it never fired, and GH-1475
    captured why: Stop is not invoked for a subagent at all (two
    completions, zero Stop records, harness 2.1.316). So there is no
    subagent branch; the empty-list steer carries a text disposition
    for any reader without a supervisor instead;
  - a session the supervisor has put **on standby**. "Are we done?" had
    no terminal answer, so confirming it only re-armed the gate next
    turn. Standby is that answer, scoped to the supervisor's next
    message rather than forever.

**A turn ends when the widget is answered (GH-1336).** GH-1334 made the
``asked`` branch reachable by ruling that a tool result is not a turn
boundary. But a widget answer arrives as a tool result, so the window
for every turn after the supervisor clicked an option still held the
original call, and the gate stayed suppressed until they next typed. An
answer is the supervisor speaking and closes the turn it belongs to;
only an *unanswered* widget keeps the gate quiet.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import yaml

from dev10x.domain.documents.plan import is_terminal_task_subject
from dev10x.domain.file_locks import atomic_write_text
from dev10x.domain.session_document import plan_identity
from dev10x.domain.session_staleness import session_stale


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

_ASK_TOOL = "AskUserQuestion"

#: The terminal answer that parks the gate (GH-1314). Matched against the
#: widget answer that opens the turn, so the option label the steer asks
#: for must contain this phrase.
_STANDBY_RE = re.compile(r"\bon standby\b", re.IGNORECASE)

#: A stand-down answer (GH-1470). Anchored to the answer side of the
#: harness's ``"<question>"="<answer>"`` rendering, because unlike standby
#: this answer outlives the turn: a question that merely mentions standing
#: down must not silence the gate until the task list changes.
_STAND_DOWN_RE = re.compile(r'="\s*stand(?:ing)?[\s-]+down\b', re.IGNORECASE)

#: The keys a widget answer carries on its top-level ``toolUseResult``
#: (GH-1336). Captured from a live transcript before being relied on,
#: which is the precondition this module has been burned three times for
#: skipping: every ``AskUserQuestion`` answer in it carries
#: ``questions`` beside ``answers`` — the widget's own prompt set echoed
#: back — and no other tool result in 300-odd entries carries either.
#:
#: This is preferred over matching ``tool_use_id`` because it is
#: self-identifying: the entry says what it answers without anything
#: having to locate the originating ``tool_use`` first. ``tool_use_id``
#: stays as the fallback below, since ``toolUseResult`` is written by the
#: transcript writer rather than promised by the wire protocol.
_ANSWER_RESULT_KEYS = ("questions", "answers")

#: The task-metadata key an orchestrator sets on a task that is waiting
#: on work it already dispatched (GH-1464). With every open task blocked
#: on running fanout children there is nothing to continue with, and the
#: harness delivers each child's completion notification on its own — so
#: waiting is the correct end of the turn, and `watch-loop-handrolled`
#: rightly forbids every way of waiting in-turn. The marker keeps a
#: mid-wave turn out of the dirty-tree block, which only a finished list
#: should reach. Any truthy value counts; clearing it (``None``) makes
#: the task actionable again.
AWAITING_KEY = "awaiting"


class StopSignal(StrEnum):
    """Which branch of :func:`decide` produced a verdict (GH-1257).

    ``STOP_HOOK_ACTIVE`` is the load-bearing member: seeing it in the
    audit log is the evidence that retiring the cooldown marker needs,
    and until it appears the marker is the only guard known to work.

    ``STANDBY`` is named for the same reason (GH-1314): it is a way for
    a turn to end legitimately, and a branch nobody can observe is a
    branch nobody can retire or trust.

    ``OPEN_WORK`` and ``NO_TASK_LIST`` are the two GH-1339 advances, kept
    apart because they answer different questions: the first says the
    plan named a next action, the second says there was no plan to read.
    Collapsing them would hide exactly the population GH-1055 is about.
    GH-1377 turned ``OPEN_WORK`` into a blocking ``CONTINUE``; with that
    block retired the name returns, since the turn now ends again.

    ``STOOD_DOWN`` and ``FOREIGN_PLAN`` are GH-1470's two quiet endings: a
    stand-down answer held until the task set changes, and a persisted
    plan this session did not write. Each is its own member so the audit
    log can say which one kept a session quiet.

    ``PROMISED_ACTION`` is GH-1829's block: a turn that closes on "now
    I'll run the tests" with no tool after it. Its own member so the
    audit log can show how often the phrase list fires — the evidence
    any later widening or narrowing of that list needs.
    """

    STOP_HOOK_ACTIVE = "stop_hook_active"
    OPEN_WORK = "open_work"
    AWAITING_SUPERVISOR = "awaiting_supervisor"
    AWAITING_SUBAGENTS = "awaiting_subagents"
    NO_TASK_LIST = "no_task_list"
    FOREIGN_PLAN = "foreign_plan"
    STOOD_DOWN = "stood_down"
    DIRTY_TREE = "dirty_tree"
    STANDBY = "standby"
    COOLDOWN = "cooldown_marker"
    NO_TRANSCRIPT = "no_transcript"
    ASKED = "asked"
    PROMISED_ACTION = "promised_action"
    BLOCKED = "blocked"

    def __repr__(self) -> str:
        return f"StopSignal.{self.name}"


#: Opt-in flag for recording the Stop payload's shape (GH-1347).
PAYLOAD_KEYS_FLAG = "DEV10X_STOP_PAYLOAD_KEYS"


def payload_capture(*, data: dict, env: Mapping[str, str]) -> dict[str, str]:
    """The payload evidence to fold into the audit record, when opted in.

    GH-1347 asks for a captured payload rather than another inference.
    Three payload guesses have already failed here (GH-1257, GH-1314,
    GH-1336). Keys only, never values: a payload can carry the final
    assistant message, and the audit log is not the place for it.
    ``session_id`` is on the record so a subagent's turn can be told
    from its parent's, which a bigger sample cannot do. GH-1475 read it
    that way on harness 2.1.316: every record carried the parent's id,
    so Stop never reached a subagent. The flag stays so a later harness
    can be re-checked the same way before a subagent branch returns.
    """
    if env.get(PAYLOAD_KEYS_FLAG, "").strip().lower() not in ("1", "true", "yes"):
        return {}
    return {
        "payload_keys": ",".join(sorted(str(key) for key in data)),
        "hook_event_name": str(data.get("hook_event_name") or ""),
        "session_id": str(data.get("session_id") or ""),
    }


@dataclass(frozen=True)
class StopVerdict:
    """Whether to block the Stop, and the steer to hand back if so."""

    block: bool
    reason: str = ""
    #: Which branch of :func:`decide` produced this verdict (GH-1257).
    #: Most members mean "let the turn end", and the caller needs to
    #: tell them apart: retiring the cooldown marker is only safe with
    #: positive evidence that ``stop_hook_active`` arrives set, and the
    #: audit log recorded nothing but wrap-phase timing, so the
    #: question could not be answered from the field at all.
    signal: StopSignal = StopSignal.BLOCKED
    #: A task-set fingerprint to persist as the stand-down marker, or
    #: ``""`` for none (GH-1470). Carried on the verdict rather than
    #: written by :func:`decide` so the rule reads markers and never
    #: writes them; ``build_stop_verdict`` does the write.
    record_stand_down: str = ""
    #: The stand-down marker no longer matches the task set and should be
    #: dropped — the task list changed, which is what re-arms the gate.
    clear_stand_down: bool = False

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
    spoken and the marker is dropped. Since GH-1336 a widget *answer*
    can be that boundary too, which is the right widening — answering a
    widget is the supervisor speaking, so it may clear a park, while an
    ordinary tool result still may not.
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


def _stand_down_path(*, session_id: str) -> Path:
    return Path("/tmp/Dev10x/stop-verdict") / f"{session_id or 'unknown'}.standdown"


def read_stand_down(*, session_id: str) -> str | None:
    """The task-set fingerprint the supervisor stood down on, if any (GH-1470).

    Standby lasts until the supervisor speaks. Stand-down has to outlast
    that: it is the terminal answer, and the field report is a session
    that re-asked after each of three follow-up questions. So its
    lifetime is keyed to the task set instead, which is what a new
    ``TaskCreate``, a status change, or a new ``work-on`` all move.

    Read-only, so :func:`decide` can consult it and stay free of writes.
    A marker that cannot be read is no stand-down, which lets the gate
    fire as it did before — never the direction that silences it.
    """
    try:
        content = json.loads(_stand_down_path(session_id=session_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        _diagnose(what="reading the stand-down marker", error=error)
        return None
    recorded = content.get("fingerprint") if isinstance(content, dict) else None
    return recorded if isinstance(recorded, str) and recorded else None


def record_stand_down(*, session_id: str, fingerprint: str) -> None:
    """Persist a stand-down answer against the task set it was given on."""
    marker = _stand_down_path(session_id=session_id)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            path=marker,
            content=json.dumps({"fingerprint": fingerprint, "at": time.time()}),
        )
    except OSError as error:
        _diagnose(what="writing the stand-down marker", error=error)


def clear_stand_down(*, session_id: str) -> None:
    """Drop a stand-down whose task set has since changed."""
    try:
        _stand_down_path(session_id=session_id).unlink(missing_ok=True)
    except OSError as error:
        _diagnose(what="clearing the stand-down marker", error=error)


def task_fingerprint(*, plan: dict | None) -> str:
    """A digest of the plan's task set: each task's id and status (GH-1470).

    Subjects are the fallback identity for a task without an id, so a
    hand-written plan still fingerprints. Sorted, so the order tasks are
    persisted in cannot make an unchanged set look changed.
    """
    tasks = _plan_tasks(plan=plan) if isinstance(plan, dict) else []
    members = sorted(
        (str(task.get("id") or task.get("subject") or ""), str(task.get("status") or ""))
        for task in tasks
    )
    return hashlib.sha256(json.dumps(members).encode("utf-8")).hexdigest()


def _stood_down_this_turn(*, entries: list[dict], boundary: dict | None) -> bool:
    return bool(_STAND_DOWN_RE.search(_turn_answers(entries=entries, boundary=boundary)))


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

    A widget **answer** ends the turn too (GH-1336). GH-1334 correctly
    stopped treating tool results as boundaries, but an answered
    ``AskUserQuestion`` is a tool result, so the window for every later
    turn still contained the original call and the gate resolved
    ``ASKED`` until the supervisor next typed. An answer is the
    supervisor speaking; a ``Bash`` result is not.

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
    return _after_last_widget_answer(turn=turn, boundary=boundary)


def _after_last_widget_answer(
    *, turn: list[dict], boundary: dict | None
) -> tuple[list[dict], dict | None]:
    """Re-cut the turn at the last widget answer in it (GH-1336).

    Run as a forward pass over the already-read turn rather than inside
    the backward walk, because the two discriminators want opposite
    directions: ``toolUseResult`` is decidable where it sits, while
    ``tool_use_id`` needs the ``AskUserQuestion`` call that produced it —
    which is *earlier* in the file and so has not been parsed yet when
    the backward walk meets the answer. One forward pass serves both, and
    costs no extra I/O: the turn is already in memory, so ``_read_turn``
    still costs one turn, the constraint GH-1334 was careful to preserve
    and GH-1336 restates.

    A turn with nothing after the answer is left uncut. There is no
    agent activity to judge there, so cutting would only replace one
    let-the-turn-end verdict with a differently-labelled one — and an
    empty window would be reported as ``NO_TRANSCRIPT``, which would be
    a lie about why.
    """
    ask_ids: set[str] = set()
    answer_index: int | None = None
    for index, entry in enumerate(turn):
        if _is_widget_answer(entry=entry, ask_ids=ask_ids):
            answer_index = index
        ask_ids.update(_ask_tool_use_ids(entry=entry))

    if answer_index is None or answer_index == len(turn) - 1:
        return turn, boundary
    return turn[answer_index + 1 :], turn[answer_index]


def _ask_tool_use_ids(*, entry: dict) -> set[str]:
    """The ids of every ``AskUserQuestion`` call this entry makes."""
    return {
        str(block["id"])
        for block in _content_blocks(entry=entry)
        if block.get("type") == "tool_use" and block.get("name") == _ASK_TOOL and block.get("id")
    }


def _is_widget_answer(*, entry: dict, ask_ids: set[str]) -> bool:
    """Whether this entry is the supervisor answering a widget (GH-1336).

    Two discriminators, both observed on a captured transcript. The
    top-level ``toolUseResult`` carrying ``questions`` and ``answers`` is
    checked first because it is self-identifying — the entry declares
    what it answers, with no need to find the call it replies to.
    ``tool_use_id`` is the fallback, matched against the calls seen
    earlier in this same turn: it is part of the wire protocol and so
    survives a transcript writer that stops recording the richer key.

    Requiring both keys, not just ``questions``, keeps the test narrow.
    A false positive here cuts the turn short and re-arms the gate on a
    turn that legitimately ended on a widget.
    """
    result = entry.get("toolUseResult")
    if isinstance(result, dict) and all(key in result for key in _ANSWER_RESULT_KEYS):
        return True
    return any(
        block.get("type") == "tool_result" and str(block.get("tool_use_id") or "") in ask_ids
        for block in _content_blocks(entry=entry)
        if block.get("tool_use_id")
    )


#: What a stop-verdict record carries when the transcript names no
#: harness version (GH-1390). Written rather than omitted, because an
#: absent key is the ambiguity this whole change removes: a query
#: returning nothing must not have to guess between "no such version",
#: "no such record" and "wrong key".
UNKNOWN_HARNESS_VERSION = "unknown"


def read_harness_version(*, transcript_path: str) -> str:
    """The Claude Code version that wrote this transcript (GH-1390).

    ``hook-dispatch-patterns.md`` makes retiring the cooldown marker conditional
    on ``stop_hook_active`` appearing "across a few harness versions",
    and nothing in the Stop payload names one — so the condition could
    not be evaluated from the log at all, whatever key the signal was
    written under. An unverifiable precondition is how a guard calcifies
    into permanent dead weight, which is the failure GH-1257's own
    paragraph warns about.

    The harness stamps ``version`` on the transcript entries it writes,
    so the answer is already on disk next to the evidence it qualifies.
    Lines are walked from the end and the first version wins: a session
    that spanned an upgrade should be attributed to the version that
    ended it, which is the one that produced this Stop.

    Read here rather than inside :func:`decide` because it is provenance
    rather than rule input — ``decide`` stays a function of the payload
    and the plan. Every read failure degrades to
    :data:`UNKNOWN_HARNESS_VERSION`; a missing version is never a reason
    to change a verdict.
    """
    if not transcript_path:
        return UNKNOWN_HARNESS_VERSION
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8")
    except OSError as error:
        _diagnose(what="reading the transcript for its harness version", error=error)
        return UNKNOWN_HARNESS_VERSION
    except UnicodeDecodeError:
        return UNKNOWN_HARNESS_VERSION

    for line in reversed(raw.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        version = entry.get("version") if isinstance(entry, dict) else None
        if isinstance(version, str) and version.strip():
            return version.strip()
    return UNKNOWN_HARNESS_VERSION


def read_session_start(*, transcript_path: str) -> str | None:
    """When this session began: its transcript's first timestamp (GH-1470).

    The transcript is the one record of the session's own start that
    the Stop hook can see — the payload carries no start time. The walk
    is forward and stops at the first stamped entry, so it costs a few
    lines, not the file. ``None`` means "could not tell", which leaves
    the plan-ownership check to the branch alone.
    """
    if not transcript_path:
        return None
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                stamp = entry.get("timestamp") if isinstance(entry, dict) else None
                if isinstance(stamp, str) and stamp.strip():
                    return stamp.strip()
    except OSError as error:
        _diagnose(what="reading the transcript for its start", error=error)
    except UnicodeDecodeError:
        return None
    return None


def _parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def plan_is_foreign(
    *,
    plan: dict | None,
    session_started: str | None,
    current_branch: str | None,
) -> bool:
    """Whether the persisted plan belongs to some other session (GH-1470).

    There is one plan per checkout, so a session that never ran
    ``TaskCreate`` was judged against whatever an earlier session left —
    the field report's "19/20 tasks completed" banner came from a plan on
    ``develop`` written days before. Two tests, each only when its facts
    are known, because an unknown fact must not manufacture silence:

    - the plan's branch fails :func:`session_stale` against the current
      branch — the same predicate the ``session_adoption`` gate uses;
    - the plan's ``last_synced`` predates the session's start, so
      nothing this session did has touched it.

    Every task hook re-stamps both, so a plan this session is using
    passes both on its next sync.
    """
    if not isinstance(plan, dict):
        return False
    identity = plan_identity(summary=plan)
    if (
        current_branch
        and identity["branch"]
        and session_stale(
            recorded_branch=identity["branch"],
            current_branch=current_branch,
            recorded_tickets=identity["tickets"],
        )
    ):
        return True
    metadata = plan.get("plan")
    synced = _parse_instant(metadata.get("last_synced") if isinstance(metadata, dict) else None)
    started = _parse_instant(session_started)
    return synced is not None and started is not None and synced < started


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
    """True when this turn used ``AskUserQuestion``.

    The predicate was never the defect (GH-1336) — the window was. Once
    a widget answer ends the turn, an ``AskUserQuestion`` left in
    ``entries`` is by construction one nobody has answered yet, which is
    the only kind that should keep the gate quiet.
    """
    for entry in entries:
        for block in _content_blocks(entry=entry):
            if block.get("type") == "tool_use" and block.get("name") == _ASK_TOOL:
                return True
    return False


INTENT_PATTERNS_PATH = Path(__file__).with_name("stop_intent_patterns.yaml")


@dataclass(frozen=True)
class IntentPatterns:
    """The phrases that declare an imminent action, and what excuses one.

    ``exempt`` names a wait, a gate on the supervisor's decision or a
    deferral, wherever it sits in the sentence. ``preference`` names a
    gate on what the supervisor would like, which a hedge is built
    from. ``condition`` opens a clause that conditions it and the
    clauses after it. ``immediate`` marks a promise as not waiting on
    anything, which only a weak excuse in another clause gives way to.
    """

    intent: tuple[re.Pattern[str], ...] = ()
    exempt: tuple[re.Pattern[str], ...] = ()
    preference: tuple[re.Pattern[str], ...] = ()
    condition: tuple[re.Pattern[str], ...] = ()
    immediate: tuple[re.Pattern[str], ...] = ()


def _compile_patterns(*, label: str, raw: object) -> tuple[list[re.Pattern[str]], bool]:
    """Compile one ``intent`` / ``exempt`` list, and say whether any entry failed.

    An absent key is an empty list, not a failure. Anything else that
    cannot become a pattern — a non-list value, a non-string entry, a
    regex that does not compile — is dropped with one diagnostic, so a
    one-character YAML slip is visible instead of silently disarming
    the gate.
    """
    if raw is None:
        return [], False
    if not isinstance(raw, list):
        _diagnose(what=f"reading {label}", error=ValueError("expected a list"))
        return [], True

    compiled: list[re.Pattern[str]] = []
    failed = False
    for pattern in raw:
        if not isinstance(pattern, str):
            _diagnose(what=f"reading {label} entry {pattern!r}", error=ValueError("not a string"))
            failed = True
            continue
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as error:
            _diagnose(what=f"compiling {label} pattern {pattern!r}", error=ValueError(error))
            failed = True
    return compiled, failed


_PATTERN_KEYS = ("intent", "exempt", "preference", "condition", "immediate")

_EXCUSING_KEYS = frozenset({"exempt", "preference", "condition"})


def parse_intent_patterns(*, data: object) -> IntentPatterns:
    """Merge every language's lists from the parsed data file (GH-1829).

    A language is a key under ``languages:`` so a new one is added
    without touching code. An unusable entry is dropped with a
    diagnostic rather than failing the hook: a pattern that cannot run
    is not evidence that a turn broke its word.

    The lists fail in opposite directions, so they are not dropped
    alike. A lost ``intent`` or ``immediate`` pattern means fewer
    blocks, which is the direction every degradation here takes. A lost
    ``exempt``, ``preference`` or ``condition`` pattern means *more*
    blocks — a promise that should have been excused starts firing — so
    any broken one of those disarms the gate entirely.
    """
    languages = data.get("languages") if isinstance(data, dict) else None
    if not isinstance(languages, dict):
        _diagnose(what="reading the intent patterns", error=ValueError("no 'languages' mapping"))
        return IntentPatterns()

    lists: dict[str, list[re.Pattern[str]]] = {key: [] for key in _PATTERN_KEYS}
    for name, language in languages.items():
        if not isinstance(language, dict):
            _diagnose(what=f"reading intent language {name!r}", error=ValueError("not a mapping"))
            continue
        for key in _PATTERN_KEYS:
            compiled, failed = _compile_patterns(label=f"{name} {key}", raw=language.get(key))
            if failed and key in _EXCUSING_KEYS:
                return IntentPatterns()
            lists[key].extend(compiled)
    return IntentPatterns(**{key: tuple(patterns) for key, patterns in lists.items()})


@lru_cache(maxsize=1)
def load_intent_patterns(*, path: Path = INTENT_PATTERNS_PATH) -> IntentPatterns:
    """The intent patterns shipped beside this module, read once per process.

    ``UnicodeDecodeError`` is a ``ValueError``, so a corrupt file lands
    in the parse branch rather than escaping and taking the whole Stop
    verdict — dirty tree and stand-down included — down with it.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        _diagnose(what="reading the intent patterns", error=error)
        return IntentPatterns()
    except (ValueError, yaml.YAMLError) as error:
        _diagnose(what="parsing the intent patterns", error=ValueError(error))
        return IntentPatterns()
    return parse_intent_patterns(data=data)


#: How much of the closing paragraph the intent patterns see. A promise
#: sits at the end of a turn, and the cap bounds the cost of every
#: pattern a future language adds, whatever its shape.
_CLOSING_TAIL_CHARS = 2000


def _closing_paragraph(*, text: str) -> str:
    """The tail of the last non-blank paragraph, apostrophes made straight.

    Only the close is judged. A summary that says "I'll keep the old
    name" three paragraphs up has moved on; the sentence the turn ends
    on is the one a supervisor reads as the state of play.
    """
    paragraphs = [part for part in (raw.strip() for raw in re.split(r"\n\s*\n", text)) if part]
    closing = paragraphs[-1][-_CLOSING_TAIL_CHARS:] if paragraphs else ""
    return closing.replace("’", "'").replace("‘", "'")


_ITEM_MARKER = r"(?:[-*+]|\d+[.)])"

_SENTENCE_BREAK = re.compile(
    r"(?<=[.!?])(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\bvs\.)[*_`\"')\]]*\s+"
    rf"|\n(?=[ \t]*{_ITEM_MARKER}[ \t])",
    re.IGNORECASE,
)

_LIST_ITEM = re.compile(rf"{_ITEM_MARKER}\s")

_ITEM_NUMBER = re.compile(r"\d+\.")


def _fragments(*, text: str) -> list[str]:
    """The text cut at every break, with item numbers kept on their item.

    "1. I'll push" breaks after "1." like any full stop, at any indent
    and any number of digits, so a fragment that is only an item number
    is glued back onto the fragment that follows it.
    """
    fragments: list[str] = []
    number = ""
    for raw in _SENTENCE_BREAK.split(text):
        fragment = raw.strip()
        if not fragment:
            continue
        if _ITEM_NUMBER.fullmatch(fragment):
            number = f"{fragment} "
            continue
        fragments.append(f"{number}{fragment}")
        number = ""
    return fragments


def _sentences(*, text: str) -> list[str]:
    """The closing paragraph cut at sentence ends (GH-1854).

    An exemption speaks for the sentence it sits in. Judged across the
    whole paragraph, "Now I'll run the tests. If you see failures, I'll
    fix them." was exempted by its second sentence, though the first is
    a promise nothing conditions.

    Two things end a sentence: terminal punctuation followed by
    whitespace, and a line that opens a list item (``-``, ``*``, ``+``,
    ``1.``, ``1)``) even when the item before it has no full stop. A
    line wrap inside a sentence does not, so a wrapped promise keeps its
    condition, and a version number or path is never split. Markdown
    bold or italics, a straight closing quote, a paren, bracket or
    backtick may sit between the punctuation and the whitespace:
    "**I'll push it now.** Once you approve…" is two sentences. "e.g.",
    "i.e.", "vs." and an item number do not end one, since splitting
    there would cut a condition off from the promise it governs.

    A list item is judged together with the lead-in that introduces it
    when that lead-in ends in a colon: in "Once you approve:\\n- I'll
    merge it" the condition governs the items below it, up to the next
    sentence that is not a list item.
    """
    lead_in = ""
    judged: list[str] = []
    for sentence in _fragments(text=text):
        if _LIST_ITEM.match(sentence):
            judged.append(f"{lead_in} {sentence}" if lead_in else sentence)
            continue
        lead_in = sentence if sentence.endswith(":") else ""
        judged.append(sentence)
    return judged


_CLAUSE_BREAK = re.compile(r"[,;:—]")


def _clause_spans(*, sentence: str) -> list[tuple[int, int]]:
    """Where each clause of the sentence starts and ends."""
    starts = [0, *(match.end() for match in _CLAUSE_BREAK.finditer(sentence))]
    ends = [*(start - 1 for start in starts[1:]), len(sentence)]
    return list(zip(starts, ends, strict=True))


def _clause_at(*, spans: list[tuple[int, int]], offset: int) -> int:
    return next(index for index, (_, end) in enumerate(spans) if offset <= end)


@dataclass(frozen=True)
class _Clauses:
    """One sentence's clauses, and which excuse each one carries."""

    spans: list[tuple[int, int]]
    waits: list[bool]
    preferences: list[bool]
    conditioned: list[bool]
    opening: list[bool]


def _read_clauses(*, sentence: str, patterns: IntentPatterns) -> _Clauses:
    """Judge every clause once, whatever number of promises it holds."""
    spans = _clause_spans(sentence=sentence)
    clauses = [sentence[start:end] for start, end in spans]
    waits = [any(pattern.search(clause) for pattern in patterns.exempt) for clause in clauses]
    preferences = [
        any(pattern.search(clause) for pattern in patterns.preference) for clause in clauses
    ]
    conditioned = [
        any(pattern.search(clause.strip()) for pattern in patterns.condition) for clause in clauses
    ]
    opening = [
        conditioned[index]
        and not preferences[index]
        and (index == 0 or bool(_LIST_ITEM.match(clause.strip())))
        for index, clause in enumerate(clauses)
    ]
    return _Clauses(
        spans=spans,
        waits=waits,
        preferences=preferences,
        conditioned=conditioned,
        opening=opening,
    )


def _promise_is_excused(
    *,
    sentence: str,
    clauses: _Clauses,
    promise: re.Match[str],
    patterns: IntentPatterns,
) -> bool:
    """Whether an excuse in the sentence governs this one promise (GH-1894).

    "Let me know if you'd like, I'll run the tests now" hedges with a
    preference; "Once you approve, I'll merge it now" waits on the
    supervisor. So an excuse is strong or weak, and where it sits
    decides. A wait (``exempt``) governs the promise from anywhere in
    the sentence, and so does a condition that opens the sentence or a
    list item up to the promise's own clause, unless that condition is
    only a preference. A preference anywhere, or any other condition up
    to the promise's clause, governs it only when the promise does not
    say it is happening now, with or without a comma between them. A
    condition never reaches back: "I'll run the tests, if you don't
    mind" asks nothing of the supervisor.
    """
    spans = clauses.spans
    first = _clause_at(spans=spans, offset=promise.start())
    last = _clause_at(spans=spans, offset=max(promise.end() - 1, promise.start()))
    if any(clauses.waits) or any(clauses.opening[: last + 1]):
        return True
    promise_text = sentence[spans[first][0] : spans[last][1]]
    if any(pattern.search(promise_text) for pattern in patterns.immediate):
        return False
    return any(clauses.preferences) or any(clauses.conditioned[: last + 1])


def _breaks_its_word(*, sentence: str, patterns: IntentPatterns) -> bool:
    promises = [promise for pattern in patterns.intent for promise in pattern.finditer(sentence)]
    if not promises:
        return False
    clauses = _read_clauses(sentence=sentence, patterns=patterns)
    return any(
        not _promise_is_excused(
            sentence=sentence, clauses=clauses, promise=promise, patterns=patterns
        )
        for promise in promises
    )


def _tool_ran_after_text(*, entries: list[dict]) -> bool:
    """Whether any tool call follows the turn's last prose block.

    A stated intention followed by the call that carries it out is
    narration, not a broken promise — so only a turn whose prose is the
    very last thing it emitted can have promised something it skipped.
    """
    seen_tool = False
    for entry in reversed(entries):
        for block in reversed(_content_blocks(entry=entry)):
            if block.get("type") == "text" and str(block.get("text", "")).strip():
                return seen_tool
            if block.get("type") == "tool_use":
                seen_tool = True
    return seen_tool


def promised_action(
    *,
    entries: list[dict],
    patterns: IntentPatterns | None = None,
) -> str:
    """The closing paragraph when it promises an action nothing performed.

    Returns ``""`` when the turn is fine: no prose, a tool ran after the
    prose, or every sentence of the close that holds an intent phrase
    also holds an exempt one — a wait, a promise conditioned on the
    supervisor, or work deferred past this session on purpose. The
    exemption is matched per sentence (GH-1854), so a conditional
    promise cannot cover an unconditional one beside it.
    """
    if _tool_ran_after_text(entries=entries):
        return ""
    closing = _closing_paragraph(text=final_text(entries=entries))
    if not closing:
        return ""
    active = load_intent_patterns() if patterns is None else patterns
    if not any(pattern.search(closing) for pattern in active.intent):
        return ""
    broken = any(
        _breaks_its_word(sentence=sentence, patterns=active)
        for sentence in _sentences(text=closing)
    )
    return closing if broken else ""


def _promised_action_reason(*, closing: str) -> str:
    """The steer for a turn that ended on an intention instead of an action.

    An instruction, not a question (GH-1339): the next action is the
    one the agent itself just named. The only alternative offered is
    the one that hands the supervisor something real — an explicit
    question or an honest status line.
    """
    quoted = "\n".join(f"> {line}" for line in closing.splitlines())
    return (
        "⛔  This turn ends on a promise, and nothing ran after it:\n\n"
        f"{quoted}\n\n"
        "A supervisor reads that as work in progress and comes back to an "
        "idle session.\n\n"
        "**Do the action now** — make the tool call you just described. "
        "Narrating the next step is not taking it.\n\n"
        "**Or end the turn honestly.** If the step genuinely needs the "
        "supervisor, ask through `AskUserQuestion` with the recommended "
        "option first. If you are stopping for another reason, say so as a "
        "status line naming what is done and what is not — not as a future "
        "tense."
    )


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
    #: Open tasks tagged with :data:`AWAITING_KEY` (GH-1464) — parked on
    #: dispatched work, so not something this turn can act on.
    awaiting_subjects: tuple[str, ...] = ()

    @property
    def has_open_work(self) -> bool:
        return bool(self.open_subjects)

    @property
    def is_depleted(self) -> bool:
        """A list that exists and holds nothing open — the one asking state."""
        return self.has_task_list and not self.has_open_work

    @property
    def actionable_subjects(self) -> tuple[str, ...]:
        """Open tasks the agent can act on — everything but the terminal gate.

        GH-149 keeps a terminal ``Verify acceptance criteria`` task open
        until the supervisor signs off, so "something is open" is true of
        almost every turn and cannot, on its own, mean "keep working".
        What distinguishes the two is whether anything *other* than that
        gate is open. A task parked on dispatched work is excluded for the
        same reason (GH-1464): it is open, and there is nothing to do on it.
        """
        return tuple(
            subject
            for subject in self.open_subjects
            if not is_terminal_task_subject(subject=subject)
            and subject not in self.awaiting_subjects
        )

    @property
    def has_actionable_work(self) -> bool:
        return bool(self.actionable_subjects)

    @property
    def awaits_dispatched_work(self) -> bool:
        """Nothing is actionable, and something is waiting on a subagent."""
        return not self.has_actionable_work and bool(self.awaiting_subjects)

    @property
    def awaits_supervisor(self) -> bool:
        """The work is done and only the sign-off gate is left."""
        return self.has_open_work and not self.has_actionable_work


def _plan_tasks(*, plan: dict) -> list[dict]:
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict)]


def task_signal(*, plan: dict | None) -> TaskSignal:
    """Read the open-work signal out of a persisted plan.

    GH-1251 also detected a **phase boundary** — a completed phase parent
    followed by a pending one — as the point `dev10x:work-on` requires a
    gate. GH-1339 retires it: a pending phase *is* an open task, so the
    boundary strictly implies open work and could never reach a block
    again. Keeping it would leave an unreachable branch asserting a
    second opinion about plan gates that ``resolve_gate`` already owns.
    """
    if not isinstance(plan, dict):
        return TaskSignal()

    tasks = _plan_tasks(plan=plan)
    open_tasks = [
        task
        for task in tasks
        if task.get("status") in ("pending", "in_progress")
        and str(task.get("subject", "")).strip()
    ]
    open_subjects = tuple(str(task["subject"]).strip() for task in open_tasks)
    awaiting_subjects = tuple(
        str(task["subject"]).strip() for task in open_tasks if _is_awaiting(task=task)
    )

    return TaskSignal(
        open_subjects=open_subjects,
        has_task_list=bool(tasks),
        awaiting_subjects=awaiting_subjects,
    )


def _is_awaiting(*, task: dict) -> bool:
    metadata = task.get("metadata")
    return isinstance(metadata, dict) and bool(metadata.get(AWAITING_KEY))


def auto_advances(*, signal: TaskSignal) -> bool:
    """Whether the plan still names a next action for the agent.

    The answer no longer blocks the Stop. Auto-advance is the skill's
    and playbook's job — "complete a task, start the next" — and a hook
    re-asserting it after every turn was noise the supervisor retired.
    What this predicate still decides is which quiet ending applies,
    and that the tree is not consulted while work remains.

    The discriminator is structural, not a guess about English: GH-149
    keeps a terminal ``Verify acceptance criteria`` task open until the
    supervisor signs off, so "something is open" is true nearly always.
    What separates "work remains" from "genuinely waiting" is whether
    anything *besides* that gate is open.
    """
    return signal.has_actionable_work


def _dirty_tree_reason(*, dirty: tuple[str, ...]) -> str:
    """The steer for a depleted list whose tree still holds changes.

    This is an instruction, not a question. GH-1339 settled that only a
    true question may ask the human, and an uncommitted edit is not one
    — the next action is known, so naming it beats asking about it.

    **The escape matters as much as the block.** A session and the
    subagents it dispatches share one worktree, so these paths may
    belong to a concurrent session. Nothing available here can settle
    whose they are: uncommitted changes carry no author, and the
    transcript window is one turn by design. Telling an agent to commit
    files it never touched would be a worse outcome than the missing
    commit this catches, so the steer names the paths and lets the
    reader — who does know what it edited — decide.
    """
    listed = "\n".join(f"  - {path}" for path in dirty)
    return (
        "⛔  Nothing actionable is left on the task list, but the working "
        "tree is not clean. A finished list says the tracking is done; it "
        "says nothing about the work.\n\n"
        f"Uncommitted changes:\n\n{listed}\n\n"
        "**If these are yours, you are not done.** Commit them via "
        "`Skill(dev10x:git-commit)` and carry on through the rest of the "
        "shipping pipeline. Do not ask whether to commit — a commit is a "
        "forward, reversible step, so the answer is always yes.\n\n"
        "**If you did not touch these files, do not commit them.** This "
        "worktree is shared with the subagents you dispatched and can be "
        "shared with another session, and nothing here can tell whose "
        "changes these are. Say so plainly, leave them alone, and stand "
        "down — committing another session's work in progress is worse "
        "than the missing commit this gate exists to catch."
    )


def _reason(*, signal: TaskSignal) -> str:
    """The steer for the one state that is genuinely the supervisor's.

    Pre-collapse ``guided`` blocked *with* a recommendation and
    ``adaptive`` auto-selected it; an open-ended "reformulate the open
    decision" is what produced manufactured questions rather than
    progress (GH-1339). So this names its recommended option.

    The steer also spends its first words sending the reader back to
    the plan. A depleted *task list* is not the same as an exhausted
    *plan*, and the cheapest wrong outcome here is an agent asking a
    question the plan already answers. Context pressure is called out
    by name because "shall I continue?" is the commonest form of it,
    and it is not a decision the supervisor owes an answer to.

    It also refuses to prescribe a fixed option list (GH-1404). The
    steer used to name "Stand down — the work is complete" as the
    `(Recommended)` option unconditionally, and an empty task list is
    the only thing this branch can see: work deferred to a tracker
    issue, a PR still awaiting review, a promised follow-up — none of
    them is a task, and all of them are invisible here. Leading with an
    offer to stop is then the one answer that loses that information.

    Reading the pending work directly was considered and is not
    available: ``metadata["status"]`` flips to ``completed`` on exactly
    the condition that depletes the list, so it carries the same bit
    rather than an independent one, and no other durable key records
    work parked outside the plan. So the steer asks for the sweep that
    *can* see it (``dev10x:ask`` Mode 3) and orders the options from
    its result, instead of naming a winner in advance.

    Finally it carries a disposition for a reader that has no
    supervisor. This is the state in which the GH-1314 subagent was
    observed asking a human "are we done?". There is no mechanism to
    spare such a reader: GH-1475 captured that Stop never reaches a
    subagent, and a swarm teammate is a full session with nothing in its
    payload to tell it apart. Naming the alternative in the text is
    model-side instruction and so skippable, but it is the only lever
    this hook has for a reader it cannot identify.
    """
    return (
        "⛔  The task list is empty. That is not the same as the plan "
        "being finished, so the next move may be the supervisor's.\n\n"
        "**First, check whether it is actually yours.** Re-read the plan "
        "and any disposition already given this session. If they answer "
        "what comes next, act on it — do not ask. The supervisor wants "
        "the work done according to the plan and the skill's "
        "instructions, and a question they have already answered costs "
        "them a round trip to say so again.\n\n"
        "**Running low on context is not a reason to ask.** "
        '"Shall I continue?" is not a decision the supervisor owes you '
        "an answer to; carry on, or hand off per the skill's documented "
        "wrap-up. Never spend the gate on a question you raised about "
        "your own budget.\n\n"
        "**Sweep for open loops before you offer to stop.** An empty "
        "task list is all this gate can see. Work you deferred to a "
        "tracker issue, a PR still awaiting review, a follow-up you "
        "promised — none of those is a task, and none of them is "
        "visible here. Run `dev10x:ask --loops` first and let what it "
        "finds order the options:\n\n"
        "- **Something is pending** — lead with that concrete next "
        "action as the `(Recommended)` option, and put standby and "
        "stand-down after it. Offering to stop first is the one answer "
        "that throws the information away.\n"
        '- **Nothing is pending** — offer "Stand down — the work is '
        'complete" as the `(Recommended)` option, with "On standby — '
        'not waiting on you" alongside it. Standby parks this gate '
        "until the supervisor speaks again; it is not a permanent "
        "disable (GH-1314). A stand-down is kept until the task list "
        "changes, so follow-up questions after it are answered plainly "
        "(GH-1470).\n\n"
        "Either way the recommended option leads and carries the "
        "marker — an unmarked option list is a gate bypass "
        "(`.claude/rules/skill-gates.md`).\n\n"
        "**If you are a subagent working for an orchestrator, none of "
        "that applies to you.** Do not render an `AskUserQuestion` at a "
        "human — your counterparty is the orchestrator or swarm team "
        "lead that dispatched you, and the human is not waiting on you. "
        "Report to them instead. If they have already told you to stand "
        "down, wait for further work rather than asking again; "
        "otherwise ask them whether you may exit."
    )


def decide(
    *,
    data: dict,
    plan: dict | None,
    dirty: tuple[str, ...] | None = None,
    now: float | None = None,
    session_started: str | None = None,
    current_branch: str | None = None,
    patterns: IntentPatterns | None = None,
) -> StopVerdict:
    """Return the Stop verdict for one hook invocation.

    ``data`` is the Stop payload; ``plan`` is the persisted plan-sync
    document (or ``None`` when there is none); ``dirty`` is the working
    tree's uncommitted paths (GH-1365).

    ``dirty`` arrives as an argument rather than being read here, so
    this stays a pure function of what it is given and testable without
    a subprocess — the same separation the module keeps for ``plan``.
    ``None`` means the read failed or was not attempted, which is not
    evidence of uncommitted work and so reads as clean.

    ``session_started`` and ``current_branch`` arrive the same way
    (GH-1470): they decide whether ``plan`` is this session's at all,
    and ``None`` for either skips that half of the check.

    ``patterns`` are the promised-action phrases (GH-1829). ``None``
    reads the file shipped beside this module, which is a constant of
    the install rather than session state; passing them in keeps a
    caller or a test independent of that file.
    """
    if data.get("stop_hook_active"):
        return StopVerdict(block=False, signal=StopSignal.STOP_HOOK_ACTIVE)

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

    # A turn parked on subagents (GH-1464) is exempt: "next I'll collate
    # the results" is exactly what the harness will resume it to do.
    if not signal.awaits_dispatched_work and (
        closing := promised_action(entries=entries, patterns=patterns)
    ):
        return StopVerdict(
            block=True,
            reason=_promised_action_reason(closing=closing),
            signal=StopSignal.PROMISED_ACTION,
        )

    if not signal.has_task_list:
        # No list is no evidence either way (GH-1055). A model without
        # the task tools never populates one, so emptiness here says
        # nothing about whether the work is finished.
        return StopVerdict(block=False, signal=StopSignal.NO_TASK_LIST)

    if plan_is_foreign(plan=plan, session_started=session_started, current_branch=current_branch):
        # Another session's plan is no evidence about this one (GH-1470),
        # so it reads as the absent list it effectively is.
        return StopVerdict(block=False, signal=StopSignal.FOREIGN_PLAN)

    fingerprint = task_fingerprint(plan=plan)
    if _stood_down_this_turn(entries=entries, boundary=boundary):
        return StopVerdict(
            block=False, signal=StopSignal.STOOD_DOWN, record_stand_down=fingerprint
        )

    stood_down_on = read_stand_down(session_id=session_id)
    if stood_down_on == fingerprint:
        return StopVerdict(block=False, signal=StopSignal.STOOD_DOWN)

    verdict = _decide_on_tasks(signal=signal, dirty=dirty)
    if stood_down_on is not None:
        # The task set moved since the stand-down, which re-arms the gate.
        return replace(verdict, clear_stand_down=True)
    return verdict


def _decide_on_tasks(*, signal: TaskSignal, dirty: tuple[str, ...] | None) -> StopVerdict:
    """The task-list half of :func:`decide`, once the list is known to count."""
    if auto_advances(signal=signal):
        # The playbook drives the next task, not a block. The tree is not
        # consulted: uncommitted work mid-task is normal, and gating it
        # would re-create the over-firing GH-1339 removed.
        return StopVerdict(block=False, signal=StopSignal.OPEN_WORK)

    if signal.awaits_dispatched_work:
        # Everything left is parked on subagents (GH-1464). Their
        # notifications resume the session, so ending the turn is the
        # only compliant move. Checked before the tree: an orchestrator
        # mid-wave is not claiming to be done.
        return StopVerdict(block=False, signal=StopSignal.AWAITING_SUBAGENTS)

    # Past here the agent is claiming to be done, which is the moment
    # the supervisor's rule applies: a clean tree is part of that claim.
    if dirty:
        # The list says done, the tree says otherwise (GH-1365). Its own
        # signal, because "finished with a missing commit" and "finished"
        # are different outcomes and only one of them needs chasing.
        return StopVerdict(
            block=True,
            reason=_dirty_tree_reason(dirty=dirty),
            signal=StopSignal.DIRTY_TREE,
        )

    if signal.awaits_supervisor:
        # Only the sign-off gate is left, and the agent must never close
        # that itself (GH-149). Waiting is the correct end of the turn.
        return StopVerdict(block=False, signal=StopSignal.AWAITING_SUPERVISOR)

    return StopVerdict(block=True, reason=_reason(signal=signal), signal=StopSignal.BLOCKED)
