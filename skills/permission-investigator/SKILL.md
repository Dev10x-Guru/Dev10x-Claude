---
name: Dev10x:permission-investigator
description: >
  Materialize a fixture, mutate settings with candidate rule shapes,
  and dispatch subagents to record which shapes the permission engine
  auto-approves vs prompts. Aggregates results into a markdown matrix
  and computes a delta against the rule shapes shipped by
  Dev10x:plugin-maintenance.
  TRIGGER when: permission prompts persist after plugin-maintenance
  cleanup, or new rule shapes need empirical validation before being
  shipped in projects.yaml.
  DO NOT TRIGGER when: a single rule needs ad-hoc debugging — write
  it to settings and reload instead.
user-invocable: true
invocation-name: Dev10x:permission-investigator
allowed-tools:
  - Bash(uv run dev10x:*)
  - mcp__plugin_Dev10x_cli__issue_create
  - Agent(general-purpose)
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - Read
---

# Permission Pattern Investigator (GH-47)

Empirically tests which permission rule shapes Claude Code's
engine auto-approves vs prompts on. Mutates settings, dispatches
a subagent in a fresh session per cell, records outcomes, and
produces a markdown matrix plus a delta report against the rules
currently shipped by `Dev10x:plugin-maintenance`.

> **Why this exists:** The engine matches rule strings literally
> against the prompt-displayed path. `~/`, `/home/<user>/`, and
> `${HOME}/` are not normalized. `*` segments work; `**` and
> `*/**` do not. Manual experimentation found these patterns —
> this skill replays them on demand and surfaces drift after
> plugin upgrades.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Phase 1: Prepare fixtures and matrix", activeForm="Preparing fixtures")`
2. `TaskCreate(subject="Phase 2: Dispatch matrix cells", activeForm="Dispatching cells")`
3. `TaskCreate(subject="Phase 3: Aggregate report and delta", activeForm="Aggregating report")`
4. `TaskCreate(subject="Phase 4: Restore settings and clean up", activeForm="Restoring settings")`

Set sequential dependencies: each phase blocked by the previous.

## Phase 1: Prepare

Run the prepare command. It materializes the fixture skill file
under `~/.claude/plugins/cache/Test-Org/Investigator/9.9.9/`,
creates a project-local `settings.local.json` stub, snapshots
the user's global settings, and persists the matrix shell to
`/tmp/Dev10x/permission-investigator/matrix.json`.

```
uv run dev10x permission investigate prepare
```

Read back the cell list — it is the source of truth for Phase 2:

```
Read /tmp/Dev10x/permission-investigator/matrix.json
```

## Phase 2: Dispatch

For **every cell** in the matrix, run this loop:

1. Apply the rule shape:

   ```
   uv run dev10x permission investigate apply <cell_id>
   ```

2. **REQUIRED: Dispatch a fresh subagent** to exercise the
   corresponding tool call against the fixture file. Use a
   `general-purpose` agent (Read tool requires no extra
   permissions; Bash needs the engine to evaluate the applied
   rule shape). Keep prompts short — the agent only needs to
   know whether the call was auto-approved or surfaced a prompt.

   ```
   Agent(
     subagent_type="general-purpose",
     model="haiku",
     description=f"Probe cell {cell_id}",
     prompt=f"""Attempt to read this file:
       {fixture_path}
       (or for Bash cells, run `cat {fixture_path}`)

       Return one of:
       - AUTO_APPROVED — the call ran without a permission prompt
       - PROMPTED — a permission prompt was surfaced
       - ERROR: <message> — the call failed for another reason

       Do not retry. Do not modify settings. Report exactly one
       line.""")
   ```

3. Record the outcome:

   ```
   uv run dev10x permission investigate record <cell_id> \
     --auto-approved   # or --prompted
   ```

4. Move to the next cell.

**Auto-advance:** Do not pause between cells. The matrix is
complete when every cell has a recorded outcome.

## Phase 3: Aggregate

Render the matrix and compute the delta against current
`plugin-maintenance` rules:

```
uv run dev10x permission investigate report \
  --output /tmp/Dev10x/permission-investigator/report.md
uv run dev10x permission investigate delta
```

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text)
when at least one rule is flagged ineffective. Options:

- File upstream issue (Recommended) — open a GH-47 follow-up
  issue at `Dev10x-Guru/Dev10x-Claude` with the matrix and
  proposed rule-shape changes
- Save report only — keep the markdown for review, no upstream
  filing
- Discard — restore settings and exit without saving

When the user picks "File upstream issue", invoke the issue
creation MCP tool with the report body:

```
mcp__plugin_Dev10x_cli__issue_create(
  title="Permission Pattern Investigator: <date> drift report",
  body=<contents of report.md>,
  labels=["permission-friction", "from-investigator"],
  repo="Dev10x-Guru/Dev10x-Claude",
)
```

## Phase 4: Restore

Always restore settings, even when the run fails or the user
discards the report:

```
uv run dev10x permission investigate restore
```

The workdir under `/tmp/Dev10x/permission-investigator/` is
left in place so the user can inspect the matrix state after
the run. It is a temp directory; the next `prepare` call
overwrites it.

## Decision Gates

| Gate | Trigger | Default in adaptive |
|------|---------|---------------------|
| Phase 3 disposition | Delta non-empty | "File upstream" auto-selected |
| Restore on error | Any phase fails | Always run restore |

Adaptive friction auto-selects the recommended option. Strict
and guided friction prompt for confirmation.

## Notes

- **Workdir:** `/tmp/Dev10x/permission-investigator/` — fixtures,
  snapshots, and `matrix.json` live here.
- **Fresh sessions:** the matrix only produces signal when each
  cell runs in a session where prior cells have not poisoned
  the engine cache. The dispatched subagents satisfy this — they
  start clean. Running probes inline in the parent session is
  not equivalent.
- **Coverage budget:** the default matrix is two tools (Read,
  Bash) × three prefixes × four wildcards × three locations =
  72 cells. Each cell is one short subagent invocation; total
  runtime is dominated by the engine's prompt-or-not decision.
- **Restore is mandatory:** never leave settings dirty. Phase 4
  runs even when an earlier phase fails.

## Resources

- `references/eval-criteria.md` — none required for this skill.
- Python implementation: `src/dev10x/skills/permission_investigator/`
- CLI: `dev10x permission investigate <subcommand>`
