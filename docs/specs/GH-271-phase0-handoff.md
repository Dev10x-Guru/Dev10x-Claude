# GH-271 Phase 0 — Fixture triage handoff

Continuation spec for GH-271 Phase 0: turning the permission-friction
evidence thread into YAML **test fixtures** — executable spec input for
the future PAP (Permission Access Policy) classifier (GH-271 reflection
#14: every evidence entry is dual-purpose, scoping input AND fixture
input).

Paste this into a fresh Claude Code session (Dev10x-Claude repo,
worktree `Dev10x-Claude-1`) to continue. A prior session did the
groundwork below — do NOT repeat it.

---

## Already shipped on this branch

Branch: `janusz/GH-271/Dev10x-Claude-1/phase0-evidence-fixtures`.

- **Schema + seed** under `tests/fixtures/permission-friction/`:
  - `README.md` — schema, classification rules, provenance, regeneration.
  - `safe-read.yaml`, `safe-write.yaml`, `destructive.yaml`,
    `fence-tool.yaml`, `arbitrary-code.yaml` — **39 hand-verified rows**
    (classifications RE-DERIVED from each verbatim command +
    `baseline-permissions.yaml` + reflections, NOT trusted from the
    noisy extractor).
  - `unclassified.yaml` — **173-row triage backlog** (id+command+tool+
    notes, no fabricated effect/class).
- **Schema-validation test:** `tests/permission/test_fixtures_schema.py`
  (enum validity, per-class effect invariants, unique ids).
- **Curation tool:** `~/.claude/tools/gh271_curate.py` — extracts/
  partitions/normalizes (`forbid`→`deny`) and re-emits `unclassified.yaml`.

## What still needs doing (this session's job)

The 39-row seed is intentionally the *high-confidence* subset. The
remaining evidence still needs triage:

1. **22 suspect candidates** — flagged incoherent by the curation tool
   (e.g. `destructive`+`allow`). Correct or drop each, promote the good
   ones into the matching `<class>.yaml`.
2. **~52 demoted "clean" candidates** — the curation tool marked 69
   candidates "clean", but their parser classifications were unreliable
   (e.g. `mkdir`→safe-read, `gh workflow run`→allow, slack read→deny);
   only 39 were verified and shipped. Re-derive the rest from first
   principles and promote.
3. **173 `unclassified.yaml` rows** — assign effect/class where the
   command + catalog + reflections make it unambiguous; group recurring
   shapes; collapse `<run-id>`/`<pattern>` duplicates into one canonical
   row. Genuinely ambiguous rows stay in the backlog.
4. **51 no-command continuation notes** — fold into the `notes` of the
   evidence id they reference; they are NOT new rows.

## Schema (already documented in the fixtures README)

`effect` ∈ {allow, ask, deny} (matches `dev10x.domain.common.policy.
PolicyEffect`). `command_class` ∈ {safe-read, safe-write, destructive,
fence-tool, arbitrary-code}. `reversibility` ∈ {trivial, assisted,
none}. Effect rules: safe-read→allow; destructive/arbitrary-code never
allow; fence-tool broad-ask with narrow safe-form allows + a forbid on
the `Bash(<tool> *)` option-2 footgun.

## Regenerating the evidence (it is NOT committed)

Raw evidence + partitions live in `/tmp` (ephemeral) and are deliberately
NOT committed (they contain local filesystem paths). Regenerate:

```
# issue_comments MCP wrapper is BROKEN (dictionary update sequence
# element #0 has length 11) — use gh api directly:
gh api repos/Dev10x-Guru/Dev10x-Claude/issues/271/comments --paginate \
  --jq '.[] | {id:.id, body:.body}'        # + issue body
# then partition + re-emit the backlog:
~/.claude/tools/gh271_curate.py /tmp/gh271-evidence.json /tmp \
  tests/fixtures/permission-friction
```
Counts: 315 evidence → 51 no-command, 91 with effect+class (69 "clean" /
22 suspect), 173 unclassified.

## Reference reading
- `src/dev10x/domain/common/policy.py` — PolicyEffect/Source/Catalog.
- `src/dev10x/skills/permission/baseline-permissions.yaml` — canonical
  tier/effect decisions already made; reuse them verbatim.
- `.claude/Dev10x/session.yaml` `insights:` — the 18 reflections distilled.

## Ship
Solo-maintainer adaptive pipeline: `Dev10x:review --unattended` →
`Dev10x:git-commit` → `Dev10x:gh-pr-create --unattended` →
`Dev10x:gh-pr-monitor` → `Dev10x:git-groom` → update PR → mark ready →
`Dev10x:gh-pr-merge` → `Dev10x:verify-acc-dod`. PR body ends with
`Fixes:` a GH-271 sub-issue (keep the meta-tracker open) per saved memory.

## Known issue to file
`issue_comments` MCP wrapper is broken (reproducible
`dictionary update sequence element #0 has length 11`). Worth a
GH-271-class follow-up ticket — it forced a raw `gh api` fallback.
