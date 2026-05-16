# ADR 0004 — Fanout via Native Agent Swarm

**Status:** Accepted (2026-05-16)
**Context:** GH-4, GH-34 (closed), GH-35 (closed), GH-36
**Supersedes:** the subprocess-based fanout plan recorded in
GH-4's earlier "Top-5 alternatives" comment.

## Context

`Dev10x:fanout` was originally documented as a parallel
work-stream orchestrator, but its implementation routed all
write-requiring work through the main session because of
three constraints:

1. Background `Agent()` could not call `Skill()`.
2. Background `Agent()` could not Write/Edit due to
   `bypassPermissions` non-propagation.
3. No first-class worktree isolation primitive existed at the
   Agent layer — workarounds via `claude -p` subprocess
   required a custom MCP launcher and permission-clamping
   settings file.

GH-4's accepted plan was to ship "Rank 1" — a subprocess
`claude -p` per worktree with a derived `--settings` clamp, a
JSONL wave dispatcher (GH-35), and a Monitor-based
auto-advance (GH-34). Estimated 13 SP across three tickets.

## Decision

Replace the subprocess plan with **native `Agent` swarm
dispatch**. The current Claude Code Agent tool exposes:

- `subagent_type="general-purpose"` with full `Tools: *`
  (Skill, Write, Edit, Bash, MCP)
- `isolation: "worktree"` — per-agent temp worktree with
  auto-cleanup when the agent makes no changes, otherwise the
  worktree path and branch are returned in the result
- `run_in_background: true` — automatic completion
  notification, no polling required
- `model:` per-agent override (`haiku` / `sonnet` / `opus`)
- `mode:` per-agent permission clamp (`acceptEdits`,
  `bypassPermissions`, `plan`, …)
- `name:` + `SendMessage` — addressable resumption of a
  running agent
- "Send multiple Agent tool uses in one assistant message and
  they run concurrently"

This collapses GH-4's Rank-1 design into four tool parameters.
GH-34 (subprocess launcher MCP tool) and GH-35 (wave
dispatcher + JSONL + Monitor) are closed as obsolete; GH-36
becomes the only remaining work.

### New architecture

- **Phase 3 dispatch** sends one wave of N non-conflicting
  items as a single assistant turn with N `Agent(isolation=
  "worktree", run_in_background=true, model="sonnet",
  mode="acceptEdits")` calls.
- **Per-agent prompt** carries a swarm context payload
  (`wave_id`, `siblings`, `your_item_id`, `conflict_group`,
  `shared_files_with_siblings`) plus etiquette rules, and
  instructs the agent to invoke
  `Skill(Dev10x:work-on, <item-url>)` so work-on remains the
  single source of truth for the implementation lifecycle.
- **Phase 4** collects completion notifications, parses
  results, and rebases conflict-chain successors between
  waves.
- **Recursive-fanout guard** is enforced via prompt etiquette
  and a skill-level self-check that scans for swarm-child
  markers; a PreToolUse hook is deferred to v2.

### Deferred alternatives

| Rank | Approach | Status |
|------|----------|--------|
| 0 | Native parallel `Agent(isolation="worktree", run_in_background=true)` | **Accepted** (this ADR) |
| 1 | `claude -p` subprocess + worktree per item | Deferred — revisit only if native isolation proves insufficient at scale |
| 2 | Tmux panes (`claude --tmux`) | Deferred — drops out without the subprocess layer underneath |
| 3 | MCP "session host" server | Deferred — would reimplement Skills outside of Claude Code |
| 4 | `RemoteTrigger` remote agents | Deferred — confirmed weak in GH-4 PoC (no Skill tool, empty plugin list) |
| 5 | `--resume --fork-session` pool | Deferred — marginal vs Rank 0 |

### Per-agent cost cap

Out of scope. `claude -p --max-budget-usd` had no native
equivalent; tracked as YAGNI until a real overrun is
observed. Per-agent cost is observable post-hoc from agent
results.

### Pub/sub coordination

Out of scope for this ADR. Mid-wave file-scope drift is
reported through the agent result message; the orchestrator
resolves between waves. Real-time sibling-to-sibling
coordination (JSONL bus, MCP `fanout_bus` server, or
`SendMessage` peer-to-peer) is a planned follow-up — see the
"future pub/sub" comment thread on GH-36 for the comparison.

## Consequences

**Positive:**

- 13 SP epic collapses to ~3 SP (GH-36 alone).
- No new MCP server, no JSONL status protocol, no Monitor
  polling, no permission-clamping settings file to maintain.
- Worktree lifecycle (creation + cleanup) is handled by the
  Agent tool, eliminating "zombie worktree" cleanup paths.
- Cache prefix is shared across siblings within a wave
  natively, preserving the cache-amortisation benefit from
  GH-4's PoC.

**Negative / open:**

- No hard per-agent cost cap (see YAGNI note above).
- No real-time sibling coordination — file-scope drift is
  surfaced only at wave boundaries until pub/sub lands.
- Spawned agents do not inherit SessionStart context
  (memory, plan-sync, MOTD). `Dev10x:work-on` must
  recognise fanout-nested invocations from the dispatch
  prompt and skip Phase 0 friction-level prompting; any
  future session-start dependency must be either inlined
  into the dispatch prompt or surfaced as `BLOCKED:` so the
  orchestrator can fall back to serial mode for that item.

## When to revisit

- Native `isolation: "worktree"` proves unreliable at scale
  → revisit Rank 1 (subprocess).
- A real runaway-cost incident occurs → add a per-agent cost
  cap (1 SP wrapper).
- Mid-wave sibling coordination becomes necessary → ship the
  JSONL bus or `fanout_bus` MCP server (follow-up ticket).
- Anthropic exposes a Skill-aware Agent SDK primitive →
  revisit Rank 3 (MCP session host).
