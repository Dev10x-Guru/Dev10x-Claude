# Rendered by Dev10x:gh-review-setup. Stack-agnostic false-positive gate.
# Loaded by EVERY reviewer before drafting any comment. No project content.

# Common Review Checks — False-Positive Prevention

Apply this gate to every drafted comment. If a comment fails any check, do
not post it. Confident-but-wrong feedback erodes trust faster than a missed
nit.

## Pre-post gate

Before posting any inline comment, confirm:

1. **Rule-backed** — it violates a documented rule or an established
   codebase pattern. No rule + no pattern = preference → drop it.
2. **Verified in source** — you read the actual file, not just the diff
   hunk. The surrounding code does not already handle the concern.
3. **Not already fixed** — a later commit in the PR does not resolve it.
4. **In scope** — it touches a changed line, not pre-existing code.
5. **Not a formatter job** — a linter/formatter would not catch it
   automatically.
6. **Actionable** — you can state the concrete fix, not just "this seems
   off".

## Common false-positive traps

- Flagging a "missing" check that exists elsewhere in the call path.
- Assuming an import/symbol is unused without grepping for its uses.
- Flagging a pattern the codebase deliberately and consistently uses.
- Re-flagging something a previous review cycle already raised.
- Treating a diff hunk's truncated context as the whole function.
- Suggesting a "safer" rewrite that changes behavior the tests rely on.
- Flagging test-only constructs (fixtures, fakes) as production risks.

## When unsure

Prefer a question over an assertion. "Is X handled when Y?" beats "X is a
bug" when you have not verified the full path. Down-rank uncertain findings
to advisory rather than blocking.
