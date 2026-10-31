# Decision Gate: Per-Gate Overrides (Gate 3)

Gate 3 asks whether any decision point should behave differently from
the adaptive baseline. The question states the effect, and every option
states what the agent will do differently.

## Step 1 — Resolve current values

Before asking, call `mcp__plugin_dev10x_cli__resolve_gate(gate=<toggle>)`
once per gate below and keep each `effect` (`ask` / `auto-advance` /
`skip`). Never read `friction.yaml` directly — the tool owns the
precedence. Put the values in the `preview` of the *Customize* option,
one line per gate, grouped as shown.

## Step 2 — Ask

```
AskUserQuestion(questions=[{
    question: "Should any decision point stop and ask you, or be skipped, instead of following the adaptive baseline?",
    header: "Gate overrides",
    options: [
        {label: "Keep baseline (Recommended)",
         description: "The agent continues through every decision point on its own, except safety floors and the review choice you made in Gate 1. Nothing extra is saved.",
         preview: "<same grouped list, current effective values>"},
        {label: "Customize gates",
         description: "You pick gates and set each to ask, auto-advance or skip. Saved for this repo and all its worktrees; re-run this skill to change it.",
         preview: "<grouped list below with current effective values>"}
    ],
    multiSelect: false
}])
```

## Gate groups (the 17 gates in `_ENUM_TOGGLES`)

Render each group as one line in the preview, `gate = current value`:

- **Planning** — `plan_approval`, `batch_layout`, `strategy_choice`,
  `artifact_preview`
- **Review / PR** — `triage_response`, `thread_resolution`,
  `comment_hide`, `yagni_routing`, `request_review`, `external_notify`
- **Merge / history** — `merge`, `history_rewrite`, `branch_cleanup`
- **Session** — `shipping_continuation`, `completion_signoff`,
  `workspace_choice`, `session_adoption`

## Step 3 — Only on *Customize gates*

Ask once per group which gates to change, then per chosen gate for
`ask` / `auto-advance` / `skip`. Collect each as
`--gate-override <toggle>=<value>`. Pass only values that differ from
the resolved current value.
