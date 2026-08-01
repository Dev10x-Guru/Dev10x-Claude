# Merge Check 1b: Limitations and Workarounds

Central reference for understanding `gh-pr-merge` Check 1b, why it works the way it does, and what actions actually clear it.

## What Check 1b Scans

`gh-pr-merge` Check 1b scans the **REST API `issue-comments` array** for unaddressed top-level bot findings. This surface includes:
- Top-level comments from CI checks (e.g., flaked tests, lint failures)
- Top-level comments from manual reviews
- Resolved status of review threads (via thread resolution, not comment minimization)

## What Check 1b Does NOT Scan

The REST `issue-comments` array has **no `isMinimized` field**. Therefore:
- Comment minimization is **invisible** to Check 1b
- Hidden threads are **invisible** to Check 1b
- The `minimizeComment` GraphQL mutation has **no effect** on this check

This is an API schema limitation, not a design choice. The mutation works for UI rendering, but the merge check cannot see it.

## Why This Matters (GH-920)

Users may assume that hiding/minimizing a comment "addresses" it and clears the check. This is incorrect:

| Action | Effect on Check 1b | Effect on UI |
|--------|-------------------|-------------|
| Minimize comment | ❌ No effect (REST field missing) | ✓ Hides on GitHub.com |
| Resolve review thread | ✓ Clears check | ✓ Marks as resolved |
| Post keyed `Re:` reply | ✓ Clears check | ✓ Shows reply |
| Hide comment only | ❌ No effect on check | ✓ Hides on GitHub.com |

## Clearing Check 1b: The Correct Pattern

**For threaded review comments:**
1. Resolve the thread (via thread resolution)
2. Optionally minimize the comment (cosmetic noise reduction, does not clear check)
3. Post a keyed `Re:` reply if required by the skill

**For top-level bot comments (GH-920):**
- Post a keyed `Re:` reply (only option; no thread to resolve)
- Minimization has no effect on the check
- Do NOT treat hiding as a disposition

## Related Issues

- **GH-920**: Documentation fix clarifying that minimization is cosmetic, not a disposition
- **GH-907**: Keyed reply pattern — the `Re:` prefix is the disposition that clears Check 1b

## Reference

- Scanning code: `top-level-comments.jq` (parses REST `issue-comments` array)
- Used by: `Dev10x:gh-pr-merge`, `Dev10x:gh-pr-respond` (Step 1c, Step 5b)
- See also: `references/config-resolution.md` § Playbooks (users customizing `gh-pr-respond` should understand this constraint)
