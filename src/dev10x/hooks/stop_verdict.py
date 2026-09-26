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

**Blocking continues the turn (GH-1366).** A Stop hook's ``block``
means *do not stop*: the steer becomes the continued turn's next
instruction. So "auto-advance" — proceed to the next task without
asking — is expressed by BLOCKING with a continue-steer, not by
letting the turn end. An earlier cut read it the other way and let a
session with pending tasks stop at a "natural reporting point".

Open work therefore continues the turn. The discriminator is the
terminal ``Verify acceptance criteria`` task GH-149 keeps open until
the supervisor signs off: since that makes "something is open" true
almost always, what separates "keep going" from "genuinely waiting" is
whether anything *besides* that gate is open.

An **absent task list** is not a depleted one (GH-1055):
the task tools ship by default only on older models, so a session
without them never populates ``plan.tasks``, and ``essentials.md`` says
that emptiness "must not be treated as evidence of anything else".
Conflating the two would block every turn of every such session, which
is the very over-firing this rule ends.

That leaves exactly one blocking state: a task list that exists and is
wholly completed. There the next move genuinely is the supervisor's,
and the steer asks to stand down — carrying its own recommended option
rather than an open-ended "reformulate something".

**A deferral in prose is not a decision.** An earlier cut of this rule
also blocked on closing shapes like "shall I push?" / "want me to…",
reasoning that the agent had taken a decision out of the supervisor's
hands. The supervisor's ruling is that it had not: pushing is forward
and reversible, so the answer is always yes, and asking is the defect.
Blocking never made the agent push — it made it render a widget about
work it should have simply done. Removing that carve-out took the last
guess about English out of the gate; everything left is structural.

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
    received. The branch GH-1314 added for it never once fired, because
    every discriminator it keyed on was a guess at the payload shape;
    GH-1340 replaced the guess with the transcript layout, which is
    observable and was captured before being relied on;
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

import json
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dev10x.domain.documents.plan import is_terminal_task_subject
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

_ASK_TOOL = "AskUserQuestion"

#: The terminal answer that parks the gate (GH-1314). Matched against the
#: widget answer that opens the turn, so the option label the steer asks
#: for must contain this phrase.
_STANDBY_RE = re.compile(r"\bon standby\b", re.IGNORECASE)

#: The documented payload marker of a subagent's stop (GH-1314): the
#: harness contracts a ``SubagentStop`` event for a dispatched agent.
#:
#: GH-1314 also checked five guessed keys (``is_subagent``, ``subagent``,
#: ``subagent_id``, ``agent_id``, ``parent_session_id``). GH-1347 retired
#: them on the evidence: ``StopSignal.SUBAGENT`` fired 0 times in 224
#: records (GH-1340) and the subagent branch 0 times in 488 records on a
#: day five subagents ran to completion. A name nobody has seen arrive
#: reads as coverage without being any. Payload keys are now captured
#: under ``DEV10X_STOP_PAYLOAD_KEYS`` (see ``session_dispatch``), so a
#: real discriminator is re-added from a recorded payload, not a guess.
_SUBAGENT_EVENT = "SubagentStop"

#: The directory a subagent's transcript lives in, and its filename
#: prefix (GH-1340). Captured from live dispatches rather than inferred:
#: a session writes ``<project>/<session-uuid>.jsonl`` while its
#: subagents write ``<project>/<session-uuid>/subagents/agent-<id>.jsonl``.
#: This is the one discriminator observed to arrive, and ``decide``
#: already reads ``transcript_path``, so it costs no new payload
#: dependency.
_SUBAGENT_DIR = "subagents"
_SUBAGENT_FILE_PREFIX = "agent-"

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
#: rightly forbids every way of waiting in-turn. Without a marker the
#: verdict could not tell such a task from actionable work and re-blocked
#: every turn. Any truthy value counts; clearing it (``None``) makes the
#: task actionable again.
AWAITING_KEY = "awaiting"


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

    ``SUBAGENT_PATH`` is separated from ``SUBAGENT`` for the same reason
    (GH-1340). The payload-key discriminators have never fired, and the
    only way to learn whether the transcript-layout check carries the
    population — and so whether the old guesses can be retired — is for
    the audit log to say which of the two matched.
    """

    STOP_HOOK_ACTIVE = "stop_hook_active"
    CONTINUE = "continue"
    AWAITING_SUPERVISOR = "awaiting_supervisor"
    AWAITING_SUBAGENTS = "awaiting_subagents"
    NO_TASK_LIST = "no_task_list"
    DIRTY_TREE = "dirty_tree"
    SUBAGENT = "subagent"
    SUBAGENT_PATH = "subagent_path"
    STANDBY = "standby"
    COOLDOWN = "cooldown_marker"
    NO_TRANSCRIPT = "no_transcript"
    ASKED = "asked"
    BLOCKED = "blocked"

    def __repr__(self) -> str:
        return f"StopSignal.{self.name}"


def subagent_signal(*, data: dict) -> StopSignal | None:
    """Which discriminator marks this Stop as a subagent's, or ``None``.

    A subagent has no supervisor to hand a widget to. Its final message
    is its report to whoever dispatched it, so blocking that message
    both corrupts the report — the observed subagent echoed this
    module's own steer text back as a status question — and risks
    hanging an unattended run that cannot answer.

    Degrades toward **not** blocking only on positive evidence: an
    absent discriminator leaves the session treated as a main session,
    which is the pre-GH-1314 behaviour. Guessing the other way would
    silently disable the gate everywhere the payload shape surprises us.

    The transcript path is checked because no payload discriminator has
    ever arrived (GH-1340, GH-1347). It infers identity from a directory
    layout the harness has not contracted to keep, so it is the fallback
    until a captured payload names a field that does.

    Returning *which* one matched, rather than a bool, is deliberate:
    the audit log has to separate the transcript check from the guesses
    it replaces, and deciding that a second time at the call site would
    let the attribution drift from what actually matched here.
    """
    if data.get("hook_event_name") == _SUBAGENT_EVENT:
        return StopSignal.SUBAGENT
    if _is_subagent_transcript(path=str(data.get("transcript_path") or "")):
        return StopSignal.SUBAGENT_PATH
    return None


#: Opt-in flag for recording the Stop payload's shape (GH-1347).
PAYLOAD_KEYS_FLAG = "DEV10X_STOP_PAYLOAD_KEYS"


def payload_capture(*, data: dict, env: Mapping[str, str]) -> dict[str, str]:
    """The payload evidence to fold into the audit record, when opted in.

    GH-1347 asks for a captured payload rather than another inference.
    Three payload guesses have already failed here (GH-1257, GH-1314,
    GH-1336). Keys only, never values: a payload can carry the final
    assistant message, and the audit log is not the place for it.
    ``session_id`` is on the record so a subagent's turn can be told
    from its parent's, which a bigger sample cannot do. That is the
    ambiguity the 0-of-488 reading left open.
    ``transcript_layout`` says what the path check concluded beside the
    keys, so the two sources can be compared record by record.
    """
    if env.get(PAYLOAD_KEYS_FLAG, "").strip().lower() not in ("1", "true", "yes"):
        return {}
    return {
        "payload_keys": ",".join(sorted(str(key) for key in data)),
        "hook_event_name": str(data.get("hook_event_name") or ""),
        "session_id": str(data.get("session_id") or ""),
        "transcript_layout": (
            "subagent"
            if _is_subagent_transcript(path=str(data.get("transcript_path") or ""))
            else "session"
        ),
    }


def is_subagent(*, data: dict) -> bool:
    """Whether this Stop belongs to a subagent rather than the session."""
    return subagent_signal(data=data) is not None


def _is_subagent_transcript(*, path: str) -> bool:
    """Whether this transcript is a subagent's, by where the harness puts it.

    Both halves are required. The directory alone would misread a main
    session that merely happened to sit under one, and the prefix alone
    would misread a project directory named after an agent.
    """
    if not path:
        return False
    transcript = Path(path)
    return transcript.parent.name == _SUBAGENT_DIR and transcript.name.startswith(
        _SUBAGENT_FILE_PREFIX
    )


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

    ``hook-patterns.md`` makes retiring the cooldown marker conditional
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
    followed by a pending one — as the point `Dev10x:work-on` requires a
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
    """Whether the agent should keep working rather than end the turn.

    **The name of the verdict is not the direction of the turn**
    (GH-1366). A Stop hook's ``block`` means *do not stop* — the turn
    continues and the steer becomes its next instruction. GH-1339 read
    "auto-advance" as "let the turn end quietly" and so returned
    ``block=False`` on open work, which removed the only mechanism that
    keeps an agent going. A session with real pending tasks then
    stopped at a "natural reporting point" and nothing objected.

    Auto-advance in this codebase means *proceed to the next task
    without asking*, and proceeding requires the turn to stay alive. So
    actionable work now continues the turn.

    The discriminator is structural, not a guess about English: GH-149
    keeps a terminal ``Verify acceptance criteria`` task open until the
    supervisor signs off, so "something is open" is true nearly always
    and would fire this gate every turn — the exact over-firing GH-1339
    was filed to end. What separates "keep going" from "genuinely
    waiting" is whether anything *besides* that gate is open.
    """
    return signal.has_actionable_work


def _continue_reason(*, signal: TaskSignal) -> str:
    """The steer for a turn that stopped with work still to do.

    It names the next task and never mentions ``AskUserQuestion``.
    There is no decision here to hand anyone: the plan already says
    what comes next, and asking about it is the defect GH-1339
    removed.
    """
    nxt = signal.actionable_subjects[0]
    remaining = len(signal.actionable_subjects)
    tail = "" if remaining == 1 else f" ({remaining} tasks still open.)"
    return (
        "⛔  The plan still has work on it, so this turn is not over.\n\n"
        f"Next: **{nxt}**.{tail}\n\n"
        "Continue with it now. Do not summarise progress and stop — a "
        "report is not a stopping point, and the supervisor asked for "
        "the work, not a status update. Do not ask whether to carry on; "
        "the plan is the authorisation.\n\n"
        "Running low on context is not a reason to stop either. Carry "
        "on, or hand off through the skill's documented wrap-up so the "
        "remaining tasks survive — never simply end mid-plan.\n\n"
        "If this task genuinely cannot proceed, say what blocks it and "
        "pick up the next unblocked task instead of ending here.\n\n"
        "If it is waiting on a subagent you already dispatched, do not "
        "poll or loop — tag it with `TaskUpdate(taskId, "
        f'metadata={{"{AWAITING_KEY}": "subagent"}})` and end the turn. '
        "The completion notification wakes you; clear the tag "
        f'(`{{"{AWAITING_KEY}": null}}`) when it arrives.'
    )


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
        "⛔  Every task on the list is complete, but the working tree is "
        "not clean. An empty task list says the tracking is done; it "
        "says nothing about the work.\n\n"
        f"Uncommitted changes:\n\n{listed}\n\n"
        "**If these are yours, you are not done.** Commit them via "
        "`Skill(Dev10x:git-commit)` and carry on through the rest of the "
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
    *can* see it (``Dev10x:ask`` Mode 3) and orders the options from
    its result, instead of naming a winner in advance.

    Finally it carries a disposition for a reader that has no
    supervisor. :func:`subagent_signal` is meant to spare subagents
    this block entirely, but that detector has been wrong before — it
    went 224 records without firing — and this is precisely the state
    in which the GH-1314 subagent was observed asking a human "are we
    done?". Naming the alternative in the text is model-side
    instruction and so skippable, which is why it is the fallback
    rather than the mechanism; a skippable instruction still beats none
    when the mechanism it backs has a recorded history of missing.
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
        "visible here. Run `Dev10x:ask --loops` first and let what it "
        "finds order the options:\n\n"
        "- **Something is pending** — lead with that concrete next "
        "action as the `(Recommended)` option, and put standby and "
        "stand-down after it. Offering to stop first is the one answer "
        "that throws the information away.\n"
        '- **Nothing is pending** — offer "Stand down — the work is '
        'complete" as the `(Recommended)` option, with "On standby — '
        'not waiting on you" alongside it. Standby parks this gate '
        "until the supervisor speaks again; it is not a permanent "
        "disable (GH-1314).\n\n"
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
    """
    if data.get("stop_hook_active"):
        return StopVerdict(block=False, signal=StopSignal.STOP_HOOK_ACTIVE)

    subagent = subagent_signal(data=data)
    if subagent is not None:
        # A subagent's last message is its report, not an unanswered
        # question — there is nobody on the other end of a widget. The
        # signal carries which discriminator matched, because that is the
        # only way to learn whether the payload-key guesses ever fire.
        return StopVerdict(block=False, signal=subagent)

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

    if not signal.has_task_list:
        # No list is no evidence either way (GH-1055). A model without
        # the task tools never populates one, so emptiness here says
        # nothing about whether the work is finished.
        return StopVerdict(block=False, signal=StopSignal.NO_TASK_LIST)

    if auto_advances(signal=signal):
        # Blocking CONTINUES the turn (GH-1366). The tree is not
        # consulted: uncommitted work mid-task is normal, and gating it
        # would re-create the over-firing GH-1339 removed.
        return StopVerdict(
            block=True,
            reason=_continue_reason(signal=signal),
            signal=StopSignal.CONTINUE,
        )

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
