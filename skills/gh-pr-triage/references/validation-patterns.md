# Validation Patterns for PR Comment Triage

This reference catalogs common patterns where a PR review comment can be
validated against the codebase without making code changes.

## Pattern: Inherited Field

**Detection:** Reviewer claims a field, method, or property is missing from a
class.

**Investigation:**
1. Read the file at the commented line
2. Find the class definition
3. Check `class Foo(Base, Mixin):` — trace each parent
4. Read each parent class, check for the claimed missing member
5. If found in any ancestor → **INVALID**

**Evidence reply template:**
```
The `{member}` {field/method} is inherited from `{ParentClass}`
defined in `{file_path}:{line}`:

    class {ParentClass}:
        {member} = ...
```

## Pattern: Existing Convention

**Detection:** Reviewer suggests using pattern X instead of Y ("should use
`select_related` instead of `prefetch_related`", "use `NewType` not `str`").

**Investigation:**
1. Grep codebase for pattern X: `rg "pattern_x" --type py -c`
2. Grep codebase for pattern Y: `rg "pattern_y" --type py -c`
3. Compare occurrence counts
4. Check if Y is the established convention in this bounded context
5. If Y is dominant or matches local convention → **INVALID**
6. If X is clearly dominant → **VALID**
7. If close or context-dependent → **QUESTION** (explain both usages)

**Evidence reply template:**
```
The codebase uses `{pattern_y}` as the established convention in this
context ({count_y} occurrences vs {count_x} for `{pattern_x}`):

{file_1}: {usage}
{file_2}: {usage}
...
```

## Pattern: Already Present

**Detection:** Reviewer claims something is missing that actually exists —
type annotation, test, docstring, import, parameter.

**Investigation:**
1. Read the exact file + line range mentioned in the comment
2. Check surrounding context (may be on adjacent line)
3. If the claimed missing thing is present → **INVALID**

**Evidence reply template:**
```
The {thing} is already present at `{file_path}:{line}`:

    {code_snippet}
```

## Pattern: Established Sibling

**Detection:** Reviewer suggests changing a method signature, return type, or
pattern that has sibling implementations following the same convention.

**Investigation:**
1. Identify the interface/protocol/base class
2. Find all implementations (grep for class name or method name)
3. List each sibling's signature
4. If current code matches siblings → **INVALID**
5. If current code diverges from siblings → **VALID**

**Evidence reply template:**
```
The current signature matches the established pattern across
sibling implementations:

- `{Sibling1}.{method}({params}) -> {return}`  ({file_1})
- `{Sibling2}.{method}({params}) -> {return}`  ({file_2})
- `{Current}.{method}({params}) -> {return}`    ({file_3})  ← this PR
```

## Pattern: Previously Addressed

**Detection:** Same concern was already raised in another thread on this PR,
and was either addressed with a fixup commit or explained.

**Investigation:**
1. Fetch all PR threads
2. Search for similar keywords in other thread bodies
3. Check if those threads have fixup commit replies
4. If addressed → **INVALID** with link to the other thread

**Evidence reply template:**
```
This was addressed in {thread_url} with commit `{hash}`.
```

## Pattern: Out of Scope

**Detection:** Comment is valid but addresses something beyond the PR's scope
— pre-existing issue, future work, different bounded context.

**Signals:**
- "Also consider..." / "Might want to..."
- Suggestion touches files not modified in this PR
- Concern about pre-existing behavior, not new code
- Enhancement request beyond the ticket scope

**Investigation:**
1. Check if the concern relates to code changed in this PR
2. If it's about untouched code → **OUT_OF_SCOPE**
3. If it's a valid enhancement beyond ticket scope → **OUT_OF_SCOPE**

**Reply template:**
```
Out of scope for this PR. {optional: "Tracked in TICKET-ID" or
"Good idea for a follow-up."}
```

## Pattern: YAGNI / Scope-Drift Code (GH-297)

**Detection:** Comment correctly identifies a bug, gap, or hardening
need — but the commented code itself is speculative and does not
serve the PR's stated Job Story. Multiple such comments often cluster
on a single speculative feature riding on an unrelated PR (refactor,
bugfix, or unrelated feature).

**Signals:**
- PR title/JTBD describes outcome A (e.g., "Refactor storage shape"),
  but the commented code implements outcome B (e.g., a new
  denormalization feature)
- Several VALID-looking comments on this PR all target the same
  feature/module that the JTBD does not mention
- `git blame` shows the commented lines were added in this PR's diff
  rather than being pre-existing
- Reviewer language hints at scope ("why is this here?", "didn't
  expect this in a refactor", "is this part of the refactor?")

**Investigation:**
1. Read the PR's Job Story / title outcome (e.g., "Refactor X",
   "Fix Y") — store as the JTBD anchor
2. For the commented line, check whether it was added by this PR
   and whether it implements the JTBD outcome
3. Scan all PR threads (Pattern: Previously Addressed scan) for
   other comments on the same speculative code path
4. If the code is added-by-this-PR AND off-JTBD → **YAGNI**
5. Record the bundle of related YAGNI comment IDs so the caller
   can collapse them into one removal commit

**Reply template:**
```
Correct catch — {one-sentence acknowledgment of the bug}.

This code is out of scope for the PR's JTBD ({JTBD outcome phrase}).
The right fix is to remove {feature/module name} from this PR rather
than harden it. Will bundle with related thread(s) into a single
removal commit, or defer to a follow-up ticket if the feature is
desired.
```

**Anti-pattern to avoid:** Routing the comment as `VALID` and starting
to harden the out-of-scope code. The audit (GH-297) caught a session
where four YAGNI-class comments on one speculative feature were each
hardened individually before the reviewer manually intervened with
"remove this feature — out of scope." The investigation steps above
must run *before* the verdict is rendered, not after the fix is
drafted.

## Pattern: Intentional Design

**Detection:** Reviewer questions a design choice that was deliberate —
"Why use X instead of Y?", "This seems inconsistent with Z."

**Investigation:**
1. Read surrounding code for context
2. Check if there's an ADR or comment explaining the choice
3. Check if X and Y serve different purposes in this context
4. If intentional → **QUESTION** (explain the reasoning)

**Reply template:**
```
This is intentional. {Explanation of why X was chosen over Y, with
technical justification.}
```

## Adding New Patterns

When you encounter a validation scenario not covered above:

1. Name the pattern (2-3 words)
2. Document the detection signal
3. List the investigation steps
4. Write an evidence reply template
5. Add it to this file

Keep patterns focused — each should cover one specific type of false positive.
