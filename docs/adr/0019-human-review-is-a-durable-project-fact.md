# 19. Human review is one durable project fact, not an ephemeral per-session mode

Date: 2026-08-02

## Status

Accepted

Supersedes the ephemeral framing of the `review-deferred` structural
mode (GH-396, GH-736). Builds on
[ADR-0018](0018-session-state-relocates-out-of-project-claude-tree.md)
(nothing durable under a repo's `.claude/`) and
[ADR-0016](0016-friction-gate-policy-presets-over-toggles.md) (the gate
policy resolver). Records the supervisor decision on
[GH-950](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/950).

## Context

`review-deferred` was introduced as an **ephemeral** structural mode:
the supervisor defers open PR review threads for one session, and
`Dev10x:verify-acc-dod` skips the unresolved-threads and review-request
checks so the definition-of-done stays honest rather than red-but-
ignored.

Its writers — `Dev10x:gh-pr-request-review`'s Stand-by / Defer path and
`Dev10x:work-on`'s Scope-deferred-review-threads step — appended the
mode to `active_modes` in `.claude/Dev10x/session.yaml`. ADR-0018
retired that file. `SessionYamlDocument._durable()` now resolves:

1. a matching `friction.yaml` `projects[]` entry — **wins outright**;
2. else the legacy per-repo `config.yaml`, with a pre-split
   `session.yaml` fallback;
3. else `friction.yaml` `defaults`.

So the written flag is reachable only at step 2, i.e. only in a repo
that has **never** been configured. Once `Dev10x:friction-setup` or
`Dev10x:afk` pins a `projects[]` entry — now the documented happy path
— the deferral is silently dropped and `verify-acc-dod` re-runs the very
checks the supervisor just deferred. The write also cost a self-settings
consent prompt (an `Edit` under the repo's `.claude/`) for no effect.

GH-950 framed the fix as "pick a home for *ephemeral* structural modes"
and ruled out a durable home on lifetime grounds, leaving three
candidates (durable `friction.yaml`, playbook `active_modes`, or a new
ephemeral store under `~/.config/Dev10x/`).

**That premise is rejected.** `review-deferred` is not a property of one
night's run. Either a supervisor wants humans reviewing PRs on this
project or they do not — a standing property of the project.

The ephemeral framing also treated as independent two facts that are
one. If a team needs to review a PR, the session supervisor should be
reviewing them too; conversely, when humans are not in the loop, the
agent should merge the PR itself once automated review findings are
properly addressed. "Humans review here" and "the supervisor reviews
here" are the same fact, and merge autonomy follows from it.

## Decision

**A single durable, project-wide boolean — `human_review` — governs
whether humans (including the session supervisor) are in the review loop
on a project.** It lives in the global
`~/.config/Dev10x/friction.yaml`, alongside the other durable prefs,
keyed by the same first-match-wins `projects[]` globs.

```yaml
defaults:
  human_review: true          # humans review here (the safe default)
projects:
  - match: ["*/my-solo-repo", "*/my-solo-repo-*"]
    human_review: false       # no humans in the loop
```

Three behaviours follow from the one answer:

1. **Review request** — `Dev10x:gh-pr-request-review` does not assign
   reviewers or request review when `human_review: false`.
2. **Definition of done** — `Dev10x:verify-acc-dod` skips the **"No
   unresolved review threads"** and **"Review requested" /
   "Re-review requested"** checks when `human_review: false`, reporting
   them as `skipped (human_review: false)`.
3. **Merge autonomy** — `human_review: false` is a **precondition** for
   the agent merging after automated review findings are resolved. It is
   not a grant: see the composition rule below.
   **Wired in GH-1000.** `human_review` is a `GateContext` field, and
   `_floors()` raises a `human_review` floor on the `merge` gate whenever
   it is true. A floor can only force `ask`, never grant auto-advance —
   which is precisely what makes this a precondition rather than a grant,
   structurally, not by convention. `GateResolutionQuery` reads the flag
   from the durable prefs through `_policy_toplevel`, so a worktree
   without its own entry cannot silently lose the repo's posture.

   That read is **unconditional** — deliberately unlike the neighbouring
   `session_stale` fallback, which defers to a caller-supplied fact.
   `session_stale` is a genuine per-instance fact a caller may know
   better; `human_review` is durable project policy. Were a caller able to
   pass `context={"human_review": false}`, the floor would be
   convention-deep at the exact boundary meant to enforce it, and an
   unattended agent could self-authorise merge autonomy on a repo that
   never set the key. A supplied value is dropped into
   `ignored_context_fields`. `human_review_status` resolves through the
   same `_policy_toplevel` seam for the same reason: one durable fact must
   not have two answers.

   Note the blast radius, since the default is `true`: a repo that has
   not set `human_review: false` no longer auto-advances the merge gate,
   whatever its preset and overlays say. That is the intended reading of
   "both must agree" below — the safe pole was always `true`, and
   behaviour 3 gives it teeth. Opting a solo repo back into auto-merge is
   one key in its `friction.yaml` entry.

### Key semantics

- **Name.** A positive `human_review: true|false` rather than carrying
  `review-deferred` forward as a mode string. The positive form reads
  correctly at both poles and makes the merge-autonomy coupling explicit
  rather than implied by a mode name that mentions only deferral.
- **Default.** Absent or non-boolean reads as **`true`** — humans review.
  Every unconfigured repo keeps today's behaviour, and a malformed value
  fails toward more oversight, not less.
- **Location.** `~/.config/Dev10x/friction.yaml`, so the write never
  trips Claude Code's self-settings gate (ADR-0018) and one file serves
  every worktree of a repo by construction. `_durable()` already
  resolves it first-match-wins, which is exactly the precedence a
  project-wide flag wants — no second store and no merge-across-stores
  reader logic.
- **Writers stop writing.** `gh-pr-request-review` and `work-on` no
  longer write `.claude/Dev10x/session.yaml`; the
  `Edit(.claude/Dev10x/session.yaml)` front-matter grant and the
  `# cli-friction: allow retired-durable-pref-path` marker drop with
  them.

### Composition with the existing merge gates

`human_review: false` can only ever **reduce** review expectations; it
never overrides a gate that withholds autonomy:

- The git-tracked `.dev10x/gate-policy.yaml` `merge: ask` pin
  (ADR-0016 D-8) still wins. A team repo that pins `merge: ask` does not
  auto-merge because someone set `human_review: false` locally.
- `allowed_overlays` (ADR-0017) still drops the `solo-maintainer`
  overlay before gate resolution. `human_review` is not an overlay and
  does not re-admit one.
- `merge_config.solo_maintainer` continues to govern the
  `Dev10x:gh-pr-merge` approval override independently.

So merge autonomy requires `human_review: false` **and** the existing
gates to permit it. Both must agree; either can veto.

### Scoped out: `swarm-child`

`swarm-child` does **not** move here. It is genuinely per-dispatch — a
worker either is or is not a swarm child — and it is set by the
dispatcher, not by a supervisor expressing a project preference. It
keeps its current dispatch-time delivery. GH-950 listed it alongside
`review-deferred` as an "ephemeral mode"; only the review flag turns out
to be a durable project fact.

### Back-compat for `review-deferred`

The mode string stays **readable**: playbook `modes.review-deferred.skip`
clauses and any `active_modes` entry that names it continue to work, so
an un-migrated repo or a hand-edited playbook is not broken. It is
deprecated in favour of `human_review` and nothing writes it anymore.

## Alternatives Considered

### Alternative A — a new ephemeral store under `~/.config/Dev10x/`

GH-950's own preferred option: right location, per-session lifetime.

**Pros:** correct lifetime for a genuinely one-off deferral; no risk of
a permanent review suppression.
**Cons:** a new store plus a new reader contract to express something
that is really one durable project fact; leaves the review-assignment
and merge-autonomy halves modelled as independent when they are not.
**Verdict:** Rejected — the premise that the lifetime is per-session is
what this ADR overturns.

### Alternative B — playbook `active_modes` via `dev10x session set-playbook --mode`

The sanctioned post-ADR-0018 `active_modes` writer.

**Pros:** an existing writer; durable.
**Cons:** `_durable()` does not merge the playbook file, so the reader
would need extending too; and `active_modes` is a structural-mode list,
which buries a project policy question inside execution plumbing.
**Verdict:** Rejected — more reader work for a worse model.

### Alternative C — keep `review-deferred`, just point it at `friction.yaml`

Minimal diff: same mode string, durable home.

**Pros:** smallest change; no new key.
**Cons:** a name that says "deferred" describing a standing property
invites exactly the lifetime confusion GH-950 recorded; and it leaves
merge autonomy implicit, so the third behaviour stays uncoupled.
**Verdict:** Rejected — the rename is the point.

## Consequences

### What becomes easier

1. A supervisor states the review posture once per project and all three
   behaviours follow — no per-session flag to remember or re-set.
2. `verify-acc-dod` is honest by construction in a configured repo: the
   flag it reads is the flag that was written.
3. No `Edit` under a repo's `.claude/` on the review path, so the
   self-settings consent prompt disappears.

### What becomes more difficult

1. **The one-off "defer just this session" deferral is gone.** A
   supervisor who wants to skip review threads for a single session must
   either change the project setting or accept the red check and hand
   over. This is intended: the check staying red is the honest outcome
   when the project says humans review.
2. A supervisor flipping `human_review: false` for convenience silently
   changes merge posture too. The coupling is the design, but it means
   the flag deserves more thought than a per-session toggle did — which
   is why the gate composition above keeps `merge: ask` and
   `allowed_overlays` as independent vetoes.

### Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `human_review: false` set casually, suppressing review on a team repo | Medium | High | `merge: ask` pin and `allowed_overlays` are independent vetoes; the flag alone cannot auto-merge |
| Malformed value (e.g. `"no"`) read as false | Low | High | Non-boolean reads as `true`; only a real boolean `false` disables review |
| Supervisor expects the old per-session deferral and finds none | Medium | Low | `verify-acc-dod` names the flag in its skipped-check report; `references/active-modes.md` documents the deprecation |

## References

### Internal

- [GH-950](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/950) —
  the divergence, the three candidate homes, and the supervisor decision
  comment this ADR records
- [GH-948](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/948) —
  the A1/A2 audit this split out of
- [GH-396](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/396) /
  [GH-736](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/736) —
  the `review-deferred` mode and the honest-DoD rule it serves
- [ADR-0016](0016-friction-gate-policy-presets-over-toggles.md) — gate
  policy resolver; D-8 git-tracked `merge: ask` project pin
- [ADR-0017](0017-durable-mode-guard-policy-is-local-not-git-tracked.md)
  — `allowed_overlays` overlay guard
- [ADR-0018](0018-session-state-relocates-out-of-project-claude-tree.md)
  — nothing durable under a repo's `.claude/`
- `references/active-modes.md` — mode catalog and resolution order
