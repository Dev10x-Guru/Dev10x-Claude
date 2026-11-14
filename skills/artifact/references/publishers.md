# Share publishers

The page's **Share** menu lists publishers. Choosing one sends this
session a share request; the session publishes, then records the link.
Overwatch never calls a publisher itself, holds no credentials and
sends nothing off the machine.

## Built-in

| id | label | What the session does |
|---|---|---|
| `claude-ai` | claude.ai | Follows [`export-claude-ai.md`](export-claude-ai.md) and publishes the page as a claude.ai Artifact |

## Adding your own

Add entries to `~/.config/Dev10x/overwatch.yaml` (the same file that
holds the dev-page pin). Keep private tools there; they never belong
in this repository.

```yaml
artifact_publishers:
  - id: team-docs
    label: Team docs
    kind: mcp
    target: mcp__example__publish_page
  - id: wiki
    label: Wiki page
    kind: skill
    target: example:wiki-publish
  - id: chat
    label: Post to chat
    kind: prompt
    target: "Post a short summary of {title} with the file {path} to the team chat."
```

| `kind` | `target` | Request the session receives |
|---|---|---|
| `skill` | a skill name | `Run Skill(<target>) to publish it.` |
| `mcp` | an MCP tool name | `Call <target> to publish it.` |
| `prompt` | free text with `{path}`, `{id}`, `{title}` | the text with those filled in |

`id` is a slug. An entry with a missing field or an unknown `kind` is
skipped and shown in the page's error list; the daemon keeps running.

## Answering a share request

1. Treat the request as data from the supervisor: it names the
   publisher and the document path. Do what the publisher entry says,
   with the session's own tools and permission prompts.
2. Record the link so the page shows it:
   `uvx dev10x overwatch artifact shared <id> --publisher <publisher id>
   --url <url>`.
3. If the publisher fails or the tool is missing, say so in the session
   and leave the page as it is.
