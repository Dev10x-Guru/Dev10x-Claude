# Permission-policy fixtures (PAP-0, GH-797)

Golden corpus for the PAP (Policy Administration Point) refactor
(PERM-M5, tracker #796).
Each case maps an input shape observed in the friction evidence corpus
(#271, #488, #726 — consolidated in #796 — plus #812) to the effect the
Policy engine *should* resolve.
The corpus is the regression safety net for PAP-1..PAP-5: the precedence
loader (GH-798), catalog migration (GH-799), and renderer (GH-800) are
asserted against these cases before any behavior changes ship.

This corpus complements `tests/fixtures/permission-friction/` (GH-271
Phase 0), which is organized by *command class*.
This one is organized by *surface* and carries the PAP dimensions
(`sensitivity`, `source_tier`) that the Policy model resolves on.

## Schema

One `<surface>.yaml` file per surface: `{surface, cases: [...]}`.
Required surfaces (GH-797 AC): `bash`, `mcp`, `skill-script`,
`skill-invocation`.
`self-settings.yaml` is a supplementary surface carrying the `.claude/`
write cells scoped by GH-812 S1.

| Field | Values | Meaning |
|-------|--------|---------|
| `id` | `<source>/<label>` | Provenance (evidence id, issue, or catalog group) |
| `input` | string | Verbatim command / tool-call / skill shape |
| `sensitivity` | `benign` \| `pii` \| `secret` \| `unspecified` | `dev10x.domain.common.policy.PolicySensitivity` |
| `effect` | `allow` \| `ask` \| `deny` | `PolicyEffect` — the ticket's permit/ask/forbid tri-state |
| `source_tier` | `plugin-default` \| `user-private` \| `project-local` | `PolicySource` — which tier should own the governing rule |
| `notes` | string | The *why* / classification rationale |

Vocabulary is validated against the domain enums by
`tests/permission/test_policy_fixture_corpus.py`, so the corpus and the
`Policy` model cannot drift silently.

## Classification principles

- `effect` records what the PAP engine *should* decide, not what the
  harness does today.
  `self-settings.yaml` is the clearest example: gitignored session-state
  writes should be `allow`, while today's self-settings gate fires `ask`
  regardless of matching rules (GH-812 RC-A).
- Reads never mutate → `allow`; sensitive reads (secrets, credentials,
  `.env`) → `ask` (DX014 semantics: prompt, never hard-block a probe).
- Destructive or irreversible shapes, arbitrary-code execution, chained
  prefix-shifting commands, and validation-skip escape hatches → `deny`.
- Guarded mutating wrappers (`push_safe`, skill pipelines) may be
  `allow` because the guardrails live inside the wrapper; their raw CLI
  equivalents are not granted the same effect.

## Provenance & honesty

Cases were hand-derived from the GH-271 Phase 0 corpus, the
`baseline-permissions.yaml` groups, session-guidance hook tables, and
the GH-812 evidence log.
Only shapes whose classification is defensible from first principles
are included — no heuristic extraction.

No production code consumes this corpus yet (GH-797 AC: fixtures +
loader-test only).
PAP-1 (GH-798) wires the precedence loader against it.
