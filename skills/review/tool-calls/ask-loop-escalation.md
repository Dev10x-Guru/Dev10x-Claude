# Decision Gate: Loop Round Cap (GH-1831)

Fires when round 4 of `dev10x:review --loop` — or any later round
reached through "Continue one more round" — is not clean. It fires
before that round's fixes, so the open defects are still unfixed.
Order the options so the one computed from the round ledger comes
first and carries `(Recommended)` — see
`references/loop-mode.md` § Escalation recommendation.

Each round from 2 to the current one found fewer defects than the
round before it (converging):

```
AskUserQuestion(questions=[{
    question: "Self-review round <R> is not clean: <N> defect(s) open (defects per round: <r1>, …, <rR>). The count is falling. How should the loop proceed?",
    header: "Review loop",
    options: [
        {label: "Continue one more round (Recommended)",
         description: "Fix the open defects and review the fixes in round <R+1> with fresh reviewers; this gate fires again if that round is not clean"},
        {label: "Ship with open defects listed",
         description: "Stop the loop without fixing; the open defects stay unfixed and are listed in the summary with the polish list"},
        {label: "Stop and hand back",
         description: "End the review here, leave the defects unfixed and return control to the supervisor"}
    ],
    multiSelect: false
}])
```

Any round from 2 to the current one found as many defects as the
round before, or more (churning):

```
AskUserQuestion(questions=[{
    question: "Self-review round <R> is not clean: <N> defect(s) open (defects per round: <r1>, …, <rR>). Fixes are not converging. How should the loop proceed?",
    header: "Review loop",
    options: [
        {label: "Stop and hand back (Recommended)",
         description: "End the review here, leave the defects unfixed and return control to the supervisor"},
        {label: "Continue one more round",
         description: "Fix the open defects and review the fixes in round <R+1> with fresh reviewers; this gate fires again if that round is not clean"},
        {label: "Ship with open defects listed",
         description: "Stop the loop without fixing; the open defects stay unfixed and are listed in the summary with the polish list"}
    ],
    multiSelect: false
}])
```

"Continue one more round" re-arms the gate after every further round
that is not clean — the cap moves by one round per answer, never to
unbounded. A clean round reached that way ends the loop and is
stamped as usual.
