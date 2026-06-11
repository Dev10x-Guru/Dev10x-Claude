# Permission-friction fixtures (GH-271 Phase 0)

Executable-spec fixtures for the forthcoming PAP (Permission Access
Policy) classifier. Each row maps a real command observed in the GH-271
permission-friction evidence thread to the decision the classifier
*should* produce. Per GH-271 reflection #14, every evidence entry is
dual-purpose: scoping input **and** test-fixture input — this directory
is the fixture side.

## Schema

Each `<command_class>.yaml` file is `{command_class, rows: [...]}`. Each
row:

| Field | Values | Meaning |
|-------|--------|---------|
| `id` | `#N` | GH-271 evidence label (provenance) |
| `command` | string | The verbatim command that triggered friction |
| `tool` | `Bash` \| `Read` \| `WebFetch` \| `<mcp tool>` | Invoking tool |
| `friction` | `permission-prompt` \| `hook-block` \| `PREFIX_POISONED_CHAIN` \| `MISSING_RULE` \| `option-2-footgun` \| `agent-bouncing-loop` \| null | What was observed |
| `effect` | `allow` \| `ask` \| `deny` | Cedar-style decision — matches `dev10x.domain.common.policy.PolicyEffect` |
| `command_class` | `safe-read` \| `safe-write` \| `destructive` \| `fence-tool` \| `arbitrary-code` | Classification tier (reflection taxonomy) |
| `reversibility` | `trivial` \| `assisted` \| `none` | Tri-state (reflection #43) |
| `rule` | string \| null | Proposed `settings.json` rule shape |
| `notes` | string | The *why* / classification rationale |

`unclassified.yaml` is the triage backlog: it carries only `id`,
`command`, `tool`, `notes` — **no** `effect`/`command_class`, because the
thread prose did not determine them and we do not fabricate.

## Classification rules (how the seed was derived)

- `effect` follows `command_class`:
  - `safe-read` → `allow` (never mutates state)
  - `safe-write` → `allow` for local trivially-reversible writes; `ask`
    for shared/external-state writes
  - `destructive` → **never** `allow`; `ask` when assisted/trivially
    reversible, `deny` when irreversible or privilege-escalating
  - `fence-tool` (npx/uv run/uvx/yarn/pnpm dlx/pipx run/bunx/railway) →
    broad `ask`; specific safe sub-forms (`--version`, `uv run pytest`)
    may be narrow `allow`; the catch-all `Bash(<tool> *)` shape is the
    option-2 UI footgun and must be FORBID
  - `arbitrary-code` (`python -c`, `sh -c`, `bash <script>`, `perl -e`,
    raw `curl`) → `deny` — structured alternatives exist (jq, yq,
    yamllint, actionlint, or extract to `~/.claude/tools/<name>.py`)

## Provenance & honesty

The seed rows were **re-derived by hand** from the verbatim command +
`src/dev10x/skills/permission/baseline-permissions.yaml` + the GH-271
reflections. They were NOT taken from the heuristic extractor, whose
`effect`/`command_class` labels proved unreliable even on rows it marked
"clean" (e.g. `mkdir` → safe-read, `gh workflow run` → allow, a Slack
read → deny). Only rows whose classification is defensible from first
principles are included; everything else is in `unclassified.yaml` or
deferred to the triage handoff.

## Regeneration

Evidence + partitions are produced from the GH-271 thread by
`~/.claude/tools/gh271_curate.py`:

```
# 1. (Re-)extract the thread — issue_comments MCP wrapper is broken,
#    so use gh api directly:
gh api repos/Dev10x-Guru/Dev10x-Claude/issues/271/comments --paginate \
  --jq '.[] | {id:.id, body:.body}'   # + the issue body

# 2. Partition + emit unclassified.yaml:
~/.claude/tools/gh271_curate.py /tmp/gh271-evidence.json /tmp \
  tests/fixtures/permission-friction
```

Current counts: 315 evidence entries → 51 no-command notes, 91 with both
effect & class (69 "clean" / 22 incoherent per the parser), 173
unclassified. The classified `<class>.yaml` files are the hand-verified
subset; `unclassified.yaml` + the remaining candidates await triage (see
`docs/specs/GH-271-phase0-handoff.md`).
