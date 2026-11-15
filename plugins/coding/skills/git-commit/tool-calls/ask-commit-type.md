# Decision Gate: Commit Type Selection

```
AskUserQuestion(questions=[{
    question: "What type of change is this?",
    header: "Commit type",
    options: [
        {label: "Feature", description: "New functionality"},
        {label: "Fix", description: "Bug fix"},
        {label: "Refactor", description: "Code restructuring"},
        {label: "Test", description: "Adding or updating tests"}
    ],
    multiSelect: false
}])
```

Additional options beyond the 4-option limit are presented as
plain text in the skill workflow (Docs, Security, Performance,
UI, Config, Other).
