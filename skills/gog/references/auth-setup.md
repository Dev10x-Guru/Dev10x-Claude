# gog OAuth setup

The grant every other chapter depends on. Setup fails in four
reproducible ways; each one below names the symptom first, because the
symptom rarely points at the cause.

`gog auth setup` walks the Cloud/OAuth/account sequence interactively and
is the right starting point. This chapter covers what it cannot do for
you and the failures that survive it.

## 1. The OAuth client must be a desktop app

**Symptom:** `redirect_uri_mismatch`, naming a localhost port. The port is
different on the next attempt.

gog binds a *random* loopback port for the consent callback. Only
desktop-app clients get Google's any-port redirect exemption — a web
client must pre-register every exact redirect URI, which is impossible
against a random port. Because the error names a port, it reads as a
port problem, and the natural next move (registering that port) fixes
nothing.

Create a **Desktop app** OAuth client. Do not reuse an existing web
client.

## 2. Use the two-step remote flow, not the browser flow

**Symptom:** `context deadline exceeded`, every time, on a flow that
works when run by hand in a terminal.

Claude Code backgrounds any command still running at 120s. The loopback
browser flow waits for a human to finish consent, which reliably exceeds
that, so the process is backgrounded and the callback never lands.

`--remote` splits the wait across two short commands:

```bash
# 1 — prints the consent URL and exits immediately
gog auth add <email> --services <service> --force-consent --remote --step 1

# 2 — paste the full redirect URL the browser landed on
gog auth add <email> --remote --step 2 --auth-url '<redirect URL>'
```

This is the documented path for agent sessions, not a fallback. It also
makes trap 4 fixable, because the URL is printed rather than opened.

`--manual` is the browserless sibling (paste the redirect URL); `--remote`
is the one to reach for, since step 1 exits cleanly rather than holding
the terminal.

## 3. Authorize incompatible services as separate grants

**Symptom:** `scopes that cannot be requested together`.

Google will not issue certain scope families in a single consent — Drive
and YouTube is the pairing that bites in this repo. So a command shaped
like:

```bash
# refused whenever the account already holds the Drive grant
gog auth add <email> --services drive,gmail,calendar \
    --extra-scopes https://www.googleapis.com/auth/youtube.upload
```

cannot succeed, and it is exactly the shape the "repeat your existing
service list or you will drop what you had" rule pushes you toward.

**Both rules are real; they apply to different operations.** Repeating
the full service list matters when you *extend an existing grant* —
omitting a service there silently drops it. It does not apply when you
authorize a new, incompatible service, which needs its own grant:

```bash
gog auth add <email> --services youtube \
    --extra-scopes https://www.googleapis.com/auth/youtube.upload \
    --force-consent --remote --step 1
```

A separate grant leaves Drive and Gmail untouched. Check what you
currently hold with `gog auth list`, and the available service names and
their scopes with `gog auth services`.

## 4. `include_granted_scopes` is hardcoded on

**Symptom:** `scopes that cannot be requested together` — *even after*
splitting the grant per trap 3.

gog sets `include_granted_scopes=true` on the consent URL
unconditionally. When the project's consent screen already carries Drive
scopes, Google folds them back into a request that never asked for them,
then refuses the combination it just assembled. A third-party
integration on the project is enough to put them there — a 1Password
integration is the case this was diagnosed on.

**Fix:** in step 1's printed URL, change `include_granted_scopes=true` to
`include_granted_scopes=false` before opening it. This is upstream gog
behaviour, so the workaround lives here rather than in a patch.

Re-check on a gog upgrade: if the parameter becomes configurable, this
trap and the hand edit both go away.

## Scope modes and extras

| Flag | Effect |
|------|--------|
| `--services` | `user` \| `all` \| comma-separated service names (`gog auth services` lists them) |
| `--drive-scope` | `full` \| `readonly` \| `file` — prefer the narrowest that works |
| `--gmail-scope` | `full` \| `readonly` |
| `--extra-scopes` | Comma-separated scope URIs appended after the service scopes |
| `--force-consent` | Force the consent screen so a refresh token is issued |
| `--readonly` | Requests read-only scopes at `auth add` time, and blocks mutations at runtime |

Prefer a narrow scope mode over `full`. A read-only grant is the one that
cannot be talked into deleting a Drive folder later.

## Diagnosing an existing grant

```bash
gog auth status      # auth configuration and keyring backend
gog auth list        # stored accounts
gog auth doctor      # auth, keyring and refresh-token diagnosis
gog auth services    # supported services and their scopes
```

Exit code `4` means auth, specifically — branch on it rather than
pattern-matching the message, which reads much like a not-found.

`gog auth doctor` is the first call when a command that worked yesterday
returns `4` today: an expired or revoked refresh token and a missing
keyring backend produce similar surface errors.

## Tokens

`gog auth tokens export` writes a **live access token** to a file. It is
a credential: create its directory with `mkdtemp` (mode `0700`, atomic)
rather than building a path in world-writable `/tmp`, tighten the umask
before invoking gog so the file is owner-only from creation, use it as a
Bearer header, and shred it in a `finally` plus a `SIGTERM` handler.
`skills/yt-upload/scripts/upload-video.py` is the worked reference
implementation.

Never log the token, never pass it in a gog argv, and never include it in
returned JSON.

## Verified against

`gog v0.34.1 (4747fb05)`. Re-check on upgrade: whether
`include_granted_scopes` becomes configurable (trap 4), and whether
`--remote --step` keeps its two-step shape (trap 2).
