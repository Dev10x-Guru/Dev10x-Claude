# Decision Gate: Architecture Design Approval

```
AskUserQuestion(questions=[{
    question: "Architecture design complete. Proceed?",
    header: "Design",
    options: [
        {label: "Proceed to implementation plan (Recommended)",
         description: "Design looks good, create actionable steps"},
        {label: "Revise design",
         description: "I have corrections to the architecture"},
        {label: "More research needed",
         description: "Need to explore additional patterns"}
    ],
    multiSelect: false
}])
```
