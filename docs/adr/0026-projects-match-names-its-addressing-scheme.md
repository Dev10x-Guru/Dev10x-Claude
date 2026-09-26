# ADR-0026: `projects[].match` names its addressing scheme

- **Status:** Accepted
- **Date:** 2026-09-16
- **Supersedes:** none
- **Amends:** ADR-0018 (names the key that carries D3's path keying)
- **Related:** GH-1344, GH-1313 (Q2 overlay storage), ADR-0018 D1/D3,
  ADR-0008 (domain boundary)

## Context

**Four** global config files under `~/.config/Dev10x/` carry a
`projects:` list with a selector key called `match`, and the key is
compared against a different value in each. GH-1344 reports two; the
other two surfaced while implementing this decision.

| File | `match` is compared against | Implementation |
|---|---|---|
| `playbooks/<skill>.yaml` | the repo's `nameWithOwner` — `org/repo` | **none** — prose only |
| `settings-pr-merge.yaml` | the current repo, org-form by example (`Dev10x-Guru/*`) | **none** — "resolved by the skill" (`github_tools.py:781`) |
| `gitmoji.yaml` | the **full origin URL** — `git@github.com:org/repo.git` | **none** — prose only |
| `friction.yaml` | an absolute directory path | `_match_globs`, `src/dev10x/domain/documents/session_yaml.py:158-175` |

**A fifth scheme sits alongside, under the same key name.** Three more
files — `slack-config-code-review-requests.yaml`,
`gchat-config-code-review-requests.yaml`,
`github-reviewers-config.yaml` — spell `projects:` as a **mapping keyed
by bare repo name** (`tt-pos:`), with no `match` key at all. They are
out of scope for the rename, but they matter to the reader this ADR is
written for: `projects:` is not even the same *structure* across the
config directory, so "look at how the other file does it" is unsound
advice regardless of which key name wins.

The third is the sharpest case, because URL matching is
**protocol-dependent**. `skills/git-commit/references/project-override.md:101`
specifies "Glob pattern against remote origin URL", and the shipped
`gitmoji.yaml` uses `*/tt-pos*`. That works against both an SSH and an
HTTPS remote only because the leading `*` absorbs everything before the
last `/`. A glob written the way `config-resolution.md` documents for a
playbook — `org/*` — matches `https://github.com/org/repo.git` and
silently fails against `git@github.com:org/repo.git`, because the SSH
form has no `/` after the host. So the same config can resolve for one
contributor and not another, purely by clone style.

### Current State

The `friction.yaml` side is real code. `FrictionYamlDocument.matched()`
(`session_yaml.py:217-230`) returns the first `projects[]` entry whose
globs hit the toplevel; `_match_globs` tests each pattern with
stdlib `fnmatch` against both the full resolved path and the final path
segment. Repo identity comes from the git **common dir**
(`src/dev10x/session/preset_pin.py:118-154`), which every worktree of a
repo shares by construction, and `match_globs_for_repo`
(`session_yaml.py:398-439`) writes `["*/<name>", "*/<name>-*"]` for the
default `repo` scope.

The playbook side has no resolver at all. `skills/playbook/discovery.py`
locates override *files* by path and never reads a `projects:` list.
The "walk `projects[].match`" behaviour exists only as instructions an
agent follows by hand, in `references/config-resolution.md:72-95`:

> 1. Get current repo: `git remote get-url origin` → extract `owner/repo`
> 2. Walk the `projects` list — first `match` glob that fits selects the
>    config block
> 3. If no match, skip Tier 2 (fall through to Tier 3 or 4).

`gitmoji.yaml` is the third site, prose-resolved like the playbooks but
against a third target. `skills/git-commit/references/project-override.md:101`
specifies the field as a "Glob pattern against remote origin URL", and
`instructions.md:467-468` resolves it by `git remote get-url origin`.
It is absent from GH-1344's account.

### Problems

1. **One key name, four meanings — five if the keyed-map files
   count.** The name promises a consistency the schema does not have,
   which is the defect GH-1344 reports, and it holds across twice as
   many files as the issue found.

2. **The failure is asymmetric, and that is worse than symmetry.**
   GH-1344 states both cross-uses match nothing. Measured against the
   real matcher and the documented playbook rule, only one does:

   | glob | `friction.yaml` (path) | playbook (`org/repo`) | `gitmoji.yaml` (SSH URL) |
   |---|---|---|---|
   | `Dev10x-Guru/*` (org form) | **no match** | match | **no match** |
   | `*/Dev10x-Claude` (path form) | match | match | **no match** |
   | `*/Dev10x-Claude*` (path, trailing `*`) | match | match | match |

   The first two rows were measured against the real matcher and the
   documented playbook rule; the third column follows from the SSH
   remote form `git@github.com:Dev10x-Guru/Dev10x-Claude.git`, whose
   only `/` precedes the org.

   The path form works in **both** prose-free cases, because `fnmatch`'s
   `*` spans `/`, so `*/<repo>` matches `owner/repo` with `*` absorbing
   the owner. Only one spelling — a path glob with a trailing `*` —
   resolves under all three. A symmetric collision announces itself the
   first time either convention is crossed; this one lets a reader cross
   it successfully, conclude the key is interchangeable, and be wrong
   only later, in the direction that fails silently.

3. **Every failure mode is silent, and two are unobservable.** Tier-2
   playbook resolution documents the miss as "skip Tier 2"
   (`config-resolution.md:93`) with no warning, and since no code
   performs the match there is nothing that *could* report it.
   `FrictionYamlDocument.matched()` returning `None` is likewise a
   normal fallback path, not an error.

4. **The maturity gap is itself load-bearing for the decision.**
   Renaming a key that no code reads is a documentation edit. Renaming
   the key `pin_project_prefs` writes and `_match_globs` reads is a
   migration over every user file already on disk.

### Prerequisites

GH-1313 settled (2026-09-15) that the permission overlay lives in
`friction.yaml`'s `projects[]` entry, keyed by git common dir, reusing
`pin_project_prefs` wholesale. That decision extends the path-glob
convention rather than the org-glob one, so this ADR must not rename
the key underneath it.

ADR-0018 D3 is the standing justification for path keying:

> Match on directory-path globs, not the git remote. Keeping the
> resolver keyed on the toplevel path (glob against `projects[].match`)
> leaves the durable readers I/O-free — no `git remote` shell-out inside
> the domain layer (ADR-0008 boundary).

## Decision

We will **keep the bare `match:` on the path-addressed side and rename
the repo-addressed side to `match_repo:`.**

- `friction.yaml` `projects[].match` keeps its name and its directory-path
  semantics. It is the code-backed side, it is what ADR-0018 D3 blesses,
  and it is what GH-1313's overlay builds on.
- `playbooks/<skill>.yaml`, `settings-pr-merge.yaml` and
  `gitmoji.yaml` use `match_repo:`, compared against `nameWithOwner`.
  All three are prose-resolved, so the rename is a documentation
  change with no migration and no code.
- **`gitmoji.yaml` stops matching the full origin URL** and matches
  `nameWithOwner` like the playbooks, collapsing three targets to two.
  URL matching has no advantage and one serious defect: it is
  protocol-dependent, so a glob that resolves for an HTTPS clone can
  silently fail for an SSH clone of the same repo. `nameWithOwner` is
  the same fact with the protocol removed. The shipped `gitmoji.yaml`
  globs (`*/tt-pos*`, `*/tiretutorv2-backend*`) keep working unchanged
  under `nameWithOwner`, so this costs no user migration.
- `match:` in a repo-addressed file is accepted as a deprecated alias
  until its removal version in the ADR-0028 register
  (`dev10x.domain.deprecations`), so existing user playbooks keep
  working.
- `*/<repo>` is documented as the **portable form** — the one spelling
  that resolves correctly under both schemes. It is the form
  `match_globs_for_repo` already generates.

This satisfies GH-1344's acceptance criterion that "the key name says
which" while putting the rename on the side where it costs nothing.

### Why not converge on one scheme

Because the two schemes answer different questions, and ADR-0018 D3
already decided that for the durable layer. Path keying covers every
worktree of a repo by construction and keeps the domain layer free of a
`git remote` shell-out. Org keying buys org-wide globs (`Dev10x-Guru/*`)
that a path glob cannot express, and it is the only scheme available to
a config consulted before a repo's remote is known. Keeping both and
naming them is cheaper and more honest than forcing either to carry the
other's job.

## Alternatives Considered

### Alternative 1: Rename the `friction.yaml` key to `match_path:`

Keeps `match` meaning `org/repo`, which is the reading a newcomer
reaches for first.

**Pros:**
- `match` retains the meaning most people assume.
- Leaves the prose-resolved sites untouched.

**Cons:**
- Requires a code change to `_match_globs` / `FrictionYamlDocument` plus
  a back-compat alias, and a migration for every `friction.yaml` on
  disk.
- `pin_project_prefs` writes `match` today, so the writer, the reader
  and every fixture move together.
- Renames the key GH-1313's overlay design was specified against, one
  day after that decision.

**Verdict:** Rejected — all of the cost lands on the only side that has
working code.

### Alternative 2: Rename both — `match_repo:` and `match_path:`

**Pros:**
- Neither file keeps an ambiguous bare `match`; no implicit winner.
- Maximally self-describing.

**Cons:**
- Carries Alternative 1's full migration cost and adds the doc churn.
- Two renames to explain instead of one.

**Verdict:** Rejected — buys marginal clarity over the selected option
for the whole of Alternative 1's cost.

### Alternative 3: Keep `match` everywhere; document `*/<repo>` as portable

The measured truth table shows the path form resolves under both
schemes, so a single documented spelling would work today with no
rename at all.

**Pros:**
- Zero schema change, zero migration, zero code.
- One spelling for a user to learn.

**Cons:**
- Leaves the key ambiguous, which is precisely what GH-1344 asks to fix
  — the acceptance criterion names the key, not the glob.
- The overlap is incidental, not designed: it holds because `fnmatch`'s
  `*` spans `/` and an owner contains no `/`. A future matcher switched
  to `pathlib`-style globbing (where `*` does not span `/`) would break
  the portable form silently.
- Forms outside the overlap still diverge — `/work/dx/**` resolves only
  under path keying, `Dev10x-Guru/*` only under repo keying.

**Verdict:** Rejected as the whole answer, adopted in part — the
portable form is documented, but it is guidance layered on named keys
rather than a substitute for naming them.

### Alternative 4: Rename the repo-addressed side to `match_repo:`

**Pros:**
- The rename lands on prose-only config: no resolver, no migration, no
  code.
- Leaves `match` on the side ADR-0018 D3 and GH-1313 both build on.
- A reader copying `Dev10x-Guru/*` into `friction.yaml` now meets a
  differently-named key, which is the cue that was missing.

**Cons:**
- The bare `match` still means the path form, which is not the meaning a
  newcomer guesses first.
- Three documents change, and one of them (`skills/git-commit`) was not
  in GH-1344's scope.

**Verdict:** Selected.

## Consequences

### What Becomes Easier

1. A glob's meaning is readable from the key that carries it, without
   knowing which file is open.
2. The deferred shape validator has an unambiguous rule to enforce: a
   pattern containing `/` that does not start `*/` is wrong under
   `match:`, and a pattern starting `*/` is suspicious under
   `match_repo:` only if the user meant a path.
3. GH-1313's overlay work proceeds against an unchanged `match:`.

### What Becomes More Difficult

1. Two key names exist where one did, so documentation must keep saying
   which file takes which.
2. The deprecated `match:` alias on the repo-addressed side is a
   second code path to carry for a release, and nothing enforces its
   removal but a note.
3. `skills/git-commit` joins the set of documents that must change
   together whenever this convention moves.
4. Changing `gitmoji.yaml`'s comparison target is a behaviour change,
   not just a rename. A user glob written to exploit the URL form —
   one anchored on the host, say — would stop resolving. None ships
   today, but a hand-written one could exist.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A user's playbook keeps `match:` past the deprecation window and silently stops resolving | Medium | Medium | The deferred no-match report (GH-1344 item 2) is the real fix; until it lands, the alias is not removed |
| The rename lands in some documents, leaving one drifting | Medium | Low | All four paths named explicitly in the implementation plan below and in GH-1375 |
| A hand-written `gitmoji.yaml` glob anchored on the remote host stops resolving when the target becomes `nameWithOwner` | Low | Low | The no-match report (GH-1344 item 2) surfaces it; no shipped glob depends on the host |
| A future matcher change breaks the portable `*/<repo>` form | Low | Medium | Documented as convenience, not contract; named keys remain the guarantee |

## Implementation Plan

This ADR records the decision only. No schema or resolver changes ship
with it, per the scoping call on GH-1344.

### Phase 1: This ADR

1. `docs/adr/0026-projects-match-names-its-addressing-scheme.md`.

### Phase 2: Deferred to GH-1375

1. Rename the key in `references/config-resolution.md:72-95`,
   `skills/playbook/instructions.md:35-46`,
   `skills/git-commit/instructions.md:467`,
   `skills/git-commit/references/project-override.md:101,105-110` and
   `skills/gh-pr-merge/instructions.md:21-61`, with `match:` accepted
   as a deprecated alias. Five documents, not two — the count is the
   point: this convention is restated per-skill in prose, so every
   restatement is a place it can drift.
2. Change `gitmoji.yaml` resolution from the origin URL to
   `nameWithOwner` — `skills/git-commit/instructions.md:467-468` and
   `project-override.md:101,110`. Verify the shipped globs still
   resolve, and add a case for an SSH-vs-HTTPS remote pair.
2. Report a `projects:` list that matched nothing — GH-1344 item 2 — in
   `playbook diff` and `dev10x config doctor`
   (`src/dev10x/commands/config.py:111-133`), neither of which evaluates
   `projects[].match` today.
3. Document the no-origin-remote Tier 2 case — GH-1344 item 3 — which
   `config-resolution.md:90` states as a step with no failure handling.
4. Add the glob-shape check — GH-1344 item 4 — using the rule in
   § Consequences above.

## References

### Internal References

- [ADR-0018](0018-session-state-relocates-out-of-project-claude-tree.md)
  — D1/D3, directory-path keying for durable prefs
- [ADR-0008](0008-context-boundary-protocol.md) — the domain boundary
  D3 protects
- [ADR-0025](0025-projects-yaml-is-the-authoritative-permission-catalog.md)
  — the catalog GH-1313's overlay merges over
- `references/config-resolution.md:72-95`, `:140-155` — the two
  documented conventions
- `src/dev10x/domain/documents/session_yaml.py:158-175`,
  `:217-230`, `:398-439` — the only implemented matcher
- `src/dev10x/session/preset_pin.py:118-154` — git-common-dir identity
- [GH-1344](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1344) —
  the issue this decides
- [GH-1375](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1375) —
  the implementation follow-up carrying Phase 2
- [GH-1313](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1313)
