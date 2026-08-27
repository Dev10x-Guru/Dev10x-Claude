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

### 2. Per-skill labels: `skill:<name>`

One label per unique skill that appears in the findings table
"Skill" column. The `Dev10x:` prefix is stripped — e.g., findings
about `Dev10x:work-on` produce `skill:work-on`.

Color: `#1D76DB` (blue). Description:
`Findings about the Dev10x:<name> skill`.

These labels bundle all findings about the same skill so a
maintainer can sweep them in one fixup pass when touching the
skill.

### 3. Topical labels (heuristic)

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

1. Parse the findings file for the unique skill names
2. Initialize labels = `[enhancement]`
3. Add one `skill:<name>` per unique skill (after stripping `Dev10x:`)
4. Scan finding descriptions + proposed fixes against the topical
   heuristic table; add each matching topical label once
5. De-duplicate; cap at 8 labels per issue (GitHub UI noise)

Do **not** mint a per-session date label (the retired
`audit-YYYY-MM-DD` category): the session date already lives in the
issue body (`## Session Context` → `- **Date**: ...`), and dated
labels accumulate one per session with no bundling value beyond
what milestones provide.

## Ensure-exists protocol (best-effort)

GitHub fails issue creation if a label is missing, so reconcile the
set before filing. Every call below can fail for a reporter without
push access to `$TARGET_REPO` — label *creation* needs push access
and applying labels at filing needs triage access — and some `gh`
builds ship without the `label` subcommand at all. Treat the whole
protocol as best-effort: on any failure, file with no labels and
list the intended set in the issue body instead (GH-931 finding 6).
Filing beats bundling.

`$TARGET_REPO` is the destination confirmed by the caller (GH-816)
— a finding about a non-Dev10x plugin syncs labels at that
plugin's repo, not at the Dev10x one.

```bash
gh label list --repo "$TARGET_REPO" --limit 200 \
    --json name -q '.[].name' > /tmp/existing-labels.txt

for label in $LABELS; do
    grep -qxF "$label" /tmp/existing-labels.txt || \
        gh label create "$label" --repo "$TARGET_REPO" \
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
- ❌ Passing `--label` for a label that does not exist — `gh` fails the
  whole call on the first missing label. Reconcile first, or omit the
  flag entirely
- ❌ **Aborting the filing because labels are unavailable** — a
  non-maintainer can neither create nor apply labels, so a hard
  precondition makes the issue unfileable for exactly the reporters
  most likely to have findings (GH-931 finding 6). File unlabelled and
  put the intended labels in the body
