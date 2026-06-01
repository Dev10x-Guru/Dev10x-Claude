# GitHub MCP Tool: Mock vs. Contract Test Boundary

This document defines the test contract classes for `tests/github/` and
explains why each class exists. New tool tests must declare which class
they belong to in their module docstring.

## Root cause (GH-329)

GH-329 shipped two runtime failures that passed CI green:

- `pr_get` requested the invalid `merged` field via `gh pr view --json`
- `resolve_review_thread` queried a non-existent field
  `PullRequestReviewComment.pullRequestReviewThread` in GraphQL

Both failures were invisible in CI because every test for these tools
patched `dev10x.github._gh_api_raw` with an `AsyncMock`. A mock returns
whatever shape the test author specifies, so an invalid field name or
selection passes green. The failures surfaced only in real sessions.

## Contract classes

### `mock`

Tests in this class patch the API boundary (`_gh_api_raw`, `async_run`,
`async_run_script`) and supply canned payloads. They verify:

- Business logic (field extraction, error handling, routing)
- Argument construction (endpoint URLs, HTTP methods, field names in
  request bodies)
- Return-value shapes (SuccessResult / ErrorResult, key presence)

**What they cannot catch:** invalid GraphQL field selections or invalid
`gh pr view --json` fields — the mock accepts any shape the test author
supplies.

Primary file: `tests/github/test_github.py`

### `static-lint`

Tests in this class operate on source files and shell scripts using
Python's `ast` module and `re`. No live API calls, no mock patching.
They validate:

- **Known-invalid field list** (`_KNOWN_INVALID_GRAPHQL_FIELDS`): any
  field documented as invalid via real-session failures is checked
  against all extracted GraphQL fragments. Adding a field here
  permanently prevents its reintroduction.
- **Structural query checks**: required fields present, mutation inputs
  correct (`threadId` not `commentId`, `subjectId` + `classifier`).
- **`gh pr view --json` field list**: all declared fields in
  `gh-pr-get.sh` are compared against `_KNOWN_VALID_GH_PR_VIEW_JSON_FIELDS`.

Primary file: `tests/github/test_graphql_static.py`

### `contract` (gated on `GITHUB_TOKEN`)

Tests in this class call the real GitHub API against a known fixture PR
and assert the returned shape (GH-398). They run:

- In CI on a weekly schedule (Monday 06:00 UTC) via
  `.github/workflows/github-contract-tests.yml`
- Locally when `GITHUB_TOKEN` is set (skipped otherwise)
- Never on every push/PR — too slow, requires a token

**Fixture:** PR #394 in `Dev10x-Guru/Dev10x-Claude` — a merged PR
(GH-386 Parts 2 & 3) that is stable, public, and has review comments.

**What they catch that static-lint cannot:** REST response-shape drift
(a field removed from or renamed in the real GitHub API response).

Primary file: `tests/github/test_github_contract.py`

## How to classify a new test

When adding a new test for a GitHub MCP tool:

1. **If you patch `_gh_api_raw`, `async_run`, or `async_run_script`**
   → `contract-class: mock`. Add it to `test_github.py` or a
   module-level `TestXxx` class with a `mock` contract note.

2. **If you parse source/script files and check field names or query
   structure without making network calls**
   → `contract-class: static-lint`. Add it to `test_graphql_static.py`.
   Update `_KNOWN_INVALID_GRAPHQL_FIELDS` if you found a newly-invalid
   field.

3. **If you call the real GitHub API**
   → `contract-class: contract`. Skip with
   `pytest.mark.skipif(not os.getenv("GITHUB_TOKEN"), ...)`.
   Add to `tests/github/test_github_contract.py`.

## Extending the static-lint tier

When a new real-session failure is found via GH-329-class bugs:

1. Add the invalid field/selection to `_KNOWN_INVALID_GRAPHQL_FIELDS`
   in `tests/github/test_graphql_static.py`.
2. Verify the new test fails on the broken code and passes on the fix.
3. If the failure is in a `gh pr view --json` field, add it to the
   comment in `_KNOWN_VALID_GH_PR_VIEW_JSON_FIELDS` with a note about
   which version of `gh` introduced or removed it.

## Known-invalid fields (GH-329 post-mortem)

| Field | Type | Reason |
|-------|------|--------|
| `merged` | `gh pr view --json` | Not a valid field; use `mergedAt` |
| `pullRequestReviewThread` | GraphQL on `PullRequestReviewComment` | Field does not exist in GitHub's schema; use `reviewThreads` on the parent PR |
