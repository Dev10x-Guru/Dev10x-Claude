# Background Friction Preamble (GH-610)

Canonical friction-avoidance preamble for background-dispatched
subagents (workflow / monitor / loop / fanout).

## Why this exists

Background subagents start with a **fresh system prompt** — they never
receive the SessionStart "Session Guidance — Patterns & Anti-Patterns"
briefing the main session gets. Without it they reproduce hook-tripping
command shapes (`cd && …`, `$(…)`, pipe chains, worktree-pinned paths)
and bypass MCP wrappers, then the harness offers the "switch to auto
mode" nudge (the GH-310 footgun). Parent: **GH-488** (S13 / G13 / D11).

This file is the **single source of truth**. Dispatchers MUST prepend
the block below verbatim to every background subagent prompt, and
pre-seed the subagent's tool surface (see § Pre-seed). Fetch the text
programmatically via the `mcp__plugin_Dev10x_cli__background_preamble`
tool (no Read prompt, no drift) or read this file.

## Coverage and limits

| Dispatch path | How the preamble lands |
|---------------|------------------------|
| `Dev10x:fanout` swarm children | Inlined into the per-item agent prompt template |
| `Dev10x:gh-pr-monitor` micro-agents | Inlined into each micro-agent prompt |
| Any Dev10x skill dispatching `Agent(...)` | Prepend per `references/orchestration/subagent-dispatch.md` |
| Built-in `Workflow` tool agents | Inline into each `agent()` prompt the script builds |
| Built-in `/loop` iterations | Harness-owned; the loop body's dispatched skills inline it |

`/loop` and the built-in `Workflow` tool are harness-owned — Dev10x
cannot inject into them automatically. The contract is therefore on the
**dispatcher**: whenever a Dev10x skill or workflow script builds a
subagent prompt, it prepends this preamble.

**Monitor tool commands are permission-matched like Bash (GH-879).**
The built-in Monitor tool's `command` string goes through the same
allow-rule matching as a Bash call — an inline `while … sleep` loop or
pipeline stage can prompt even when a near-identical shape passed
earlier, and in an unattended session that prompt freezes the
dispatching turn until a human returns (field case: 7 hours). Arm
monitors ONLY with pre-approved single-command shapes: the
`dev10x foreman watch` CLI, or a bare script path under
`~/.claude/tools/` — never an inline loop.

## The preamble (prepend verbatim)

<!-- BEGIN PREAMBLE -->
You are a background subagent. You did NOT receive the session's
friction briefing, so follow these rules to avoid tripping PreToolUse
hooks and to stay on the pre-approved tool surface.

Command shapes to avoid (each trips a hook or breaks allow-rule matching):
- No `cmd1 && cmd2`, `cmd1; cmd2`, or `a | b` chaining — one command per
  Bash call.
- No **chained** `cd /path && …` — chaining shifts the allow-rule
  prefix. A **standalone** `cd /path` as its own Bash call IS allowed.
- Do not assume your CWD is already the right worktree, and do not
  assume `cd` sticks: a spawned subagent inherits its dispatcher's
  directory, and whether CWD survives to the next call is
  spawn-depth-dependent (GH-1050). When your brief names a workspace
  path, **test which mode you are in** with two separate Bash calls —
  `cd /path`, then `pwd` — before editing anything (GH-959):
  - `pwd` == the path → **Mode P**: run plain `git` from here on, and
    never `git -C /path …`; the hook denies a `-C` whose path already
    equals CWD as redundant.
  - `pwd` != the path → **Mode C**: CWD reset, so pin the path as an
    argument on every call (`git -C /path …`, `uv run --directory
    /path …`, absolute paths for Read/Write/Edit).
- The `-C` rule generalises, so do not read Mode P as "never `-C`"
  (GH-1089): the hook denies `git -C <path>` only when `<path>` is
  already your CWD — that one case is redundant, nothing more.
  Pinning a *different* worktree with `-C` is allowed in both modes,
  and is the correct shape for reaching a sibling worktree.
- No `$(…)` command substitution and no `ENV=value cmd` prefixes.
- No heredocs or redirects (`cat <<EOF`, `cat > file`, `echo > file`) —
  use the Write tool.
- No inline interpreters (`python3 -c`, `sh -c`, `perl -e`, `node -e`) —
  use jq / yq / yamllint / actionlint, or extract a `uv run --script`
  tool.
- Never prefix git with `-P` or `--no-pager` (commonly denied as
  friction). Use the `git nopager` alias, or run git directly — it
  does not page non-interactively.

Prefer:
- `Read` / `Grep` / `Glob` over `cat` / `grep` / `find` in Bash.
- MCP wrappers and skills over raw CLI: commit → Skill(Dev10x:git-commit),
  PR → Skill(Dev10x:gh-pr-create), push → Skill(Dev10x:git), temp files →
  mcp__plugin_Dev10x_cli__mktmp.
- Git base aliases for diffs/logs: `git develop-log`, `git develop-diff`.
- To rebase onto a base that has MOVED, use two separate Bash calls —
  `git fetch origin`, then `git rebase origin/develop` — and then
  assert the postcondition, because "Successfully rebased" is not
  proof: `git merge-base --is-ancestor origin/develop HEAD` must exit
  0. Do NOT use `git develop-rebase` for this: it is an interactive
  (`-i`) grooming alias that resolves against a possibly stale LOCAL
  `develop` ref, so it hangs with no editor attached and can report
  success while HEAD never left stale ancestry (GH-964).
- To squash `fixup!` commits, use the non-interactive `rebase_groom`
  MCP tool.

Your tool surface is pre-seeded — the tools you need are already
allowed. Use them. Do NOT ask to "switch to auto mode" or disable
permission prompts to escape a blocked command (GH-310 footgun). If a
command is blocked, switch to the wrapper / structured tool named above.
<!-- END PREAMBLE -->

## Pre-seed (dispatcher responsibility)

The preamble tells the subagent to prefer `Read`/`Grep`/`Glob` and MCP
wrappers — those tools must actually be available, or the subagent
falls back to raw Bash and re-trips hooks. When constructing the
`Agent(...)` / `agent()` call, ensure `allowed_tools` includes:

- `Read`, `Grep`, `Glob`
- `mcp__plugin_Dev10x_cli__mktmp` and the workflow's needed `cli`
  wrappers (e.g. `push_safe`, `create_pr`, `ci_check_status`)
- `Skill` only when the subagent is meant to delegate (monitor
  micro-agents intentionally omit it)

Recommend pre-seeding over the auto-mode nudge: a narrow, correct tool
surface beats blanket `bypassPermissions`, which defeats the whole
friction model.
