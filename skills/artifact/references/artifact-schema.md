# Artifact document schema (`dev10x.artifact/v1`)

The local page is a JSON document. Overwatch renders every string as
plain text, so write prose, not HTML or Markdown.
`uvx dev10x overwatch artifact put <file>` validates it and names the
first bad field by path (`views[1].blocks[3].type`).

## Document

| Field | Required | Notes |
|---|---|---|
| `schema` | yes | `dev10x.artifact/v1` |
| `id` | yes | slug, `^[a-z0-9][a-z0-9-]{0,63}$`; reuse it for every revision |
| `title` | yes | short name, shown as the page heading |
| `description` | no | one line under the title |
| `meta` | no | `as_of`, `sources`, `asked_by` (strings) |
| `views` | yes | one or more; the first is the summary, evidence last |
| `revision`, `updated_at`, `owner`, `shares` | — | set by the store and the CLI; values you send are ignored |

The document stays under 512 KiB.

## View

`{"id": "summary", "label": "Summary", "group": "Overview", "badge": "",
"blocks": [...]}` — `id` is a slug, unique in the document; `group`
groups nav entries under a small label; `badge` is optional (`C4`, a
count).

## Blocks

| `type` | Fields | Use for |
|---|---|---|
| `claim` | `text` | The answer, stated as a claim, first in the summary |
| `prose` | `paragraphs: [str]` | Short explanation |
| `callout` | `tone`, `text` | One warning or note; `tone` is `ok`, `warn`, `bad` or `info` |
| `kv` | `items: [{key, value}]` | Key facts |
| `table` | `columns: [str]`, `rows: [[cell]]` | A cell is a string or `{text, tone}` (a pill) |
| `pills` | `items: [{text, tone}]` | Status at a glance |
| `stats` | `items: [{label, value, note}]` | Only when the numbers are the point |
| `mermaid` | `source` | Flows, sequences, states, C4-style boxes |
| `draft` | `label`, `text` | A ready-to-paste message; the page adds a copy button |
| `evidence` | `items: [{claim, ref, check}]` | `ref` is `file:line@sha`, a ticket, a PR or a query |
| `decisions` | `items: [{question, owner, control}]` | `control` names a control block that answers it |

### Controls

Each control has an `id` (slug, unique across the document) and sends
one event to this session when the supervisor uses it.

| `type` | Fields | Value the session receives |
|---|---|---|
| `button` | `label`, `tone` (`primary`, `danger`, `default`), `value` | `value`, or the label |
| `choice` | `label`, `options: [str]` (two or more), `multi` | the option, or a list when `multi` |
| `form` | `label`, `fields: [{name, label, kind, options}]`, `submit` | `{name: text}`; `kind` is `text`, `textarea` or `select`; a `select` value is one of its `options` or empty |

A control works only on the current revision. After you `put` a new
revision, presses made on the old page are refused and the page asks
for a reload.

## Example

```json
{
  "schema": "dev10x.artifact/v1",
  "id": "cache-rollout",
  "title": "Cache rollout: go or wait",
  "meta": {"as_of": "2026-11-14", "sources": "GH-1938, Grafana", "asked_by": "supervisor"},
  "views": [
    {"id": "summary", "label": "Summary", "group": "Overview", "blocks": [
      {"type": "claim", "text": "Roll out on Monday; the hit rate holds at 92%."},
      {"type": "decisions", "items": [
        {"question": "Ship Monday?", "owner": "supervisor", "control": "ship"}
      ]},
      {"type": "choice", "id": "ship", "label": "Ship Monday?", "options": ["Yes", "Wait a week"]}
    ]},
    {"id": "evidence", "label": "Evidence", "group": "Detail", "blocks": [
      {"type": "evidence", "items": [
        {"claim": "Hit rate 92%", "ref": "dashboard cache-hit, 7 days", "check": "read by the session"}
      ]}
    ]}
  ]
}
```
