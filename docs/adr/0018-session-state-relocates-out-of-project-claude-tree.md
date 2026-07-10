# 18. Session state relocates out of the project `.claude/` tree

Date: 2026-07-10

## Status

Proposed

Supersedes the per-repo `.claude/Dev10x/config.yaml` location established
by the GH-774 config split, and retires the ephemeral
`.claude/Dev10x/session.yaml` introduced alongside it. Builds on
[ADR-0016](0016-friction-gate-policy-presets-over-toggles.md) (gate policy
resolver) and [ADR-0017](0017-durable-mode-guard-policy-is-local-not-git-tracked.md)
(`allowed_overlays`). Addresses GH-812 and GH-813 Finding 1.

## Context

GH-774 split session config into a durable `config.yaml` and an ephemeral
`session.yaml`, both under the project's `.claude/Dev10x/`, and had the
`post-checkout` hook **provision** them so no runtime `Write(.claude/…)`
would happen on the hot path. That design was incomplete:

- **RC-A — the self-settings gate ignores allow rules.** Claude Code
  classifies any Write/Edit under the project `.claude/` directory as a
  "let Claude edit its own settings" action and prompts for consent
  *regardless of allow rules on disk*. GH-812 observed this twice in one
  day, with exact-path `Read/Write/Edit(.claude/Dev10x/session.yaml)`
  rules verified present. No `base_permissions` entry can suppress it.
- **RC-B — skills still runtime-write the files.** `Dev10x:work-on`
  Phase 0 still `Write`/`Edit`s `session.yaml` (branch/tickets identity)
  and `config.yaml` (friction choice) whenever the adoption gate reports
  `session_stale` or the friction choice changes. The provisioning hook
  only covers the no-change case; any genuinely stale session hits the
  gate. So the split moved the files but not the writes.
- **RC-C / RC-D — per-repo durable prefs do not sync.** A durable
  preference is a property of *the repo*, yet it lives once per checkout;
  the ADR-0017 `post-checkout` **copy** exists only to paper over this,
  and nothing syncs prefs across sibling worktrees or projects.

Contrast: plan-sync state (`~/.claude/projects/_session_state/<md5>.json`
and `.claude/session/plan.yaml`) is written by **MCP tools**, not the
Write tool, and never trips the gate. The gate is a Write/Edit *tool*
phenomenon, not a path phenomenon.

The maintainer's framing (2026-07-10): after the GH-774 split, the
durable prefs are the only thing gates actually read, and `session.yaml`
has been reduced to a `branch`/`tickets` staleness stamp that plan-sync
already carries. So: read gate preferences from one global per-project
file, and make the session file trivial or unnecessary.

## Decision

**D1 — Durable preferences move to a single global
`~/.config/Dev10x/friction.yaml`, keyed by project directory-path globs.**
It holds the durable keys (`friction_level`, `active_modes`,
`allowed_overlays`, and the ADR-0016 gate keys `gate_preset`,
`gate_overlays`, `gate_overrides`) under a `defaults:` block plus a
`projects: [{match: [...glob], ...prefs}]` list — the same shape as the
existing `~/.config/Dev10x/projects.yaml`. `resolve_gate`'s single durable
seam (`SessionYamlDocument._durable()`) repoints to this resolver. The
per-repo `.claude/Dev10x/config.yaml` is retired.

**D2 — The ephemeral `.claude/Dev10x/session.yaml` is deleted.** Its only
post-GH-774 job was the `branch`/`tickets` identity feeding the
adoption/staleness gate, and plan-sync already persists both. The
staleness check reads identity from the plan-sync state instead. Result:
**nothing Dev10x writes under the project `.claude/` via the Write/Edit
tool**, so the self-settings gate can never fire on Dev10x session state
again (RC-A/RC-B closed at the source).

**D3 — Match on directory-path globs, not the git remote.** Keeping the
resolver keyed on the toplevel path (glob against `projects[].match`)
leaves the durable readers I/O-free — no `git remote` shell-out inside the
domain layer (ADR-0008 boundary). "Repos and project dirs" are both
addressable as path globs.

**D4 — Legacy per-repo `config.yaml` is a read-only migration fallback
for one cycle.** When `friction.yaml` has no matching entry, the durable
reader falls back to the legacy `.claude/Dev10x/config.yaml` (and the
pre-split `session.yaml`) so existing repos keep working untouched.
`Dev10x:upgrade-cleanup` / `Dev10x:plugin-doctor` fold the legacy file
into `friction.yaml` and delete the stale `.claude/Dev10x/{session,config}.yaml`
— tracked as follow-up, not required for correctness because of the
fallback.

**Composition with prior ADRs.** The git-tracked `.dev10x/gate-policy.yaml`
team pin (ADR-0016 D-8) is unchanged — it remains the shared, disputable
hard floor. `allowed_overlays` (ADR-0017) keeps its "local, not
git-tracked" character: it moves from per-repo `config.yaml` into the
project's `friction.yaml` entry, which lives in the user's `~/.config`
(personal machine), still gitignored-by-construction (never in any repo).
ADR-0017's rationale (personal trust preference, not a shared fact) is
preserved — arguably strengthened, since the value is now unambiguously
outside every repo.

## Alternatives Considered

### Alternative A — route `.claude/Dev10x/` writes through an MCP tool (GH-812 O1)

Keep the files per-repo; add a `session set` MCP tool so the server
process (not the Write tool) writes them, escaping the gate.

**Pros:** smallest blast radius; MCP allow rules already ship.
**Cons:** needs a documented gate-bypass ADR (deliberately sidestepping a
harness safety gate); does nothing for RC-C/RC-D (prefs still per-repo,
still need the copy hack); keeps two file locations. **Verdict:**
Rejected — relocation solves the same gate problem *and* the sync problem
without a bypass.

### Alternative B — per-session timestamped file in `~/.cache/Dev10x/sessions/`

The literal path from the ticket:
`~/.cache/Dev10x/sessions/YYYYMMDD-HHSS-<repo>-<worktree>-<session-id>.yaml`.

**Pros:** clean per-session isolation.
**Cons:** the MCP tools that read session policy (`resolve_gate`,
plan-sync) run in a long-lived server with **no session-id**, so they
cannot locate "the current" per-session file; adoption/staleness would
need a "find latest for this worktree" scan. Breaks deterministic lookup
for no benefit once durable prefs are global and identity comes from
plan-sync. **Verdict:** Rejected — D1+D2 make a per-session file
unnecessary.

### Alternative C — relocate session.yaml unchanged to `~/.cache`, keep it

Move the file out of `.claude/` but keep it as the identity store.

**Pros:** minimal design change.
**Cons:** keeps a redundant store (plan-sync already has branch/tickets)
and a second file to seed/read. **Verdict:** Rejected — deleting it is
strictly simpler (the maintainer's explicit choice).

## Consequences

### What becomes easier

1. The self-settings-gate friction class is eliminated at the source for
   Dev10x session state — no per-repo, per-session prompt ever again.
2. Durable prefs sync across every worktree and checkout of a repo by
   construction (one global file), retiring the `post-checkout` copy hack.
3. One authoritative prefs file per machine; `resolve_gate` has one seam.

### What becomes more difficult

1. A machine-global file means a new project inherits `defaults:` until a
   `projects[]` entry is added — an explicit opt-in per repo (mirrors
   `projects.yaml`).
2. `friction.yaml` is unversioned and machine-local; the git-tracked
   `.dev10x/gate-policy.yaml` pin remains the only in-repo, team-visible
   policy signal (unchanged from ADR-0016/0017).

### Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Existing repos' per-repo `config.yaml` prefs silently ignored after the move | Medium | Medium | D4 legacy read-fallback; doctor migration folds them into `friction.yaml` |
| Two repos match overlapping globs → wrong prefs | Low | Medium | First-match-wins, most-specific ordering; document like `projects.yaml` |
| A skill still Write/Edits `.claude/Dev10x/**` after the move | Medium | Medium | Follow-up `check-skill-cli-friction` scanner rule (GH-812 S3c); work-on Phase 0 doc updated in this change |

## References

### Internal

- [GH-812](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/812) —
  session-config writes defeat allow rules (self-settings gate); this ADR
  is the relocation decision the evidence log scopes
- [GH-813](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/813) —
  skill-audit Finding 1 (same root cause, fixed here) + Finding 2
  (worktree discovery, separate commit)
- [GH-774](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/774) —
  durable/ephemeral split this ADR completes
- [ADR-0016](0016-friction-gate-policy-presets-over-toggles.md),
  [ADR-0017](0017-durable-mode-guard-policy-is-local-not-git-tracked.md)
- `references/session-config-schema.md` — user-facing key docs (to update)
- `feedback_dev10x_not_solo_maintainer_afk_mode` — human review/merge here
