# YouTube via gog

Reading channels, videos, playlists and comments — and the one thing gog
cannot do, which is why `Dev10x:yt-upload` exists.

**Publishing a recording is not this chapter's job.** Use
`Dev10x:yt-upload`, which owns the provenance gate, artifact selection,
channel assertion, token borrowing and the shred-on-exit guarantee. This
chapter is the gog surface underneath it.

## Command surface

```bash
gog youtube channels list --mine -a <email>
gog youtube videos list --id <videoId> -a <email>
gog youtube playlists <command>
gog youtube activities <command>
gog youtube comments <command>
gog youtube search <command>
gog youtube subscriptions <command>
```

## `-a <email>` is not optional

Without `-a`, `gog youtube` falls back to the **API-key path** and fails
with "YouTube API key required" — the account flag is what selects OAuth.
The error names a missing key, so the natural fix is to go hunting for
one; the actual fix is to name the account. Always pass `-a`.

## Setup: the two traps that are YouTube's own

Both are covered in full by
[`auth-setup.md`](auth-setup.md) — repeated here because YouTube is where
they bite:

1. **YouTube needs its own grant.** Google will not issue Drive and
   YouTube scopes in one consent, so appending
   `--extra-scopes .../youtube.upload` to a service list containing
   `drive` is refused with "scopes that cannot be requested together".
   Authorize `--services youtube` separately; the existing Drive and
   Gmail grants are untouched by doing so.
2. **`include_granted_scopes=true` re-adds Drive anyway** when the
   project's consent screen already carries Drive scopes. Edit it to
   `false` in the printed consent URL.

```bash
gog auth add <email> --services youtube \
    --extra-scopes https://www.googleapis.com/auth/youtube.upload \
    --force-consent --remote --step 1

gog auth add <email> --remote --step 2 --auth-url '<redirect URL>'
```

The YouTube Data API v3 must also be enabled on the OAuth client's Cloud
project. The failure says `accessNotConfigured` / "has not been used in
project", and it needs a few minutes to propagate after you enable it —
an immediate retry re-reports the same error and reads like the enable
did not take.

## There is no upload command

`gog youtube videos` offers `list` and `get`; there is no `insert`. And
`gog api call` takes `--params` / `--body` as **JSON only** — no
`--media` / `--upload-file` — so no gog invocation can carry a media
body.

That is the whole reason `skills/yt-upload/scripts/upload-video.py`
hand-rolls the resumable `videos.insert` with a token exported from gog.
Everything gog *can* do stays with gog: warming the token
(`youtube channels list --mine`), minting the credential
(`auth tokens export`), and confirming the upload landed
(`youtube videos list --id`).

**Re-check this on a gog upgrade.** If a media flag appears, the transfer
moves to gog and the hand-rolled `open_session`/`upload` pair is deleted —
it exists only because gog cannot do it.

## Resolve a channel before publishing anything

An upload with no channel resolved lands on whichever channel the grant
happens to default to, silently. `gog youtube channels list --mine`
enumerates what the grant can reach; pin the intended one
(`upload-video.py pin --channel UC…`) so the wrapper can assert the match
and fail loudly on a mismatch.

A wrong-channel publish is not quietly withdrawable — unlisted is
world-readable to anyone holding the link, forever.

## Verified against

`gog v0.34.1 (4747fb05)`. Re-check on upgrade: whether
`youtube videos` gains an `insert` subcommand, and whether `api call`
gains a media-body flag — either one retires the hand-rolled transfer.
