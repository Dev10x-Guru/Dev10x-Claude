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

## The preamble (prepend verbatim)

<!-- BEGIN PREAMBLE -->
You are a background subagent. You did NOT receive the session's
friction briefing, so follow these rules to avoid tripping PreToolUse
hooks and to stay on the pre-approved tool surface.

Command shapes to avoid (each trips a hook or breaks allow-rule matching):
- No `cmd1 && cmd2`, `cmd1; cmd2`, or `a | b` chaining — one command per
  Bash call.
- No `cd /path && …` and no `git -C /path …` — your CWD is already the
  correct worktree; run commands directly.
- No `$(…)` command substitution and no `ENV=value cmd` prefixes.
- No heredocs or redirects (`cat <<EOF`, `cat > file`, `echo > file`) —
  use the Write tool.
- No inline interpreters (`python3 -c`, `sh -c`, `perl -e`, `node -e`) —
  use jq / yq / yamllint / actionlint, or extract a `uv run --script`
  tool.

Prefer:
- `Read` / `Grep` / `Glob` over `cat` / `grep` / `find` in Bash.
- MCP wrappers and skills over raw CLI: commit → Skill(Dev10x:git-commit),
  PR → Skill(Dev10x:gh-pr-create), push → Skill(Dev10x:git), temp files →
  mcp__plugin_Dev10x_cli__mktmp.
- Git base aliases for diffs/logs/rebases: `git develop-log`,
  `git develop-diff`, `git develop-rebase`.

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
