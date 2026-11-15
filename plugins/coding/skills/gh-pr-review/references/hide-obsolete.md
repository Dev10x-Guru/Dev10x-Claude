# Step 7: Hide Obsolete Review Summaries

**Skip Step 7 entirely on closed/merged PRs (GH-181 F7).** The
`minimizeComment` mutation only meaningfully affects the
reviewer's pane on open PRs; on merged PRs nobody reads it and
the call is a no-op. Closed/merged PR → jump straight to Step 8.

Before posting the new review on an **open** PR, minimize previous
Claude review summaries that are fully resolved (per
`review-guidelines.md` step 6):

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
