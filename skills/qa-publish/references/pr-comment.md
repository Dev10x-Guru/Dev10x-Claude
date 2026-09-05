# The PR comment — caveats, supersede, poster frame

Depth for `SKILL.md` § 6. The rules that gate execution stay inline
there; this file carries the template, the check that produces it, and
the reasoning.

## Why a fixture caveat is a publishing concern

A QA fixture is chosen for convenience — an order with the right shape,
at a store the test user can reach. **Its feature flags are incidental,
and nobody checks them.**

The field case (GH-1213): fixtures were moved between stores mid-session
purely to find one with three services. The new store's dealer carried
`rollout-authorization-amounts`, which has **zero dealers in
production**. The published walkthrough therefore showed **Presented
total** and **Authorized amount** rows that no production shop will ever
see, in a video whose stated purpose was to demonstrate the PR. A
reviewer would reasonably have concluded the money rows were part of the
change under review.

Every existing gate passed. `verify-evidence.py`, the `qa-self` § 4.4
evidence review, and the `Dev10x:yt-upload` provenance gate all ask *is
the artifact well-formed* and *is the data synthetic*. **None asks: is
this configuration representative.** That is the gap this section fills.

## The check that produces the caveat

Before publishing, enumerate the flags, labels, and settings in force on
the chosen fixture and compare them to production.

For dealer labels the boolean alone is not the answer:
`enabled_for_all_dealers` and the per-dealer M2M are **ORed**, so only
the join says who actually has a label. A label reading `false` with a
populated M2M is enabled for those dealers; a label reading `true` is
enabled for everyone regardless of the M2M.

## Template

A GitHub alert callout is the right shape — it renders as a coloured,
iconned block that survives skimming, which a trailing note does not:

```markdown
> [!IMPORTANT]
> **The money rows in this video are not what production shows.** The dialog
> here displays **Presented total** and **Authorized amount** because the
> staging shop it was filmed on (dealer 585) carries
> `rollout-authorization-amounts`. That label has **zero dealers in
> production** — no production shop sees those two rows. They are not part of
> TD-5706 and this PR does not change them. Everything else in the video is
> what production will get.
```

## Why all three properties are required

A vaguer caveat is worse than none, because a caveat that only casts
doubt makes the whole artifact unusable. Require:

1. **What differs** — name the specific UI, rows, or behaviour.
2. **Why** — name the flag, label, or setting responsible.
3. **What is still trustworthy** — state plainly what in the video does
   represent production.

Property 3 is the one that gets dropped, and it is the one that keeps
the evidence usable.

## Why one comment, edited in place

A walkthrough gets re-recorded — four times in the field case, for
capture defects only a human watching could catch (#1204). Each
re-record produces a **new YouTube id**.

Posting a new comment each time leaves a PR carrying several comments
whose poster frames point at superseded videos, and `Dev10x:yt-upload`
cannot delete the old uploads (#1206), so they stay live indefinitely.

This is the same "the tool creates state it cannot clean up" shape as
#1206 and #1207 — and edit-in-place is the one destination where the
cleanup is actually available. Hence: one QA comment per PR, edited via
`mcp__plugin_Dev10x_cli__issue_comment_edit`.

## The poster frame 404s briefly

`Dev10x:yt-upload` returns `thumbnail_may_404: true`. YouTube takes a
minute or two to generate `maxresdefault.jpg`, so a PR comment posted
immediately shows a broken image. It resolves itself — do not "fix" a
correct embed, and do not switch to a lower-resolution thumbnail to
dodge it.
