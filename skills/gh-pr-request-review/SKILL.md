---
name: Dev10x:gh-pr-request-review
description: >
  Request review on a GitHub PR from teams or users.
  TRIGGER when: PR is ready for review and needs reviewer assignment.
  DO NOT TRIGGER when: PR is still draft or WIP, or review was already
  requested.
user-invocable: true
invocation-name: Dev10x:gh-pr-request-review
allowed-tools:
  - mcp__plugin_Dev10x_cli__request_review
  - mcp__plugin_Dev10x_cli__resolve_gate
  - mcp__plugin_Dev10x_cli__pr_detect
  - Bash(gh pr view:*)
  - Bash(gh pr ready:*)
  - Bash(gh api orgs/:*)
  - Bash(git remote get-url:*)
  - Bash(yq:*)
  - Bash(jq:*)
  - AskUserQuestion
  - Write(.claude/Dev10x/session.yaml)
---

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Request PR review", activeForm="Requesting review")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

Request reviews on GitHub pull requests from teams or individual users.
Auto-resolves reviewers from per-project config when available.

## Reviewer Resolution

The skill resolves reviewers in this order:

1. **Explicit argument** — if the user passes reviewer names, use those
2. **Config file** — read `<Dev10x config>/github-reviewers-config.yaml`
   and look up the current repo's project entry
3. **Ask the user** — if no config entry exists and `default_action: ask`

### Config file format

The config file is optional. If it does not exist or lacks an entry
for the current repo, the skill falls back to `default_action`
behavior (ask or skip).

```yaml
# <Dev10x config>/github-reviewers-config.yaml
default_action: ask  # "skip", "ask", or "standby" for unconfigured projects

projects:
  app-pos:
    reviewers:
      - example-org/backend-devs
  Dev10x-ai:
    skip: true
  my-solo-repo:
    standby: true  # defer review to supervisor self-review
```

- Keys are GitHub repo short names (last segment of `owner/repo`)
- `reviewers` list uses GitHub format: `org/team-slug` for teams,
  `username` for individual users
- `skip: true` suppresses the review request for that project permanently
- `standby: true` defers the review request for one-time deferral
  (supervisor self-reviews first); records `review-deferred` in
  `active_modes` so `verify-acc-dod` skips the "Review requested" check
- `default_action: ask` prompts the user for unconfigured projects;
  `skip` silently skips them; `standby` defers without prompting

## Gate Resolution (ADR-0016 D-9)

Before any pre-flight check, resolve whether this invocation should
request review at all. Use `resolve_gate` for this — do NOT read
`friction_level`, `active_modes`, or `walk_away` directly, and do NOT
re-derive preset behavior in prose. The tool reads session policy
(preset + overlays) itself.

1. Call `mcp__plugin_Dev10x_cli__resolve_gate(gate="request_review",
   context={})`.
2. `effect == "ask"` → **REQUIRED: Call `AskUserQuestion`** (the
   Stand-by widget below) before doing anything else.
3. `effect == "auto-advance"` → skip the widget entirely; proceed
   straight to the Pre-flight checks and Reviewer Resolution below;
   surface the returned `record` line to the transcript.
4. `effect == "skip"` → do NOT request review (solo-maintainer / no
   review posture). Print "Skipping review request (solo-maintainer)"
   and stop — do not run pre-flight checks or reviewer resolution.
5. `error` key present → fail safe: treat exactly like `effect ==
   "ask"` and fire the Stand-by widget.

### Stand-by widget (the "ask" branch)

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) with a
`Review` header. Options:

- **Request review now** — proceed to the Pre-flight checks and
  Reviewer Resolution below (the skill's normal action).
- **Stand-by — self-review first** — hold off requesting review; run
  a self-review pass (e.g. `Dev10x:review`) before requesting. On this
  choice: record `review-deferred` in `active_modes` per the Stand-by
  / Defer path below, return without requesting review, and hand
  control back to the caller to self-review — the caller re-enters
  this gate afterward.
- **Skip — no review needed** — suppresses this request only; does
  not modify config.

### Pre-flight: Approval State Check (GH-993, GH-128)

Before requesting review, verify the PR is not already approved
on its current HEAD **by a human reviewer**. Spamming reviewers
with redundant requests on already-approved PRs is the failure
mode this guard prevents — but bot approvals (e.g., `claude[bot]`,
automated CI workflows) MUST NOT short-circuit human review.

1. Fetch review state (no MCP wrapper exists for review-decision
   data — `gh pr view` is the supported call site):
   ```bash
   gh pr view {pr_number} --repo {repo} \
     --json reviewDecision,reviews,headRefOid
   ```
2. **Filter bot approvals first (GH-128).** Before matching reviews
   against `headRefOid`, drop any review whose `author.login` ends
   with `[bot]` (e.g., `claude[bot]`, `github-actions[bot]`) or
   whose `author.type == "Bot"` if that field is available. Bot
   approvals do not satisfy the "human review" requirement and
   MUST NOT trigger the short-circuit gate below. If the only
   approvals on the current HEAD are bot approvals, treat the PR
   as **unapproved by humans** and proceed normally to Step 4.
3. **If a HUMAN review with `state == "APPROVED"`** and matching
   `commit.oid == headRefOid` exists: the PR is approved on the
   current HEAD by a human. **REQUIRED: Call `AskUserQuestion`**
   (do NOT use plain text) with options:
   - **Skip — already approved (Recommended)** — short-circuit;
     suggest `Dev10x:gh-pr-merge` instead
   - **Force request anyway** — proceed (e.g., need additional
     reviewers beyond the existing approver)
   - **Cancel** — do nothing
4. **If any HUMAN `APPROVED` review exists** but newer commits
   invalidate the approval (latest human review `commit.oid` !=
   `headRefOid`): proceed to the re-request flow but **filter out**
   any human reviewer whose latest review on the current HEAD is
   `APPROVED`. Build the per-reviewer filter from `reviews[]`
   grouped by `author.login` (excluding bots), taking each author's
   most recent review.
5. **Otherwise** (only bot approvals, `CHANGES_REQUESTED`, or
   `null`): proceed normally. When only bot approvals exist on the
   current HEAD, optionally surface this in the user-facing log
   line ("PR has only a bot approval — requesting human review").

Skip this precheck when invoked with `--force` flag or when the
caller passes `bypass_approval_check: true` (e.g., from
`Dev10x:gh-pr-monitor` Phase 3 after fixup commits where the monitor
has already validated the state transition).

### Pre-flight: Draft State Check (GH-851 F7)

Before requesting review, verify the PR is not in draft state.
GitHub silently accepts review requests on draft PRs but does
NOT notify the requested reviewers — the request is lost.

1. Confirm PR identity via
   `mcp__plugin_Dev10x_cli__pr_detect(arg="<pr_number_or_url>")`
   to resolve `pr_number` and `repo`, then fetch the draft flag
   (no MCP wrapper exists for `isDraft`):
   ```bash
   gh pr view {pr_number} --repo {repo} --json isDraft -q .isDraft
   ```
2. If draft: run `gh pr ready` first, then proceed
3. If not draft: proceed to reviewer resolution

### Resolution workflow

1. Detect the current repo: parse `git remote get-url origin`
   (or call `mcp__plugin_Dev10x_cli__pr_detect` and use its
   returned `repo` field — last path segment is the repo name)
2. Read and parse the config file using `yq`:
   `yq '.projects["REPO_NAME"]' <Dev10x config>/github-reviewers-config.yaml`
3. Look up the repo name in `projects`:
   - **Found with `skip: true`** → print "Skipping review request
     for {repo}" and stop
   - **Found with `standby: true`** → defer (see Stand-by / Defer
     path below): record `review-deferred` in `active_modes` and stop
   - **Found with `reviewers` list** → use those reviewers
   - **Not found, `default_action: ask`** → **REQUIRED: Call
     `AskUserQuestion`** to ask the user who to request review
     from (do NOT use plain text). Gate options (presented as
     structured buttons):
     - **Reviewer names / teams** — one option per known collaborator
       (populate from `gh api repos/{repo}/collaborators` if desired)
     - **Stand by — defer (I'll self-review first)** — triggers the
       Stand-by / Defer path (see below); recommended when supervisor
       wants to eyeball the PR before pinging a teammate
     - **Skip — no review needed** — suppresses this request only;
       does not modify config
     - **Other** — free-text fallback for one-off team slugs
   - **Not found, `default_action: standby`** → defer without
     prompting (see Stand-by / Defer path below)
   - **Not found, `default_action: skip`** → print "No reviewers
     configured for {repo}, skipping" and stop
4. Call the `request_review` MCP tool with the resolved reviewers

### Stand-by / Defer path (GH-396)

When the supervisor wants to self-review before pinging a teammate,
the deferral path:

1. Print `"Review deferred for {repo} — self-review before requesting
   teammate review."`
2. Record `review-deferred` in `active_modes` by appending it to
   `.claude/Dev10x/session.yaml`:
   - Read the file, append `review-deferred` to the `active_modes`
     list if not already present, write back via the Write tool
3. Do NOT mark the PR as draft; leave it ready
4. Return cleanly so the calling orchestrator's completion gate does
   not treat the missing review request as a failure

`verify-acc-dod` will skip the "Review requested" / "Re-review
requested" check when `review-deferred` appears in `active_modes`
(the check's `modes.review-deferred.skip: true` clause handles this).

## Usage

### Auto-resolve from config (no arguments)

Invoke the skill without arguments. It reads the config, detects
the current repo, and requests review from the configured reviewers:

```
/Dev10x:gh-pr-request-review
```

### Explicit reviewers (override config)

Pass reviewer names directly to skip config lookup:

```
mcp__plugin_Dev10x_cli__request_review(
    pr_number=PR_NUMBER, reviewers=["org-name/team-slug"], team=true)
```

```
mcp__plugin_Dev10x_cli__request_review(
    pr_number=PR_NUMBER, reviewers=["user1", "user2"])
```

### With verification

```bash
gh pr view PR_NUMBER --json reviewRequests \
  --jq '.reviewRequests[].login // .reviewRequests[].name'
```

## Notes

- Use the `request_review` MCP tool for requesting reviews (handles
  both users and teams)
- Team format: `org-name/team-slug`
- Config awareness lives in the skill layer, not the MCP tool
- Verify the review request was assigned by checking `reviewRequests`

### Team review request 422 fallback

If team review request returns HTTP 422 (e.g., team not found,
team has no access to the repo, or org settings prevent team
reviews), fall back to requesting from individual team members:

1. List team members:
   `gh api orgs/{org}/teams/{slug}/members --jq '.[].login'`
2. Filter out the PR author
3. Request review from individual collaborators instead
4. Log the fallback: "Team request failed (422), falling back
   to individual reviewers: {list}"

This pattern was discovered in audit session GH-446 where the
team request consistently returned 422.
