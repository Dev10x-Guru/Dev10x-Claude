---
name: Dev10x:review-fix
invocation-name: Dev10x:review-fix
description: >
  Consume structured findings from Dev10x:review and create one
  standalone fixup! commit per finding via Dev10x:git-fixup.
  TRIGGER when: Dev10x:review has produced a findings JSON file that
  needs fixup commits.
  DO NOT TRIGGER when: no findings file exists, or addressing PR review
  comments from external reviewers (use Dev10x:gh-pr-fixup).
user-invocable: false
allowed-tools:
  - Bash(git log:*)
  - Bash(git add:*)
  - Bash(git develop-log:*)
  - Bash(ruff check:*)
  - Bash(black --check:*)
  - Bash(uv run:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Read(/tmp/Dev10x/review/**)
  - Write(/tmp/Dev10x/review/**)
  - Bash(git commit:*)
---

# Review Fix

Consume structured findings from `Dev10x:review` and create one
`fixup!` commit per finding using the standalone mode of
`Dev10x:git-fixup`.

## Arguments

- **findings file path** — path to the JSON findings file produced
  by `Dev10x:review` (e.g., `/tmp/Dev10x/review/findings-abc.json`)

## When to Use

- Called by `Dev10x:review` after findings are approved
- Part of the `work-on` shipping pipeline (review → fix cycle)
- Not intended for standalone invocation

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Standard).

**Auto-advance:** Complete each finding and immediately start the
next — no checkpoints under adaptive friction. Never pause
between findings.

**REQUIRED: Create tasks before ANY work.** Execute at startup:

1. `TaskCreate(subject="Process review findings", activeForm="Fixing findings")`

After reading findings, create one subtask per finding.

## Workflow

### Step 1: Load Findings

Read the JSON findings file from the path argument. Parse the
findings array. Filter to only `ERROR` and `WARNING` severity
(skip `INFO`). When a `confidence` field is present, also skip
findings below the configured threshold (default: 70).

Sort findings by file path to minimize context switches.

### Step 2: Process Each Finding

For each finding:

1. **Read the file** at the specified path and line
2. **Implement the fix** — apply the suggested fix or implement
   a better solution based on the description
3. **Validate the fix**:
   - Run `ruff check` on the changed file
   - Run `black --check` on the changed file
   - If the fix introduces new lint/format errors, fix those too
4. **Stage the changes**: `git add <file>`
5. **Create fixup commit** — find the original commit that
   introduced the finding's file and line using
   `git log --oneline -- <file>`, then create a fixup commit:

   Write the commit message to a temp file via `mktmp.sh`,
   then commit with `git commit -F <path>`.

   Commit message format:
   ```
   fixup! <original commit subject>

   Standalone fixup
   Review finding: <description>
   ```

   This uses the same `Standalone fixup` marker that
   `Dev10x:git-fixup` uses, so the pre-commit hook accepts it.

6. **Mark subtask completed**

### Step 3: Handle Failures

If a finding cannot be fixed (e.g., requires architectural change,
ambiguous fix, or fix breaks other code):

1. Log the finding as deferred
2. Continue to the next finding — do not block

### Step 4: Report Results

After processing all findings, report:

```
Review fix complete:
- Fixed: N findings (M fixup commits)
- Deferred: K findings
  - <file>:<line> — <reason>
```

## Finding Format (Input Contract)

Reads the same JSON format produced by `Dev10x:review`:

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

Required fields: `file`, `line`, `description`
Optional fields: `severity`, `confidence`, `source`,
`suggested_fix`, `category`

## Integration

```
Dev10x:review (produces findings JSON)
└─ Dev10x:review-fix (this skill)
   └─ git commit -F <msg-file> (one fixup! commit per finding)
```

After this skill completes, the calling pipeline typically
proceeds to commit, PR creation, or CI monitoring.

Uses the `Standalone fixup` marker in the commit body so the
pre-commit hook accepts fixup commits without a PR comment link.
