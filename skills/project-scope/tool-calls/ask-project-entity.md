# Decision Gate: Project Entity Creation

When this gate fires is decided in `SKILL.md` § 3.3. It fires only
for JIRA and for Linear with no milestones planned. It never fires for
Linear with milestones, where the project is created without asking
(GH-1509), nor for GitHub Issues, which has no project entity to create
(GH-1513).

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
