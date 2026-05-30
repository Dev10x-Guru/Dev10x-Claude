# Step 8: Post Review to GitHub — Transport Selection

Pick the transport based on the PR state and diff size detected
in Step 2 (GH-181 F3, F8).

| Condition | Transport |
|---|---|
| PR is OPEN AND diff fits in `gh pr diff` (≤ ~5,000 LOC, no 406) | A. `gh api .../pulls/{N}/reviews` with inline comments |
| PR is MERGED / CLOSED, OR `oversize_diff=true`, OR inline anchors infeasible | B. Bot top-level comment via `~/.claude/tools/gh-bot-comment.py` |

## A. Standard review payload (open PR, normal diff)

Use the Write tool to create the review JSON, then post via
`gh api --input`:

1. **MUST** create the unique temp path via the MCP tool — the
   shell `mktmp.sh` is a fallback for when the MCP server is
   unavailable. Reaching for the shell first is the regression
   GH-181 F8 closes:

   ```
   mcp__plugin_Dev10x_cli__mktmp(namespace="git", prefix="pr-review", ext=".json")
   ```

   Shell fallback (only when MCP unavailable):
   `/tmp/Dev10x/bin/mktmp.sh git pr-review .json`

2. Write the review payload to the returned path:

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

> **Do not use `cat <<'JSON' | gh api --input -`** — the heredoc
> is blocked by `validate-bash-security.py`. Always Write to a
> file first.

### `event` field and PENDING semantics (GH-319)

The `event` field controls whether the review is submitted
immediately or left as a draft visible only to you:

| `event` value | Result | Visible to others? |
|---|---|---|
| `"COMMENT"` | Submitted immediately as a comment | Yes |
| `"REQUEST_CHANGES"` | Submitted, blocks merge | Yes |
| `"APPROVE"` | Submitted, approves the PR | Yes |
| *(omitted entirely)* | `state: PENDING` — draft only | No (only you) |

**PENDING visibility:** When `event` is omitted, the GitHub API
returns `state: PENDING` and `submitted_at: null`. Only the
review author can see the draft until they submit it by visiting
the PR's "Files changed" tab and clicking "Finish your review",
or by calling `PUT .../reviews/{review_id}/events` with
`{"event": "COMMENT"}` (or another event value).

**Why prefer Draft-first for self-review handoff:** When the
reviewer is also the PR author — or when the invocation
explicitly says "leave as draft", "hold", "before submitting",
"do not submit", or "let me review/submit" — the intent is to
create the review payload on GitHub but let a human finalize it.
Omitting `event` achieves exactly this.

### Rules

- Default `event` is driven by the Step 8a decision gate (see
  SKILL.md Step 8a); do NOT hard-code `"COMMENT"` without first
  running the gate.
- `"APPROVE"` is blocked when the reviewer is the PR author —
  GitHub returns HTTP 422 for self-approval. Detect via
  `pr_detect` author field vs current user.
- `"REQUEST_CHANGES"` blocks merge; confirm explicitly with the
  user before selecting this event.
- Include `commit_id` from the PR's latest commit for all
  submitted events.
- Inline comments must reference lines that exist in the PR diff.

## B. Bot top-level comment (merged PR / oversize diff)

### Prerequisites

Transport B requires two user-provided resources outside this
plugin:

- `~/.claude/tools/gh-bot-comment.py` — user-installed script
  that posts comments under a GitHub App identity. Not bundled
  with Dev10x. Users wire it up alongside their own GitHub App
  credentials.
- `~/.claude/Dev10x/github-bot/github-app.yaml` — App identity
  config (App ID, private-key path, installation ID). Users
  create this file when setting up the bot. Step 1 below checks
  `enabled: true` before selecting Transport B.

If either is missing, Transport B falls back to Transport A even
for merged or oversize PRs. The fallback posts under the user's
own GitHub identity rather than the App's — document the chosen
identity in the eventual review summary.

The `pulls/{N}/reviews` endpoint requires every entry in
`comments[]` to anchor on a line that exists in the diff. On
merged PRs the diff is finalized and inline anchors still work,
but the bot-identity transport is preferred because it preserves
review attribution after merge. For oversize diffs, inline
anchors are unavailable (no diff fetched). In both cases,
restructure the review into a single top-level issue comment
posted as the GitHub App.

**Transport B bypasses the Step 8a draft gate** — bot comments
have no PENDING state. The review is always posted immediately
under the App identity.

### Steps

1. **Detect bot config:**
   `Read(file_path="~/.claude/Dev10x/github-bot/github-app.yaml")`.
   If `enabled: true`, proceed; otherwise fall back to transport
   A (best-effort with whatever inline anchors are available).

2. **Restructure the payload:** convert each `comments[]` entry
   into a quoted `file:line` block inside the body:

   ```markdown
   ## Review Summary

   <summary text>

   ### Findings

   **`src/file.py:42`** — Issue description

   ```suggestion
   fix
   ```

   **`src/other.py:101`** — …
   ```

3. **Create the body file** via the MCP tool (MUST, not shell):

   ```
   mcp__plugin_Dev10x_cli__mktmp(namespace="git", prefix="pr-review-body", ext=".md")
   ```

   Write the restructured body to the returned path.

4. **Post via the bot tool:**

   ```bash
   ~/.claude/tools/gh-bot-comment.py OWNER/REPO PR_NUMBER <body-path>
   ```

   This posts a top-level issue comment using the GitHub App
   identity configured in `github-app.yaml`. The bot transport
   does NOT support inline review threads — every finding must
   be in the body with explicit `path:line` references.

5. Report the resulting comment URL to the user in Step 9.
