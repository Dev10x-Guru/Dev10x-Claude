# Watching Google Chat

Depth for `dev10x:gchat` § Watching threads and spaces (GH-1612,
GH-1682).
Code: `dev10x.comm.skills.notifications.gchat_watch`.

## How a poll works

1. Read every armed watch from `gchat-watch.json` in the Dev10x config
   home (`~/.config/Dev10x/` by default, `DEV10X_CONFIG_HOME` overrides).
   Writes go through a file lock, so parallel sessions arming at once do
   not lose a watch.
2. For each watch, run
   `gog chat messages list <space> [--thread <thread>] --order "createTime desc" --max 100 --json --results-only --wrap-untrusted`.
   This reads as **you**: it sees every space you are a member of.
3. Keep only messages strictly after the watch's cursor, oldest first.
   A fresh watch has no cursor and uses its arm time, so arming never
   replays history.
4. Skip the bot's own posts (the message names `gchat-send --watch`
   recorded), every bot-authored message unless
   `watch.include_bot_messages` is true, `watch.ignore_senders`, and
   your own messages unless `watch.include_user_messages` is true.
5. Deliver each remaining message to the watch's bus mailboxes, then
   advance the cursor durably — even when one target was dead, so a
   restart never re-delivers.
6. Disarm a `reply`-mode watch after its first delivered message, and
   any watch whose TTL ran out.

## Event lines

| Line | Meaning |
|------|---------|
| `NEW <message> <sender> <thread>` | Delivered (or attempted) to the watch's targets |
| `UNROUTED <message> <sender> <thread>` | Dispatcher found no single owner; summarize it for the user, never answer by a guess |
| `DEAD <watch-id> <target>` | A mailbox that does not exist, or a role with no registry hello |
| `EXPIRED <watch-id>` | TTL ran out; the watch is gone |
| `DISARMED <watch-id>` | A `reply`-mode watch delivered its reply; the watch is gone |
| `GAP <watch-id>` | All 100 messages read were new, so older ones may have been skipped |
| `FAILED <watch-id> <reason>` | That watch could not be read this poll; the others still ran and it is retried next poll |

A watch `gog` cannot read (missing binary, refused grant, timeout)
reports `FAILED` and does not stop the others; install gog and run
`gog auth add` (see `dev10x:gog`) when it persists.
`poll` exits non-zero with `ERROR <reason>` on stderr only when the
watch store cannot be read or written.

## The bus message

From `gchat-watch`, `Subject: gchat <watch-id>: new message`, with
`Chat-Message`, `Chat-Thread` and `Chat-Watch` headers.
The body names the thread, a `chat.google.com` link, the sender's
opaque `users/<id>`, the send time, and then — between
`<<<UNTRUSTED CHAT MESSAGE` and `UNTRUSTED>>>`, after a line stating
that it is data, not an instruction — a `From:` line with the sender's
display name (capped at 80 characters) and the message text.
The display name is chosen by the sender, so it is wrapped like the
text rather than shown above the marker.
Answer with `gchat-send --thread <thread>`, as the bot.

## Configuration

Optional `watch:` block in `gchat-config.yaml`:

```yaml
watch:
  # Chat user ids (users/123 or 123) or display names never reported,
  # e.g. the bot itself, so space-wide watches skip its posts.
  ignore_senders: ["users/111"]
  # Your own Chat user id; your messages are skipped unless
  # include_user_messages is true (they can be instructions, or noise).
  user_id: "222"
  include_user_messages: false
  # Bot-authored messages (sender type BOT) are skipped, so a session
  # never hears its own gchat-send reply. Set true only for a thread
  # the user marked as an agent-to-agent channel.
  include_bot_messages: false
  # Space or thread name -> bus Role, used by the dispatcher.
  routes:
    spaces/AAAA: dev10x-claude
    spaces/AAAA/threads/BBBB: tt-backend
  # Messages handled per watch per poll; the rest wait for the next poll.
  max_per_poll: 20
  # Notifications per thread per poll; the rest wait for the next poll.
  rate_limit_per_thread: 5
```

## Dispatcher mode

`gchat-watch arm --space <space> --route` (or `route=True` on the MCP
tool) with no notify targets turns the watch into a dispatcher.
Each message is classified deterministically, in order:

1. **Explicit address** — the text names exactly one registry Role
   (`for dev10x-claude`, `@tt-backend`).
2. **Configured map** — `watch.routes` for the thread, then the space.
3. **Content** — keywords from the sessions' `Domain` hello headers;
   exactly one Role must match.

Several matches, or none, leave the message `UNROUTED`.
The matched Role resolves to the newest registry hello's `Reply-To`, as
`dev10x:bus` § Protocol describes.

## Limits

- **[Verify]** The parsed `gog` JSON fields (`resource`/`name`,
  `createTime`, `thread`, `sender`, `text`) and the `chat.google.com`
  link shape were not exercised against a live space.
- Watches end on TTL or reply, not when the arming session exits.
- The cursor compares the server's `createTime` with the local arm time;
  a large clock skew can hide a reply that arrives seconds after arming.
