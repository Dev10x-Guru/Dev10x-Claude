# Decision Gate: Remember the Phase-0 Preset (GH-855)

Fires **only** when `mcp__plugin_Dev10x_cli__preset_pin_status` returned
`pinned: false` — the first-pick condition. Substitute the `repo_name`
the status tool returned into the question text.

```
AskUserQuestion(questions=[{
    question: "Remember this preset for `<repo_name>`?",
    header: "Remember",
    options: [
        {label: "This repo + worktrees (Recommended)",
         description: "Covers the main checkout and every present or future worktree",
         preview: 'match: ["*/<stem>", "*/<stem>-*"]'},
        {label: "This repo only",
         description: "Main checkout alone; sibling worktrees keep asking",
         preview: 'match: ["*/<stem>"]'},
        {label: "This directory only",
         description: "Pins the literal path of this checkout",
         preview: 'match: ["/abs/path/to/checkout"]'},
        {label: "No, just this session",
         description: "Persist nothing; the gate fires again next session"}
    ],
    multiSelect: false
}])
```

On a *Yes*, call `pin_gate_preset` with the matching scope
(`repo` / `repo-only` / `dir`); on **No**, write nothing.
