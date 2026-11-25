# Base-Branch Red Override (GH-1891)

Check 2's path for a red CI leg that the base branch already carries.
The PR did not cause it, no fixup on the PR can clear it, and the
`ALWAYS_ASK` widget only freezes unattended sessions on a question
whose answer the project's merge posture already holds.

On 2026-11-09 three parallel afk sessions reached the "merge anyway"
widget with the same single red test, which failed the same way on
`develop`. None got an answer within 600 s; two held their PRs and
one merged. The maintainer then decided: a red leg proven identical
on the base branch is decided by the merge posture, with a recorded
override reason.

## When a leg qualifies

Run the comparison only after the code-failure auto-fix loop has
classified the failure as not caused by the PR, or has been
exhausted. Every failing leg must qualify. One red leg the base does
not carry sends the whole PR back to the `ALWAYS_ASK` widget.

A leg qualifies as `base_red` when it has ONE of these pieces of
evidence:

1. **Same check, same test, red at the base tip.** The base
   branch's latest completed run of the same workflow, for the
   base tip `git rev-parse origin/<base>`, failed on the same
   test ids or error lines as the PR's run.
2. **An open issue says so.** An open issue in the repo names the
   failing test, and says it fails on the base branch. Find it with
   `mcp__plugin_dev10x_cli__issue_list(state="open", search="<test id>")`.

"The same check is red on the base" is not enough on its own. Compare
the failing tests: a different test failing in the same job is a new
failure, and the PR may have caused it.

## Reading the base branch's runs

```bash
git fetch origin <base>
git rev-parse origin/<base>
gh run list --branch <base> --workflow <workflow> --limit 5 --json databaseId,headSha,conclusion,status
gh run view <run-id> --log-failed
```

Choose the run whose `headSha` equals the base tip and whose
`status` is `completed`. If no completed run exists for the base
tip, use the newest completed run on the base branch, and record
its SHA in the evidence. Get the PR's failing tests from the same
`gh run view <pr-run-id> --log-failed` output, so both sides are
compared at the same level of detail.

## Recording the evidence

Always record the evidence before resolving the gate, even when the
gate resolves to `ask`:

1. Record it in task metadata:
   `TaskUpdate(taskId, metadata={"merge_override_reason": "base_red: <tests> fail identically on <base>@<sha> (run <url> | issue #<n>)", "override_check": "<check-name>", "override_state": "base_red"})`.
2. Add it to the PR body as a `Merged past base-red:` line that
   names the check, the tests and the evidence link. Use
   `mcp__plugin_dev10x_cli__update_pr`. Then re-read the body with
   `pr_get`, because a write is a request, not a receipt.

## Resolving the gate

Call `mcp__plugin_dev10x_cli__resolve_gate(gate="merge",
context={"base_red": true})`:

| `effect` | Action |
|----------|--------|
| `auto-advance` | Check 2 passes as base-red. Surface the `record` line in the transcript and continue with the remaining checks. Step 5 resolves the merge gate again as usual. |
| `ask` | Fire the Check 2 `AskUserQuestion` widget. Name the base-red evidence in the question, and make **Merge anyway** the recommended option, because the evidence is already recorded. |
| `skip` | Do not merge. Hand the merge to a human, as Step 5 does. |
| `error` key | Fail safe: fire the widget. |

`base_red` never lifts a safety floor. A floor in `floors_applied`
(for example `supervisor_review`) resolves to `ask`, as it does for
every other merge.

Only the literal `true` counts as the fact. If `base_red` is omitted,
`false` or malformed, the gate resolves exactly as if the fact were
absent, so passing it wrongly never loosens the posture.
