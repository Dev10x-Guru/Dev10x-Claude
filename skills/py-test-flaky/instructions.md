# Dev10x:py-test-flaky — Instructions

**Announce:** "Using Dev10x:py-test-flaky to investigate flaky test [name]."

## When to Use

- User reports: "flaky test X" or "test X is flaky"
- Test is marked with `@pytest.mark.flaky` decorator
- Test passes inconsistently in CI
- Test failures appear random or order-dependent
- Asked to "fix a flaky test"

## Shape

This skill is a **narrow investigator + ticket scoper**. It
produces a fully-scoped ticket whose description names the
failure signature, root cause, proposed patch (verbatim), and
verification plan. Delivery — branch, implementation, py-test
gate, self-review, PR creation, CI monitor, review-comment
triage, merge — runs through `Dev10x:work-on` once the ticket
exists.

**Invariants:**

- **Do NOT apply the fix to the working tree.** The proposed
  patch lives in the ticket description as a verbatim code
  block, not in tracked files. `Dev10x:work-on` re-applies
  it inside its own branched workspace.
- **Do NOT create a branch, commit, or PR inline.** Every
  delivery action delegates through `Dev10x:work-on`. The
  supervisor sees one coherent task list, not two stacked
  ones.
- **Order matters.** Ticket is created *before* hand-off,
  so the verification plan in the description drives the AC
  `Dev10x:work-on`'s py-test gate later enforces.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each step, immediately start the
next — no checkpoints under adaptive friction. Never pause
between steps except at documented decision gates.

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Reproduce flakiness", activeForm="Reproducing")`
2. `TaskCreate(subject="Identify root cause", activeForm="Investigating")`
3. `TaskCreate(subject="Draft proposed patch", activeForm="Drafting patch")`
4. `TaskCreate(subject="File ticket via Dev10x:ticket-create", activeForm="Filing ticket")`
5. `TaskCreate(subject="Hand off to Dev10x:work-on", activeForm="Handing off")`

Mark each task `completed` as its step finishes; auto-advance
to the next.

## Workflow

### Step 1: Reproduce the Flakiness

Goal: produce the failure reliably so the fix can be validated
later inside `Dev10x:work-on`.

1. Identify the target test from user input, a CI failure
   link, or a `@pytest.mark.flaky` marker.
2. Run the single test in a tight loop (start with 20
   iterations):

   ```bash
   pytest path/to/test_file.py::TestClass::test_method --count=20
   # If pytest-repeat is unavailable:
   for i in $(seq 1 20); do pytest path/to/test_file.py::TestClass::test_method || break; done
   ```

3. If failures do not reproduce, broaden scope — run the full
   test class or module to surface order-dependencies, shared
   state, or randomized Faker values.
4. Record the failure signature (traceback, assertion message,
   random seed if printed). It becomes part of the ticket
   description in Step 4.

### Step 2: Identify Root Cause

Read the test and its collaborators. Common flakiness sources:

- **Randomized Faker values** that occasionally violate
  constraints
- **Shared DB / filesystem state** bleeding across tests
- **Time-sensitive assertions** (freezegun missing, sleep
  tolerances)
- **Non-deterministic iteration** over sets or unordered dicts
- **Async / thread race conditions** between fixture and SUT
- **Conditional branches** in tests that mask failures

Name the root cause in one sentence — it becomes the ticket
title.

### Step 3: Draft the Proposed Patch

Compose the fix *without applying it to the working tree*.
The patch lives in the ticket description as a verbatim code
block, so `Dev10x:work-on`'s implementation step can apply it
inside its own branched workspace.

| Cause | Fix pattern |
|-------|-------------|
| Random value violates constraint | Constrain Faker: `faker.pyint(min_value=1, max_value=100)` |
| Conditional in test | Replace with `@pytest.mark.parametrize` |
| Shared state | Scope fixture to `function` or add explicit teardown |
| Time flake | Wrap in `freezegun.freeze_time`; avoid `sleep`-based waits |
| Order dependency | Remove global state; isolate DB/files per test |
| `@pytest.mark.flaky` as a hide | Remove the decorator after fixing the cause |

Capture the proposed patch as a unified diff or a before/after
code block. Keep it minimal — `Dev10x:work-on`'s self-review
will refine wording, but the structural change should be
ready to apply verbatim.

**Anti-patterns that MUST NOT appear in the proposed patch:**

- Adding `@pytest.mark.flaky` as the "fix" — it hides the bug.
- Replacing randomized data with broad `try/except` swallows.
- Increasing `sleep()` durations to paper over a race.

Prefer **deterministic seeds** over retries for randomized data.

### Step 4: File the Ticket

Delegate to `Dev10x:ticket-create` with a structured
description that becomes the spec `Dev10x:work-on` will scope
against. The skill routes to the configured tracker (GitHub
Issues, Linear, or JIRA) and returns the ticket ID.

`Skill(skill="Dev10x:ticket-create", args="<title> | <description>")`

**Suggested title:** `Fix flaky test: <TestClass>::<test_method>`

**Description structure** (each section is required):

```
## Failure signature

<traceback / assertion message / seed captured in Step 1>

## Root cause

<one-sentence root cause from Step 2>

## Proposed solution

<verbatim code block / unified diff from Step 3>

### Solution guidance (do NOT regress on these)

- Never add `@pytest.mark.flaky` as the fix — it hides the bug.
- Prefer deterministic seeds over retries for randomized data.
- Re-read the fix diff before committing — flaky fixes can be
  one-line patches that touch wide fixture surface area.
- If the root cause is infrastructure (CI runner, external
  service), still commit the mitigation here, then escalate
  separately via `Dev10x:park-todo` or a follow-up ticket.

## Verification plan

- Reproduce the failure with: `pytest <path>::<test> --count=20`
- Confirm fix with: `pytest <path>::<test> --count=30`
- Acceptance: 30 consecutive passes on the targeted test, plus
  zero regressions in the sibling class/module.

## Acceptance criteria

- [ ] `pytest <path>::<test> --count=30` passes 30/30
- [ ] `pytest <path>::<TestClass>` passes (no sibling regressions)
- [ ] `@pytest.mark.flaky` decorator removed (if it was the hide)
- [ ] Root cause documented in commit body
```

The structured `Acceptance criteria` block lets
`Dev10x:work-on`'s py-test gate parse the `--count=N` target
and enforce it as the AC line during verification.

### Step 5: Hand Off to Dev10x:work-on

Delegate the entire delivery pipeline to `Dev10x:work-on` so
branching, implementation, py-test gate, self-review, PR
creation, CI monitor, review-comment triage, request-review,
and merge all run through the project-standard flow. The
ticket created in Step 4 is the sole input.

`Skill(skill="Dev10x:work-on", args="<ticket-url-or-id>")`

This skill returns control once the hand-off is made. The
supervisor sees `Dev10x:work-on`'s task list from this point
forward; do not re-create a parallel task scaffold here.

## Validation Checklist

Before marking the hand-off task complete, verify:

- Failure reproduces reliably (Step 1)
- Root cause is named in one sentence (Step 2)
- Proposed patch is captured verbatim in the ticket
  description (Step 3) — NOT applied to the working tree
- Ticket exists with failure signature, root cause, proposed
  solution, verification plan, and a structured AC block
  (Step 4)
- `Dev10x:work-on` is invoked with the new ticket ID (Step 5)
- Working tree is clean — no files modified by this skill

## Integration with Other Skills

```
Dev10x:py-test-flaky (narrow investigator + scoper)
├── delegates to: Dev10x:ticket-create   (Step 4)
└── hands off to: Dev10x:work-on          (Step 5)
                  └── owns: branch → implement → py-test
                            → review → pr-create → monitor
                            → respond → request-review → merge
```

## Important Notes

- This skill does NOT modify tracked files. The proposed patch
  lives in the ticket description.
- This skill does NOT create branches, commits, or PRs. All
  delivery is delegated to `Dev10x:work-on`.
- Open question (resolved): the proposed patch is staged
  verbatim in the ticket description — the investigation
  already did the work; re-deriving it inside `Dev10x:work-on`
  wastes effort.
- The `--count=N` verification target is encoded in the
  structured `Acceptance criteria` block so `Dev10x:work-on`'s
  py-test gate can parse and enforce it.
