# Herdr Dispatch — one workspace per item (GH-1702)

Used when fanout runs inside [Herdr](https://herdr.dev)
(`HERDR_ENV=1`). Each item gets its own Herdr workspace with a Claude
agent named after its ticket, created through `dev10x:git-worktree`
Path C ([`herdr-path.md`](../../git-worktree/references/herdr-path.md)).
The `Agent(isolation="worktree")` swarm stays the path outside Herdr.

## Why a status file

A swarm child reports its trailing status line (`DONE` /
`DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`) through
`SendMessage(to="main", …)`. A Herdr-started agent is an independent
session: it has no `SendMessage` channel back to the orchestrator, so
without another channel the orchestrator loses the one signal it
branches on.

The channel is a file. The child writes its final status line to a
file the orchestrator named in the brief; the orchestrator reads it
once the agent stops working. Reading the agent's terminal instead
(`herdr agent read`) was rejected: TUI wrapping and scrollback can
hide or split the last line, and a parse of rendered output is not a
contract.

## Orchestrator side

### 1. Create the wave directory

Same as the swarm path (instructions.md § Swarm Dispatch): one
`mktmp(namespace="fanout", prefix=wave_id, directory=True)` per wave.
Each item's status file is `<wave_dir>/status-<TICKET>.md`. Do not
create it — its absence is the "no report yet" signal.

### 2. Start each item through Path C

For each item in the wave, follow `herdr-path.md` Steps C1–C5. The
brief written in Step C4 MUST carry, in addition to the usual ticket,
worktree path, branch and starting skill:

- the absolute status-file path;
- the merge mode and its finish line (§ Merge Mode), because the
  child cannot ask the orchestrator what "done" means;
- the status-line contract, verbatim:

  > When you stop — finished, interrupted, or blocked — write exactly
  > one line to `<status-file>` with the Write tool: one of `DONE`,
  > `DONE_WITH_CONCERNS: <text>`, `NEEDS_CONTEXT: <what>` or
  > `BLOCKED: <reason>`, followed by the PR URL if one exists. Write
  > it before your turn ends, every time you end a turn without
  > finishing. Never leave the file holding free-form prose.

Wave sizing (`max_concurrency`, host memory — GH-1068) applies
unchanged: a Herdr workspace is a full session and costs at least as
much as a background agent.

### 3. Wait without polling

The Step C4 prompt is the wait: send it in its waiting form
(`herdr agent prompt … --wait`, see `herdr-path.md` Step C4) as a
`run_in_background` Bash call, so its exit is the item's completion
notification. Omit `--timeout`; the item may legitimately take hours.
Never a `while … sleep` loop or a `Monitor` poll
(`ci-loop-handrolled` / `watch-loop-handrolled` block those).

### 4. Read the status file

When a prompt's wait exits, branch on the state it reports first:

| Agent state | Status file | Reading |
|---|---|---|
| `blocked` | not read | `BLOCKED: <agent> is waiting on a prompt` — surface it; the supervisor can answer in that workspace |
| `idle` / `done` | terminal token | that token, then § 5 |
| `idle` / `done` | missing, empty, or no terminal token | `NEEDS_CONTEXT: agent stopped without a status line` — resume it (§ 6) |

### 5. Verify before reporting

When several waits exit together, issue the reads and checks below
for all of them in one parallel tool block. Every guarantee of
instructions.md § Phase 4 still holds:

- run the stranded-work check against the item's worktree path;
- confirm the PR state with `mcp__plugin_dev10x_cli__pr_get` — a
  `DONE` on a PR that is still OPEN under `autonomous`/`cascade` is
  downgraded to `NEEDS_CONTEXT: PR open, merge incomplete`;
- no item is reported done without its PR state verified.

### 6. Resume through the agent, not a new one

The Herdr counterpart of a `SendMessage` resume is a prompt to the
same agent. Run `herdr-path.md` Step C5 first (never type over a
working agent or a user), then:

```bash
herdr agent prompt <TICKET>-<slug> "Continue the brief at <path>; finish to the finish line and write the status file" --wait
```

Same shape as § 3: backgrounded, and git-free (Step C4).

## Teardown

The workspace and worktree belong to the briefed agent. Swarm
Teardown's worktree steps do not apply to them; report each
workspace's label in the swarm summary so the supervisor can close
it in Herdr.
