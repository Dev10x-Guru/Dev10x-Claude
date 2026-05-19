---
name: Dev10x:doctor
description: >
  Diagnose drift between user intent and observed agent behavior in
  Dev10x sessions. Runs pluggable strategies that each detect one
  drift category (MCP-vs-script confusion, missing dir coverage,
  stale memories, monorepo uv-run-project friction, missing local
  skill pre-approvals), explain the root cause, and propose a
  remediation patch — never auto-applied; always confirmed via
  AskUserQuestion.
  TRIGGER when: user hits repeated permission friction despite prior
  cleanup, notices the agent reaching for shell-script fallbacks
  instead of MCP tools, or wants a systemic audit of intent drift.
  DO NOT TRIGGER when: a single permission rule needs ad-hoc
  debugging (use Dev10x:permission-investigator) or the issue is a
  one-off skill bug (file a ticket instead).
user-invocable: true
invocation-name: Dev10x:doctor
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - mcp__plugin_Dev10x_cli__audit_hook_recent
  - mcp__plugin_Dev10x_cli__issue_create
  - Bash(dev10x config doctor:*)
  - Bash(dev10x config migrate:*)
---

# Dev10x:doctor — Intent Drift Diagnostic (GH-87)

Surfaces systemic drift across settings, memories, hook messages,
and skill docs that no single permission rule can fix. The skill
is composed of **strategies** — small detectors, each owning one
drift category. Strategies share a common interface so adding a
new one requires only a new file under
`src/dev10x/skills/doctor/strategies/`; the skill core does not
change.

## Why a separate skill

| Existing | Scope | Limitation |
|----------|-------|-----------|
| `Dev10x:permission-investigator` | Rule shape mutation matrix | Doesn't read memories or doc drift |
| `Dev10x:plugin-maintenance` | Ensures permissions present | Doesn't diagnose why intent breaks |
| `Dev10x:memory-maintenance` | Memory consolidation | Doesn't link drift to permission friction |

`Dev10x:doctor` orchestrates these as remediation targets — it
diagnoses, then delegates concrete edits.

## Orchestration

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Phase 1: Load enabled strategies", activeForm="Loading strategies")`
2. `TaskCreate(subject="Phase 2: Detect drift per strategy", activeForm="Detecting drift")`
3. `TaskCreate(subject="Phase 3: Present findings and remediations", activeForm="Presenting findings")`

## Step 0 — Check Dev10x config location (GH-215)

Before strategy detection, run `dev10x config doctor` to report
any legacy Dev10x config files still living under `~/.claude/`.
If files are found, offer to run `dev10x config migrate` (or
delegate to `Dev10x:upgrade-cleanup` which migrates as Step 1).

```
Bash("dev10x config doctor")
```

Treat any "Found N legacy ..." output as a finding to surface
in Phase 3, alongside the strategy detections.
4. `TaskCreate(subject="Phase 4: Apply approved fixes", activeForm="Applying fixes")`

Set sequential dependencies. Mark each completed when done.

### Phase 1: Load strategies

The plugin ships a default strategy catalog under
`src/dev10x/skills/doctor/strategies/`. Each strategy module
exports a `Strategy` dataclass:

```python
@dataclass
class Strategy:
    id: str                                 # "mcp-vs-script-drift"
    description: str                        # one-line summary
    detect: Callable[[Context], list[Finding]]
    remediate: Callable[[Finding], Remediation]
```

`Context` carries paths to settings files, memory directories, and
hook log access — strategies read but do not mutate. The first
shipped strategy is :mod:`dev10x.skills.doctor.strategies.mcp_vs_script_drift`
(MCP tool vs shell fallback). See
[`references/strategy-catalog.md`](references/strategy-catalog.md)
for the planned strategy roster.

### Phase 2: Detect drift

Iterate enabled strategies. Each strategy:

1. Reads the relevant input (memory file, settings JSON, SKILL.md,
   audit log).
2. Returns a list of :class:`Finding` records with:
   - `strategy_id`
   - `severity` (`critical` / `drift` / `suggestion`)
   - `location` (file path + line, or memory slug)
   - `evidence` (the offending text, quoted)
   - `proposed_fix` (string description; the actual edit is in the
     `Remediation`)

### Phase 3: Present findings

**REQUIRED: Call `AskUserQuestion`** for each finding (do NOT use
plain text). Options:

- **Apply (Recommended)** — execute the strategy's remediation
- **Skip** — leave as-is for this session
- **Defer** — file a ticket for follow-up via `issue_create`

Group findings by strategy in the presentation. For 5+ findings in
one strategy, offer "Apply all in this strategy" as a batch option.

### Phase 4: Apply approved fixes

Each remediation either:

- Edits a memory file in place (use `Edit`)
- Delegates to `Dev10x:plugin-maintenance` for settings changes
- Delegates to `Dev10x:memory-maintenance` for memory restructuring
- Files an upstream issue via `mcp__plugin_Dev10x_cli__issue_create`
  when the drift originates in the plugin itself

Never auto-apply across strategies — each Finding is its own gate.

## Initial Strategy: `mcp-vs-script-drift`

Detects memory entries, SKILL.md examples, and allow rules that
reference shell-script paths (`/tmp/Dev10x/bin/mktmp.sh`,
`~/.claude/plugins/cache/.../skills/.../scripts/*.sh`) when an
MCP tool offers the same capability. The negative-reinforcement
problem is real: "never use the script" memories load the literal
forbidden path into context every session, paradoxically priming
the agent to reach for it.

See [`references/mcp-vs-script-drift.md`](references/mcp-vs-script-drift.md)
for the script-to-MCP equivalence table and detection heuristics.

## Pluggability

Adding a new strategy:

1. Drop a module under `src/dev10x/skills/doctor/strategies/`
2. Export `Strategy` per the interface above
3. Add the module path to `strategies.yaml`

No skill-core changes required. User strategies under
`~/.claude/Dev10x/doctor/strategies/` are loaded after defaults.

## Anti-patterns

- **Auto-applying remediations** — every fix passes through
  `AskUserQuestion`. Drift detection is high-signal but
  remediation context is user-specific.
- **Quoting the offending path in fix output** — memories with
  negative examples (`"never use X"`) reinforce the wrong pattern.
  Strategies rephrase fixes to avoid literal forbidden tokens.
- **Running periodically** — the doctor is on-demand. A periodic
  run would re-prompt for findings the user already chose to skip.
