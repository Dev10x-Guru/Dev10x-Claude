# Decision Gate: Restructuring Strategy

```
AskUserQuestion(questions=[{
    question: "Which restructuring strategy for N commits?",
    header: "Strategy",
    options: [
        {label: "Fixup (Recommended)",
         description: "Small targeted fixes to specific commits",
         preview: "git commit --fixup=<sha>\nGIT_SEQUENCE_EDITOR=true git rebase -i --autosquash"},
        {label: "Full restructure",
         description: "Reset all commits, rebuild from scratch",
         preview: "git reset --soft <base>\ngit reset HEAD\ngit add -p"},
        {label: "Mass rewrite",
         description: "Non-interactive message rewrite from JSON",
         preview: "mass-rewrite.py --config rewrite.json"},
        {label: "Interactive rebase",
         description: "Full manual control over commit order"}
    ],
    multiSelect: false
}])
```

**The `(Recommended)` marker is computed from Phase 1 state, never
fixed** (`.claude/rules/skill-gates.md`). Exactly one option carries it,
and that option is listed first:

| Phase 1 found | Recommended (listed first) |
|---------------|----------------------------|
| Rename-first candidates (GH-1629) | Rename-first split |
| `fixup!` / `squash!` commits, no candidates | Fixup |
| Neither | Full restructure |

The block above shows the fixups-present order. When rename-first
candidates exist, put this option first, drop "(Recommended)" from
Fixup, and drop "Interactive rebase" to keep four options ("Other"
still reaches it):

```
        {label: "Rename-first split (Recommended)",
         description: "Pure rename commit first, then the edits — for file moves",
         preview: "exec git mv <old> <new> && git commit -F <rename-msg>\nexec git read-tree -u --reset <C> && git commit -C <C>"}
```
