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
  - mcp__plugin_Dev10x_cli__supervisor_review_status
  - mcp__plugin_Dev10x_cli__pr_detect
  - mcp__plugin_Dev10x_cli__pr_labels
  - Bash(gh pr view:*)
  - Bash(gh pr ready:*)
  - Bash(gh api orgs/:*)
  - Bash(git remote get-url:*)
  - Bash(yq:*)
  - Bash(jq:*)
  - AskUserQuestion
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
- `standby: true` means the supervisor self-reviews before a teammate
  is pinged. It does NOT stop the skill: the Stand-by / Defer path
  below still runs and asks whether the supervisor has reviewed yet,
  so a reviewed PR can be cleared for merge or escalated to the team
  without re-arguing the override (GH-998). Persists nothing — for a
  standing "no humans review here" posture set durable
  `human_review: false` instead (ADR-0019)
- `default_action: ask` prompts the user for unconfigured projects;
  `skip` silently skips them; `standby` defers without prompting

## Gate Resolution (ADR-0016 D-9)

Before any pre-flight check, resolve whether this invocation should
request review at all. Use `resolve_gate` for this — do NOT read
`friction_level`, `active_modes`, or `walk_away` directly, and do NOT
re-derive preset behavior in prose. The tool reads session policy
(preset + overlays) itself.

0. **Durable posture pre-check (ADR-0019, renamed by ADR-0022 D-2).** Call
   `mcp__plugin_Dev10x_cli__supervisor_review_status()` and read
   `supervisor_review` from the response (default `required`; the
   deprecated boolean `human_review` rides along for one release, where
   `required` is `true`). Do NOT read
   `~/.config/Dev10x/friction.yaml` directly or re-derive its
   first-match-wins precedence in prose — same rule this section already
   applies to `resolve_gate`. When it is `false`, this project has no humans in
   the review loop: do NOT request review and do NOT resolve reviewers,
   but STILL run the **Pre-flight: Draft State Check** below (same
   reasoning as `effect == "skip"` in step 4 — a draft PR whose CI is
   suppressed would never become mergeable). Print "Skipping review
   request (human_review: false)" and stop. Otherwise continue to
   step 1.
1. Call `mcp__plugin_Dev10x_cli__resolve_gate(gate="request_review",
   context={})`.
2. `effect == "ask"` → **REQUIRED: Call `AskUserQuestion`** (the
   Stand-by widget below) before doing anything else.
3. `effect == "auto-advance"` → skip the widget entirely; proceed
   straight to the Pre-flight checks and Reviewer Resolution below;
   surface the returned `record` line to the transcript.
4. `effect == "skip"` → do NOT request review (solo-maintainer / no
   review posture), but STILL run the **Pre-flight: Draft State Check**
   below first (GH-854 F4): a draft PR whose CI is suppressed until it
   is marked ready would otherwise never run CI and never become
   mergeable. Flip draft→ready via `gh pr ready`, then print "Skipping
   review request (solo-maintainer)" and stop — skip only reviewer
   resolution, not the draft flip.
5. `error` key present → fail safe: treat exactly like `effect ==
   "ask"` and fire the Stand-by widget.

### Stand-by widget (the "ask" branch)

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) with a
`Review` header. Options:

- **Request review now** — proceed to the Pre-flight checks and
  Reviewer Resolution below (the skill's normal action).
- **Stand-by — self-review first** — hold off requesting review; run
  a self-review pass (e.g. `Dev10x:review`) before requesting. On this
  choice: follow the Stand-by / Defer path below (which persists
  nothing), return without requesting review, and hand control back to
  the caller to self-review — the caller re-enters this gate afterward.
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
   - **Found with `standby: true`** → run the Stand-by / Defer path
     below. It asks whether the supervisor has already reviewed; only
     the "not reviewed yet" answer stops here. Persist nothing.
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
   - **Not found, `default_action: standby`** → run the Stand-by /
     Defer path below (same clearance gate as the configured case)
   - **Not found, `default_action: skip`** → print "No reviewers
     configured for {repo}, skipping" and stop
4. Call the `request_review` MCP tool with the resolved reviewers

### Stand-by / Defer path (GH-396, ADR-0019, GH-998)

`standby` means "the supervisor reviews before a teammate is pinged"
— it does **not** mean "never request review". So this path does not
silently stop: it **still executes** and offers the supervisor the
exit. Deferring unconditionally was the GH-998 defect — the only way
out was to argue the override down again on the next PR, and the one
next PR after that.

**Read the durable clearance first (GH-1008).** Before firing the
gate, call:

```
mcp__plugin_Dev10x_cli__pr_labels(pr_number=<n>, action="list")
```

If `review:cleared` is in the returned `labels`, the supervisor already
cleared THIS PR in an earlier session. **Skip the gate entirely** —
print `"PR #{pr_number} already cleared (review:cleared) —
self-review recorded in a previous session."`, do not resolve
reviewers, and report the PR as cleared so the caller's completion
gate treats the review requirement as satisfied. Re-asking a question
the supervisor already answered is the friction this label exists to
remove.

Otherwise fire the gate.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). This
gate is `ALWAYS_ASK` — it fires at every friction level, because
auto-selecting either branch is exactly the silent deferral the gate
replaces. Question: `"{repo} is on stand-by: you self-review before a
teammate is pinged. Where is PR #{pr_number}?"` Options:

- **Stand by — I have not reviewed it yet (Recommended)** — the
  pre-GH-998 behavior. Print `"Review deferred for {repo} —
  self-review before requesting teammate review."` and stop. Write
  **no** label: nothing has been reviewed.
- **I reviewed it — OK to merge** — the supervisor's review IS the
  sign-off. Record the clearance (below), then do not resolve
  reviewers and do not request review; report the PR as cleared so
  the caller's completion gate treats the review requirement as
  satisfied rather than missing.
- **I reviewed it — request team review now** — clearance plus
  escalation. Record the clearance (below), then fall through to
  normal reviewer resolution (step 4 of the resolution workflow) and
  request review from the configured reviewers, ignoring `standby`
  for this PR.

**Record the clearance (GH-1008).** On either "I reviewed it" answer:

```
mcp__plugin_Dev10x_cli__pr_labels(pr_number=<n>, action="add",
                                  labels=["review:cleared"])
```

This is the durable half of the gate — it is what makes the read at
the top of this path able to skip. The call is idempotent, so a
re-clearance costs nothing.

Then, on every branch:

1. **Persist nothing about the *session*.** The clearance is a fact
   about the PR, carried by the PR's own label — not a session mode.
   Do NOT write `active_modes`, and in particular do NOT write
   `.claude/Dev10x/session.yaml` — ADR-0018 retired that file, and the
   durable read facade reaches it only in a repo with no
   `friction.yaml` entry, so in any configured repo the flag was
   written and never read (GH-950).
2. Do NOT mark the PR as draft; leave it ready.
3. Return cleanly so the calling orchestrator's completion gate does
   not treat the missing review request as a failure.

**Clearance dies when the head moves (GH-1008).** A review the
supervisor gave applies to the commits they read, so the label is
scoped to that head — not to the PR forever. Any force-push
(`Dev10x:git-groom`, a conflict rebase, an amend) rewrites what is
under review, and the push path removes `review:cleared` so the next
request-review invocation asks again. That is deliberate: silently
carrying a clearance across a rewrite would let unreviewed commits
inherit a sign-off. Ordinary added commits are treated the same way,
since the reviewed diff is no longer the current one.

**When to change the config instead.** Three "I reviewed it — OK to
merge" answers in a row on one repo means `standby` is describing the
wrong posture: that repo wants durable `supervisor_review: none`
(ADR-0022 D-2), not a per-PR clearance. Say so rather than letting the
gate fire forever.

**Standing posture vs one-off deferral (ADR-0022 D-2, superseding
ADR-0019).** Whether the supervisor reads a project's PRs is a
**durable project fact**, not a session flag. It lives as
`supervisor_review: required|none` in the matching `projects[]` entry
of the global `~/.config/Dev10x/friction.yaml`, read via
`mcp__plugin_Dev10x_cli__supervisor_review_status()` (default
`required`):

- `supervisor_review: none` → skip reviewer resolution and the review
  request entirely, and `verify-acc-dod` skips the unresolved-threads
  and review-requested checks. It is also a **precondition** for the
  agent merging once automated findings are resolved — never a grant:
  the git-tracked `merge: ask` pin and `allowed_overlays` remain
  independent vetoes.
- `supervisor_review: required` (default) → the supervisor reads the PR
  first. Where that park lands follows repo shape (ADR-0022 D-3):
  before `merge` in a solo repo, before `request_review` in a team one
  — where it **precedes** the team request rather than replacing it.
  The `review:cleared` label the two "I reviewed it" answers write is
  what lifts the park; `Dev10x:git-groom` removes it after a
  force-push, so the park comes back on rewritten history.

The deprecated `human_review: true|false` spelling is still read for
one release (`true` → `required`, `false` → `none`); an explicit
`supervisor_review` always wins over it.

The legacy `review-deferred` mode string is still **read** for
back-compat (a playbook `modes.review-deferred.skip` clause or an
existing `active_modes` entry keeps working), but nothing writes it.

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
