---
name: Dev10x:yt-upload
description: >
  Publish a recording to YouTube as unlisted and hand back the embed form each
  destination can actually use — a bare watch URL for Linear (the only thing
  its editor will turn into a player) and a clickable poster frame for GitHub
  (which strips iframes).
  TRIGGER when: a video file needs to become a shareable link — a QA
  walkthrough, a demo recording, a bug repro.
  DO NOT TRIGGER when: capturing the recording (use Dev10x:qa-self),
  converting or verifying evidence files (use qa-self's own scripts), or
  publishing a full QA evidence set to a ticket and PR (use
  Dev10x:qa-publish, which calls this skill).
user-invocable: true
invocation-name: Dev10x:yt-upload
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/yt-upload/scripts/upload-video.py:*)
  - AskUserQuestion
---

# Dev10x:yt-upload — publish a recording as unlisted

Everything runs through `scripts/upload-video.py`. Never call `gog` or the
YouTube API directly — the wrapper owns token borrowing, scope verification,
artifact selection, channel assertion, and the shred-on-exit guarantee.

## Never publish a production recording

**Unlisted is not private.** Anyone holding the link can watch, forever, with
no org boundary and no audit trail. Staging fixtures are fine; production
recordings are not.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) before the first
upload in a session. The operator must *state* the judgement — a recording's
provenance is not something a script can determine, and letting it pass
silently is how real customer data reaches a world-readable URL. Options:

- **Staging / synthetic fixture — publish (Recommended)** — the footage shows
  seeded or `[TEST]` data only.
- **Contains real customer data — do not publish** — stop here; hand over the
  local file path instead.
- **Unsure** — treat as production and stop. Verify before publishing, not
  after.

A general "go ahead" earlier in the session does **not** satisfy this gate.
Neither does an approval from a caller's own review gate: approving *that the
footage is good* is a different decision from approving *that it may become
world-readable*.

## Review the footage locally first

An upload cannot be quietly withdrawn. When invoked from
`Dev10x:qa-self`, its Phase 4.4 gate has already shown the frames — but this
skill re-reads the narration manifest itself rather than assuming a caller
gated, because it can also be invoked directly.

**On a direct invocation, actually watch the footage** (`mpv --no-terminal
<file>`, or hand the path to the operator) before the gate below. A recording
is the one artifact whose defects are invisible to every automated check: the
capture run goes green while the overlay failed to install, a caption plays
over the wrong element, or the footage documents behaviour that changed last
week. A minute of human watching catches all three. A missing player is not a
reason to publish unreviewed — hand over the path instead.

```bash
${CLAUDE_PLUGIN_ROOT}/skills/yt-upload/scripts/upload-video.py \
  resolve-video --run-dir <RUN_DIR>
```

`resolve-video` picks the **one** artifact to publish and reports why. It
prefers `*-narrated.mp4` when present: `convert-evidence.sh narrate` writes
the narrated take as a *sibling* and deletes nothing, so a run directory can
hold both, and detection is presence-only — there is no manifest field saying
a run was narrated. Publishing both would put two near-identical videos on an
append-only evidence trail.

It also returns `narration_defects`. When that list is non-empty — captions
that played with no audio, or an `install` anchor that offsets every cue —
**do not publish without surfacing it.** A partly-silent or systematically
offset walkthrough is worse on YouTube than on a ticket: the ticket has
watchers, the URL has whoever holds it. Report the defects and re-capture, or
publish only on an explicit operator decision that names them.

**An empty `narration_defects` is not a quality verdict.** It means nothing
*mechanically* detectable went wrong — the overlay installed, the audio
rendered, the timing lines up. It says nothing about whether the captions are
*true*. A caption that renders perfectly and asserts something false about
the UI passes every check here.

That is not hypothetical: on one recorded run (TD-5642) the closing card
claimed an empty state reads as a sentence, which was true on one surface and
false on another — the video reached YouTube and a merged PR's evidence trail
before a human watching caught it and it was re-recorded. Never treat a clean
`resolve-video` as clearing the footage; that is what the human watching is
for.

## Commands

| Command | Purpose |
|---|---|
| `check` | Is gog reachable, is `youtube.upload` granted, who will publish |
| `pin` | Persist account/channel defaults to `~/.config/Dev10x/yt-upload.yaml` |
| `resolve-video` | Pick the one artifact to publish from a qa-self run dir |
| `upload` | Upload and return the per-destination embed forms |

```bash
${CLAUDE_PLUGIN_ROOT}/skills/yt-upload/scripts/upload-video.py check

${CLAUDE_PLUGIN_ROOT}/skills/yt-upload/scripts/upload-video.py \
  upload --video <RUN_DIR>/video/qa-GH-42-narrated.mp4 \
         --title "GH-42 — assigning a work order from the queue" \
         --description-file <RUN_DIR>/description.txt
```

Every command prints JSON to stdout. On failure it prints `{"error": "..."}`
to **stdout** and exits non-zero, so a caller parses one channel and never
sees empty output on failure.

**Always resolve a channel.** Without one, an upload lands on whichever
channel the grant happens to default to, silently. `upload` asserts the
stored channel matches and fails loudly if it does not — but only when a
channel is configured, so pin one.

## Use the returned markdown verbatim

`upload` returns `linear_markdown` and `github_markdown`. They are **not**
interchangeable, and hand-reconstructing either is how a link ends up
unclickable or an image ends up broken. See
[`references/destinations.md`](references/destinations.md) for why each
destination needs its own form, the poster-frame 404 window, and the
image-host trap that catches screenshots too.

Once a Linear comment is handed to a human to finish embedding, **stop
writing to that comment** — a later API write silently overwrites their edit.

## Prerequisites

This skill borrows a live token from [`gog`](https://gogcli.sh) rather than
holding a credential of its own, so there is no client secret to distribute
and nothing secret in the repo or the config file.

```bash
gog auth list          # copy the current service list FIRST
gog auth add <email> --services <that list> \
    --extra-scopes https://www.googleapis.com/auth/youtube.upload \
    --force-consent
```

Repeat the **existing** service list when re-authorizing. Omitting it silently
drops the Drive and Gmail grants that other skills depend on.

`check` reports what is missing. The YouTube Data API v3 must also be enabled
on the Cloud project behind the OAuth client; `check` names the console URL
when it is not.

### Why the script transfers the bytes itself

gog owns auth but **cannot carry the media body**, so the resumable
`videos.insert` is done here with gog's exported token. Verified against
`gog v0.34.1 (4747fb05, 2026-07-16)`:

- `gog youtube videos --help` — the only subcommand is `list`; there is no
  `insert`.
- `gog api call --help` — `--params` and `--body` take JSON only; there is no
  `--media` / `--upload-file`.

`videos.insert` needs a media body and `--body` is JSON, so no gog invocation
can move the file. Everything gog *can* do stays with gog: warming the token
(`youtube channels list --mine`), minting the credential (`auth tokens
export`), and confirming the upload landed (`youtube videos list --id`).

**Re-check this on a gog upgrade.** If a media flag appears, move the transfer
to gog and delete the hand-rolled `open_session`/`upload` pair — it exists
only because gog cannot do it.

Note `gog youtube videos list` without `-a <account>` falls back to the
API-key path and fails with "YouTube API key required" — the account flag is
what selects OAuth. The script always passes it.

## Account and channel preference

Resolved highest-first: flag → `DEV10X_YT_ACCOUNT` / `DEV10X_YT_CHANNEL` →
a matching `projects[]` entry in `~/.config/Dev10x/yt-upload.yaml` → its
`defaults` → nothing. There is deliberately **no built-in account default** —
a wrong-account default publishes to a stranger's channel, which is exactly
what a default must not invent.

```yaml
# ~/.config/Dev10x/yt-upload.yaml
defaults:
  account: you@example.com
  channel: UCxxxxxxxxxxxxxxxxxxxxxx
projects:
  - match: ["*/my-repo", "*/my-repo-*"]
    channel: UCyyyyyyyyyyyyyyyyyyyyyy
```

```bash
${CLAUDE_PLUGIN_ROOT}/skills/yt-upload/scripts/upload-video.py \
  pin --account you@example.com --channel UCxxxxxxxxxxxxxxxxxxxxxx
```

The file lives under `~/.config/Dev10x/` alongside the other durable prefs
(ADR-0018), so one answer covers a repo and every worktree of it and no
self-settings consent gate fires.

## How the token is handled

`gog auth tokens export` writes a live access token to a file. The script
creates that file's directory with `mkdtemp` — atomically, mode `0700`, owned
by the calling user — rather than building a path by hand: `mkdir(exist_ok=True)`
in a world-writable `/tmp` would silently reuse a directory another local user
pre-created and owns. Directory ownership is the control here, not path
secrecy. It also tightens the umask before invoking gog, so the file is
owner-only from creation rather than from the `chmod` that follows.

The token is used as a Bearer header, never logged, never passed in a gog
argv, and never included in the returned JSON. The OAuth client secret is
never read and the refresh token is never exchanged.

Cleanup shreds the file and removes its directory in a `finally`, so an
exception mid-upload still zeroes it, and a `SIGTERM` handler routes an
external `kill` through the same path — Python's default SIGTERM disposition
would otherwise kill the process without unwinding and leave the export
behind. `SIGKILL` and a host crash cannot be covered by any design. If
shredding fails, the script says so on stderr: a surviving export is a live
credential.

Shredding is best-effort, not a secure erase — on copy-on-write filesystems,
SSDs with wear levelling, or an encrypted volume the original blocks may
survive. That is an accepted trade-off for a token that lives for seconds and
that gog can revoke and reissue.
