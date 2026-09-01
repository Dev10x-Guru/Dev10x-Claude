# Per-destination embed forms

Why `upload` returns two markdown fields instead of one, and the host traps
that make them non-interchangeable.

> **Provenance.** These claims have three different strengths, and lumping
> them together once already caused an error on this page. Read the tier
> before acting on a claim.
>
> **Measured** on a real run (TD-5642 / PR #1931, video 5:14, ~10 MB): the
> poster-frame 404 window, with the bound stated in that section.
>
> **Confirmed against the source skill** being ported: the
> `linear_markdown` / `github_markdown` split, the production-recording
> prohibition, and Linear's paste-time embed behaviour — its author observed
> the latter directly.
>
> **[Verify] Unverified by anyone.** The `img.youtube.com` /
> `uploads.linear.app` cross-over, and the Jira anchor behaviour. These come
> from the ported skill's **own documentation**, not from any run — an
> earlier version of this page wrongly filed the cross-over under the field
> report, which would have laundered inherited folklore into a corroborated
> observation. The session that ran the tool explicitly declined to
> corroborate it: they only ever used `img.youtube.com` on GitHub (rendered
> fine, camo-proxied) and a bare URL in Linear, and never tested either host
> in the opposite destination. Measuring it wants a deliberate two-post test
> on a scratch issue.

## Linear wants a bare watch URL

Linear's YouTube player is built at **paste time, in its editor**. Nothing
posted through the API ever embeds — so a human has to cut the URL and
re-paste it to get a player.

That makes a bare URL strictly better than a titled link: a link hides the
URL behind the edit view, so the human cannot easily retrieve the thing they
need to re-paste.

```markdown
https://www.youtube.com/watch?v=<id>
```

Once you hand a comment to a human to finish embedding, **stop writing to
it**. A later API write silently overwrites their edit.

## GitHub wants a linked poster frame

GitHub strips `<iframe>`, so no player can render in a comment or PR body. A
linked poster frame is the closest equivalent — and unlike a plain link, it
cannot be scrolled past.

```markdown
[<img src="https://img.youtube.com/vi/<id>/maxresdefault.jpg" width="640">](https://www.youtube.com/watch?v=<id>)
```

## The poster frame 404s for the first minutes after upload

Measured on a 5:14 / ~10 MB unlisted upload:

| When | `maxresdefault.jpg` | `hqdefault.jpg` |
|---|---|---|
| Immediately after `videos.insert` returned | 404 | not checked |
| ~1 min later | 404 | 404 |
| ~2 min later | 404 | 404 |
| Later in the same session | 200 | 200 |

So the window is **at least ~2 minutes for both sizes**, and both were live
by the end of the session. The upper bound is loose — under ~15 minutes, and
not worth stating more precisely than that, because the run did not poll on a
timer. `upload` therefore returns `thumbnail_may_404: true`.

**The fallback is time-based, not size-based.** Dropping from
`maxresdefault.jpg` to `hqdefault.jpg` does *not* help: they 404 together and
come up together. Any advice of the form "fall back to hqdefault, which
always exists" is wrong during this window.

Probe the thumbnail before committing to a poster. If it is not ready, post
the comment with a plain link and edit the poster in afterwards — a broken
image is worse than a link, because it reads as a mistake rather than as a
pending asset.

## The image hosts do not cross over

This is the trap that catches screenshots as well as posters:

| Host | GitHub | Linear |
|---|---|---|
| `img.youtube.com` | renders (camo-proxied) | does **not** render |
| `uploads.linear.app` | 401 for everyone | renders |

So a screenshot uploaded to Linear must never be linked from a GitHub
comment, and a YouTube poster must never be used inside Linear. There is no
single markdown that works in both places, which is the whole reason
`upload` returns two fields.

Google Drive links embed nowhere. Use them as links only.

## Jira-synced Linear issues need a threaded reply

An issue synced to Jira carries a null-author anchor comment marking the
sync. A **top-level** comment on such an issue never reaches Jira watchers —
it has to be a reply.

Check `list_comments` for that anchor and pass its id as `parentId` when
posting. `Dev10x:qa-publish` does this as part of its ticket step.

## Privacy is a publishing decision, not a setting

`unlisted` means anyone with the link can watch, indefinitely, outside any org
boundary. `private` plays **only** for the uploader — it will not play for a
teammate and will not render embedded, so it is not a way to share something
cautiously; it is a way to publish something nobody can watch.

There is no privacy level that makes a production recording safe to upload.
That is why the prohibition is a gate in `SKILL.md` rather than a default
here.
