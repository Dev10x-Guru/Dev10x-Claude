# Decision Gate: Which approved call to pre-approve

Fired only when two or three calls since the supervisor's previous
message prompted and then ran. With one candidate the gate is skipped;
with none the skill stops.

The newest candidate leads and is the only `(Recommended)` option.
That choice is computed from the conversation: the most recent prompt
is the one the supervisor just approved. "None of these" is always
last, so the supervisor can refuse every guess.

```
AskUserQuestion(questions=[{
    question: "Which approved call should be pre-approved everywhere?",
    header: "Approval",
    options: [
        {label: "<newest target> (Recommended)",
         description: "Most recent prompt you approved"},
        {label: "<older target>",
         description: "Approved earlier since your last message"},
        {label: "None of these",
         description: "Stop without granting anything"}
    ],
    multiSelect: false
}])
```

Truncate a long Bash command in the label to about 60 characters, and
put the full command in the description, so the supervisor can tell
two similar calls apart.
