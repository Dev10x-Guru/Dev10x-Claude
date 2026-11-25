# Groom continuation after a standalone fixup (GH-1989)

A change the supervisor asks for in the conversation — not in a PR
comment — reaches this skill in standalone mode. `gh-pr-respond` step 5
offers a groom after its fixups; this path had no equivalent, so a
fixup was pushed and the turn ended with "squash after approval". No
human had reviewed the PR, and the fixup reached the base branch.

## When it applies

All of these hold:

1. Standalone mode (no review comment was linked).
2. No parent orchestrator owns the shipping pipeline — a `work-on`
   plan with a "Groom commit history" step open means the parent
   grooms.
3. The fixup was pushed to a PR, or the branch has an open PR.
4. No human (non-bot) review or reply exists on that PR yet.

When a human review already exists, keep the fixup so the reviewer can
follow it, and stop. Posture (`supervisor_review: required`) alone never
defers the groom.

## The gate

**REQUIRED: Call `resolve_gate(gate="shipping_continuation",
context={})`** — the same toggle `gh-pr-respond` uses, never a new one.
Branch on `effect`:

- `ask` or an `error` key → **REQUIRED: Call `AskUserQuestion`** (do NOT
  use plain text). Options, recommended first:
  - **Groom + push + monitor (Recommended)** — `Skill(dev10x-coding:git-groom)`,
    `Skill(dev10x-coding:git)` with `--force-with-lease`, then
    `Skill(dev10x-coding:gh-pr-monitor)`.
  - **Push only** — leave the fixup on the branch; say it must be groomed
    before the review request.
  - **Stop** — no push.
- `auto-advance` → run the groom path without asking; print the `record`
  line first.
- `skip` → stop without pushing.

Never end the turn with "the fixup stays separate until you approve"
before a first human review exists.
