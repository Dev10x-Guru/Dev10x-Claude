---
name: Dev10x:review
invocation-name: Dev10x:review
description: >
  Review your own branch changes before creating a PR. Reviews diff
  against base branch, runs automated checks, and produces structured
  findings with severity, file, line, and suggested fix. Works in
  attended (pick findings) or unattended (auto-advance to fixer) mode.
  TRIGGER when: reviewing own branch changes before PR creation, or
  self-reviewing code quality.
  DO NOT TRIGGER when: reviewing an external PR (use Dev10x:gh-pr-review),
  or no changes exist on the branch.
user-invocable: true
allowed-tools:
  - Bash(git log:*)
  - Bash(git diff:*)
  - Bash(git status:*)
  - Bash(git develop-log:*)
  - Bash(git develop-diff:*)
  - Bash(ruff check:*)
  - Bash(black --check:*)
  - Bash(mypy:*)
  - Bash(uv run:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Write(/tmp/Dev10x/review/**)
  - AskUserQuestion
---

# Self-Review Branch

Review current branch changes against the base branch, applying project
review guidelines. Produces structured findings that `Dev10x:review-fix`
can consume to create fixup commits.

## Arguments

- `--unattended` — skip finding approval, auto-advance to
  `Dev10x:review-fix` for all actionable findings
- No arguments — attended mode, present findings for user approval

## When to Use

- Before creating a PR (self-review catches issues early)
- As the "Code review" step in the `work-on` shipping pipeline
- When asked to review your own changes

**Not for remote PR review** — use `Dev10x:gh-pr-review` to post
findings to GitHub.

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Standard).

**Auto-advance:** Complete each step and immediately start the next.
Never pause between steps to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Verify branch state", activeForm="Checking branch")`
2. `TaskCreate(subject="Run spec compliance gate", activeForm="Checking spec compliance")`
3. `TaskCreate(subject="Run automated checks", activeForm="Running checks")`
4. `TaskCreate(subject="Review changed files", activeForm="Reviewing files")`
5. `TaskCreate(subject="Present findings", activeForm="Presenting findings")`

Set sequential dependencies.

**Nested-mode exemption:** When invoked as a nested skill within
a parent orchestrator (e.g., via `Skill()` from `Dev10x:work-on`),
startup task creation is optional — at most 1 summary task. The
parent provides progress visibility. See
`references/task-orchestration.md` § Delegated Invocation Exception.

## Workflow

### Step 1: Verify Branch State

1. Confirm inside a git repository
2. Detect base branch — use `git develop-log` alias to find commits
   ahead of develop. If alias fails, fall back to `origin/develop`
3. Verify branch has commits ahead of base (warn if nothing to review)
4. Check for uncommitted changes — warn but continue

### Step 1b: Phase 0 — Spec Compliance Gate (GH-69)

Before running automated checks or per-file review, dispatch the
`spec-reviewer` agent to confirm the diff matches its declared
specification. Domain-level review is wasted effort when scope is
wrong or acceptance criteria are unmet — surfacing that early
short-circuits the rest of the pipeline.

**Skip Phase 0 when:**
- The branch has no linked ticket and no Job Story (e.g., trivial
  typo fixes, plugin-maintenance commits)
- The diff is purely additive infra (e.g., a new agent spec file)
  where scope is self-evident
- The caller invoked `Dev10x:review` with `--skip-spec` (reserved
  flag for explicit opt-out)

**Pre-read inputs (controller side):** Read the linked ticket
body (via `mcp__plugin_Dev10x_cli__issue_get` or the appropriate
tracker MCP) and the PR Job Story if present, plus the full
`git develop-diff` output. Inline both into the dispatch prompt
under `<ticket>` and `<diff>` blocks — `spec-reviewer` will not
Read files dynamically (see `agents/spec-reviewer.md`).

**Dispatch:**

```
Agent(
    subagent_type="spec-reviewer",
    description="Spec compliance check for current branch",
    prompt="""Verify the following diff matches the linked ticket's
    acceptance criteria and Job Story.

    <ticket>
    {inlined ticket body + AC}
    </ticket>

    <job_story>
    {inlined Job Story from latest commit or PR body}
    </job_story>

    <diff>
    {inlined output of `git develop-diff`}
    </diff>

    Follow the checklist in your spec. Return one paragraph per
    finding (AC ref / file:line / verdict).

    Report your final status as the LAST line of your output,
    with exactly one of these prefixes:

    - DONE                       — PASS
    - DONE_WITH_CONCERNS: <text> — PARTIAL (proceed but flag)
    - NEEDS_CONTEXT: <what>      — re-dispatch needed
    - BLOCKED: <verdict>: <reason> — FAIL_SCOPE / FAIL_MISSING /
                                     FAIL_OVER

    Do not write anything after the status line.""")
```

**Parse the trailing status line** and branch:

- `DONE` → continue to Step 2 (automated checks)
- `DONE_WITH_CONCERNS: <text>` → continue, queue the concern for
  the final findings summary (severity WARNING, source `spec`)
- `NEEDS_CONTEXT: <what>` → re-dispatch with the requested
  additional inline context once
- `BLOCKED: <verdict>: <reason>` → short-circuit the review and
  call `AskUserQuestion` with options:
  - **Address spec gap first (Recommended)** — stop and let the
    user fix scope/missing AC before continuing
  - **Continue review anyway** — proceed to Step 2; record the
    verdict as an INFO finding

### Step 2: Get Branch Diff

```bash
git develop-diff
```

Parse the diff to extract the list of changed files with their
change types (added, modified, deleted, renamed).

### Step 3: Run Automated Checks

Run in parallel where possible:

1. **Lint**: `ruff check` on changed Python files
2. **Format**: `black --check` on changed Python files
3. **Types**: `mypy` on changed Python files (if configured)

Collect any failures as findings with severity `ERROR` and
source `automated`.

### Step 4: Review Each Changed File

For each changed file in the diff:

1. Read the full file (current version)
2. Review the diff hunks for this file
3. Apply review guidelines:
   - `references/review-checks-common.md` — false positive prevention
   - `.claude/agents/reviewer-*.md` — domain-specific checks based
     on file type (see `.claude/rules/INDEX.md` for routing)
4. For each issue found, create a structured finding

**False Positive Prevention Gate** (from `review-checks-common.md`):
Before recording any finding, verify:
1. Does this violate a documented rule? (No rule = preference, skip)
2. Does this contradict an established codebase pattern?
3. Is this a quality improvement or just preference?
4. Did the author already fix this in a later commit?

### Step 5: Compile Findings

Each finding is a structured object:

```
Finding:
  severity: ERROR | WARNING | INFO
  confidence: <0-100>
  source: automated | manual
  file: <path>
  line: <number>
  description: <what's wrong>
  suggested_fix: <code or guidance>
  category: <bug | security | architecture | style | test>
```

**Confidence scoring (GH-872):** Each finding includes a
`confidence` score (0-100) indicating how certain the reviewer
is that this is a genuine issue:

| Range | Meaning | Example |
|-------|---------|---------|
| 90-100 | Certain defect | Missing null check on user input |
| 70-89 | Likely issue | Broad exception catch in prod path |
| 50-69 | Possible issue | Style preference, debatable pattern |
| 0-49 | Low confidence | Nitpick, subjective suggestion |

**Threshold filtering:** In unattended mode, only findings with
`confidence >= 70` are passed to `Dev10x:review-fix`. Below-
threshold findings are reported as INFO in the summary but not
auto-fixed. In attended mode, all findings are presented
regardless of confidence.

The threshold is configurable via session config:
```yaml
# .claude/Dev10x/session.yaml
review_confidence_threshold: 70  # default
```

Write findings to a temp file for handoff:

```bash
/tmp/Dev10x/bin/mktmp.sh review findings .json
```

Write the findings array as JSON to the temp file path.

### Step 6: Present Findings

**Unattended mode** (`--unattended`):
- Skip presentation
- Filter findings by confidence threshold (default: 70).
  Only pass findings with `confidence >= threshold` AND
  severity `ERROR` or `WARNING` to `Dev10x:review-fix`
- Below-threshold findings are logged as INFO in summary
- Invoke: `Skill(skill="Dev10x:review-fix", args="<findings-file-path>")`
- Auto-advance after fixer completes

**Attended mode** (default):
- Present findings grouped by severity, then by file
- Show count: "Found N issues (X errors, Y warnings, Z info)"
- For each finding: severity, file:line, description, suggested fix

**When findings = 0:**

**REQUIRED: Call `AskUserQuestion`** even when no findings exist.
This confirms the clean review to the user and prevents silent
skip-through (GH-447 F5).

**Unattended mode exemption (GH-760 F6):** When invoked with
`--unattended` flag (e.g., from `Dev10x:work-on` shipping
pipeline), skip this gate and auto-advance. The parent
orchestrator already approved the work plan — pausing for
zero-findings confirmation adds friction without safety value.

**Attended mode** options:
- Continue (Recommended) — Proceed to next pipeline step
- Re-review — Run the review again with different scope

**When findings > 0:**

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- Fix all (Recommended) — Send all ERROR and WARNING findings to
  `Dev10x:review-fix`
- Pick findings — Review each finding and select which to fix
- Skip — No fixes, continue with pipeline

If "Pick findings": present each finding with fix/skip choice,
collect approved findings, then invoke `Dev10x:review-fix`.

If "Fix all" or after picking: invoke `Dev10x:review-fix` with
the findings file path.

### Step 7: Summary

Report:
- Total findings by severity
- Which were sent to fixer (if any)
- Any deferred findings (INFO severity or user-skipped)

## Findings Format (Handoff Protocol)

The JSON findings file is the contract between `Dev10x:review`
and `Dev10x:review-fix`:

```json
[
  {
    "severity": "WARNING",
    "confidence": 85,
    "source": "manual",
    "file": "src/auth/middleware.py",
    "line": 42,
    "description": "Missing type annotation on return value",
    "suggested_fix": "def validate(self, token: str) -> bool:",
    "category": "style"
  }
]
```

Both skills must agree on this format. The fixer reads the file
path passed as its argument.

## Integration

```
work-on shipping pipeline
└─ Dev10x:review          ← this skill (reviewer)
   └─ Dev10x:review-fix   ← fixer (consumes findings)
      └─ git commit fixup!  ← one fixup commit per finding
```

Complements:
- `Dev10x:gh-pr-review` — posts findings to GitHub (remote PRs)
- `Dev10x:gh-pr-respond` — responds to PR review comments
