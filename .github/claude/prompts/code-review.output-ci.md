STEP 5 — PRODUCE REVIEW OUTPUT:
Follow the review workflow from review-guidelines.md:
- Check existing review comments to avoid duplicates
  (`.claude-ci/pr-context/review-comments.json` and
  `review-threads.json`)
- Before writing a summary, search previous summaries
  (`.claude-ci/pr-context/reviews.json` and
  `issue-comments.json`) to determine the correct round number
  (highest existing round + 1)
- Use inline comments for specific issues
- The inline comment tool works and posts at once. Never call
  it to test it, and never post a placeholder: every call is a
  real finding on the PR. Tell subagents the same; they report
  findings to you and never post themselves
- Create ONE summary per review cycle: Write it with the Write
  tool to `review-summary-body.md` in the current directory,
  then run `gh pr review <PR> --comment --body-file review-summary-body.md`
- Positive validation when PR has no issues
- After author pushes fixes: acknowledge, focus on new issues only

Be constructive and helpful in your feedback.

STEP 6 — HIDE OBSOLETE REVIEW SUMMARIES:
Before posting the new summary, minimize previous Claude review
summaries where ALL associated review threads are resolved.
`.claude-ci/pr-context/review-threads.json` gives each thread's
`is_resolved` and the `review_id` of its comments, and
`reviews.json` gives each review's `node_id`. Hide a
fully-resolved summary with the `minimizeComment` mutation via
`gh api graphql`. Leave reviews with any unresolved threads
visible.

STEP 7 — CONVERT TO DRAFT IF ISSUES FOUND:
After completing the review, check the real inline-comment count
from the GitHub API — do NOT rely on your own recollection of
whether you called create_inline_comment, and do NOT use the
pre-fetched files, which predate this run:
  `gh api repos/<REPO>/pulls/<PR>/comments --jq length`
If the returned count is greater than 0, convert the PR to draft:
  `gh pr ready --undo <PR>`
This lets the author fix all issues without triggering re-reviews
on each fixup push. The author marks "Ready for review" when done.
If the count is 0 (no inline comments), do NOT convert to draft.
