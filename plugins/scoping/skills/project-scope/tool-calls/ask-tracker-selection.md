# Decision Gate: Tracker Selection

```
AskUserQuestion(questions=[{
    question: "Which tracker should we use for this project?",
    header: "Tracker",
    options: [
        {label: "Linear (Recommended)",
         description: "Create Linear project with milestones"},
        {label: "JIRA",
         description: "Create JIRA epic with sub-tasks"},
        {label: "GitHub Issues",
         description: "Create milestones and issues via gh CLI"}
    ],
    multiSelect: false
}])
```
