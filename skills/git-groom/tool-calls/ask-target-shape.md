# Decision Gate: Target Shape (Full Restructure)

```
AskUserQuestion(questions=[{
    question: "Confirm the target shape for the rebuilt commit sequence (Full Restructure). Deselect any axis that does not apply to this branch.",
    header: "Target Shape",
    options: [
        {label: "Final location/structure (Recommended)",
         description: "No commit refactors code an earlier commit in this PR introduced — author each file in its final module path the first time"},
        {label: "One commit per layer, bottom-up (Recommended)",
         description: "Each architectural layer/component gets its own commit, ordered so every commit builds on the ones before it"},
        {label: "Tests ship with subject (Recommended)",
         description: "Tests and fakers land in the SAME commit as the production code they cover — never a separate 'add tests' commit"},
        {label: "Split on ticket/PR boundary (Recommended)",
         description: "Commit sequence maps 1:1 onto this PR's stated scope — no unrelated tickets or drive-by fixes folded in"},
        {label: "Extract repository/DAL layer",
         description: "If a service/orchestration class does direct data access, give the extracted repository/DAL its own bottom commit"}
    ],
    multiSelect: true
}])
```

Deselecting an axis means it does not apply to this particular
rebuild (e.g. there is no service class doing direct data access,
so axis 5 is a no-op) — it is not permission to violate an axis
that does apply. See
[`../references/target-shape-gate.md`](../references/target-shape-gate.md)
for the full rationale per axis and the named atomicity criterion.
