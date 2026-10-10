# Cowork, Voice and the Bus

How a Claude Desktop / claude.ai chat — typed or spoken — drives work
in Claude Code sessions through `dev10x:bus`. Verified 2026-10-09/10 on
one Linux host running both Claude Desktop and Claude Code.

## Who is who

Keep these words exact; confusing them cost a full morning once.

- **Cowork agent ("Cowork")** — a separate agent session inside the
  same claude.ai chat, with access to local folders and Desktop
  Commander. It is the one that writes bus files. Its mailbox name is
  the stable `cowork` (not a session ID, which changes with the model).
- **Voice session** — the spoken side of the chat. Its only reach into
  Cowork is the `send_to_cowork_agent` tool, which posts an instruction
  into the chat as if the user typed it. It cannot write files or
  touch the bus itself.
- **Subagent** (the `Agent` tool) — a short-lived helper that *Cowork*
  launches. Cowork runs each delegated job under its own subagent so
  jobs proceed in parallel; subagents editing the same file go one at
  a time or rebase. The voice session has no subagents. **Cowork is
  not a subagent** — when the user says "subagent" in voice, ask "to
  Cowork?".
- **Claude Code sessions** — repo work happens here. Each announces a
  `Role` in the registry (e.g. `dev10x-claude`, `gymos`, `kb`); Cowork
  delegates to them over the bus, or to its own cloud subagents.

## Delivery paths

| From | Reaches a Claude Code session how |
|------|-----------------------------------|
| Desktop chat, text | Cowork writes a file via Desktop Commander (`SendMessage` from the cloud is "not reachable") |
| Same chat, voice | voice → `send_to_cowork_agent` → Cowork → file; the answer returns the same way, ~1–2 min per loop |
| Claude Code on the same host | `SendMessage`, or the bus |
| Cloud Claude Code (claude.ai/code) | `SendMessage`; replies via its own remote `send_message` |

## Replying to a voice request

When a request carries `Voice: yes`, the reply is read aloud:

- At most three plain sentences — no tables, code, paths or
  abbreviations.
- Technical detail for the text side goes after a line
  `--- for the text session (do not read aloud) ---`.

## Merging work requested over the bus

A bus request starts work; it does not approve a merge. Merge only on
green CI **and** the supervisor's explicit go-ahead (or a standing
exception the supervisor named), through `dev10x:gh-pr-merge`.

## Limits

- **One host.** The Maildir lives in that host's `/tmp`. A Claude Code
  session on a *different* PC cannot see it, and `device_bash` in the
  chat does not see it either — only Desktop Commander on the same
  host does. Reaching another PC needs a transport the bus does not
  provide yet (a synced directory, or SSH from Desktop Commander);
  treat that as an open design question, not a workaround to improvise.
- Timestamps: take `Date` and the filename stamp from a clock tool,
  never from the model's head — a Cowork once stamped files ~15 min
  ahead, which scrambles mailbox order.

## For the Desktop chat

Paste this block into the Claude Desktop project instructions
(`dev10x:bus prompt` prints it).

```markdown
## claude-bus (local Maildir on this computer)

You (Cowork) write bus files with Desktop Commander; the voice session
asks you via send_to_cowork_agent. Your mailbox: /tmp/claude-bus/cowork/.

Find a recipient: list /tmp/claude-bus/registry/new and /cur, read the
`hello` files, take the NEWEST one whose `Role:` matches, and use its
`Reply-To` as the mailbox name. Never reuse a name from memory.

Send:
1. mkdir -p <root>/<mailbox>/{tmp,new,cur}
2. write_file <root>/<mailbox>/tmp/<YYYYMMDDTHHMMSS>.<random>.cowork.<topic>
3. mv it into <root>/<mailbox>/new/
Mark your own mail read: mv cowork/new/X cowork/cur/X:2,S

Message format:
---
From: cowork
To: <mailbox>
Date: <ISO-8601 from current_time>
Subject: <topic>
Message-ID: <stamp.random.cowork@claude-desktop>
In-Reply-To: <id you answer, if any>
Reply-To: cowork
Voice: yes            # only when the answer will be read aloud
---

<request, on the user's behalf>

First message in a new chat: Subject `hello` to registry with
Reply-To: cowork and Role: cowork.

Voice: call send_to_cowork_agent with "find <role> in the claude-bus
registry, send it <question> with Voice: yes, then check
/tmp/claude-bus/cowork/new/ about every 60 s and relay the answer
verbatim". Tell the user the answer arrives in 1–2 minutes; when it
does, read it aloud and skip everything after the "for the text
session" line.

Never: start Telegram polling, promise in voice to write something
yourself, or write outside /tmp/claude-bus/.
```
