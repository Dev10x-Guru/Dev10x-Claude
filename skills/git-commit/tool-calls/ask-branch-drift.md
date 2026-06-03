# Decision Gate: Branch Drift Detected

**Branch-exists variant** (use when `git rev-parse --verify <expected-branch>`
exits 0 — the expected branch exists):

```
AskUserQuestion(questions=[{
    question: "HEAD is on `<actual-branch>` but this session's plan expects ticket `<expected-ticket>` (last branched as `<expected-branch>`). Continue committing here, or switch back?",
    header: "Branch drift",
    options: [
        {label: "Switch back to expected branch",
         description: "git checkout <expected-branch>; abort this commit. Use when the drift was unintended (e.g., post-rebase HEAD reset)."},
        {label: "Continue on current branch",
         description: "Commit on `<actual-branch>` anyway. Use when the drift is intentional (e.g., you switched tasks mid-session)."},
        {label: "Abort",
         description: "Cancel commit without switching. Investigate manually."}
    ],
    multiSelect: false
}])
```

**Branch-gone variant** (use when `git rev-parse --verify <expected-branch>`
exits non-zero — the expected branch was deleted, e.g., after merge).
Replace the "Switch back" option with "Archive stale plan":

```
AskUserQuestion(questions=[{
    question: "HEAD is on `<actual-branch>` but this session's plan expects ticket `<expected-ticket>`. The expected branch `<expected-branch>` no longer exists (likely merged and deleted). Archive the stale plan and commit here?",
    header: "Branch drift — stale plan",
    options: [
        {label: "Archive stale plan (Recommended)",
         description: "Call plan_sync_archive() to clear the obsolete in_progress plan, then commit on `<actual-branch>`."},
        {label: "Continue on current branch",
         description: "Commit on `<actual-branch>` without archiving. Plan sync will remain in a stale state."},
        {label: "Abort",
         description: "Cancel commit without changes. Investigate manually."}
    ],
    multiSelect: false
}])
```

## When this gate fires

Fires when ALL of:
- Plan-sync context exists with a non-empty `tickets` list
- Current branch name does NOT contain any of the expected ticket IDs

Marked `ALWAYS_ASK` — fires at every friction level (including
`adaptive`). Auto-selecting either option silently masks the
drift the gate is designed to catch.

## Substitutions

- `<actual-branch>` — output of `git symbolic-ref --short HEAD`
- `<expected-ticket>` — first entry in `plan.context.tickets`
- `<expected-branch>` — best-effort reconstruction. Walk
  `git reflog --no-decorate -n 50` for the most recent
  `checkout: moving to <branch>` line whose target contains the
  expected ticket ID; fall back to `"<user>/<expected-ticket>/..."`
  if no reflog entry matches.

## Branch existence check (GH-462 F5)

Before presenting the gate, run:
```bash
git rev-parse --verify <expected-branch>
```

- Exit 0 → use the **branch-exists** variant above
- Non-zero → use the **branch-gone** variant above

This prevents offering "Switch back to expected branch" for a
branch that no longer exists, which would fail with
`error: pathspec did not match any file(s) known to git`.
