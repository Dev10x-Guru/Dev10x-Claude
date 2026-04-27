---
name: Dev10x:fanout-parallel
description: >
  EXPERIMENTAL — parallel fanout using worktree-isolated agents.
  Tests whether Write/Edit constraints from GH-549/PR #584 still
  apply. Creates one worktree per issue and dispatches background
  agents with mode: "dontAsk" + isolation: "worktree".
  TRIGGER when: user explicitly invokes for parallel testing.
  DO NOT TRIGGER when: production fanout work (use Dev10x:fanout).
user-invocable: true
invocation-name: Dev10x:fanout-parallel
allowed-tools:
  - AskUserQuestion
  - Agent
  - Skill(skill="Dev10x:work-on")
  - Skill(skill="Dev10x:gh-pr-monitor")
  - Skill(skill="Dev10x:git-groom")
  - Skill(skill="Dev10x:git-commit")
  - Skill(skill="Dev10x:gh-pr-create")
  - Skill(skill="Dev10x:ticket-branch")
  - Skill(skill="Dev10x:gh-pr-merge")
  - Skill(skill="Dev10x:session-wrap-up")
  - Write(~/.claude/Dev10x/**)
  - mcp__plugin_Dev10x_cli__*
  - Bash(gh pr view:*)
---

# Dev10x:fanout-parallel — Experimental Parallel Fanout

> **EXPERIMENTAL**: This skill tests whether worktree-isolated
> background agents can perform Write/Edit operations. The
> assumptions from PR #584 (GH-549, GH-555, GH-562) may no
> longer hold. Use this skill to validate and collect evidence.

**Announce:** "Using Dev10x:fanout-parallel to process [N]
work items with parallel worktree agents (EXPERIMENTAL)."

## Overview

This is a parallel variant of `Dev10x:fanout` that dispatches
implementation tasks to background agents with worktree
isolation, testing whether the Write/Edit permission
constraints documented in PR #584 still apply.

**Key difference from `Dev10x:fanout`:** Where fanout routes
all write-requiring tasks to the main session sequentially,
this skill dispatches them as parallel worktree-isolated
background agents with `mode: "dontAsk"`.

**What we're testing:**
1. Can `isolation: "worktree"` agents use Write/Edit tools?
2. Does `mode: "dontAsk"` enable file operations in subagents?
3. Can background agents invoke `Skill()` calls?
4. Do worktree agents have access to MCP tools?

## Orchestration

**REQUIRED: Create tasks before ANY work.** Execute at startup:

1. `TaskCreate(subject="Scan: discover work items", activeForm="Scanning")`
2. `TaskCreate(subject="Classify: dependency and conflict analysis", activeForm="Classifying")`
3. `TaskCreate(subject="Dispatch: launch parallel agents", activeForm="Dispatching")`
4. `TaskCreate(subject="Collect: gather results and evidence", activeForm="Collecting")`
5. `TaskCreate(subject="Report: summarize capability findings", activeForm="Reporting")`

## Phase 0: Session Friction Level

**Skip when:** Session config exists at `.claude/Dev10x/session.yaml`.

Otherwise, prompt via `AskUserQuestion` (ALWAYS_ASK):
- Guided (Recommended)
- Adaptive (AFK)
- Strict

Persist to `.claude/Dev10x/session.yaml`.

## Phase 1: Scan

Identical to `Dev10x:fanout` Phase 1. Accept space-separated
list of URLs, issue numbers, or PR numbers. Classify each:

| Pattern | Type |
|---------|------|
| `https://github.com/.../issues/N` | `github-issue` |
| `https://github.com/.../pull/N` | `github-pr` |
| `GH-N` | `github-issue` |
| `#N` | `github-pr` |

Fetch details via `mcp__plugin_Dev10x_cli__issue_get` or
`gh pr view`. Create one subtask per discovered item.

## Phase 2: Classify

Build conflict graph (same as `Dev10x:fanout` Phase 2):

1. For each pair, check file overlap
2. Conflicting items → sequential chain
3. Non-conflicting items → parallel group

Present execution plan showing parallel groups.

**Supervisor gate:**

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- Approve plan (Recommended) — Launch parallel agents
- Edit — Change grouping or ordering
- Sequential fallback — Use standard Dev10x:fanout instead

## Phase 3: Dispatch Parallel Agents

This is where the experiment happens. For each parallel group,
dispatch worktree-isolated background agents simultaneously.

### Dispatch Strategy

For each non-conflicting issue in a parallel group:

```
Agent(
    subagent_type="general-purpose",
    description="Implement GH-{N}: {title}",
    isolation="worktree",
    mode="dontAsk",
    run_in_background=true,
    prompt="""
    EXPERIMENTAL PARALLEL AGENT — Evidence Collection Required

    You are testing whether worktree-isolated agents can perform
    full implementation work. Your primary goal is implementing
    the issue, but you MUST also collect capability evidence.

    Issue: {issue_url}
    Title: {title}
    Description: {body_summary}

    ## Implementation Instructions

    1. Create a feature branch: git checkout -b {branch_name}
    2. Read the relevant code to understand the change needed
    3. Implement the fix/feature
    4. Run tests if applicable
    5. Commit changes with proper gitmoji format

    ## Capability Evidence (REQUIRED)

    After each operation, record whether it succeeded or failed.
    Return your results in this exact format at the end:

    CAPABILITY_REPORT:
    - Write tool: {SUCCESS|FAILED|NOT_ATTEMPTED} — {detail}
    - Edit tool: {SUCCESS|FAILED|NOT_ATTEMPTED} — {detail}
    - Skill() tool: {SUCCESS|FAILED|NOT_ATTEMPTED} — {detail}
    - MCP tools: {SUCCESS|FAILED|NOT_ATTEMPTED} — {detail}
    - Bash: {SUCCESS|FAILED|NOT_ATTEMPTED} — {detail}
    - Read: {SUCCESS|FAILED|NOT_ATTEMPTED} — {detail}
    - Glob/Grep: {SUCCESS|FAILED|NOT_ATTEMPTED} — {detail}
    - git operations: {SUCCESS|FAILED|NOT_ATTEMPTED} — {detail}
    - Branch created: {branch_name or NONE}
    - Commits made: {count}
    - Files changed: {count}
    - Worktree path: {path}

    If Write/Edit fails, attempt the Bash workaround:
      Bash: printf '%s' 'content' > file.py
    Record whether the workaround succeeded.

    ## Fallback Protocol

    If Write/Edit tools are blocked:
    1. Record the failure in the capability report
    2. Attempt Bash-based file creation as workaround
    3. If Bash also fails, record that and return findings only
    4. Do NOT hang or retry indefinitely
    """
)
```

**For sequential chains** (conflicting items), process in the
main session via `Skill(Dev10x:work-on)` — same as standard
fanout. The experiment only applies to parallel groups.

**For PRs ready to merge** (no code changes needed), dispatch
as background agents WITHOUT worktree isolation — same as
standard fanout.

### Create subtasks per dispatch

Before dispatching, create one subtask per agent:

```
TaskCreate(
    subject="Agent: GH-{N} — {title}",
    metadata={"type": "parallel-agent", "item": "GH-{N}",
              "dispatch_mode": "worktree-isolated"})
```

### Dispatch all parallel agents in one message

**REQUIRED:** Launch all agents in a single tool-call block
so they run concurrently. Do NOT dispatch sequentially.

## Phase 4: Collect Results

As each background agent completes, parse its result for:

1. **Implementation outcome** — did it successfully implement
   the change?
2. **Capability report** — extract the CAPABILITY_REPORT block
3. **Worktree state** — was the worktree cleaned up or does it
   contain changes?

For each agent result, update the subtask:
```
TaskUpdate(taskId, status="completed",
    metadata={"capability_report": {parsed_report},
              "implementation_success": true|false})
```

If an agent's worktree has uncommitted changes (implementation
failed mid-way), note the worktree path for manual recovery.

### Merge successful worktree branches

For agents that succeeded:
1. Check if the worktree branch has commits ahead of develop
2. If yes, the branch is ready for PR creation
3. Create PRs from the main session (agents can't do this)
4. Monitor CI via `Skill(Dev10x:gh-pr-monitor)`

## Phase 5: Report Findings

Synthesize all capability reports into a summary:

### Evidence Summary Table

```markdown
| Capability | Agent 1 | Agent 2 | Agent 3 | Conclusion |
|------------|---------|---------|---------|------------|
| Write      | ?       | ?       | ?       | ?          |
| Edit       | ?       | ?       | ?       | ?          |
| Skill()    | ?       | ?       | ?       | ?          |
| MCP tools  | ?       | ?       | ?       | ?          |
| Bash       | ?       | ?       | ?       | ?          |
| Read       | ?       | ?       | ?       | ?          |
| Glob/Grep  | ?       | ?       | ?       | ?          |
| git ops    | ?       | ?       | ?       | ?          |
```

### Conclusions

Based on evidence, determine:

1. **Can we re-enable parallel implementation?** If Write/Edit
   works in worktree agents with `mode: "dontAsk"`, the
   Permission-Aware Dispatch table in `task-orchestration.md`
   and `Dev10x:fanout` can be updated.

2. **Which workarounds are needed?** If Write/Edit fails but
   Bash file creation works, document the reliable workaround
   pattern.

3. **What hasn't changed?** If the constraints still hold,
   document that PR #584's assumptions remain valid with the
   current Claude Code version.

### Output

Present findings via `AskUserQuestion`:
- Update fanout (Recommended) — Apply findings to Dev10x:fanout
- File issue — Create GH issue documenting findings
- Done — Keep findings in this session only

## Known Limitations

- **This is experimental.** Results may vary across Claude Code
  versions. The capability landscape changes as Anthropic updates
  the CLI's permission model.
- **Worktree cleanup:** Failed agents may leave worktrees behind.
  Clean up manually with `git worktree remove <path>`.
- **No Skill() in subagents:** Even with `mode: "dontAsk"`,
  background agents likely cannot call `Skill()`. The experiment
  tests this explicitly.
- **MCP tool availability:** MCP tools may not be available in
  worktree-isolated agents. The experiment tests this explicitly.
