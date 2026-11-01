---
name: dev10x:voice-channel
invocation-name: dev10x:voice-channel
description: >
  Use when one voice conversation (a Claude Desktop Cowork chat or a
  Claude Code hub session) supervises several coding sessions and the
  supervisor listens instead of reading — so each spoken turn names
  work in words a listener can hold, asks for at most one decision,
  and leaves code reviews and diffs for when they are at a screen.
  TRIGGER when: the user drives several sessions by voice, asks "what
  needs me?" / "what's next?" across sessions, or a bus request
  carries `Voice: yes` from a hub. DO NOT TRIGGER when: the user reads
  a single session in a terminal, or only needs the bus wiring (use
  dev10x:bus).
user-invocable: true
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/bus/scripts/:*)
  - ListAgents
  - SendMessage
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - TaskList
  - Read
  - Glob
---

# dev10x:voice-channel — One Voice, Many Sessions

**Announce:** "Using dev10x:voice-channel to keep the voice channel
short and send screen work to the screen."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Supervise sessions by voice", activeForm="Supervising by voice")`

Leave it open while the voice conversation lasts; mark it completed
when the supervisor ends the voice session.

## Overview

A listener cannot scroll back. Ticket numbers, PR numbers, mailbox
names and paths blur after one hearing, and two questions in one turn
lose the first. This skill sets what a spoken turn is, how work is
named, and which supervisor todos wait for a screen. The bus mechanics
(mailboxes, status board, notices) live in `dev10x:bus`.

## Step 1: Read the state

1. Run `${CLAUDE_PLUGIN_ROOT}/skills/bus/scripts/board.py` for the
   status board (Needs you / Working / Done, one line per session).
2. Call `ListAgents` for Claude Code sessions that are not on the
   board; ask them with `SendMessage` for one-line status.
3. Call `TaskList` for the decision queue and the screen list below.

## Step 2: Speak one turn

A spoken turn has exactly these parts, in this order:

1. **Headline** — one sentence with counts: "Two sessions need you,
   three are working."
2. **Items** — at most two, each as `<callsign>: <what changed>`:
   "The login fix is done and waits for your review."
3. **One question** — the single most urgent decision, or none.

Three sentences at most. Name work by **callsign and what it does**
("the login fix", "the payments migration"). Counts are fine;
identifiers are not — no ticket, PR, commit, line or mailbox numbers,
no paths, no code. Put identifiers and links after a line
`--- for the text session (do not read aloud) ---`.

Worked examples: [`references/narration.md`](references/narration.md).

## Step 3: Queue decisions, ask one

Record every pending decision as a task before speaking:
`TaskCreate(subject="Decide: <callsign> — <question>",
metadata={"decision": true, "options": [...]})`. Ask only the most
urgent one per turn; the rest stay queued and the headline counts them.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) when this
skill runs in a Claude Code hub: exactly **one** question, the
recommended option listed first and marked `(Recommended)`, labels in
callsign words. When the turn is a bus reply with `Voice: yes`, put the
same single question as the last spoken sentence instead. Relay the
answer to the session it belongs to (`SendMessage` or `send.py`), then
mark the decision task completed.

## Step 4: Keep screen work off the voice channel

Sort every supervisor todo into one of two lists:

| Voice-OK (ask now) | Screen-only (queue for the desk) |
|--------------------|----------------------------------|
| Approve / decline a plan | Code review, reading a diff |
| Pick A or B | Visual QA, screenshots, UI checks |
| Say "merge" after green CI | Long documents, tables, logs |
| Answer a factual question | Resolving a merge conflict |
| Pause / resume a session | Anything that needs a password or 2FA |

Queue a screen-only item as
`TaskCreate(subject="[screen] <callsign> — <what to look at>",
metadata={"needs_screen": true, "link": "<URL>"})`. In voice, mention
only the count and callsigns: "Two things wait for your screen: the
login fix review and the checkout screenshots." When the supervisor
says they are at the screen, print the `[screen]` list with links as
text, oldest first.

## Common mistakes

| Mistake | What the supervisor loses |
|---------|---------------------------|
| "PR 1624 is green" | Cannot tell which work that was by ear |
| Two questions in one turn | Answers the second; the first is dropped silently |
| Reading a diff or code review aloud | Cannot review by ear; the review is worthless |
| Listing every session every turn | The one item that needs them is buried |
| Asking "should I continue?" | A decision nobody needed — the plan already said yes |
| New callsign after a restart | The supervisor thinks a new session appeared |

## Related

- `dev10x:bus` — mailboxes, `status.py` / `board.py`, notices,
  callsigns, the Cowork prompt.
- `dev10x:ask` — turns stray prose questions into one widget.
