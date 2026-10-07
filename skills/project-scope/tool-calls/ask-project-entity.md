# Decision Gate: Project Entity Creation

When this gate fires is decided in `SKILL.md` § 3.3 — it is skipped
only for Linear with milestones (GH-1509).

```
AskUserQuestion(questions=[{
    question: "Create a project-level entity in the tracker?",
    header: "Project",
    options: [
        {label: "Create project entity (Recommended)",
         description: "Enables roadmap views and project tracking"},
        {label: "Skip",
         description: "No project entity; milestones (if any) and tickets only"}
    ],
    multiSelect: false
}])
```
