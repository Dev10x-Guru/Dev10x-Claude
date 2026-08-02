# Phase 0.4 — Permission pre-flight detail

The full command-shape enumeration behind Phase 0.4 of
`instructions.md`. Read this before running pre-flight on a new
night-shift; the numbered list in `instructions.md` names the six
checks, this file carries the exact invocations and field evidence.

## 1. Resolve the CLI shape once, and reuse it

`dev10x foreman probe --scratchpad <run-dir>` proves the watcher CLI
runs unprompted and the quota/base/heartbeat reads work. **Resolve the
CLI shape here and record it in the manifest** — the bare `dev10x`
entry point exists only when the CLI is installed as a uv tool. Probe
once with the bare shape; on a 127 exit fall back in this order, and
use whichever answers for `watch` in Phase 1 too:

| Install shape | Working invocation |
|---|---|
| `dev10x` installed as a uv tool | `dev10x foreman probe …` |
| CWD is a plugin-repo checkout | `uv run dev10x foreman probe …` (GH-947) |
| Normal plugin-cache install, CWD is the target repo | `uv run --project $CLAUDE_PLUGIN_ROOT dev10x foreman probe …` (GH-961) |

The third row is the common case for a night run: the plugin lives
under `~/.claude/plugins/cache/<owner>/<plugin>/<version>` while the
CWD is the repo being worked, so `uv run` alone resolves the wrong
project and the bare command exits 127. Two consecutive night runs
burned pre-flight window rediscovering this. Discovering it while
arming the watcher costs the night; discovering it now costs one
command.

## 2. One representative MCP call per wrapper

One call per MCP wrapper the crew will need (`ci_check_status`,
`issue_get`, `pr_get`, …) proves the MCP server is up and the tools
resolve before any worker depends on them.

## 3. The subagent tool surface

Spawn a throwaway probe subagent that runs the crew template's
`ToolSearch` select-query and then one read-only MCP call. The
watchdog's own surface proves nothing about a worker's: subagents get
MCP wrappers only as deferred tools and get no `Skill(...)` at all. If
the probe comes back empty, narrow the worker contract in the
manifest rather than letting workers improvise raw CLI
(`tool-surface.md`).

## 4. Per-domain test tools

The per-domain test tools for THIS repo (e.g. `run_node_tests`,
`uv run --directory <api> pytest`) — proves the exact invocation
shape and records it for the crew prompt (§ crew template).

## 5. Script deliverables, not just test runners (GH-961)

For every queued chunk whose *deliverable* includes an executable
artifact — a `bin/*.sh`, a generated compose file, a CLI entry point
— dry-run THAT artifact's own invocation shape, or add a narrow allow
rule for it, during this window. A worker that modifies a shell
script legitimately needs to execute it to verify the change, and a
manifest that bans "executing repo shell scripts" wholesale as
unproven leaves that worker with no sanctioned path.

Field case: a chunk whose deliverable was
`bin/render-worktree-config.sh` hit a permission prompt mid-night,
then hit a second one from the banned-shape workaround it improvised
(`ENV=x docker compose config 2>&1 | grep -A2 …` — env prefix plus
redirect plus pipe). Record each proven shape in the manifest so the
worker never has to improvise.

## 6. Write access

Write access to the run directory and the repo tree.

## Any prompt fired during pre-flight

Fix it NOW: prefer switching to a wrapper/skill; propose a narrow
allow rule only when no wrapper exists. If neither fits, that command
shape is BANNED for the night and the plan must route around it.
