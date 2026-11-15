# Phase 2, 2.5 and 2.7: Review Comments, QA Scope, Re-review

## Phase 2: Review Comment Handling (orchestrator + thread-scan)

The supervisor handles comment response in-band, with full
reasoning context and the user available for `AskUserQuestion`
gates. Loop until no unaddressed comments remain.

1. Dispatch `haiku-thread-scan` (Micro-agent B) inline (not
   background — it's cheap and the supervisor needs the result
   before the next decision).

2. Parse the returned JSON. If all three arrays are empty, exit
   Phase 2 and proceed to Phase 2.5.

3. Invoke `Skill(dev10x:gh-pr-respond)` in batch mode with the PR
   URL — that skill runs in the supervisor session, has full
   reasoning + user gates, and handles validation, fixup commits,
   and reply posting:

   ```
   Skill("dev10x:gh-pr-respond", "{pr_url}")
   ```

   The supervisor's BLOCKED OPERATIONS list (Step 0) is preserved
   across this delegation — `gh-pr-respond` does not see it
   automatically, so if a thread asks for an operation that
   matches a directive (e.g., reviewer requests "squash these
   fixups now" when the dispatch prompt said `leave UNSQUASHED`),
   the supervisor refuses the action and explains to the reviewer
   via a reply.

4. After `gh-pr-respond` completes, fixups have been pushed. Re-run
   the Phase 0.5 readiness check first — a push can draft a ready PR
   (GH-1731), and a draft gets no CI. Re-dispatch `haiku-ci-poll` (Phase 1) until
   verdict is green again, then re-dispatch `haiku-thread-scan`
   in case more comments arrived during the cycle.

5. When `haiku-thread-scan` returns three empty arrays AND
   `haiku-ci-poll` returns `green` AND at least one approval
   exists (or no reviews yet) → Phase 2 complete.

### Counting Unaddressed Comments (Thread Resolution Awareness)

**CRITICAL (GH-464):** Do NOT count root PR comments as unaddressed
based solely on the REST API (`gh api .../pulls/.../comments`). The
REST API returns ALL root comments regardless of thread resolution
status. Use the GraphQL `reviewThreads` query to check `isResolved`:

```bash
gh api graphql -f query='
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          comments(first: 1) {
            nodes { databaseId path body author { login } }
          }
        }
      }
    }
  }
}' -f owner='{owner}' -f repo='{repo}' -F pr={pr_number} \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
        | select(.isResolved == false)
        | .comments.nodes[0]]'
```

Only threads where `isResolved == false` AND the author has not
replied count as unaddressed. Resolved threads are done — do not
report them as needing attention.

**Re-scan after a review submits (GH-904 F5a).** Do not treat the
first `haiku-thread-scan` result as the complete comment set. When
a human review transitions to submitted, or on any re-monitor pass,
re-scan ALL of that review's threads rather than only the ones
already triaged — GitHub commonly attaches new comments to the
submit event. Comments still in `PENDING` review state are
non-repliable (no stable ID yet) — flag them for the next pass
instead of dropping them.

### Exit condition for Phase 2 loop

Move to Phase 2.5 when ALL of these are true:
- All CI checks passing
- No unresolved review threads (use GraphQL `isResolved` check)
- No unaddressed body-only review findings (GH-564) — check
  review bodies for structured findings without corresponding
  top-level PR comment replies
- No unaddressed top-level automated review comments (GH-698)
  — check `issueComments` for severity markers from bot users
- Blocking bots at head (`references/bot-review-wait.md`)
- PR has at least one approval OR no reviews yet

## Phase 2.5: QA Scope Assessment (REQUIRES USER CONFIRMATION)

This phase runs ONCE when Phase 2 completes. It delegates to the
`dev10x:qa-scope` skill if available.

1. Invoke the dev10x:qa-scope skill:
   ```
   Skill(skill="dev10x:qa-scope", args="{pr_number}")
   ```

   The dev10x:qa-scope skill will:
   - Analyze the PR diff for QA risk (low/medium/high)
   - Check the project's e2e test directory for existing coverage
   - Present a QA assessment to the user via AskUserQuestion

2. Wait for the skill to complete before proceeding to Phase 3.

3. If dev10x:qa-scope determines the change is low-risk (config-only,
   test-only, docs-only), it will skip ticket creation automatically.

**Note:** This phase only runs once per PR monitor session. If already
executed, skip directly to Phase 3.

## Phase 2.7: Re-review Notification (REQUIRES USER CONFIRMATION)

This phase runs when Phase 2 addressed review comments (i.e., at least
one reviewer requested changes and those changes have been pushed). Skip
if Phase 2 found no comments to address.

**Trigger:** PR had CHANGES_REQUESTED reviews AND fixup commits were
created to address them.

### Step 1: Identify reviewers who requested changes

```bash
gh pr view {pr_number} --json reviews \
  --jq '.reviews[] | select(.state=="CHANGES_REQUESTED") | .author.login'
```

### Step 2: Compose and format each notification

For each reviewer who requested changes, compose:
```
@{reviewer} please take another look
```

Format this as a Slack message suitable for posting.

### Step 3: Resolve notification gate

Call `mcp__plugin_dev10x_cli__resolve_gate(gate="external_notify",
context={})` before posting.

1. `effect == "ask"` → Fire the EXISTING `AskUserQuestion` widget
   showing the exact message that will be posted. Options: "Post
   re-review notification" / "Skip".
2. `effect == "auto-advance"` → Proceed straight to Step 4 (post
   the notification) without prompting. Surface the returned
   `record` line in the transcript.
3. `effect == "skip"` → Do not post. Skip straight to Phase 3.
4. Response has an `error` key → fail safe: treat as `ask`.

In an unattended run (the test in Phase 3 Step 3a), the `ask`
branch posts nothing and fires no widget: treat it as `skip` and
report `Re-review notification: skipped — unattended run`.

### Step 4: Post the notification

If the gate resolved to post (user approved the `ask` widget, or
the gate auto-advanced), invoke the skill with the composed
message. The skill reads the project's Slack config and posts to
the configured channel.

Example invocation:
```
Skill(skill="dev10x:slack-review-request", args="--pr {pr_number} --repo {repo} --message '@{reviewer} please take another look'")
```

The dev10x:slack-review-request skill will:
- Resolve the project's configured channel from userspace config
- Post the message to that channel
- Report the result back to the agent
