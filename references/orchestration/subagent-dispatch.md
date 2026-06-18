# Pattern 4: Subagent Dispatch

Use subagents to reduce main-session token usage. Feed them
only the context they need; receive only the summary back.

## When to dispatch subagents

| Scenario | Dispatch? |
|----------|-----------|
| Research/exploration (docs, codebase) | Yes — Explore agent |
| Independent triage (N items, no shared state) | Yes — parallel general agents |
| Sequential execution (rebase, ordered commits) | No — run inline |
| Quick lookup (single file read, one grep) | No — direct tool call |

## Dispatch pattern

```
Agent(
    subagent_type="Explore",
    description="Research payment retry patterns",
    prompt="""
    Context: We're implementing retry logic for Square payments.
    The current code is in src/payments/square_client.py.

    Find:
    1. Existing retry patterns in the codebase
    2. Square API documentation on idempotency
    3. Test patterns for retry scenarios

    Return: A summary of patterns found with file paths and
    line numbers. Do not return full file contents.
    """
)
```

**Key principles:**
- Include only relevant context in the prompt (not full conversation)
- Ask for summary output, not raw data
- Use `run_in_background=true` when you have other work to do
- Use `isolation="worktree"` when the agent needs to modify files
- **Specify `model:` explicitly** for generic-purpose agents —
  see `.claude/rules/model-selection.md` for the tier framework:
  `haiku` for monitoring/gathering, `sonnet` for analysis,
  `opus` for code review and architecture decisions

## Parallel dispatch

When N items need independent processing, spawn agents in a
single tool-call block:

```
# Triage 4 PR comments in parallel
Agent(description="Triage comment r101", prompt="...", run_in_background=true)
Agent(description="Triage comment r102", prompt="...", run_in_background=true)
Agent(description="Triage comment r103", prompt="...", run_in_background=true)
Agent(description="Triage comment r104", prompt="...", run_in_background=true)
```

Collect results as notifications arrive. Update tasks accordingly.

## Background Agent Tracking (GH-854)

When launching a background agent via `run_in_background=true`,
the caller session MUST create a visible tracking task so the
supervisor knows work is ongoing:

```
TaskCreate(
    subject="PR #N monitor running (background)",
    description="Background agent monitoring CI. "
                "Output at {output_file}",
    activeForm="Monitoring PR #N")
TaskUpdate(taskId=..., status="in_progress")
```

Mark `completed` ONLY when the agent's completion notification
arrives — NOT on dispatch. Without this task, the session
appears idle and may be closed prematurely.

This pattern applies to ALL skills that launch background
agents, not just `gh-pr-monitor`.

## Background Friction Preamble (REQUIRED, GH-610)

Background subagents (workflow / monitor / loop / fanout) start
with a **fresh system prompt** — they never receive the
SessionStart "Session Guidance — Patterns & Anti-Patterns"
briefing. Without it they emit hook-tripping command shapes
(`cd && …`, `$(…)`, pipe chains, `git -C`) and bypass MCP
wrappers, then the harness offers the "switch to auto mode"
nudge (the GH-310 footgun).

**REQUIRED for every background dispatch:** prepend the canonical
friction-avoidance preamble to the subagent prompt, and pre-seed
its tool surface so the preferred tools are actually available.

1. Fetch the preamble text via
   `mcp__plugin_Dev10x_cli__background_preamble` (no Read prompt,
   single source of truth). The canonical document is
   [`background-preamble.md`](background-preamble.md).
2. Prepend the returned text verbatim to the subagent's prompt.
3. Ensure `allowed_tools` includes `Read`, `Grep`, `Glob`, the
   `cli` wrappers the work needs (`mktmp`, `push_safe`,
   `create_pr`, `ci_check_status`, …), and `Skill` only when the
   subagent is meant to delegate.

Recommend pre-seeding over disabling prompts: a narrow correct
tool surface beats blanket `bypassPermissions`. See
`background-preamble.md` § Pre-seed for the full contract and
the harness-owned coverage limits (`/loop`, built-in `Workflow`).

## Wave-Based Orchestration

When orchestrating multiple independent analysis phases, structure
work into logical waves with explicit task dependencies:

**Wave structure:**
1. **Setup (sequential)**: Create tasks, detect context, initialize state
2. **Wave 1 (parallel)**: Independent analysis phases with no inter-phase dependencies
3. **Wave 2 (parallel)**: Analysis phases dependent on Wave 1 output
4. **Synthesis (sequential)**: Consolidate findings, present decisions to user

**Task dependency annotation:**
```markdown
Set dependencies:
- Task 1→2→3: Sequential setup chain (prerequisite context)
- Task 4 and 5: Blocked by task 3 (Wave 1 — independent, run in parallel)
- Task 6, 7, 8: All blocked by task 4 (Wave 2 — run in parallel after Phase 1 output)
- Task 9: Blocked by tasks 4, 5, 6, 7, 8 (Synthesis — depends on all analysis)
```

**When to use wave-based orchestration:**
- Multiple independent analysis phases (e.g., 5+ parallel subagents)
- Partial dependencies between phases (some are independent, others depend on earlier outputs)
- Long-running workflows where parallelization saves significant time
- Example: `Dev10x:skill-audit` with 5 parallel analysis phases + dependency on Phase 1 output

## Fanout Execution (Multiple Items)

When executing a plan with multiple independent items (fanout), each item
MUST execute the **full orchestration pipeline** — not a collapsed subset.
Fanout does NOT exempt individual items from verification, grooming, or
review guardrails.

**Anti-pattern (PROHIBITED):**
```
for each issue:
  branch → edit → commit → push → create-pr   # 5 steps
```

This collapses the pipeline and skips:
- Verification (design review, implementation review)
- Grooming (commit message validation, fixup handling)
- Re-review (CI must run after grooming, pre-merge checks)

**Required pattern:**
```
for each issue:
  full play → branch → design → implement → verify →
  review → commit → groom → update → ready → verify-acc   # 12+ steps
```

**Why:** Evidence from audit session 05d49f11 showed that agents
rationalized pipeline collapse under fanout: "parallel processing
optimizes by reducing steps." This assumption was wrong. Each issue
requires independent verification and review. Parallel execution
(via Agent with `run_in_background=true`) is orthogonal to the
pipeline length — parallelizing execution does NOT justify skipping
steps.

**Phase reference pattern:**
Create a "Phase Reference" section in SKILL.md that documents each phase's
inputs, outputs, and instructions. This section can be pasted verbatim into
subagent prompts without modification:

```markdown
## Phase Reference

### Phase 1 (Output file: <PHASE1_OUTPUT>)
[Phase 1 instructions and acceptance criteria]

### Phase 2 (Output file: <PHASE2_OUTPUT>)
[Phase 2 instructions and acceptance criteria]

## Synthesis (Phase 6)
[Synthesis instructions]
Read all output files from phases 1-5 to synthesize findings.
```

Subagents receive only the relevant phase section, reducing prompt size and
improving focus.

**Cross-phase dependency handling:**
When a synthesis phase reads output from earlier phases, verify the dependency
list includes all upstream phase tasks. Example: If synthesis reads `<PHASE1_OUTPUT>`,
task 4 (Phase 1) must be in the synthesis task's `blockedBy` list.

## Agent Isolation Matrix (GH-36)

Native `Agent` isolation (`isolation: "worktree"`) and full
`Tools: *` access for `general-purpose` subagents superseded
the prior Permission-Aware Parallel Dispatch model. Background
agents now have Skill, Write, Edit, Bash, and MCP tools, and a
per-agent temp worktree with automatic cleanup.

| Task type | Dispatch | Why |
|-----------|----------|-----|
| Issue implementation, PR fixes, rebase, conflict resolution | `Agent(subagent_type="general-purpose", isolation="worktree", run_in_background=true, model="sonnet", mode="acceptEdits")` | Has Skill + Write + Edit; worktree isolates file changes; auto-cleanup if no changes |
| PR ready-to-merge (CI green, no comments) | `Agent(subagent_type="general-purpose", run_in_background=true, model="haiku")` | Read-only orchestration; no isolation needed |
| CI monitoring, status polling | `Agent(subagent_type="general-purpose", run_in_background=true, model="haiku")` | Read-only; cheaper without isolation |
| Investigation, research | `Agent(subagent_type="Explore"` or specialized agent`)` | Specialized agents with the right tool surface |

**Decision rule**: Default to `isolation="worktree"` for any
write-touching work item. Drop isolation only when the work
is provably read-only (monitoring, fetching, reviewing).

**Decision rule (legacy)**: The historic "write-requiring
tasks must run in the main session" constraint no longer
applies for the dispatch surface this rule targets. When
references to the old "Permission-Aware Dispatch table" appear
in skill docs, treat them as superseded by the Agent Isolation
Matrix above.

**Example**: `Dev10x:fanout` dispatches each non-conflicting
work item as a worktree-isolated `Agent` whose prompt invokes
`Skill(Dev10x:work-on)`, running the full lifecycle inside the
isolated worktree. Conflict-chain successors wait for upstream
items to merge, then dispatch in the next wave.

See `.claude/rules/essentials.md` "Permission & Tool Availability Limits"
for the complete constraint specification.
