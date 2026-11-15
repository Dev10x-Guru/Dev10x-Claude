# Decision Gate: Message Preview Approval

```
AskUserQuestion(questions=[{
    question: "Commit with this message?",
    header: "Preview",
    options: [
        {label: "Commit (Recommended)",
         description: "Create the commit as shown"},
        {label: "Edit message",
         description: "I want to change the message"},
        {label: "Abort",
         description: "Cancel commit"}
    ],
    multiSelect: false
}])
```
