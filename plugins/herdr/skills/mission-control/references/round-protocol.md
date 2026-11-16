# Mission-Control Round Protocol (GH-1984)

The briefs, status files and safety checks a round uses. The delivery
mechanics come from `dev10x-coding:git-worktree` Path C
(`plugins/coding/skills/git-worktree/references/herdr-path.md`, Steps
C4–C5). The status-file channel comes from `dev10x-coding:fanout`'s
Herdr dispatch (GH-1702). A Herdr session has no `SendMessage` channel
back to its caller, so a file it writes is the only reliable reply.

Paths below are inside the round directory from SKILL.md Step 1.
A status file is never created by the sender: its absence means "no
report yet".

## 1. Repo-mode brief (global mode → coordinator)

File: `brief-<repo_name>.md`. Status file: `status-<repo_name>.md`.

```markdown
# Mission-control round for <repo_name>

You are the main-checkout session of <repo_name> (<repo_root>).
Run `/dev10x-herdr:mission-control <question>` in repo mode: ask only
this repository's worktree sessions, and keep their answers in this
session so you can answer follow-up questions about them.

Question: <question, verbatim>

When the round ends, write your repository report to <status-file>
with the Write tool. Its last line must be exactly one of `DONE`,
`DONE_WITH_CONCERNS: <text>`, `NEEDS_CONTEXT: <what>` or
`BLOCKED: <reason>`.
```

Add nothing else: no scope limits, approval gates or plan. The brief is
pasted as a human prompt, so every extra word becomes an instruction.

## 2. Worktree brief (repo mode → worktree session)

File: `brief-<workspace_label>.md` (pane ID if the label is empty).
Status file: `status-<workspace_label>.md`.

```markdown
# Question from the <repo_name> main session

Question: <question, verbatim>

Answer from what you already know about your own work. Do not start new
work because of this question. When it is an instruction rather than a
question, carry it out as you would any request from the supervisor.

Write your answer to <status-file> with the Write tool, in this shape:

    Summary: <one line>
    Branch: <branch>
    PR: <url or none>
    Next / waiting on: <one line>
    <status line>

The last line must be exactly one of `DONE`, `DONE_WITH_CONCERNS: <text>`,
`NEEDS_CONTEXT: <what>` or `BLOCKED: <reason>`.
```

## 3. Pre-send check (before every prompt)

```bash
herdr agent get <pane_id>
herdr agent read <pane_id> --source visible --lines 5
```

- `working` or `blocked` → do not send. Report it per SKILL.md Step 3.
- The visible input line holds text → the supervisor is typing there.
  Do not send; report the pane as busy.
- Re-check right before sending: the roster is a snapshot, and a state
  can change between the roster read and the prompt.

## 4. Reading replies

When a `--wait` call exits, branch on the state it reports:

| Agent state | Status file | Reading |
|---|---|---|
| `blocked` | not read | `BLOCKED: <pane> is waiting on a prompt` — the supervisor answers in that pane |
| `idle` / `done` | ends with a status token | use the report |
| `idle` / `done` | missing, empty, or no token | `NEEDS_CONTEXT: <pane> stopped without a report` — read the pane, report what it shows; resend at most once |

When several waits exit together, read their status files in one
parallel tool block.

The round directory lives under `/tmp/Dev10x`, which a restart clears.
It is a handoff, not a record. What must survive belongs in the
coordinator's transcript or on a ticket.
