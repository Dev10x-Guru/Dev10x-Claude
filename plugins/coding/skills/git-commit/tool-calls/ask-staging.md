# Decision Gate: Staging Approval

```
AskUserQuestion(questions=[{
    question: "Stage these changes for commit?",
    header: "Staging",
    options: [
        {label: "Stage all (Recommended)",
         description: "git add -A"},
        {label: "Stage specific files",
         description: "I'll specify which files to include"},
        {label: "Abort",
         description: "Cancel commit"}
    ],
    multiSelect: false
}])
```
