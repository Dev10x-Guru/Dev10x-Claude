# 15. Shared read-only config I/O helper in `domain/common/`

Date: 2026-06-29

## Status

Accepted

Clarifies [ADR-0007](0007-rule-policy-archetype-unification.md) D3.

## Context

The 2026-06-10 architecture audit (GH-536) found config loading
fragmented across the package: one cached loader
(`config/loader.py`) used by the main config file, and ~19 ad-hoc
`yaml.safe_load` / `json.loads(path.read_text())` call sites
elsewhere — each with its own (or missing) error handling. The
audit recommended "route everything through `config/loader.py`".

The maintainer **deferred GH-536** pending a DDD/ADR session,
because that recommendation appeared to have no ADR-compatible home:

1. `config/` is the *outer* config layer — it imports `domain/`. So
   the domain call sites (`session_rules`, `common/policy`,
   `install_version`, `rule_engine`, …) cannot import
   `config/loader.py` back without inverting the dependency rule
   ([ADR-0008](0008-context-boundary-protocol.md) §The Rule #1–2).
2. Relocating a loader *into* `domain/` looked like it would violate
   [ADR-0007](0007-rule-policy-archetype-unification.md) D3 — "policy
   logic doing I/O".

### The false dilemma

Re-reading the ADRs dissolves the deadlock:

- **ADR-0007 D3 governs read-*mutate*-write, not read-only parse.**
  Every D3 example is a persistence cycle:
  `MigratePluginPermissionsRule.apply()` "reads, **parses, mutates
  and atomically rewrites** `settings.json`" (ADR-0007:51-57); the
  code example is `json.loads(...) → mutate → atomic_write_text(...)`
  under `file_lock` (ADR-0007:124-131); the invariant is scoped to
  **Policy Rules** ("MUST be free of I/O … **persistence** is
  delegated to the Document layer", ADR-0007:81-83). A bare
  `yaml.safe_load(path.read_text())` that returns a parsed value and
  mutates nothing is not what D3 forbids.

- **The codebase already reads config in `domain/` and was never
  flagged.** `domain/common/baseline_catalog.py:40` is a shared
  read-only loader (`yaml.safe_load`, `strict` toggling raise-vs-`{}`)
  imported by the non-Document module `domain/common/policy.py`. It
  shipped under GH-587 as "the single chokepoint for reading
  baseline-permissions.yaml" — i.e. this very pattern is already
  accepted architecture. `domain/documents/session_yaml.py:41`,
  `documents/plan.py:130`, and `documents/settings_document.py:88`
  also read inside `domain/` by design (the Document layer is D3's
  *sanctioned* I/O home).

- **ADR-0008 permits intra-`domain/` dependencies freely.** A
  Protocol + injection seam is required only "when one adapter needs
  a capability another adapter provides" (ADR-0008:83-87). A helper
  *inside* `domain/` consumed by other `domain/` modules crosses no
  boundary, so no Separated Interface is needed.

What remains is genuine: ~7 in-`domain/` raw reads with divergent or
absent error handling — `rule_engine.py:33` and `platform/registry.py:167`
have **no** `try/except`, so a malformed/missing file raises straight
out into the hook path, while their siblings degrade to `{}`.

## Decision

1. **Add a shared read-only helper** `src/dev10x/domain/common/config_io.py`
   exposing `load_yaml(path, *, strict=False)` and
   `load_json(path, *, strict=False)`. It performs **read + parse
   only**, with uniform handling of `FileNotFoundError`,
   `yaml.YAMLError`, and `json.JSONDecodeError`: tolerant mode returns
   `{}`, `strict=True` raises a single project error type. It has **no
   write counterpart** — write-back stays in `file_locks` /
   the Document layer. Home and shape mirror the shipped
   `domain/common/baseline_catalog.py` (GH-587), which becomes the
   canonical thin caller.

2. **Clarify ADR-0007 D3** (this ADR; cross-referenced from ADR-0007):
   the I/O-free invariant targets **read-modify-write / persistence**
   inside a Policy Rule. **Read-only config/catalog deserialization**
   via `config_io` is permitted in `domain/`. Guardrail: no
   `atomic_write_*` / write-back may appear in the same function as a
   `config_io.load_*` call — read-only stays read-only by
   construction, backstopped by review (and, later, a lint rule).

3. **Scope the helper to config/catalog *files*.** Not for
   subprocess stdout (`json.loads(result.stdout)` is a different
   category), not for inline markdown frontmatter parsing.

### Migration (resolves GH-536), ADR-safe order

| Site group | Action |
|------------|--------|
| `rule_engine.py:33` | Prefer deleting `from_yaml`; callers use the already-pure `from_config(Config)`. Failing that, route through `config_io` (adds the missing error handling). |
| `install_version.py:46,63`, `common/allow_rule.py:119` | Route through `config_io`. |
| `common/baseline_catalog.py:40` | Re-point onto `config_io` (or keep as the canonical example). |
| `documents/*` (`session_yaml`, `plan`, `settings_document`) | Already correct (Document layer); optional internal dedup onto `config_io`. |
| `file_locks.py:170,201` | **Stay as-is** — `config_io` would itself depend on `file_locks`; routing them risks an import cycle. |
| Outer-layer (`hooks/`, `commands/permission.py` ×11 JSON, `platform/registry.py:167`, `skills/permission/*`, `skills/notifications/*`) | Import `config_io` inward (legal, ADR-0008 rule #2). Fixes `registry.py:167` missing error handling. |
| uv-scripts (`skills/slack/slack-notify.py`, `skills/db-psql/scripts/parse-databases.py`) | **Stay self-contained** — cannot import `dev10x` (ADR-0010). |

The migration ships as GH-536 implementation work, separate from
this decision.

## Alternatives Considered

### Alternative A — helper under `domain/documents/`

Place the helper in the Document layer.

**Pros:** D3 explicitly blesses `domain/documents/` for I/O.
**Cons:** a stateless `load_*(path)` function is not a Document
(`Plan`, `SettingsDocument`, `SessionYamlDocument` are stateful
objects bound to a path); homing it under `documents/` mis-frames it,
and importing it from non-Document domain modules (`rule_engine`) is
awkward. The shipped precedent (`baseline_catalog`) lives in
`domain/common/`, not `documents/`.
**Verdict:** superseded by the selected placement (`domain/common/`),
which matches the precedent exactly.

### Alternative B — inject a `FileReader`/`YamlReader` Protocol into domain

Extend the ADR-0008 Separated-Interface pattern
(`domain/config_loader.py::ConfigLoader` ← `config/loader.py`) with a
low-level reader Protocol, injected into domain callers.

**Pros:** statically enforceable; matches the named pattern; gives a
test-double seam.
**Cons:** ADR-0008 reserves Protocol+injection for **adapter→adapter**
boundaries — an intra-`domain/` helper crosses none, so this is
ceremony with no boundary to invert. Free-function loaders
(`rule_engine.from_yaml`, `baseline_catalog.load_baseline_dict`) have
no natural injection point; adopting it forces either hidden
module-global seams or threading a `reader=` argument through every
caller. ADR-0013's `GitGateway` deferral logic applies: don't build
the seam until a caller needs the polymorphism.
**Verdict:** Deferred. **Revisit trigger:** a lint rule banning raw
`import yaml`/`import json` in `domain/**`, or a genuine test-double /
second-backend need.

### Alternative C — relax ADR-0007 D3 with a read-only carve-out

Same helper as the selected option, but framed as *amending* D3.

**Pros / Cons:** identical helper; differs only in framing. "Relaxing
an Accepted ADR" reads as rules bending under pressure, and "read-only
is fine" is a slippery slope toward read-modify-write unless the
helper is write-free by construction.
**Verdict:** Folded into the selected option as a **clarification**
(D3 always governed write-back), not a relaxation — with the
write-free-by-construction guardrail.

### Alternative D — dedicated infra `ConfigFileGateway` (ADR-0013)

Wrap filesystem read+parse as a named Gateway alongside
`dev10x.github` and `subprocess_utils`.

**Pros:** consistent boundary vocabulary; a home for cwd-aware
relative-path resolution.
**Cons:** the filesystem is an in-process syscall, not a
child-process/network boundary with auth/timeout machinery — calling
it a "Gateway" stretches ADR-0013's intent. ADR-0013 explicitly
deferred extracting a `GitGateway` class as "churn without a caller
that needs polymorphism" (ADR-0013:53-57) — the same objection lands
here.
**Verdict:** Deferred. **Revisit trigger:** cwd-aware config-path
resolution becomes a real cross-cutting need, or a second config
backend appears.

## Consequences

### What becomes easier

1. One documented home for read-only config/catalog parsing; the "which
   loader do I reach for?" confusion ADR-0007 set out to end no longer
   reappears for config I/O.
2. Uniform error handling retrofits the missing guards at
   `rule_engine.py:33` and `platform/registry.py:167` in one place.
3. GH-536 is unblocked with a low-churn, layering-safe plan.

### What becomes more difficult

1. Contributors must keep `config_io` read-only — no write-back in the
   same function. This is the intended constraint that keeps D3 intact.

### Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Slippery slope back to read-modify-write in domain | Medium | Medium | Helper is write-free by construction; review check (later lint): no `atomic_write_*` beside `config_io.load_*` |
| `config_io` overused for non-config reads | Low | Low | Scope documented (config/catalog files only); subprocess stdout and markdown frontmatter excluded |
| `file_locks` routed through `config_io` → import cycle | Low | Medium | Explicitly excluded from migration (table above) |

## References

### Internal

- [GH-536](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/536) —
  config loading consolidation (deferred pending this session)
- [GH-587] — `baseline_catalog` shared-loader precedent
- [ADR-0007](0007-rule-policy-archetype-unification.md) — Policy Rule
  I/O-free invariant (D3), clarified here
- [ADR-0008](0008-context-boundary-protocol.md) — dependency-direction
  rule; Separated Interface (`ConfigLoader`)
- [ADR-0010](0010-uv-script-skills-as-importable-modules.md) —
  uv-script exemption
- [ADR-0013](0013-gateway-layer.md) — Gateway layer; `GitGateway`
  deferral precedent

### External

- [The Clean Architecture](https://8thlight.com/blog/uncle-bob/2012/08/13/the-clean-architecture.html)
  — dependencies point inward
