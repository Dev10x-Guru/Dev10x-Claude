# Phase 0 and 0.5: Job Story and Review Readiness

## Phase 0: JTBD Job Story Check

The PR body **must** start with a JTBD Job Story as its first paragraph.

1. Fetch the current PR body:
   ```bash
   gh pr view {pr_number} --json body -q '.body'
   ```

2. Check if the first paragraph matches the Job Story pattern:
   - Starts with `**When**` (bold "When")
   - Contains `**[actor] wants to**` and `**so [beneficiary] can**`
     (legacy first-person `**I want to**` / `**so I can**` also matches)
   - Uses the project or ticket language; when BDD/Gherkin-derived
     keywords appear, they match Cucumber's language reference:
     https://cucumber.io/docs/gherkin/languages/

3. If a valid Job Story is present → skip to Phase 1.

4. If missing or malformed → generate one using the `dev10x:ticket-jtbd` skill.

5. After the skill completes, verify the PR body now starts with the
   Job Story.

## Phase 0.5: Review-Readiness Precondition (GH-1410 Finding 1)

A repository whose review workflows gate on
`on.pull_request.types: [opened, ready_for_review, synchronize]`
never runs them against a draft PR. Every later phase in this
skill — CI monitoring, fixup handling, notification, verification —
can complete successfully on a drafted PR that no reviewer, human or
bot, ever saw. This phase exists so that outcome cannot happen
silently.

1. `pr_get(number={pr_number})` and read `isDraft`.
2. If `isDraft == false` → proceed to Phase 1.
3. If `isDraft == true` → call
   `pr_ready(pr_number={pr_number})`, then re-read `pr_get` and
   confirm `isDraft == false`.
4. If the PR still reports `isDraft == true` after `pr_ready` — the
   host refused or the write did not land (writes are requests, not
   receipts, per `.claude/rules/mcp-tools.md`) — this is
   `BLOCKED: pr-still-draft`. Stop and surface it; do not proceed to
   CI monitoring on a PR review workflows will skip.

This does not replace Finding 2's payload-level guard (see Phase 1's
**Interpret verdict** table, `skipping_checks`) — a PR can be marked
ready here and still have an unrelated check legitimately skip later.
This phase only closes the specific gap where the *entire monitor run*
never observed the PR in a reviewable state.
