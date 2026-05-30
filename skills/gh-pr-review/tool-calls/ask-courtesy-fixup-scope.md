# Decision Gate: Courtesy-Fixup Scope

## Call Specification

Present the full batch of courtesy-fixable findings:

```
AskUserQuestion(questions=[{
  question: "Found N courtesy-fixable finding(s). Push them as
    fixup! commits?\n\n<findings_list>",
  header: "Courtesy fixups",
  options: [
    {
      label: "Push all (Recommended)",
      description: "Create and push fixup! commits for all listed
        findings, then reply in each thread linking the commit."
    },
    {
      label: "Pick individually",
      description: "Decide per-finding (asks N more questions)."
    },
    {
      label: "Skip — leave all for author",
      description: "Post all as inline comments only (current
        behavior)."
    }
  ],
  multiSelect: false
}])
```

The `<findings_list>` placeholder is a numbered markdown list:
`N. \`file.py:LINE\` — one-sentence description of the fix`.

## Per-Finding Mode

If the user selects "Pick individually", call `AskUserQuestion`
for each finding in `courtesy_fixes` with options:
- "Push fixup"
- "Leave as comment"

Move un-approved findings into `author_comments`.
