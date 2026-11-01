# Decision Gate: Test Failure Recovery

```
AskUserQuestion(questions=[{
    question: "Playwright tests failed. How to proceed?",
    header: "Test Failure Recovery",
    options: [
        {label: "Fix and retry (Recommended)",
         description: "Adjust the test script and re-run"},
        {label: "Skip failing test case",
         description: "Mark as skipped, continue with passing tests"},
        {label: "Abort",
         description: "Stop QA execution entirely"}
    ],
    multiSelect: false
}])
```
