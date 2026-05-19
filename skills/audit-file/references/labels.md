# Bundling Label Taxonomy

Labels applied to upstream skill-audit issues so similar findings
can be grouped and worked together during implementation.

## Goal

When several audit issues share a root cause (e.g., five findings
about permission friction across different skills), a maintainer
should be able to filter by one label and address them as a bundle
rather than re-discovering the relationship per issue.

## Label Categories

### 1. `enhancement` (always applied)

Every audit-filed issue carries this label — it places the issue
in the standard "feature request" backlog and matches GitHub's
default label set.

### 2. Audit-session label: `audit-YYYY-MM-DD`

One label per audit session, derived from the **Audit date** line
in the findings file (`## Session Context` → `- **Date**: ...`).
All findings filed from a single audit session share this label.

Precedents already present in `Dev10x-Guru/Dev10x-Claude`:

- `audit-2026-04-29` — Skill-audit findings from session c83f5182
- `audit-2026-05-09` — Architecture audit 2026-05-09 findings

Color: `#5319E7` (purple). Description:
`Skill-audit findings from session YYYY-MM-DD`.

### 3. Per-skill labels: `skill:<name>`

One label per unique skill that appears in the findings table
"Skill" column. The `Dev10x:` prefix is stripped — e.g., findings
about `Dev10x:work-on` produce `skill:work-on`.

Color: `#1D76DB` (blue). Description:
`Findings about the Dev10x:<name> skill`.

These labels bundle all findings about the same skill so a
maintainer can sweep them in one fixup pass when touching the
skill.

### 4. Topical labels (heuristic)

Topical labels capture cross-cutting failure modes so that issues
about the same anti-pattern across different skills cluster
together. Apply each label when the heuristic matches any finding
description, classification, or proposed fix.

| Label | Heuristic match (case-insensitive) | Precedent |
|-------|-----------------------------------|-----------|
| `permission-friction` | "permission prompt", "allow rule", "friction" | existing label |
| `silent-failure` | "silent", "swallowed", "no error surfaced" | new |
| `routing-bypass` | "raw `git`", "raw `gh`", "bypass skill", "skill routing" | new |
| `gate-bypass` | "plain text", "skipped AskUserQuestion", "decision gate" | new |
| `compaction-loss` | "after compaction", "lost context", "routing table" | new |
| `task-orchestration` | "TaskCreate skipped", "task list", "phase task" | new |
| `playbook-drift` | "ad-hoc plan", "playbook", "fragment" | new |

Color: `#D73A4A` (red). Description: tied to the anti-pattern.

## Label Resolution

1. Parse the findings file for the audit date and unique skill names
2. Initialize labels = `[enhancement, audit-<date>]`
3. Add one `skill:<name>` per unique skill (after stripping `Dev10x:`)
4. Scan finding descriptions + proposed fixes against the topical
   heuristic table; add each matching topical label once
5. De-duplicate; cap at 8 labels per issue (GitHub UI noise)

## Ensure-exists protocol

GitHub fails issue creation if a label is missing. Before filing:

```bash
gh label list --repo Dev10x-Guru/Dev10x-Claude --limit 200 \
    --json name -q '.[].name' > /tmp/existing-labels.txt

for label in $LABELS; do
    grep -qxF "$label" /tmp/existing-labels.txt || \
        gh label create "$label" --repo Dev10x-Guru/Dev10x-Claude \
            --color "$COLOR" --description "$DESCRIPTION"
done
```

Use the colors and descriptions from the tables above. Skip the
create call for labels already present — `gh label create` errors
on duplicates and `--force` is not idempotent across descriptions.

## Anti-patterns

- ❌ Hardcoding a single `enhancement` label — defeats the bundling goal
- ❌ Adding a label per finding row — labels are issue-level, not row-level
- ❌ Creating labels with the real (non-fictional) skill name when the
  finding references a private project skill — public Dev10x skills only
- ❌ Filing the issue without ensuring labels exist — `gh` fails the
  whole call on the first missing label
