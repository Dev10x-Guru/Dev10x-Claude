# Dev10x:py-test-flaky — Instructions

**Announce:** "Using Dev10x:py-test-flaky to fix flaky test [name]."

## When to Use

- User reports: "flaky test X" or "test X is flaky"
- Test is marked with `@pytest.mark.flaky` decorator
- Test passes inconsistently in CI
- Test failures appear random or order-dependent
- Asked to "fix a flaky test"

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each step, immediately start the next — no checkpoints under adaptive friction.
Never pause between steps except at documented decision gates.

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Reproduce flakiness", activeForm="Reproducing")`
2. `TaskCreate(subject="Identify root cause", activeForm="Investigating")`
3. `TaskCreate(subject="Implement fix", activeForm="Implementing fix")`
4. `TaskCreate(subject="Verify with repeat runs", activeForm="Verifying")`
5. `TaskCreate(subject="File tech debt ticket", activeForm="Filing ticket")`
6. `TaskCreate(subject="Create branch", activeForm="Creating branch")`
7. `TaskCreate(subject="Commit fix", activeForm="Committing")`
8. `TaskCreate(subject="Create PR", activeForm="Creating PR")`

Mark each task `completed` as its step finishes; auto-advance to the
next.

## Workflow

### Step 1: Reproduce the Flakiness

Goal: produce the failure reliably so the fix can be validated.

1. Identify the target test from user input, a CI failure link, or
   a `@pytest.mark.flaky` marker.
2. Run the single test in a tight loop (start with 20 iterations):

   ```bash
   pytest path/to/test_file.py::TestClass::test_method --count=20
   # If pytest-repeat is unavailable:
   for i in $(seq 1 20); do pytest path/to/test_file.py::TestClass::test_method || break; done
   ```

3. If failures do not reproduce, broaden scope — run the full test
   class or module to surface order-dependencies, shared state, or
   randomized Faker values.
4. Record the failure signature (traceback, assertion message,
   random seed if printed) for the ticket description.

### Step 2: Identify Root Cause

Read the test and its collaborators. Common flakiness sources:

- **Randomized Faker values** that occasionally violate constraints
- **Shared DB / filesystem state** bleeding across tests
- **Time-sensitive assertions** (freezegun missing, sleep tolerances)
- **Non-deterministic iteration** over sets or unordered dicts
- **Async / thread race conditions** between fixture and SUT
- **Conditional branches** in tests that mask failures

Name the root cause in one sentence — it becomes the ticket title
and commit message.

### Step 3: Implement the Fix

Patch the root cause; do not mask it.

| Cause | Fix pattern |
|-------|-------------|
| Random value violates constraint | Constrain Faker: `faker.pyint(min_value=1, max_value=100)` |
| Conditional in test | Replace with `@pytest.mark.parametrize` |
| Shared state | Scope fixture to `function` or add explicit teardown |
| Time flake | Wrap in `freezegun.freeze_time`; avoid `sleep`-based waits |
| Order dependency | Remove global state; isolate DB/files per test |
| `@pytest.mark.flaky` as a hide | Remove the decorator after fixing the cause |

### Step 4: Verify the Fix

Run the test 20–30 consecutive times; confirm zero failures:

```bash
pytest path/to/test_file.py::TestClass::test_method --count=30
```

Then run the sibling class and module to catch regressions:

```bash
pytest path/to/test_file.py
```

If any run fails, return to Step 2 — do not proceed until the test
is stable.

### Step 5: File Tech Debt Ticket

Delegate to `Dev10x:ticket-create` with a structured description.
The skill routes to the configured tracker (GitHub Issues, Linear,
or JIRA) and returns the ticket ID.

`Skill(skill="Dev10x:ticket-create", args="<title> | <description>")`

Suggested title: `Fix flaky test: <TestClass>::<test_method>`

Description should include:
- Failure signature captured in Step 1
- Root cause from Step 2
- Fix summary from Step 3
- Verification evidence from Step 4 (N consecutive passes)

### Step 6: Create Branch

Delegate to `Dev10x:ticket-branch` with the ticket ID and title.

`Skill(skill="Dev10x:ticket-branch", args="<TICKET-ID> <title>")`

The skill handles worktree detection, latest-develop sync, and
branch naming per project convention
(`username/TICKET-ID/fix-flaky-<slug>`).

### Step 7: Commit the Fix

Delegate to `Dev10x:git-commit`. The skill enforces gitmoji, ticket
reference, 72-char limit, and JTBD-style outcome titles.

`Skill(skill="Dev10x:git-commit")`

Commit title example: `🐛 TICKET-123 Stabilize user-login assertion`

### Step 8: Create Pull Request

Delegate to `Dev10x:gh-pr-create`. The skill sources the Job Story
from the ticket, builds the PR description, and pushes safely.

`Skill(skill="Dev10x:gh-pr-create")`

Optionally follow with `Dev10x:gh-pr-monitor` to watch CI and apply
fixups if re-runs surface adjacent flakiness.

## Validation Checklist

Before marking the final task complete, verify:

- Test runs 20–30+ times consecutively without failure
- All tests in the same class pass
- Tracker ticket created with root cause, fix, and verification
- Branch follows `username/TICKET-ID/fix-flaky-<slug>` convention
- Commit message uses gitmoji + ticket ID + outcome-focused title
- PR created and linked to the ticket
- `@pytest.mark.flaky` decorator removed (if the fix replaces it)

## Integration with Other Skills

```
Dev10x:py-test-flaky
├── delegates to: Dev10x:ticket-create     (Step 5)
├── delegates to: Dev10x:ticket-branch     (Step 6)
├── delegates to: Dev10x:git-commit        (Step 7)
├── delegates to: Dev10x:gh-pr-create      (Step 8)
└── optionally:   Dev10x:gh-pr-monitor     (Step 8 follow-up)
```

## Important Notes

- Never add `@pytest.mark.flaky` as a fix — it hides the bug.
- Prefer deterministic seeds over retries for randomized data.
- Re-read the fix diff before Step 7 — flaky fixes can be one-line
  patches that touch wide fixture surface area.
- If the root cause is infrastructure (CI runner, external service),
  still file the ticket and commit the mitigation — then escalate
  separately via `Dev10x:park-todo` or a separate issue.
