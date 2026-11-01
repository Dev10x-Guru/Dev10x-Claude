# Domain Dispatch — Step 4 of `dev10x:review` (GH-1741)

How `dev10x:review` turns a branch diff into one parallel subagent per
reviewer spec, then folds the reports back into its findings JSON.
Routing, dispatch and merge rules are shared with the CI review and
live in [`references/review-routing.md`](../../../references/review-routing.md);
this file covers only what is local: how files reach the subagent,
the prompt template, and the mapping into the handoff format.

## 1. Build the route map

Input: the changed-file list from Step 2 (`git diff --name-status
origin/<base>...HEAD`).

1. Read `.claude/rules/INDEX.md` § "File Patterns -> Agents". Match
   each changed file against every row (Rule 1 of the shared doc).
2. Resolve each agent name to a registered spec (Rule 2):
   `.claude/agents/<name>.md` → `subagent_type="<name>"`;
   otherwise `agents/<name>.md` under the plugin root →
   `subagent_type="dev10x:<name>"`; otherwise unregistered — keep the
   files for the orchestrator's own pass.
3. No INDEX.md in the repo → route by the plugin reviewers'
   `Triggers:` patterns instead (shared doc, Rule 2).
4. Split any agent with more than ~15 files into two groups by
   top-level directory.

The result is a list of `(subagent_type, files)` pairs plus the files
the orchestrator reviews itself.

## 2. Pre-read what each subagent needs

The controller reads, the subagent does not. A subagent that has to
Read its own inputs stalls on permission prompts it cannot answer
(`.claude/rules/model-selection.md` § Inline Context vs
Read-on-Demand). For each file in a group, collect:

- its diff hunks: `git diff origin/<base>...HEAD -- <path>`
- its full content at HEAD, via `Read`

A file over ~600 lines is inlined as diff hunks only, with a note that
the subagent may Read the cited ranges. Deleted files are not routed.

## 3. Dispatch — one message, all groups

Issue every `Agent` call in ONE message, in the foreground (no
`run_in_background`). Pass no `model:` — the spec's frontmatter sets
it.

**Wait for every report before merging.** CI runs with background
tasks disabled, so each call returns its report in the same message.
A local session may instead return a launch acknowledgement per call
and deliver each report later as a completion notification. Then:

1. Record which groups were launched.
2. Merge nothing until every launched group has delivered its
   report.
3. A group still running is pending, not failed — never re-dispatch
   it (§5 applies only to a report that arrived and is unusable).

```
Agent(
    subagent_type="<project spec name, or dev10x:<plugin spec name>>",
    description="<name> review of <N> files",
    prompt="""Review these changed files on branch <branch> against
    your spec's checklist. This is a pre-push self-review: there is
    no PR yet.

    Required reading: <the Required Reading list from the spec>.

    Report every issue you find, including ones you are uncertain
    about or consider low-severity. Do not filter for importance or
    confidence — the orchestrator verifies and ranks findings. For
    each finding include file:line, severity (CRITICAL / WARNING /
    INFO), confidence, and a one-sentence rationale.

    Review only the changed lines and what they break; issues in
    untouched code are out of scope. Do not edit files.

    End your report with exactly one status line: `DONE` when the
    review ran (with or without findings), or `BLOCKED: <reason>`
    when it could not. Write nothing after it.

    <file path="<path>" change="modified">
    <diff>
    {diff hunks}
    </diff>
    <content>
    {full file at HEAD}
    </content>
    </file>
    ...""")
```

The coverage-first paragraph is verbatim from the shared doc (Rule 4);
`tests/test_claude_ci_prompts.py` keeps the two in step.

## 4. Merge into findings

Apply the shared doc's Rule 5 (dedupe, false-positive gate, verify),
then map each surviving report item onto the unchanged handoff format
in SKILL.md § Findings Format:

| Subagent field | Finding field |
|----------------|---------------|
| severity CRITICAL | `"severity": "ERROR"` |
| severity WARNING / INFO | same value |
| confidence | `confidence` (0-100; default 60 when omitted) |
| file:line | `file`, `line` |
| rationale + suggested pattern | `description`, `suggested_fix` |
| the checklist item's domain | `category` (`bug`/`security`/`architecture`/`style`/`test`) |

Every domain finding gets `"source": "manual"`. Do not add fields:
`dev10x:review-fix` reads this file as-is. Name the reviewer at the
start of `description` (`[reviewer-security] …`) so the summary can
say who raised what.

Dedupe key is `(file, line)`. When two agents disagree, keep the
higher severity and the higher confidence, and join the two
descriptions.

## 5. Failure handling

| Situation | Action |
|-----------|--------|
| A delivered report is an error, is empty, or lacks its status line (`BLOCKED` counts as unusable) | Re-dispatch that one group once; then review its files yourself and say so in the summary |
| No changed file matches any row | Skip dispatch; review against `references/review-checks-common.md` yourself |
| The `Agent` tool is unavailable | Review inline, spec by spec, and record an INFO finding naming the degraded mode |

A failed dispatch is never a clean review. The summary always names
the agents dispatched, the files each covered, and any files reviewed
by the orchestrator instead.
