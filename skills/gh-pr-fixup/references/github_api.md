# GitHub Pull Request Comments API Reference

This document provides detailed information about the GitHub API endpoints
used for working with pull request review comments.

## Authentication

All API calls require authentication. Use the GitHub CLI (`gh`) which
handles authentication automatically:

```bash
gh auth status
gh auth login  # if not authenticated
```

## Shell Compatibility

GraphQL examples use `gh api graphql -f query=`. Fish shell
interpolates `$variable` inside both single and double quotes.
To avoid breakage:

- **Safest**: inline literal IDs in the query body:
  ```bash
  gh api graphql -f query="mutation { resolveReviewThread(input: { threadId: \"PRRT_abc123\" }) { ... } }"
  ```
- **If variables are needed**: double-quote with escaped `$`:
  ```bash
  gh api graphql -f query="mutation(\$threadId: ID!) { ... }" -f threadId="PRRT_..."
  ```

## API Endpoints

### List Pull Request Comments

**Endpoint**: `GET /repos/{owner}/{repo}/pulls/{pull_number}/comments`

Fetches all review comments for a pull request.

**Example**:
```bash
gh api repos/owner/repo/pulls/42/comments
```

**Response Structure**:
```json
[
  {
    "id": 2637416290,
    "node_id": "PRRC_kwDO...",
    "diff_hunk": "@@ -52,10 +57,60 @@ ...",
    "path": "src/app/service.py",
    "commit_id": "fe5d08f2a6181ae7b2f85d718917e2bc407dd76d",
    "original_commit_id": "fe5d08f2a6181ae7b2f85d718917e2bc407dd76d",
    "user": {
      "login": "claude[bot]",
      "id": 123456,
      "type": "Bot"
    },
    "body": "Comment text here",
    "created_at": "2025-12-21T10:30:00Z",
    "updated_at": "2025-12-21T10:30:00Z",
    "html_url": "https://github.com/owner/repo/pull/42#discussion_r2637416290",
    "pull_request_url": "https://api.github.com/repos/owner/repo/pulls/42",
    "line": 90,
    "original_line": 90,
    "side": "RIGHT",
    "in_reply_to_id": null,
    "pull_request_review_id": 3601669595
  }
]
```

**Key Fields**:
- `id`: Unique comment ID (use this for replies and updates)
- `body`: The comment text
- `path`: File path the comment is on
- `line`: Line number in the diff
- `in_reply_to_id`: Parent comment ID (null for root comments)
- `user.login`: Username of commenter
- `html_url`: Direct link to comment in GitHub UI

### Get Single Comment

**Endpoint**: `GET /repos/{owner}/{repo}/pulls/comments/{comment_id}`

Fetches a specific comment by ID.

**Example**:
```bash
gh api repos/owner/repo/pulls/comments/2637416290
```

### Create Comment Reply

**Endpoint**: `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies`

Posts a reply to an existing review comment.

**Preferred: MCP tool** (no Bash permission friction):
```
mcp__plugin_dev10x_cli__pr_comment_reply(
    pr_number=42,
    comment_id=2637416290,
    body="✅ Fixed - explanation here"
)
```

**Parameters**:
- `body` (required): The reply text (supports markdown)

**Fallback** (raw CLI — triggers Bash permission prompt):
```bash
gh api \
  --method POST \
  repos/owner/repo/pulls/42/comments/2637416290/replies \
  -f body="✅ Fixed - explanation here"
```

### Update Comment

**Endpoint**: `PATCH /repos/{owner}/{repo}/pulls/comments/{comment_id}`

Updates an existing comment (useful for fixing broken links or adding
information).

**Parameters**:
- `body` (required): The new comment text (replaces entire comment)

**Example**:
```bash
gh api \
  --method PATCH \
  repos/owner/repo/pulls/comments/2637416290 \
  -f body="Corrected response text here"
```

## Filtering and Querying

### Filter for Root Comments Only

To find only top-level review comments (excluding replies):

```bash
gh api repos/owner/repo/pulls/42/comments | jq '.[] | select(.in_reply_to_id == null)'
```

### Filter by Reviewer

To find comments from a specific user:

```bash
gh api repos/owner/repo/pulls/42/comments | jq '.[] | select(.user.login == "claude[bot]")'
```

### Group Comments by File

```bash
gh api repos/owner/repo/pulls/42/comments | jq 'group_by(.path)'
```

## Rate Limits

GitHub API has rate limits:
- **Authenticated requests**: 5,000 requests per hour
- **Unauthenticated requests**: 60 requests per hour

Check rate limit status:
```bash
gh api rate_limit
```

## Error Handling

### Common Errors

**404 Not Found**:
- Comment ID doesn't exist
- PR doesn't exist
- No permission to access repository

**422 Unprocessable Entity**:
- Invalid JSON in request body
- Missing required fields
- Body text exceeds maximum length

**403 Forbidden**:
- Rate limit exceeded
- No permission to comment on PR

### Error Response Format

```json
{
  "message": "Not Found",
  "documentation_url": "https://docs.github.com/rest/pulls/comments#get-a-review-comment-for-a-pull-request"
}
```

## Best Practices

1. **Always use the `gh` CLI**: It handles authentication and rate
   limiting automatically
2. **Filter for root comments**: Use `in_reply_to_id == null` to avoid
   responding to replies
3. **Verify after posting**: Fetch the comment again to confirm it was
   posted correctly
4. **Handle errors gracefully**: Check for 404/422/403 errors and retry
   if appropriate
5. **Batch API calls**: When posting multiple responses, make all API
   calls in parallel

## GitHub CLI Reference

### Basic Usage

```bash
# List comments
gh api repos/{owner}/{repo}/pulls/{pr}/comments

# Post reply (preferred: MCP tool)
# mcp__plugin_dev10x_cli__pr_comment_reply(pr_number=N, comment_id=ID, body="text")
# Fallback:
gh api --method POST repos/{owner}/{repo}/pulls/{pr}/comments/{id}/replies -f body="text"

# Update comment
gh api --method PATCH repos/{owner}/{repo}/pulls/comments/{id} -f body="text"
```

### JSON Processing with jq

```bash
# Extract comment IDs
gh api repos/owner/repo/pulls/42/comments | jq '.[].id'

# Extract body text
gh api repos/owner/repo/pulls/comments/123 | jq -r '.body'

# Filter and format
gh api repos/owner/repo/pulls/42/comments | jq '.[] | {id, user: .user.login, body}'
```

## Resolving Review Threads (GraphQL API)

GitHub's REST API does not support resolving review threads. Use the
GraphQL API instead.

### Step 1: Find the Thread ID

```bash
gh api graphql -f query="
query(\$owner: String!, \$repo: String!, \$pr: Int!) {
  repository(owner: \$owner, name: \$repo) {
    pullRequest(number: \$pr) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          comments(first: 1) {
            nodes {
              body
              path
              databaseId
            }
          }
        }
      }
    }
  }
}" -f owner='{owner}' -f repo='{repo}' -F pr='{pr_number}' \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[]
        | select(.comments.nodes[0].databaseId == {comment_id})'
```

### Step 2: Resolve the Thread

```bash
gh api graphql -f query="
mutation(\$threadId: ID!) {
  resolveReviewThread(input: { threadId: \$threadId }) {
    thread {
      id
      isResolved
    }
  }
}" -f threadId='{thread_id}'
```

### Combined: Find and Resolve by Comment ID

```bash
THREAD_ID=$(gh api graphql -f query="
query(\$owner: String!, \$repo: String!, \$pr: Int!) {
  repository(owner: \$owner, name: \$repo) {
    pullRequest(number: \$pr) {
      reviewThreads(first: 100) {
        nodes {
          id
          comments(first: 1) {
            nodes { databaseId }
          }
        }
      }
    }
  }
}" -f owner='{owner}' -f repo='{repo}' -F pr={pr_number} \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[]
        | select(.comments.nodes[0].databaseId == {comment_id})
        | .id')

gh api graphql -f query="
mutation(\$threadId: ID!) {
  resolveReviewThread(input: { threadId: \$threadId }) {
    thread { id isResolved }
  }
}" -f threadId="$THREAD_ID"
```

### Notes

- Thread resolution requires **write access** to the repository
- Only root comments have review threads — replies share the parent thread
- A resolved thread can be re-opened by the reviewer
- Use `isResolved` field to check current state before resolving

## Additional Resources

- [GitHub REST API - Pull Request Review Comments](https://docs.github.com/en/rest/pulls/comments)
- [GitHub GraphQL API - resolveReviewThread](https://docs.github.com/en/graphql/reference/mutations#resolvereviewthread)
- [GitHub CLI Manual](https://cli.github.com/manual/)
- [jq Manual](https://stedolan.github.io/jq/manual/)
