# 17. Durable-mode guard policy (`allowed_overlays`) is a local pref, not a git-tracked pin

Date: 2026-07-09

## Status

Accepted

Builds on [ADR-0016](0016-friction-gate-policy-presets-over-toggles.md)
(D-8 project pin) and the GH-774 config split. Documents the decision
behind the GH-805 durable-mode guard, which shipped in PR #810
(commit `e6eec9e4`); `references/session-config-schema.md` documents the
`allowed_overlays` key for users.

## Context

GH-774 moved the durable session preferences (`friction_level`,
`active_modes`, and the ADR-0016 gate keys) out of the ephemeral
`session.yaml` into a sibling **`config.yaml`**, which the
`post-checkout` hook **copies** source→worktree so every worktree of a
repo shares them. That copy is the point — but it also means a stale or
incorrect high-autonomy mode (`active_modes: [solo-maintainer]`, which
unlocks `merge: auto-advance`) now propagates **repo-wide** rather than
living in a single worktree. On a team repo like Dev10x-Claude — which
requires human review and a human merge — a stray `solo-maintainer` is
the PR #740 silent-auto-merge incident class.

GH-805 asks for a guard that validates the durable overlays a session
derives against a repo policy before honoring them. The open question —
the one **ticket authors and investigators keep re-deriving the wrong
answer to** — is *where that policy lives*:

- **The GH-805 ticket body** proposes a git-tracked pin under `.dev10x/`
  (next to the existing `.dev10x/gate-policy.yaml` `merge: ask`).
- **Two independent design investigations** (this session's, and the
  one behind PR #810) both initially leaned toward the git-tracked
  location, reasoning that a gitignored, worktree-copied file is the
  very propagation vector being guarded, so putting the allow-list
  there looks self-defeating.

Both readings are reasonable. Neither is what the maintainer wants —
and the fact that *two* parallel sessions had to re-derive the same
decision is exactly why it belongs in an ADR rather than being
rediscovered on every pass.

## Decision

**The `allowed_overlays` policy lives in the local, gitignored
`.claude/Dev10x/config.yaml`, NOT in a git-tracked `.dev10x/` pin.**

As shipped in PR #810:

- `allowed_overlays: [...]` is read from `config.yaml` (pre-split
  `session.yaml` fallback) by
  `SessionYamlDocument.read_allowed_overlays()`, and carried forward on
  `dev10x session seed` / `config.yaml` render so a re-seed or migration
  never silently drops it.
- Semantics are **absent = permissive** (guard off, backward
  compatible): a repo that never sets the key sees no behaviour change.
  An **explicit list (even `[]`) turns the guard on** — the resolver
  drops any session overlay not on the list before resolving the
  merge/request-review/notify toggles. Dropping only ever *removes*
  autonomy, so it can never make a gate less safe.
- `resolve_gate_for_toplevel` performs the drop inline and surfaces the
  removed overlays as `dropped_overlays` in the payload; `ModeGuardRule`
  emits a SessionStart warning naming them so the durable config is
  corrected at source rather than silently overridden every session.
- The **git-tracked `.dev10x/gate-policy.yaml` `merge: ask` pin stays a
  separate, independent tier** (ADR-0016 D-8). The two compose: the
  project pin is the team-enforced hard floor on `merge`; the local
  `allowed_overlays` is the personal-machine guard on which overlays are
  honoured at all.

### Why local, not git-tracked

1. **Repo character is a shared fact; "which autonomy overlays *I* trust
   on *this* machine" is a personal one.** `allowed_overlays` is the
   second kind — a safety preference of the operator running the agent,
   in the same family as `settings.local.json` and `.idea/`:
   deliberately gitignored so a teammate cannot commit, dispute, or
   "clean up" it away. The git-tracked `merge: ask` pin already carries
   the team-level, disputable statement ("this repo never auto-merges");
   a second team artifact for overlays is redundant with it.
2. **Defense-in-depth, not a single chokepoint.** The propagation-vector
   objection (a stale `config.yaml` could carry a permissive
   `allowed_overlays` too) is real but does not defeat the guard: it is
   one of *two independent* layers. Even if `allowed_overlays` is
   stale-permissive, the git-tracked `merge: ask` pin still blocks
   auto-merge on a team repo; conversely, on a repo with no `merge` pin,
   a locally-set `allowed_overlays: []` closes the gap. Both must be
   wrong simultaneously for auto-merge to leak.
3. **It matches an explicit maintainer directive** (recorded across
   sessions, reaffirmed 2026-07-09). The ticket body and both design
   passes defaulted to git-tracked; this ADR exists precisely because
   that default is wrong for this decision and keeps being picked up
   again.

## Alternatives Considered

### Alternative A — git-tracked `.dev10x/gate-policy.yaml: allowed_overlays`

Add the allow-list to the existing git-tracked project pin.

**Pros:** cannot be a stale uncommitted copy; co-located with `merge:
ask`; team-enforced; matches the ticket body and both investigators'
first instinct.
**Cons:** conflates a personal-machine trust preference with a shared
repo fact; makes the operator's autonomy choice a committed artifact a
teammate can revert; redundant with the `merge: ask` pin, which already
states the team-level "no auto-merge here" position. The
propagation-vector argument for this option is weakened by the
defense-in-depth composition above.
**Verdict:** Rejected — this is the recurring wrong default this ADR is
written to stop.

### Alternative B — drop at resolve-time only, no SessionStart warning

Silently drop the disallowed overlay in the resolver; never surface it.

**Pros:** minimal.
**Cons:** the durable `config.yaml` stays wrong forever; the operator
never learns to fix the source, so the drop fires every session.
**Verdict:** Rejected — the drop (behavioural safety) and the
`ModeGuardRule` warning (source correction) compose; both shipped.

### Alternative C — rewrite `config.yaml` to remove the mode at SessionStart

Mutate the durable file to delete the disallowed mode.

**Pros:** self-healing.
**Cons:** fights the `post-checkout` copy every session; a repo write on
the SessionStart hot path is exactly what GH-774 engineered the
copy-not-write design to avoid. **Verdict:** Rejected — warn, don't
mutate.

## Consequences

### What becomes easier

1. The location question is settled once — future GH-805-adjacent work
   (and confused ticket authors) has a citable decision.
2. A stale `solo-maintainer` copied into a team-repo worktree can no
   longer silently auto-merge, and the operator is told why at session
   start.

### What becomes more difficult

1. A genuinely-solo operator must set `allowed_overlays:
   [solo-maintainer]` in their local `config.yaml` to keep auto-merge —
   an explicit opt-in rather than an inherited default. This is the
   intended friction. Because an explicit list drops *every* unlisted
   overlay (not only `solo-maintainer`), an operator who opts in must
   list every overlay they rely on (e.g. `afk`).
2. Because the policy is gitignored, it is not visible in the repo; the
   `ModeGuardRule` SessionStart warning is the only in-band signal, so
   it must stay.

### Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Stale-permissive `allowed_overlays` copied across worktrees | Medium | Medium | Git-tracked `merge: ask` pin is the independent second layer; `ModeGuardRule` warns |
| An explicit allow-list silently drops an overlay the operator still wants (e.g. `afk`) | Medium | Low | `dropped_overlays` in the resolve payload + the SessionStart warning name every dropped overlay |
| Operator surprised auto-merge stopped | Low | Low | `dropped_overlays` + SessionStart warning name the removed overlay and point at `config.yaml` |

## References

### Internal

- [GH-805](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/805) —
  guard durable `config.yaml` overlays (this ADR fixes the location the
  ticket body got wrong); shipped in PR #810
- [GH-774](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/774) —
  durable/ephemeral session config split (the copy that created the
  blast radius)
- [ADR-0016](0016-friction-gate-policy-presets-over-toggles.md) — gate
  policy resolver; D-8 git-tracked project pin (`merge: ask`)
- `references/session-config-schema.md` — user-facing `allowed_overlays`
  key documentation (shipped with PR #810)
- `feedback_dev10x_not_solo_maintainer_afk_mode` — Dev10x-Claude
  requires human review/merge (PR #740 incident class)
