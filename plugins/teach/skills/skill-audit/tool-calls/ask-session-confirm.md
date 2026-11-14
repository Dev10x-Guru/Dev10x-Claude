# Decision Gate: Confirm Auto-Resolved Session

```
AskUserQuestion(questions=[{
    question: "Is this the session you want to audit?\n\n"
              "Session: <session-id>\n"
              "Path: <resolved-path>\n"
              "Last modified: <mtime>",
    header: "Session",
    options: [
        {label: "Yes, audit this session (Recommended)",
         description: "Proceed with the resolved session file"},
        {label: "No, let me provide the path",
         description: "I'll specify the correct JSONL path"}
    ],
    multiSelect: false
}])
```
