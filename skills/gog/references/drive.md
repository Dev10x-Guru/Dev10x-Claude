# Google Drive via gog

Listing, searching, moving bytes, and — the part worth the most care —
sharing.

## Reading

```bash
gog drive ls [--folder <id>]           # list a folder (default: root)
gog drive search <query> ...           # full-text search
gog drive tree                         # read-only folder tree
gog drive du                           # folder size summary
gog drive get <fileId>                 # file metadata
gog drive raw <fileId>                 # lossless Files.Get JSON
gog drive inventory                    # read-only inventory export
gog drive drives                       # shared drives (Team Drives)
```

`gog drive search` takes free text by default. For an exact Drive API
query — `mimeType = '...'`, `modifiedTime > '...'`, `'<id>' in parents` —
pass `--raw-query`, otherwise your operators are searched for as words
and you get a confidently wrong empty result.

`raw` is the one to reach for when scripting: it is lossless, so a field
the friendlier commands omit is still there.

## Moving bytes

```bash
gog drive download <fileId> [--out <path>]
gog drive upload <localPath> [--folder <id>]
gog drive copy <fileId> <name>
gog drive mkdir <name>
gog drive move <fileId> --folder <id>
gog drive rename <fileId> <newName>
```

`download` **exports** Google-native formats rather than downloading them
byte-for-byte — a Doc becomes docx/pdf/txt depending on the requested
format. So a "download then re-upload" round trip is a conversion, not a
copy, and it loses comments and revision history. Use `gog drive copy`
to duplicate a native file.

`gog docs` and `gog slides` export through Drive for the same reason.

## Deleting

```bash
gog drive delete <fileId>              # moves to trash — recoverable
gog drive delete <fileId> --permanent  # gone
```

Trashing is recoverable and is the default; `--permanent` is not
recoverable by anyone, including Google support. Permanent deletion is
never a step to take on inference — it needs the supervisor to have asked
for that specific file, in those words.

## Sharing is the sharp edge

```bash
gog drive permissions <fileId>         # who can see it now
gog drive share <fileId> [flags]
gog drive unshare <fileId> <permissionId>
gog drive audit <command>              # audit sharing WITHOUT mutating
gog drive bulk <command>               # bulk permission operations
```

A share is outward-facing and effectively irreversible in the way that
matters: once a link has been opened, revoking it does not un-see the
content. Treat every `share` as publishing — state the file, the
recipient, and the access level, and get an explicit yes first.

**"Anyone with the link" is not privacy.** It is a world-readable URL
with no org boundary and no audit trail; the fact that it is unguessable
is not access control.

`gog drive audit` exists precisely so you can answer "who currently has
access?" without changing anything — run it before proposing a share, and
after a bulk operation to confirm the result. `gog drive bulk` multiplies
one mistake across a whole tree, so dry-run it (`-n`) first and read the
plan.

## Shortcuts, labels, comments, revisions

```bash
gog drive shortcut <command>     # shortcuts to files and folders
gog drive labels <command>       # read and modify Drive labels
gog drive comments <command>     # comments on files
gog drive revisions <command>    # list and inspect revisions
gog drive changes <command>      # track changes for sync/automation
gog drive activity <command>     # Drive Activity audit events
gog drive sync <command>         # reconcile local files with Drive
```

A shortcut resolves to a file the viewer may not have access to — so
sharing a folder of shortcuts shares nothing, and an inventory that
counts shortcuts as files overcounts. `gog drive activity` answers "who
changed this and when" and is the right tool for a forensic question,
rather than inferring from `modifiedTime`.

## Scope down

`--drive-scope` at `auth add` time takes `full`, `readonly`, or `file`
(per-file access to what the app created or the user opened). Prefer the
narrowest that works: a `readonly` Drive grant is structurally incapable
of the deletion and the accidental re-share, which no amount of care at
call time can guarantee.

Add `--readonly` at runtime for a session that only needs to read.

## Aliases

`gog ls`, `gog search`, `gog download`, `gog upload` are top-level
aliases for the `drive` subcommands. They are convenient interactively;
prefer the explicit `gog drive …` form in scripts and docs so the target
service is legible.

## Verified against

`gog v0.34.1 (4747fb05)`. Re-check on upgrade: `download`'s export
behaviour for native formats, and the `bulk` subcommand surface.
