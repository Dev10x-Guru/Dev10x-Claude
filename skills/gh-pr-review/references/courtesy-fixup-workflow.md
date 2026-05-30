# Courtesy-Fixup Workflow (Steps 5b–6b)

## Step 5b: Classification

After the False Positive Prevention Gate, classify each surviving
finding as one of two dispositions:

### Courtesy-Fixable Criteria

ALL of the following must hold:

- **Mechanical**: no design judgement required; the fix is
  unambiguous given existing conventions
- **Small and localized**: the change fits in a diff hunk or two
  (rough guide: ≤ 15 lines across ≤ 3 files)
- **Low risk of author disagreement**: purely cleanup or a
  convention the project already enforces. Examples: removing
  redundant/self-evident comments; extracting explaining variables
  to reduce excessive nesting; removing dead code or unused
  imports; trivial clarity renames already mandated by conventions
- **Not already pushed back on**: the author has not defended
  this pattern in a comment on this PR or a prior review cycle

### Leave for Author

Everything else: architectural choices, behavioral changes,
debatable trade-offs, contract-touching edits, large or
multi-file refactors, or anything the author has already
defended. This is the current default behavior.

### Building Classification Lists

Create two lists:
- `courtesy_fixes`: findings classified as courtesy-fixable
- `author_comments`: findings to post as inline comments

## Step 6b: Scope Gate

**Skip entirely when `courtesy_fixes` is empty** — no gate, no
action, proceed directly to Step 6.

**When `courtesy_fixes` is non-empty** (ALWAYS_ASK — fires at ALL
friction levels including `adaptive`): Pushing to another author's
branch is outward-facing and requires explicit reviewer consent
regardless of session mode.

### After User Approval

For each approved courtesy fix, invoke `Dev10x:gh-pr-fixup` to
implement the change, create the `fixup!` commit, push, and reply
in the thread. The reply MUST be framed as a courtesy — include
the phrase "feel free to amend or drop" so the author retains
final say.

**Do NOT auto-resolve the review thread** after pushing. Leave it
open for the author to review and close.

Move courtesy-fixed findings OUT of `author_comments` — do not
post them as inline comments too (that would duplicate the
feedback).
