# Decision Gate: Scope Approval

```
AskUserQuestion(questions=[{
    question: "Approve this scoping document?",
    header: "Scope Review",
    options: [
        {label: "Approve (Recommended)",
         description: "Save document and optionally update Linear"},
        {label: "Revise",
         description: "I have corrections to the scope"},
        {label: "More research needed",
         description: "Need to explore additional areas"},
        {label: "Run PoC",
         description: "Validate unverified architectural claims via a live proof-of-concept before approving"}
    ],
    multiSelect: false
}])
```
