# Decision Gate: Repositories Without a Main Session

Fires in global mode when a repository has worktree sessions but no live
Claude session in its main checkout. Exactly one option carries
`(Recommended)` and is listed first, computed from the sessions' states
(skill-gates.md GH-1404):

- any listed worktree session is `idle` or `done` → "Ask directly" leads;
- otherwise → "Skip" leads.

```
AskUserQuestion(questions=[{
    question: "No main-checkout session is running for <repo-a> (worktrees: <label> <state>, ...) and <repo-b> (...). How should this round reach them?",
    header: "No main",
    options: [
        {label: "Ask worktrees directly (Recommended)",
         description: "Send the worktree brief to each idle or done worktree session of these repositories this round only; busy ones are read, not prompted"},
        {label: "Skip and list them",
         description: "Prompt nobody in these repositories; list their sessions and states in the report"}
    ],
    multiSelect: false
}])
```

Swap the order and the `(Recommended)` marker when every listed session
is `working`, `blocked` or `unknown`.
