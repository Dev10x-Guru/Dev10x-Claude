# Path C — Herdr-managed worktree (GH-1617)

Used automatically when the session runs inside
[Herdr](https://herdr.dev) (`HERDR_ENV=1`). Herdr manages workspaces,
panes, git worktrees and coding agents through its `herdr` CLI, so the
skill can create the worktree, open it in its own workspace, start a
Claude agent there and hand it the brief — without the user opening a
new session by hand.

Path C exists because, without it, agents improvised the `herdr` calls
and got three things wrong in one 2026-10-18 session: they asked
"should I start an agent?" (the answer is always yes), typed a prompt
into a pane where the user was typing, and sent `Esc` to "clear" input
they had not written — which interrupted the new agent's first turn.

## Step C1: Create the worktree

Fetch the base first, so the new branch starts from the remote tip
rather than a possibly stale local ref:

```bash
git fetch origin <base>
```

Then create the worktree in a new, unfocused Herdr workspace. The
branch follows the same convention as `dev10x:ticket-branch`
(`<user>/<TICKET>/<worktree-name>/<slug>`):

```bash
herdr worktree create --cwd <repo-root> \
  --branch <user>/<TICKET>/worktree-<slug>/<slug> \
  --base origin/<base> \
  --path ~/.herdr/worktrees/<repo>/worktree-<slug> \
  --label <TICKET>-<slug> --no-focus
```

`--no-focus` keeps the user's current pane in front; the new workspace
is visible in Herdr's sidebar. Note the new workspace's root pane ID
from the command's output — Step C3 starts the agent in it.

## Step C2: Confirm the post-checkout setup ran

Herdr's `git worktree add` fires the repo's `post-checkout` hook, so
the same hook templates as Paths A and B apply (see SKILL.md § Hook
Templates). Confirm with `Read` that the new worktree holds what the
hook was meant to produce — `.env`, `.venv`, `.claude/` — rather than
assuming it.

**Warn when `.claude/` may be stale.** The hook copies `.claude/` from
the main checkout. If the main checkout's local `<base>` is behind
`origin/<base>` in a way that touches `.claude/`, the new worktree
inherits the stale copy. Tell the caller; do not try to fix it from
here.

## Step C3: Start the agent — always

Do **not** ask whether to start an agent. An empty worktree is never
the goal; the caller is creating one so that work happens in it.

```bash
herdr agent start <TICKET>-<slug> --kind claude --pane <root-pane-id>
```

Name the agent after the ticket, so `herdr agent list` reads as a
roster. `agent start` returns once the agent is detected and ready for
input (default timeout 30s).

## Step C4: Hand over the brief through a file

Never pass the brief as `herdr agent prompt` argument text. A long
brief is fragile as a shell argument, and Claude Code's worktree
isolation guard refuses any `herdr` command whose text mentions `git`:
it cannot show that text is not a git operation in this session, even
though it is input to a *different* session. That guard belongs to
Claude Code, not to Dev10x, so the supported route is a brief file:

1. `mcp__plugin_dev10x_cli__mktmp(namespace="herdr", prefix="brief",
   ext=".md")` for the path.
2. `Write` the full brief there — the ticket, the worktree path, the
   branch, and the skill the agent should start with (normally
   `/dev10x:work-on <ticket-url>`).
3. Prompt with a short, git-free line that points at it, in the
   waiting form, as a `run_in_background` Bash call so this session
   is not blocked:

```bash
herdr agent prompt <TICKET>-<slug> "Carry out the brief at <path>" --wait
```

`--wait` matches only states observed after the submission: it needs
`working` or `blocked` within 5s (else `agent_prompt_stalled`), then
returns on `idle`, `done` or `blocked`. Its exit is the end of the
agent's turn. A separate `herdr agent wait` started after the prompt
races it — on an agent that has not yet left `idle` it returns at once
(GH-1702).

`/tmp/Dev10x` is cleared on a machine restart, so the brief is a
handoff, not a record — anything that must survive belongs on the
ticket.

**When `dev10x:fanout` is the caller (GH-1702),** the brief also
names an absolute status-file path, the merge mode's finish line, and
the status-line contract from
[`fanout/references/herdr-dispatch.md`](../../fanout/references/herdr-dispatch.md)
§ 2, quoted verbatim. The child has no `SendMessage` channel back to
the orchestrator, so writing that file with the `Write` tool before
every turn end is how its `DONE` / `DONE_WITH_CONCERNS` /
`NEEDS_CONTEXT` / `BLOCKED` line reaches the orchestrator.

## Step C5: Never type over someone

Before **any** prompt to a pane this skill did not just create — and as
a habit before every prompt — read the target first:

```bash
herdr agent get <TICKET>-<slug>
herdr agent read <TICKET>-<slug> --source visible --lines 5
```

- If the agent is `working` or `blocked`, do not send. `agent prompt`
  rejects a blocked agent anyway (`agent_blocked`); a working one would
  have the text queued behind its current turn.
- If the visible input line holds text, the user is typing there. Do
  not send, and tell the caller which pane is busy.
- **Never** send `Esc`, `Ctrl+U` or any key to clear input this skill
  did not write. Clearing someone else's input is how a first turn got
  interrupted.

## Step C6: Report and continue

Path C does not end this session; it hands **the ticket** to the
briefed agent, and this session stops working it. Other work here
continues. Report:

```
✅ Herdr worktree ready
   Workspace: <TICKET>-<slug>
   Path:      ~/.herdr/worktrees/<repo>/worktree-<slug>
   Branch:    <branch>
   Agent:     <TICKET>-<slug> (claude), briefed from <brief-path>
```

The new agent owns that worktree from here. Follow its progress with
`herdr agent get` and the Step C4 prompt's `--wait` exit, not by
reading its files or arming a fresh `herdr agent wait` on an idle
agent.
