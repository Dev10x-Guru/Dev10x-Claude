# Mandatory Task Tracking

**Every skill MUST use TaskCreate** — even single-step skills.
The task list is the supervisor's interface for tracking,
expanding, and coordinating work across skills and agents.

A skill with one step creates one task. The supervisor can then
split it into two, add follow-up tasks, or let other skills
contribute tasks to the same plan. Without TaskCreate, the
skill becomes invisible to the orchestration layer.

```
# Even a simple skill like git-alias-setup:
TaskCreate(subject="Configure git aliases",
    activeForm="Configuring git aliases")
# ... do work ...
TaskUpdate(taskId, status="completed")
```

## Delegated Invocation Exception (Nested-Mode Exemption)

When a skill is invoked as a subtask of a parent orchestrator (e.g.,
`Dev10x:work-on`), internal `TaskCreate` calls MAY be skipped or
reduced to at most **1 summary task**. The parent orchestrator owns
the task lifecycle and has already created tasks that track the child
skill's progress. Duplicate task trees add clutter without value.

**Detection:** A skill is running in nested mode when:
- It was invoked via the `Skill` tool from another skill's flow
- A parent task list already exists (check via `TaskList`)
- The skill received `--unattended` or similar delegation flags

**Behavior in nested mode:**
- Startup `TaskCreate` calls are OPTIONAL (at most 1 summary task)
- The parent orchestrator provides progress visibility
- Decision gates (AskUserQuestion) may be auto-resolved per the
  parent's unattended policy

When running as a top-level invocation (user types `/skill-name`),
`TaskCreate` is mandatory as documented above.

## Startup Gate (Full and Standard tiers)

Skills that list multiple `TaskCreate` calls in their
Orchestration section MUST execute all of them **before any
other work begins**. This is a blocking prerequisite, not
an illustration. If you find yourself reading files, calling
APIs, or analyzing data without having created the documented
tasks first, STOP and create them now.

When writing a skill's Orchestration section, use a numbered
list of `TaskCreate` calls (not a fenced code block). Code
blocks read as examples; numbered lists read as instructions.

## Complexity Tiers (guidance, not opt-out)

Tiers guide HOW MUCH orchestration a skill adds, not WHETHER
it participates. All tiers use TaskCreate + auto-advance.
Under `friction_level: adaptive`, auto-advance carries the
"no checkpoints" contract from `references/friction-levels.md`
across every tier — implicit "ready to proceed?" pauses are
forbidden in Full, Standard, and Minimal alike.

| Tier | When | Additional patterns | Example skills |
|------|------|---------------------|----------------|
| **Full** | 4+ phases, 10+ min, decisions | TaskCreate per phase, AskUserQuestion gates, subagent dispatch, batched decisions | work-on, git-groom, gh-pr-respond, scope, qa-self |
| **Standard** | 3-6 steps, some decisions | TaskCreate per major step, AskUserQuestion for key choices | git-commit, gh-pr-create, gh-pr-review |
| **Minimal** | 1-2 steps, no decisions | Single TaskCreate, auto-advance, no gates | git-alias-setup, gh-pr-bookmark, park-todo |
