# Publishing the video — the PR QA comment (GH-1991)

Depth for `SKILL.md` § Video. The rule that gates execution stays
inline there; this file carries the routing, the poster-frame wait and
the external-failure fallback.

## The PR QA comment is the destination, not an option

Every exploratory self-QA video ends as **one QA comment on the PR**:
the linked YouTube poster frame, the verdict in one line and the
fixture caveat when one applies.
It is posted whether or not a QA ticket exists.
`dev10x-qa:yt-upload` alone is never the end of the path — it returns
a link, and a link in the PR body or the pack does not give a reviewer
the poster frame they scroll to.

The comment format is owned by `dev10x-qa:qa-publish` § 6 and
[its `pr-comment.md`](../../qa-publish/references/pr-comment.md).

| Situation | Route |
|---|---|
| A QA ticket exists | `dev10x-qa:qa-publish` — ticket write-up plus the PR comment |
| Exploratory run, no ticket | `dev10x-qa:yt-upload`, then post the PR comment in the `qa-publish` § 6 shape with `mcp__plugin_dev10x_cli__pr_issue_comment` |

The no-ticket route carries the same three parts as the ticket route:

- the fixture-vs-production caveat above the video, when one applies;
- the verdict, in one line, from the per-case results, never from an
  exit code;
- the `github_markdown` poster frame that `yt-upload` returned.

One QA comment per PR: on a re-record, edit it in place with
`mcp__plugin_dev10x_cli__issue_comment_edit` instead of posting a
second one.

## The poster frame 404s for a few minutes

`yt-upload` returns `thumbnail_may_404: true`. `maxresdefault.jpg` and
`hqdefault.jpg` both answer 404 for the first minutes after upload and
come up together, so neither a lower resolution nor a text link is a
fix. Keep the poster embed in the comment: wait, probe the thumbnail
again, and post or edit once it answers 200.
Downgrading the poster to a plain text link is the failure this rule
exists to stop (GH-1991: both posters returned 200 a few minutes
later, and the comment had already shipped without them).

Measured window and the per-destination embed forms:
[`yt-upload/references/destinations.md`](../../yt-upload/references/destinations.md).

## Fallback — external failures only

When a piece fails for a reason outside the recording — TTS balance or
quota exhausted, a voice model that will not load, a cursor overlay
that errors in this environment — try that piece **once**, then ship
without it.
State the reason in the video description **and** in the pack's video
caption, e.g. *"No narration: TTS quota exhausted"*, so it is never
silently missing.
Never use this for a failure you caused: a broken script or a wrong
locator is a bug to fix, not a piece to drop.
