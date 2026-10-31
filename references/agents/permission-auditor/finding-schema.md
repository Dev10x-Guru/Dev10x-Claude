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
| `proposed_fix.replacement` | string or null | New rule text; required for `replace` |
| `proposed_fix.note` | string | One line for the approval prompt |
| `rationale` | string | Why — the risk the fix closes |

`add`, `remove` and `replace` need `list` and `rule`. Use `manual` for
everything that is not a single edit to a permissions list — register
a hook, stabilize a path, edit a CLAUDE.md line — and put the
instruction in `note`; the apply skill shows it but never edits for it.

## What goes in the block

- Every finding listed under "Proposed changes" in the prose report.
- **Not** the "No action needed" group, and **not** anything under
  "Suppressed by accepted-findings" (Phase 4d) — a rejected proposal
  must not reach the apply skill either.

One malformed finding rejects the whole block, so a finding that
failed to parse can never be dropped silently from the applied set.
