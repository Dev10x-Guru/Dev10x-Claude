# Decision Gate: Confirm Target Tracker (GH-816)

Fired by Phase 7 sub-step B2, after origin detection and after the
user has agreed to file. Sub-step B asks **whether** to file; this
gate asks **where**, so a finding about a non-Dev10x plugin's skill
reaches that plugin's maintainer instead of the Dev10x tracker.

Skills from every installed plugin live under `~/.claude/plugins/`,
so the path alone does not identify the owner. Never infer the
destination from the fact that the audit ran inside a Dev10x
session.

## Building the options

Call `mcp__plugin_Dev10x_cli__resolve_plugin_origin` with the
absolute skill paths of the upstream-relevant findings. It returns:

- `targets[]` — one entry per distinct destination, each with
  `repo`, `issue_tracker`, `marketplace`, `plugin`, `version`, and
  the `skill_paths` that resolved to it
- `unresolved[]` — paths whose owning plugin or source repo could
  not be derived, each with a `reason`

Build one option per detected target (label = the `repo`), plus a
manual-entry option. Mark a single detected target as
`(Recommended)`. When two or more targets are detected, set
`multiSelect: true` so the user confirms each destination — one
`Dev10x:audit-file` delegation runs per confirmed repo.

## Call spec

```
AskUserQuestion(questions=[{
    question: "Detected N upstream finding(s) owned by these "
              "plugins. Which issue tracker(s) should receive them?\n\n"
              "- <repo>: <plugin> <version> (<k> finding(s))\n"
              "- ...\n"
              "Unresolved: <path> — <reason>",
    header: "Tracker",
    options: [
        {label: "<owner>/<repo> (Recommended)",
         description: "Detected owner of <k> finding(s): plugin "
                      "<plugin> <version> from marketplace <marketplace>",
         preview: "https://github.com/<owner>/<repo>/issues"},
        {label: "<other-owner>/<other-repo>",
         description: "Detected owner of <k> finding(s) ...",
         preview: "https://github.com/<other-owner>/<other-repo>/issues"},
        {label: "Enter a different repo",
         description: "Override the detected destination — I'll "
                      "supply owner/repo"},
        {label: "Skip — keep findings local",
         description: "File nothing upstream; findings stay in the "
                      "conversation and local notes"}
    ],
    multiSelect: <true when 2+ targets detected, else false>
}])
```

## Branching after the gate

| User choice | Next action |
|-------------|-------------|
| A detected repo | Delegate to `Dev10x:audit-file` with `--repo <owner>/<repo>` and only the findings whose `skill_paths` resolved to that repo. |
| Two or more detected repos | One `Dev10x:audit-file` delegation per repo, each with that repo's subset of findings. Never batch findings for repo A into repo B's issue. |
| Enter a different repo | Ask for `owner/repo` as free text, then delegate with that value. |
| Skip | Mark Phase 7 completed; file nothing. |

Findings listed under `unresolved[]` are **never** filed against a
guessed destination. Either the user assigns them a repo via
"Enter a different repo", or they are reported as unfiled in the
Phase 7 summary.
