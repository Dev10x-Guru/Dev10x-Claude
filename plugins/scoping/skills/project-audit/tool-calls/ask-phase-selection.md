# Decision Gate: Audit Phase Selection

```
AskUserQuestion(questions=[{
    question: "Which audit phases would you like to run?",
    header: "Audit Phases",
    options: [
        {label: "All phases (Recommended)",
         description: "Run all 9 audit phases for comprehensive coverage"},
        {label: "Domain focus (B, C, D)",
         description: "Domain Model Health + Value Objects + Archetypes"},
        {label: "Safety focus (E, G)",
         description: "Concurrency Audit + JTBD Coverage Matrix"},
        {label: "Pattern focus (A, F, H, I)",
         description: "Pattern Catalog + Behavioral Fit + Consistency + Cross-Context Queries"}
    ],
    multiSelect: false
}])
```

When "Other" is selected, parse comma-separated phase letters
(e.g., "B,C,E") and validate each against the phase table.
