# MCP Server Unavailable — Escape Hatch

Canonical guidance when a `plugin:Dev10x:cli` MCP tool is
disconnected mid-session.

## Problem

When the MCP server disconnects, several skills end up in a
lose-lose loop:

1. The preferred MCP tool (e.g., `mcp__plugin_Dev10x_cli__push_safe`)
   fails because the tool is listed as "no longer available" in the
   system-reminder.
2. Older skill docs instruct the agent to fall back to a wrapper
   script (e.g., `git-push-safe.sh`).
3. The wrapper is blocked by `validate-bash-command.py` with
   "use the MCP tool instead" — because the wrapper itself is
   designed to redirect back to MCP.
4. Raw CLI (`git push`) is blocked by the same hook with
   "use Skill(Dev10x:git)".
5. Prefixing with `DEV10X_SKIP_CMD_VALIDATION=true` is rejected —
   the flag is reserved for skill-authorized exceptional cases,
   not transient MCP unavailability.

## Correct Response

**STOP and ask the user to reconnect the MCP server.**

Do NOT:
- Fall back to the wrapper script (blocked by hook)
- Fall back to the raw CLI (blocked by hook)
- Prefix with `DEV10X_SKIP_CMD_VALIDATION=true`
- Keep retrying the unavailable tool

Do instead:
- Say: "The `plugin:Dev10x:cli` MCP server is disconnected.
  Please reconnect it via `/mcp` or restart the session, then
  I will retry."
- Wait for the user to reconnect before proceeding.

This "stop and ask" guidance assumes an interactive session with a
human to ask. It does not hold for unattended agents — background
workers, swarm children, or overnight automation — that have no
human channel at all. For the push case specifically, see the
unattended path below (GH-963); it exists because "abandon the
finished work" is the only alternative "stop and ask" leaves an
agent with no one to ask.

## Unattended Push Path (GH-963)

An unattended agent with committed, verified work and no MCP
server reachable is not stuck for the single most common
operation — pushing an ordinary feature branch. The `git-push`
hook rule (`src/dev10x/validators/command-skill-map.yaml`) already
lets a **non-force push that names an explicit, non-protected
branch** through directly, with no skill or MCP call required:

```
git push -u origin janusz/GH-963/my-feature-branch
```

This is safe without MCP because the guardrail `push_safe` /
`git-push-safe.sh` exist to enforce — no force-push to
`main`/`master`/`develop`/`development`/`staging`/`trunk` — is
already satisfied by construction: the command names a branch, that
branch is checked against `PROTECTED_BRANCHES`
(`src/dev10x/domain/common/branch_name.py`, pinned by test to the
same six names the push guard defaults to), and any bare
`--force`/`-f` still blocks. Narrowing the deny here doesn't
weaken the guardrail; it stops blocking exactly the case
`push_safe` would have allowed anyway.

This path does NOT cover:
- A bare `git push` or `git push origin` with no resolvable
  branch, or a symbolic `HEAD` ref — the hook can't verify safety
  without inspecting live git state, so it stays conservative and
  blocks. Always spell out the destination branch explicitly.
- Any `--force`/`-f` push (with or without `--force-with-lease`,
  which was already exempt) — still requires the skill/MCP path.
- Every other MCP-backed operation (PR creation, merge, issue
  comments, etc.) — those still hit the lose-lease loop above and
  still require "stop and ask" for an attended session, or a
  documented deferral (see below) for an unattended one.

For an unattended agent that hits the loop on an operation NOT
covered by the push exception above: do not retry, do not use
`DEV10X_SKIP_CMD_VALIDATION`. Leave the work committed on the
branch, record the blocker (status file, PR comment, or issue
comment as the run allows), and end the chunk — a human resolves
the reconnect on the next attended pass.

## Detection

The MCP server is disconnected when:
- A `mcp__plugin_Dev10x_cli__*` tool call returns an error with
  "no longer available" or "tool not found"
- The system-reminder lists the tool under "no longer available"
- Multiple MCP calls fail in sequence with connection errors

## Affected Skills

Skills that invoke `Dev10x_cli` MCP tools and have wrapper
fallbacks in their documentation:

- `Dev10x:git` — `git-push-safe.sh` (the unattended push path above
  is the one sanctioned exception: a non-force push to an explicit,
  non-protected branch needs neither the wrapper nor MCP)
- `Dev10x:git-fixup` — raw `gh api`
- `Dev10x:git-commit` — `mktmp` wrapper
- `Dev10x:git-groom` — raw git commands
- `Dev10x:gh-pr-create` — `create-pr.sh`, `verify-state.sh`
- `Dev10x:gh-pr-monitor` — `pr-notify.py`, `ci-check-status.py`
- `Dev10x:gh-pr-respond` — raw `gh api`
- `Dev10x:gh-pr-fixup` — raw `gh api`
- `Dev10x:gh-pr-triage` — raw `gh api`

All of the above should treat MCP unavailability as a hard stop,
not a signal to chain through wrapper fallbacks.

## Hook Reinforcement

The `skill_redirect` validator appends a standardized
`MCP_UNAVAILABLE_HINT` to every `use-tool` block message. When
the agent hits the hook while trying a wrapper or raw CLI, the
block message reminds them to ask the user to reconnect rather
than reach for `DEV10X_SKIP_CMD_VALIDATION`.

See `src/dev10x/validators/skill_redirect.py:MCP_UNAVAILABLE_HINT`.
