# Decision Gate: Split Strategy

```
AskUserQuestion(questions=[{
    question: "Proposed split into N commits. Approve?",
    header: "Split Strategy",
    options: [
        {label: "Approve split plan (Recommended)",
         description: "Proceed with the proposed commit boundaries"},
        {label: "Adjust boundaries",
         description: "I want to change how the split is organized"},
        {label: "Abort",
         description: "Keep the original monolithic commit"}
    ],
    multiSelect: false
}])
```
