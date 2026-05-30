# Courtesy-Fixup Disposition

A disposition classification for mechanical, unambiguous review findings
that may be pushed as `fixup!` commits by the reviewer with author consent,
instead of posting inline comments.

## Criteria for Courtesy-Fixable Findings

A finding is courtesy-fixable only when **ALL** hold:

1. **Mechanical** — no design judgement; fix is unambiguous
2. **Small and localized** — fits in a diff hunk or two (≤ 15 lines across ≤ 3 files)
3. **Low risk of author disagreement** — pure cleanup or an already-enforced project convention
4. **Not already defended** — the author has not pushed back on this pattern in this PR or any prior review cycle

## Examples of Courtesy-Fixable Changes

- Removing self-evident or redundant inline comments
- Extracting an explaining variable to reduce nesting
- Deleting unused imports or dead code
- Trivial clarity renames mandated by project conventions

## Examples That Are NOT Courtesy-Fixable

- Any change involving architectural trade-offs
- Changes to public API contracts or data shapes
- Anything the author defended ("this is intentional")
- Large or cross-file refactors

## Reply Framing

After pushing a courtesy fix, reply in the thread:

> Fixed in [`{short_hash}`]({pr_commit_url}) · [permalink]({permalink})
> — {brief explanation}. Feel free to amend or drop.

The phrase **"feel free to amend or drop"** is required — the author
retains final say over every change pushed by a reviewer.

**Do NOT resolve the thread** after pushing. Leave it open for the
author to close once they have reviewed the fixup commit.
