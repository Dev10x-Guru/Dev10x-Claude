# Permission Friction Taxonomy

The classification vocabulary for permission friction: what kinds of
friction exist, which class a given defect belongs to, and what the
standing diagnosis of the system is.

Companion to [`permission-architecture.md`](permission-architecture.md),
which covers the *mechanism* — how Claude Code evaluates a tool request
and where hooks sit in that order.
This file covers the *problem model* laid over that mechanism.

Migrated from the GH-1100 tracker, which carried it as issue prose
while twenty-plus issues cited it.
Provenance of the tracker lineage:

> #271 · #488 · #726 → #796 → #912 · #925 · #1007 → #1069 · #1076 ·
> #1090 → #1100

GitHub preserves the rest of the history; what is reproduced here is
only the part that existed nowhere else.

## Friction Types A–G

The coarsest cut: what *kind* of thing went wrong, before asking which
subsystem owns it.

| Type | Friction |
|---|---|
| A | Unseeded safe surface |
| B | Wrong rule shape |
| C | Hook hard-wall |
| D | Verb-blind wrapper |
| E | Wrong-tool routing |
| F | Background-context-generated |
| G | Should-not-run-inline |

Plus the **sensitivity overlay axis**, which is orthogonal to A–G rather
than an eighth type — it asks what the command *targets*, not what shape
it took.
It shipped as DX014; see
[`cedar-sensitivity-annotation.md`](cedar-sensitivity-annotation.md) and
`.claude/rules/hook-patterns.md` § DX014.

The tracker carried this taxonomy in exactly the compressed form above
and never expanded the seven labels into definitions.
They are reproduced as found rather than back-filled with invented
descriptions.
Where a letter's meaning is not obvious, the class map below is the
sharper instrument — it names a mechanism and an owner.

The adjacent enumerations the tracker referenced — **Gaps G1–G18**,
**Scope S1–S20**, **Decisions D1–D16** — were never migrated because
they are readable in #488's history, which is closed but intact.

## Friction Class Map

The load-bearing table.
Classes **A–J** were established in #1090 and **K–O** in #1076.
K–O are not reducible to A–J — different mechanisms, different
subsystems — and were flagged as the thing most at risk of being lost in
a consolidation.

Cite a class by its letter — `class L` — the way the issue corpus
already does.

| Class | Mechanism | Owner |
|---|---|---|
| A | User-scope dirs granted per-project only | catalog + `ensure-workspace` (directory axis) |
| B | Invocation-form / spelling aliasing | catalog schema (`spellings:` expansion) |
| C | Cross-worktree grant propagation | repo-stem keying (`pin_tracker` precedent) |
| D | Release-lag: new MCP tools prompt until maintenance re-runs | maintenance / upgrade |
| E | Option-2 catch-all on deliberately-excluded commands | eliminate-at-source > narrow entry > grant |
| F | `ask`-rule precedence, no refinement path | docs done (#1095); DX014 extension to settings-file asks open |
| G | `allowed-tools:` does not grant | `ensure-scripts` + CLAUDE.md doctrine |
| H | Rule-proof shapes (brace / simple expansion) | hook validators / templates — not catalog |
| I | Out of scope by ruling | param-normalization follow-up / by-design |
| J | Catalog split-brain | needs an ADR |
| K | Worktree runtime-state hygiene — `.claude/session/plan.yaml` is per-checkout, gitignored, no lifecycle owner, no branch-affinity check at load; recycled worktrees inherit stale plans | `domain/documents/plan.py`, `seed_worktree` — not a permission defect |
| L | CWD-forced chaining defeats rule matching — a subagent dispatched into a worktree must `cd <path> && …`, shifting the effective prefix so no allow rule can ever match; the option-2 grant it offers will not match the chained form next time either | dispatcher-side (`isolation="worktree"`, explicit `cwd`) |
| M | Own-tool enumeration drift — Dev10x's own released MCP tools never back-filled into already-seeded settings (`resolve_gate` since v0.83.0, ~15 tools since v0.90). Distinct from D | maintenance re-seed |
| N | Flag-based core checks + steer collision — `jq -f <shipped-filter>` blocked as "dangerous flags"; the check is target-blind. The plugin's own jq-over-inline-code doctrine steers into the blocked shape | core-check classification + `structured-alternatives.yaml` |
| O | Background-dispatch pre-seed gap — a background agent is offered no persistence option at all (Yes / auto-mode / No), and dispatchers often omit the preamble/wrapper pre-seed | dispatcher contract (`background_preamble`) |

### There is no class P, Q or R

The GH-1100 extraction map refers in passing to "the class map A–R".
No such rows ever existed — the map ends at O.
Treat a citation of `class P` or beyond as a reference to something
that was never written, not as a pointer to a row this file is missing.

## Diagnosis D0–D5

The standing read on *why* friction persists.
D0 is the frame; D1–D5 are the confirmed defects under it.

**D0 — the model is sound, the plumbing is not.**
An unattended run with a complete preflight shape catalog produced zero
prompts.
Every confirmed defect below is a completeness or propagation failure
rather than a design failure, which is what rules out a redesign.

**D1 — catalog split-brain. CONFIRMED.**
The legacy `skills/upgrade-cleanup/projects.yaml` is the sole write path
into `settings.local.json`; `baseline-permissions.yaml` contributes zero
rules — `migrate_flat_config` reads it only for tier/sensitivity
metadata.
ADR-0021 names the legacy file and never mentions the newer one, so
naming a single authority is an **ADR amendment, not a doc fix**.
This is class J, and it gates the scoped work under it.

**D2 — the precedence doc contradicted itself.**
Fixed in #1095.
The surviving statement of the rule lives in
[`permission-architecture.md`](permission-architecture.md)
§ Permission Group Tier Assignment ("Tier is intent, not delivery") and
§ Docs-vs-Evidence Caveat.
Do not restate it here; those sections are the live copy.

**D3 — `allowed-tools:` grants nothing.**
No directory-form rule exists in any settings file; `ensure-scripts`
enumerates per-file from disk, so the declared `Bash(<dir>/:*)` shape is
never written and a script added after the last run has no rule.
A skill that declares a tool it has not had catalogued still prompts on
every call — see `.claude/rules/mcp-tools.md`
§ "A registered tool is not a pre-approved tool".

**D4 — version-pinned paths orphan grants.**
Every release invalidates path-pinned rules until maintenance re-runs.

**D5 — measurement.**
Hook block records now carry `rule_id` / `reason` (#1095).
Settings-file prompts still have **no telemetry** — they never reach a
hook, which is why the tracker this file came from had to be
hand-transcribed.

## Standing Decisions

Rulings made on the tracker that survive it, and should not be
relitigated without new evidence.

- **`--dedupe-global` is not retired.**
  It mirrors `clean --aggressive` and stays as an opt-in flag.
  Retiring it has been proposed and declined.

## Where the PAP model lives

GH-1100 carried a PAP / PDP / PEP target-architecture sketch.
It is not reproduced here, because the repo already documents it in two
places and a third copy would be the split-brain this file's own D1
warns about:

- [`cedar-sensitivity-annotation.md`](cedar-sensitivity-annotation.md)
  — the three-axis PAP action model (tier × reversibility ×
  sensitivity), deny-overrides resolution, and the mapping of PDP + PEP
  onto Claude Code's PreToolUse hook infrastructure.
- [`domain/authz-patterns.md`](domain/authz-patterns.md) — the general
  PAP / PDP / PIP / PEP definitions as domain patterns.

Note that the acronym is expanded three different ways across the repo
("Permission Abstraction Protocol", "Policy Administration Point",
"Permission Access Policy").
They are not the same concept, and a reader should check which one a
given document means.
