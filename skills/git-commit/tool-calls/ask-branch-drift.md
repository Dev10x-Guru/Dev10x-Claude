# Decision Gate: Branch Drift Detected

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
