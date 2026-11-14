# Machine-Readable Finding Schema

The auditor's Phase 7 report ends with exactly one fenced `json` block
holding every finding it proposes. `dev10x:permission-audit-apply`
reads that block and applies findings one at a time (GH-1631). The
prose report stays the human view; the block is the contract.

Parsed and validated by `dev10x.domain.common.audit_findings` — run
`dev10x permission findings <file>` to check a block.

## Shape

```json
{
  "findings": [
    {
      "id": "F3",
      "title": "rm allowed on any path",
      "severity": "HIGH",
      "file": "~/.claude/settings.local.json",
      "line": 41,
      "current_rule": "Bash(rm:*)",
      "proposed_fix": {
        "action": "replace",
        "list": "allow",
        "rule": "Bash(rm:*)",
        "replacement": "Bash(rm /tmp/Dev10x/:*)",
        "note": "keep scratch-root cleanup, drop arbitrary deletes"
      },
      "rationale": "rm -rf on any path runs without a prompt and no hook guards it"
    }
  ]
}
```

## Fields

| Field | Type | Rule |
|-------|------|------|
| `id` | string | Unique within the block; matches the `Finding #N` heading (`F3`) |
| `title` | string | The finding's heading text |
| `severity` | string | `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` — the Severity Definitions in the agent spec |
| `file` | string | Settings or instruction file the fix edits; `~` allowed |
| `line` | int or null | Line of `current_rule`, when known |
| `current_rule` | string or null | Exact rule text as it appears in `file` today |
| `proposed_fix.action` | string | `add`, `remove`, `replace`, or `manual` |
| `proposed_fix.list` | string or null | `allow`, `deny`, or `ask` — the `permissions` list edited |
| `proposed_fix.rule` | string or null | Rule to add, or the exact existing rule to remove / replace |
| `proposed_fix.rules` | list of strings, optional | Several exact rules one `add` / `remove` fix covers, each decided separately (GH-1868); not allowed on `replace` |
| `proposed_fix.replacement` | string or null | New rule text; required for `replace` |
| `proposed_fix.note` | string | One line for the approval prompt |
| `rationale` | string | Why — the risk the fix closes |

`add` and `remove` need `list` and either `rule` or `rules`; `replace`
needs `list`, `rule` and `replacement`. Use `manual` for everything
that is not an edit to a permissions list — register a hook, stabilize
a path, edit a CLAUDE.md line — and put the instruction in `note`; the
apply skill shows it but never edits for it.

## Multi-rule findings (GH-1868)

A finding that names a family — 15 interpreter wildcards, 60 denies in
10 families, 412 rules pinned to a retired plugin version — must list
every rule in `proposed_fix.rules`, never only in free-text `note`.
A rule named only in `note` has no apply path: the supervisor has to
ask for the list, and the approved removals end up as hand edits.

```json
"proposed_fix": {
  "action": "remove",
  "list": "allow",
  "rules": ["Bash(python3:*)", "Bash(node:*)", "Bash(ruby:*)"],
  "note": "interpreter wildcards run arbitrary code unprompted"
}
```

Prefer one finding per rule when the rules need different fixes; use
`rules` when one fix applies to all of them.

## What goes in the block

- Every finding listed under "Proposed changes" in the prose report.
- **Not** the "No action needed" group, and **not** anything under
  "Suppressed by accepted-findings" (Phase 4d) — a rejected proposal
  must not reach the apply skill either.

One malformed finding rejects the whole block, so a finding that
failed to parse can never be dropped silently from the applied set.
