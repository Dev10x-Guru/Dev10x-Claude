# Decision Gate: PR Preview

```
AskUserQuestion(questions=[{
    question: "Create PR with this title and body?",
    header: "PR Preview",
    options: [
        {label: "Create PR (Recommended)",
         description: "Push branch and create draft PR as shown"},
        {label: "Edit title/body",
         description: "I want to revise before creating"},
        {label: "Abort",
         description: "Cancel PR creation"}
    ],
    multiSelect: false
}])
```
