---
name: dev10x-herdr:mission-control
invocation-name: dev10x-herdr:mission-control
description: >
  Use when many Claude sessions run in Herdr and the supervisor wants one
  status round or one instruction across them, so each repository's
  main-checkout session gathers its own worktrees' progress and can answer
  the same question later, instead of a coordinator talking to every pane.
  TRIGGER when: inside Herdr (HERDR_ENV=1) the user asks for mission
  control, a status round across sessions or repos, or "ask every session
  / every worktree" something.
  DO NOT TRIGGER when: outside Herdr, when the user wants one new worktree
  session (use dev10x-coding:git-worktree), or a localhost page of all
  sessions (use dev10x-comm:overwatch).
user-invocable: true
allowed-tools:
  - Bash(printenv HERDR_ENV)
  - Bash(pwd)
  - Bash(herdr agent get:*)
  - Bash(herdr agent read:*)
  - Bash(herdr agent prompt:*)
  - mcp__plugin_dev10x_cli__herdr_roster
  - mcp__plugin_dev10x_cli__mktmp
  - AskUserQuestion
  - Read
  - Write
  - TaskCreate
  - TaskUpdate
---

# dev10x-herdr:mission-control — Coordinate Through Main Sessions

**Announce:** "Using dev10x-herdr:mission-control to run a <global |
repo> round: <question>."

The argument is the round's question or instruction, verbatim. With no
argument the question is "status": what each session is working on, its
branch and PR, and what it is waiting on.

## Why the hierarchy

Mission control talks only to the session in each repository's **main
checkout** (the coordinator). The coordinator talks only to its own
repository's **worktree** sessions. When the supervisor later visits that
main session and asks the same question, it already holds the answer in
its own transcript. A mission control that prompts every pane directly
leaves the main sessions knowing nothing about their worktrees.

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Run mission-control round", activeForm="Running mission control")`

Mark it completed after Step 5 reports.

## Step 0: Confirm Herdr

Run `printenv HERDR_ENV`. Anything but `1` → say "not running inside
Herdr" and stop. Never drive Herdr from outside it.

## Step 1: Read the roster and pick the mode

1. Run `pwd` for the absolute working directory.
2. Call `mcp__plugin_dev10x_cli__herdr_roster(cwd=<pwd>)`. On an `error`
   key, report it and stop; never fall back to parsing `herdr` output by
   hand.
3. `caller.role == "main"` → **repo mode** for `caller.repo_root`
   (Step 3). Any other role → **global mode** (Step 2).
4. `mcp__plugin_dev10x_cli__mktmp(namespace="herdr", prefix="mission",
   directory=True)` → the round directory. Every brief and status file
   lives there.

## Step 2: Global mode — coordinators only

For each repository in `repos`:

- **Has a `coordinator`** → send it the repo-mode brief from
  [`references/round-protocol.md`](references/round-protocol.md) § 1,
  after the § 3 pre-send check. Skip the repository when the
  coordinator is the caller itself.
- **No coordinator, has worktree sessions** → queue it for the gate
  below.
- **No coordinator, no worktree sessions** → nothing to ask.

Never prompt a worktree session whose repository has a coordinator.
`unbound` sessions are listed in the report and never prompted.

**No-coordinator gate.** When the queue is non-empty, **REQUIRED: Call
`AskUserQuestion`** (do NOT use plain text, call spec:
[ask-no-coordinator.md](./tool-calls/ask-no-coordinator.md)). Name the
repositories and their worktree sessions in the question. Options,
recommended one computed from state:

- Ask their worktree sessions directly this round — leads when any of
  those sessions is `idle` or `done`
- Skip them and list them in the report — leads when every one is
  `working`, `blocked` or `unknown` (nobody can be asked safely)

Starting a new main-checkout session is not an option here: that is
`dev10x-coding:git-worktree`'s job, and the supervisor can ask for it.

## Step 3: Repo mode — own worktrees only

1. Call `herdr_roster(cwd=<pwd>, repo_root=<caller.repo_root>)`.
2. For each entry in `worktree_sessions`, apply the § 3 pre-send check,
   then act on its state:

   | State | Action |
   |---|---|
   | `idle` / `done` | Send the worktree brief (round-protocol § 2) |
   | `working` | Read only (`herdr agent read <pane> --source recent-unwrapped --lines 40`); summarise, do not prompt |
   | `blocked` | Report "waiting on the supervisor" with the visible question; never answer it |
   | `unknown` | Read only; report what the pane shows |

3. Do not prompt another repository's sessions, or the other main
   sessions of this repository.

## Step 4: Wait without polling

Send every prompt in its waiting form as a separate `run_in_background`
Bash call, all in one tool block:

```bash
herdr agent prompt <pane_id> "Carry out the brief at <brief-path>" --wait
```

Keep the line git-free and short (Path C Step C4: Claude Code's worktree
guard refuses `herdr` text that mentions git). Omit `--timeout`. Each
call's exit is that session's completion notice. Never a `sleep` loop,
a `Monitor` poll, or a fresh `herdr agent wait` on an idle agent. Read
the status files as the waits exit (round-protocol § 4).

## Step 5: Report

Print one table per repository: session (label or pane), role, state,
one-line answer, PR, and next or waiting-on. Below it, list every
session that was not asked and why (busy, blocked, unbound, skipped at
the gate). In repo mode, when the brief that started this round named a
status file, write the repository report there too.

The report stays in this session's transcript on purpose: that is what
lets a coordinator answer the supervisor's follow-up questions.

## Rules

- **Never type over someone** (round-protocol § 3). Never send `Esc`,
  `Ctrl+U` or any key to clear input you did not write.
- **Status only, no question relay.** Mission control and coordinators
  report a blocked session's question; they never answer it or pass an
  answer on. The supervisor answers in that pane.
- **Briefs go through files.** The prompt argument only points at the
  brief.
- **Never close, move or rename** a pane, tab or workspace you did not
  create.
- A wait that times out or stalls does not prove the prompt was lost.
  Read the pane (`herdr agent get` / `agent read`) before resending.
