# Loop Mode — `dev10x:review --loop` (GH-1831)

A single review pass never looks at its own fixes. `dev10x:review-fix`
turns findings into fixup commits, and those commits ship unreviewed —
yet fixes introduce defects too. Loop mode re-reviews every round of
fixes with fresh eyes until a round comes back clean.

Field data reported in GH-1831 — 98 review loops in a parallel-session
workflow — puts the median at 4 rounds and the longest at 25; one
security fix took 9. An
unbounded loop burns tokens, and a single pass misses regressions. The
rules below exist to make the loop converge rather than churn.

## Round rules

1. **Every round dispatches fresh reviewers.** Each round issues new
   `Agent` calls (SKILL.md Step 4). Never continue a previous round's
   reviewer with `SendMessage`: an agent that saw the code before the
   fix anchors on its own earlier reading.
2. **The author never re-approves its own fix.** The orchestrator that
   ran `dev10x:review-fix` does not judge whether a fix is correct.
   Only a clean reviewer round ends the loop — "I fixed it, so it is
   fixed" is not a clean round.
3. **Round 1 reviews the whole branch.** It runs SKILL.md Steps 1b–5
   against `origin/<base>...HEAD`; Step 6b then decides its fix set.
4. **Round 2 and later review only the delta.** The delta is
   `git diff <previous round_start_sha>..HEAD` — from the HEAD the
   previous round reviewed to the HEAD its fixes produced. Add its blast
   radius: for every function, class or constant whose signature or
   behavior the delta changed, the files that reference it (`rg -l
   <name>`). Files outside delta + blast radius are not re-reviewed.
   Step 1b (spec gate) runs in round 1 only; Step 3 (pre-commit) runs
   again in every later round, on the delta files only.
5. **Findings are classified as defects or polish.** Classification
   lives in the round ledger below, never in the findings JSON — the
   handoff format to `dev10x:review-fix` stays unchanged. Only findings
   the fixer could receive are classified: severity `ERROR` or
   `WARNING` at confidence >= 70.

   | Class | Such a finding with… |
   |-------|----------------------|
   | defect | severity `ERROR`, or category `bug`, `security` or `test` |
   | polish | anything else (`style` / `architecture` WARNING) |

   INFO findings, findings below the confidence threshold and Phase 0
   `spec` concerns (no file or line) are neither: they are reported in
   the summary, exactly as in a single pass, and never counted.
6. **Only defects keep the loop going.** Round 1's fix set is its
   defects and polish, as in a single pass. From round 2 on, the fix
   set is defects only; polish joins the polish list the summary
   reports.
7. **A clean round ends the loop.** A round is clean when its fix set
   is empty, so round-1 polish fixes are reviewed in round 2 like any
   other fix. A clean round is the signal the review stamp records:
   SKILL.md Step 6c calls `review_stamp_write` for it (GH-1830), unless
   the ledger holds a `declined` finding from any round.
8. **Hard stop at round 4.** When round 4 — or any later round reached
   through **Continue one more round** — is not clean, fire the
   round-cap gate in SKILL.md Step 6b before fixing anything. A clean
   round after **Continue** ends the loop and is stamped as usual.

## Round ledger

Keep one ledger per invocation, created with
`/tmp/Dev10x/bin/mktmp.sh review loop .json` (or the `mktmp` MCP tool),
and append one entry per round:

```json
[
  {
    "round": 2,
    "round_start_sha": "<HEAD when this round's review began>",
    "scope": ["<delta + blast-radius files>"],
    "findings_file": "<path handed to dev10x:review-fix>",
    "defects": 1,
    "polish": 2,
    "declined": ["<file:line of a fix-set finding left unfixed>"],
    "fixed_head_sha": "<HEAD after dev10x:review-fix, or null>"
  }
]
```

A fix-set finding lands in `declined` when the user leaves it unpicked,
or when `dev10x:review-fix` reports it as deferred, which also happens
in unattended mode. No later delta has to touch such a finding, so a
clean round says nothing about it: the loop may still end clean, but
unstamped.

A round's scope is the diff from the previous entry's
`round_start_sha` to the current HEAD; its own `round_start_sha` is
that current HEAD, which equals the previous entry's `fixed_head_sha`.
A round whose fixer made no commit cannot be followed by another: with
no delta there is nothing new to review, so the loop ends there with
`BLOCKED: review-loop: <N> findings, fixer made no commit`, whether
the fix set held defects or only round-1 polish.

## Escalation recommendation

The recommended option at the round-cap gate is computed from the
ledger, never fixed in prose (`.claude/rules/skill-gates.md`, GH-1404):

| Ledger state | Recommended option |
|--------------|--------------------|
| Each round from 2 to the current one found fewer defects than the round before it | Continue one more round |
| Any round from 2 to the current one found as many defects as the round before, or more | Stop and hand back |

A falling count means the loop is converging and one more round is
cheap. A flat or rising count means fixes are creating as many
defects as they remove — another round only churns. "Ship with open
defects listed" is never recommended at the cap: a round that reaches
it still holds defects, and shipping them is the supervisor's call.

## Summary additions

On top of SKILL.md Step 7, a loop-mode summary reports:

- rounds run, and the defect and polish counts per round
- whether the loop ended clean, at a no-commit round, or at the cap
- the final polish list, any open defects and any declined findings,
  file:line each
- the HEAD SHA the clean round reviewed (the SHA a review stamp pins)
