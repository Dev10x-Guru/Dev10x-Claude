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
  - mcp__plugin_Dev10x_cli__pr_detect
  - Bash(gh repo view:*)
  - Bash(gh pr view:*)
  - Bash(gh pr ready:*)
  - Bash(gh api:*)
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
2. **Config file** — read `~/.claude/memory/Dev10x/github-reviewers-config.yaml`
   and look up the current repo's project entry
3. **Ask the user** — if no config entry exists and `default_action: ask`

### Config file format

The config file is optional. If it does not exist or lacks an entry
for the current repo, the skill falls back to `default_action`
behavior (ask or skip).

```yaml
# ~/.claude/memory/Dev10x/github-reviewers-config.yaml
default_action: ask  # "skip" or "ask" for unconfigured projects

projects:
  app-pos:
    reviewers:
      - example-org/backend-devs
  Dev10x-ai:
    skip: true
```

- Keys are GitHub repo short names (last segment of `owner/repo`)
- `reviewers` list uses GitHub format: `org/team-slug` for teams,
  `username` for individual users
- `skip: true` suppresses the review request for that project
- `default_action: ask` prompts the user for unconfigured projects;
  `skip` silently skips them

### Pre-flight: Approval State Check (GH-993)

Before requesting review, verify the PR is not already approved
on its current HEAD. Spamming reviewers with redundant requests
on already-approved PRs is the failure mode this guard prevents.

1. Fetch review state:
   ```bash
   gh pr view {pr_number} --repo {repo} \
     --json reviewDecision,reviews,headRefOid
   ```
2. **If `reviewDecision == "APPROVED"`** and the latest review's
   `commit.oid` matches `headRefOid`: the PR is approved on the
   current HEAD. **REQUIRED: Call `AskUserQuestion`** (do NOT use
   plain text) with options:
   - **Skip — already approved (Recommended)** — short-circuit;
     suggest `Dev10x:gh-pr-merge` instead
   - **Force request anyway** — proceed (e.g., need additional
     reviewers beyond the existing approver)
   - **Cancel** — do nothing
3. **If `reviewDecision == "APPROVED"`** but newer commits invalidate
   the approval (latest review `commit.oid` != `headRefOid`): proceed
   to the re-request flow but **filter out** any reviewer whose latest
   review on the current HEAD is `APPROVED`. Build the per-reviewer
   filter from `reviews[]` grouped by `author.login`, taking each
   author's most recent review.
4. **Otherwise** (`CHANGES_REQUESTED` or `null`): proceed normally.

Skip this precheck when invoked with `--force` flag or when the
caller passes `bypass_approval_check: true` (e.g., from
`Dev10x:gh-pr-monitor` Phase 3 after fixup commits where the monitor
has already validated the state transition).

### Pre-flight: Draft State Check (GH-851 F7)

Before requesting review, verify the PR is not in draft state.
GitHub silently accepts review requests on draft PRs but does
NOT notify the requested reviewers — the request is lost.

1. Check draft state via MCP: `mcp__plugin_Dev10x_cli__pr_detect`
   or `gh pr view --json isDraft --jq .isDraft`
2. If `isDraft == true`: run `gh pr ready` first, then proceed
3. If `isDraft == false`: proceed to reviewer resolution

### Resolution workflow

1. Detect the current repo: `gh repo view --json name --jq .name`
2. Read and parse the config file using `yq`:
   `yq '.projects["REPO_NAME"]' ~/.claude/memory/Dev10x/github-reviewers-config.yaml`
3. Look up the repo name in `projects`:
   - **Found with `skip: true`** → print "Skipping review request
     for {repo}" and stop
   - **Found with `reviewers` list** → use those reviewers
   - **Not found, `default_action: ask`** → **REQUIRED: Call
     `AskUserQuestion`** to ask the user who to request review
     from (do NOT use plain text)
   - **Not found, `default_action: skip`** → print "No reviewers
     configured for {repo}, skipping" and stop
4. Call the `request_review` MCP tool with the resolved reviewers

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
