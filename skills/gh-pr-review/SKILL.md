---
name: Dev10x:gh-pr-review
description: >
  Review a GitHub pull request and post findings with inline comments.
  Fetches PR diff, reads changed files, checks for interface impact,
  applies project review guidelines, and posts a COMMENT review to GitHub.
  TRIGGER when: reviewing an external PR and posting review comments.
  DO NOT TRIGGER when: reviewing own branch changes before PR creation
  (use Dev10x:review), or PR does not exist yet.
user-invocable: true
invocation-name: Dev10x:gh-pr-review
allowed-tools:
  - Bash(gh:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Write(/tmp/Dev10x/git/**)
---

# GitHub PR Review

Review a pull request on GitHub and post findings as a review with
inline comments.

## Arguments

Accepts one of:
- **PR URL**: `https://github.com/owner/repo/pull/NUMBER`
- **PR number**: `1293` (uses current repo)

## When to Use

- Reviewing someone else's PR
- Reviewing any PR where you want findings posted to GitHub
- When asked to "review PR #N" or given a PR URL

**Not for self-review** — use `Dev10x:review` to review your own
branch before creating a PR.

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Standard).

**Auto-advance:** Complete each step and immediately start the next.
Never pause between steps to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Fetch PR diff", activeForm="Fetching PR context")`
2. `TaskCreate(subject="Run spec compliance gate", activeForm="Checking spec compliance")`
3. `TaskCreate(subject="Review changes", activeForm="Reviewing changes")`
4. `TaskCreate(subject="Post findings", activeForm="Posting review")`

Set sequential dependencies: spec gate blocked by fetch, review
blocked by spec gate, post blocked by review.

No user decision gates — this skill runs fully automated once
invoked. All review decisions (what to flag, severity) are made by
applying `review-guidelines.md` and `review-checks-common.md`.

## Workflow

### Step 1: Parse PR Reference

Extract owner, repo, and PR number from the argument. If only a
number is given, use the current git remote origin.

### Step 2: Gather PR Context

Run in parallel:
1. `gh pr view {N} --json title,body,baseRefName,headRefName,
   state,author,labels,commits,files`
2. `gh pr diff {N}`
3. `gh pr view {N} --json comments` — existing bot/human comments
4. `gh api repos/{owner}/{repo}/pulls/{N}/reviews` — existing reviews
5. `gh api repos/{owner}/{repo}/pulls/{N}/comments` — inline comments

**Why all 5?** Avoids duplicating feedback from previous review cycles
(per `review-guidelines.md` — "NEVER repeat feedback from previous
review cycles").

### Step 2b: Phase 0 — Spec Compliance Gate (GH-69)

Before reading per-file context or drafting inline comments,
dispatch the `spec-reviewer` agent to confirm the PR diff matches
the linked ticket's acceptance criteria and the PR's Job Story.
Domain-level review (architecture, style, suggestions) is wasted
effort when scope is wrong or AC are unmet — surfacing that
early lets the reviewer post a single short-circuit comment
instead of a multi-page review against the wrong target.

**Skip Phase 0 when:**
- The PR has no linked ticket AND no Job Story
- The diff is purely additive infra (a new agent spec, a new
  reference doc) where scope is self-evident from the file path

**Pre-read inputs (controller side):** The diff and PR body are
already loaded in Step 2. Fetch the linked ticket body via the
appropriate tracker MCP (parse `Fixes: GH-N` / `TEAM-N` /
`JIRA-N` from the PR body or branch name) and inline it. Do
NOT instruct the agent to fetch the ticket itself — that
triggers permission prompts inside the subagent.

**Dispatch:**

```
Agent(
    subagent_type="spec-reviewer",
    description=f"Spec compliance check for PR #{N}",
    prompt="""Verify the following PR diff matches the linked
    ticket's acceptance criteria and Job Story.

    <ticket>
    {inlined ticket body + AC, or "NO_LINKED_TICKET" if none}
    </ticket>

    <pr_body>
    {inlined PR body — Job Story is the first paragraph}
    </pr_body>

    <diff>
    {inlined output of `gh pr diff N`}
    </diff>

    Follow the checklist in your spec. Return one paragraph per
    finding (AC ref / file:line / verdict).

    Report your final status as the LAST line of your output,
    with exactly one of these prefixes:

    - DONE                       — PASS
    - DONE_WITH_CONCERNS: <text> — PARTIAL (proceed but flag)
    - NEEDS_CONTEXT: <what>      — re-dispatch needed
    - BLOCKED: <verdict>: <reason> — FAIL_SCOPE / FAIL_MISSING /
                                     FAIL_OVER

    Do not write anything after the status line.""")
```

**Parse the trailing status line** and branch:

- `DONE` → continue to Step 3 (read changed files)
- `DONE_WITH_CONCERNS: <text>` → continue; record the concern as
  a top-of-summary note in the eventual review body
- `NEEDS_CONTEXT: <what>` → re-dispatch with the requested
  additional inline context once
- `BLOCKED: <verdict>: <reason>` → skip Steps 3–6, post a
  concise review whose body cites the verdict and asks the
  author to address the spec gap before quality review. Still
  hide obsolete summaries (Step 7) and post via Step 8.

### Step 3: Read Changed Files

For each file in the PR's file list, use the Read tool to read the
file at the current HEAD of the PR's base branch. Compare with the
diff to understand the full context.

**Important**: Read files from your local checkout. If the PR branch
is not checked out locally, the diff from Step 2 is sufficient for
review — do not checkout the branch.

### Step 4: Impact Analysis

For changed interfaces (renamed methods, changed signatures, modified
DTOs):
- Grep for all callers/consumers of the changed interface
- Verify the PR updates all call sites
- Flag any missed references

### Step 4b: Architecture Evaluation (GH-916)

**Independent of prior review comments.** Do NOT anchor on
whether surface bugs from previous cycles were fixed — evaluate
the PR's structural compliance from scratch.

Load project architecture rules:
- `CLAUDE.md` — coding style, patterns, SRP
- Project-specific `code-implementation.md` (if exists)
- `review-checks-common.md` § Architecture Checklist

Check each new or substantially modified file for:

| Signal | Violation | Severity |
|--------|-----------|----------|
| New endpoint/view with >50 lines | Missing service layer extraction | WARNING |
| View calling repository directly | Missing Service layer (View→Service→Repository) | WARNING |
| Inline dict with 4+ keys passed across boundaries | Missing DTO | INFO |
| Manual `request.data["field"]` parsing | Missing serializer/DTO validation | WARNING |
| Function/method >50 lines | SRP violation — extract | WARNING |

**Anti-pattern (anchoring bias):** When previous review comments
exist, the skill tends to check only whether those bugs were fixed
and declare the PR "solid". This step forces an independent
structural evaluation regardless of prior feedback.

### Step 5: Apply Review Guidelines

Load project review guidelines from `references/`:
- `review-guidelines.md` — workflow, threads, summaries
- `review-checks-common.md` — false positive prevention
- Domain-specific agents from `.claude/agents/` based on file types

Apply the **False Positive Prevention Gate** before drafting any
inline comment:
1. Does this violate a documented rule? (No rule = preference)
2. Does this contradict an established codebase pattern?
3. Quality improvement or just preference?

### Step 6: Draft Review

Compose:
- **Summary body**: High-level assessment, positives, cross-cutting
  concerns
- **Inline comments**: One per substantive issue, with file path and
  line number. Use GitHub suggestion syntax for committable fixes:
  ````
  ```suggestion
  fixed code here
  ```
  ````

### Step 7: Hide Obsolete Review Summaries

Before posting the new review, minimize previous Claude review
summaries that are fully resolved (per `review-guidelines.md` step 6):

1. Query review threads via GraphQL — check `isResolved` and group
   by `pullRequestReview.databaseId`
2. For each previous Claude review with a non-empty body:
   - ALL threads resolved → minimize with `OUTDATED` classifier
   - ANY thread unresolved → leave visible
   - No inline threads (summary-only) → minimize
3. Use `gh api graphql` with `minimizeComment` mutation:
   ```graphql
   mutation { minimizeComment(input: {
     subjectId: "<review_node_id>", classifier: OUTDATED
   }) { minimizedComment { isMinimized } } }
   ```

Skip this step on the first review (no previous summaries exist).

### Step 8: Post Review to GitHub

Use the Write tool to create the review JSON, then post via `gh api --input`:

1. Create a unique temp file:
```bash
/tmp/Dev10x/bin/mktmp.sh git pr-review .json
```

2. Write the review payload to the unique path:
```json
{
  "event": "COMMENT",
  "commit_id": "{HEAD_SHA}",
  "body": "## Review Summary\n\n...",
  "comments": [
    {
      "path": "src/file.py",
      "line": 42,
      "body": "Issue description\n\n```suggestion\nfix\n```"
    }
  ]
}
```

3. Post the review:
```bash
gh api repos/{owner}/{repo}/pulls/{N}/reviews \
  --method POST --input <unique-path>
```

> **Do not use `cat <<'JSON' | gh api --input -`** — the heredoc is
> blocked by `validate-bash-security.py`. Always Write to a file first.

**Rules**:
- Always use `"event": "COMMENT"` — never REQUEST_CHANGES or APPROVE
- Include `commit_id` from the PR's latest commit
- Inline comments must reference lines that exist in the PR diff

### Step 9: Report to User

Confirm what was posted:
- Link to the review on GitHub
- Count of inline comments
- Brief summary of findings

## Review Principles

From `review-guidelines.md` and `review-checks-common.md`:

- Focus on substance: bugs, security, architecture, performance
- Trust automated tools (Black, Ruff) for formatting
- Review only changed lines; pre-existing issues are out of scope
- Verify claims by reading actual code, not just diff context
- Check for fixes in later commits before flagging
- One summary per review cycle
- Positive validation is valuable — clean code deserves acknowledgment

## Integration

```
Dev10x:gh-pr-review
├─ Standalone review of any GitHub PR
└─ Posts findings directly to GitHub
```

Complements:
- `Dev10x:review` — self-review before PR creation (no GitHub posting)
- `Dev10x:gh-pr-respond` — respond to review comments on YOUR PR
- `Dev10x:gh-pr-triage` — validate a single review comment
