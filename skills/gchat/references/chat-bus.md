# Chat bus service

The Chat bus (ADR-0035) turns Google Chat messages, mentions and
reactions into durable work items that local sessions claim.
It runs as one long-lived process, `dev10x chatbus run`, under a
systemd **user** unit, so it keeps running across terminals and comes
back after a crash.
This page covers the Google Cloud setup, the `chat_bus:` config block,
installing the unit and reading its status.

## What one tick does

Every 60 seconds the daemon:

1. reloads the allowlist if it received `SIGHUP`;
2. at start-up, or after a wall-clock gap longer than two ticks (a
   suspend or a stop), recreates a lapsed Workspace Events
   subscription and backfills every watched space from its cursor;
   otherwise renews the subscription once an hour;
3. polls the newest page of every watched space, DM and thread;
4. pulls one batch of reactions from the Pub/Sub subscription;
5. authorizes every new event against the `bus_role` allowlist;
6. hands owner-approved privileged items to a matching session or a
   new herdr worktree session.

A phase that fails is logged and retried on the next tick; the other
phases still run.
A window the daemon could not recover is recorded as a gap and shown by
`dev10x chatbus status`.

## Google Cloud prerequisites

Reactions reach the daemon through a Workspace Events subscription
that publishes to a Pub/Sub topic, read through a **pull**
subscription, so nothing needs a public endpoint.
Messages come from polling, and need no Cloud setup beyond the `gog`
grant the watcher already uses.

[Verify] The commands below follow Google's published setup for Chat
events through Workspace Events; they were not run end to end in the
session that wrote this page.

```bash
gcloud services enable chat.googleapis.com pubsub.googleapis.com \
  workspaceevents.googleapis.com
gcloud pubsub topics create chat-bus
# Chat publishes Workspace Events as this Google-owned service account.
gcloud pubsub topics add-iam-policy-binding chat-bus \
  --member=serviceAccount:chat-api-push@system.gserviceaccount.com \
  --role=roles/pubsub.publisher
gcloud pubsub subscriptions create chat-bus-pull --topic=chat-bus \
  --message-retention-duration=7d --ack-deadline=60
```

The daemon reads Chat history, pulls from Pub/Sub and manages the
Workspace Events subscription as **you**, through Application Default
Credentials.
Log in once with the scopes those calls need:

```bash
gcloud auth application-default login --scopes=\
openid,https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/chat.messages.readonly,\
https://www.googleapis.com/auth/chat.messages.reactions.readonly
gcloud auth application-default set-quota-project <project-id>
```

A subscription that carries resource data lapses after 4 hours; the
daemon renews it hourly and recreates it after a sleep.
Google documents reaction events for single-space subscriptions; the
daemon subscribes to `spaces/-`, which is unconfirmed (ADR-0035 risk
table).
Check `dev10x chatbus status` after the first reaction you add.

## Configuration

The daemon reads the `chat_bus:` block of `gchat-config.yaml`, next to
the `users:` allowlist it authorizes against (ADR-0035 D3):

```yaml
users:
  my-login:
    chat_user_id: "1234567890"
    bus_role: owner          # exactly one owner; trusted users optional

chat_bus:
  bot_user: users/9876543210 # required: the Chat bot's own user name
  spaces:                    # read whole, in addition to armed watches
    - spaces/AAAA1234567
  direct_messages:           # DMs with the bot, read whole
    - spaces/BBBB7654321
  pubsub:                    # omit to run on polling alone
    subscription: projects/<project-id>/subscriptions/chat-bus-pull
    topic: projects/<project-id>/topics/chat-bus
  dispatch:                  # omit to leave privileged work queued
    repo_root: /work/my/repo
  routes:                    # optional space -> session role routing
    spaces/AAAA1234567: web
```

| Key | Effect when absent |
|-----|--------------------|
| `bot_user` | the daemon refuses to start |
| `spaces`, `direct_messages` | only threads and spaces armed with `gchat-watch arm` are polled |
| `pubsub.subscription` | no reactions arrive; messages still do |
| `pubsub.topic` | the daemon pulls, but never creates or renews the Workspace Events subscription |
| `dispatch.repo_root` | approved privileged items wait in `queued`; sessions can still claim them |

The daemon refuses to start unless `users:` names exactly one owner.
After editing the allowlist, reload it without a restart:

```bash
systemctl --user reload dev10x-chatbus.service
```

A trusted user's privileged command waits in `awaiting_approval`.
The approval DM is not sent yet (GH-1932); the owner approves with
`approve <item id>` in a DM with the bot.

## Installing the service

```bash
uvx dev10x chatbus install-unit
```

The command writes `dev10x-chatbus.service` under
`$XDG_CONFIG_HOME/systemd/user/` (default `~/.config/systemd/user/`)
and prints the `systemctl --user` commands to enable it.
It never runs `systemctl` itself.
Re-running it leaves an identical unit untouched; a changed one is
rewritten and the printed steps add a restart.
Pass `--exec-start /path/to/dev10x` when the `dev10x` on `PATH` is not
the one the service should run.

The unit is `Type=simple` with `Restart=on-failure`.
It carries no secrets and sets no `PassEnvironment`: credentials come
from the ADC file and the keyring the Chat bot already uses.

## Status and logs

```bash
uvx dev10x chatbus status          # human-readable
uvx dev10x chatbus status --json   # for scripts
journalctl --user -u dev10x-chatbus.service -f
```

`status` reports the service state, the subscription's expiry, each
cursor's age, the queue depth per status (with expired leases) and the
open gaps.
It works before the store exists and never creates it.
A cursor that stops advancing while the service is `active` points at
a polling failure; the journal names the phase that failed.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Chat bus refused to start: ... exactly one user with bus_role: owner` | The allowlist names zero or several owners | Fix `users:` in `gchat-config.yaml` |
| `chat_bus.bot_user must be the bot's users/<id>` | `bot_user` missing or not a user name | Set it to the bot's `users/<id>` |
| Subscription `EXPIRED` in `status` | Renewal failed (scopes, API disabled) | Read the journal; re-run the ADC login with the scopes above |
| `poll spaces/...` failures in the journal | The `gog` grant expired | Re-authorize with `gog auth add` (see `dev10x:gog`) |
| Open gap with `window_exceeded` | The machine was off longer than the 7-day backfill window | Read the space by hand for that window |
