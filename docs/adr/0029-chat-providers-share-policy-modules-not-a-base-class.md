# ADR-0029: Chat providers share policy modules, not a base class

- **Status:** Accepted
- **Date:** 2026-09-26
- **Supersedes:** none
- **Amends:** none
- **Related:** GH-1441, GH-1423, GH-1421, GH-1307, GH-1451, ADR-0013,
  GH-1454 (the same "no forced common base" call for documents)

## Context

Slack and Google Chat each ship two sibling modules with a similar
shape:

| Layer | Slack | Google Chat |
|---|---|---|
| Review request | `skills/notifications/slack_review_request.py` (238 lines) | `gchat_review_request.py` (383) + `gchat_cards.py` (213) |
| Transport | `skills/notifications/slack_notify.py` (666) | `gchat_notify.py` (547) |

(All paths are under `src/dev10x/`.)

The 2026-09-19 audit (`docs/memos/architecture-audit-2026-09-19.md`
§ F2) proposed a `ChatProvider` protocol plus a shared
`review_request_base.py`. It recommended deferring that work behind an
explicit trigger: "a third provider is planned, or a second
cross-ported bug fix appears". GH-1441 exists to record that trigger
deliberately. This ADR checks the audit's premise against history
before recording it.

### What the history shows

**At the review-request layer, the fixes did not need porting.** Every
GH-referenced fix in `gchat_review_request.py` concerns a Chat-only
feature:

| Fix | What it touched | Slack equivalent? |
|---|---|---|
| GH-1113 | cardsV2 formatted text | none. Slack posts mrkdwn text |
| GH-1115 | `card` defaults on | none. No `card` key |
| GH-1262 | `preview` deploy-URL button | none |
| GH-1307 | `default_card` reaching the ask branch (`gchat_review_request.py:85-91`) and the ask envelope (`:268-289`) | none. `slack_review_request.py:41-62` resolves no `card` or `default_*` key |

GH-1441's "immediate, cheap action" was to check whether GH-1307's
fix needs porting to Slack. **It does not.** The fixed field does not
exist on the Slack side.

The code the two review-request modules truly share is small.
`load_yaml` is 6 lines (`slack_review_request.py:33-38`,
`gchat_review_request.py:25-30`). The three-branch resolver is about
20 lines. `resolve_mention` is 14 lines and differs in its token
spelling. `_repo_name` is already shared: GH-1451 (`895bbd5d`) moved
both copies onto `RepositoryRef.basename_or`. The remaining 150+
lines per side are provider-specific. A base class would hoist about
40 lines and put a protocol in front of divergent features.

**At the transport layer, a real cross-port was missed.** `cac896d0`
(2026-09-21) adopted two provider-neutral policies on the Slack path
only:

- GH-1423 retry, via `domain/retry.py`, applied at `call_slack_api`
  (`slack_notify.py:209`)
- GH-1421 dead-letter log, via `domain/dead_letter.py`, applied at
  `notify_slack` (`slack_notify.py:404-438`)

`gchat_notify._request_json` (`gchat_notify.py:267-300`) is still a
single `urlopen` attempt, and `notify_gchat` (`:492-514`) records
nothing. Its docstring still claims it "mirrors
`slack_notify.notify_slack`" (`:503`). A Chat-only team therefore
loses exactly the "crew stalled" ping that GH-1421 was written to
save.

### Problems

1. The audit located the risk at the review-request layer. The
   evidence puts it at the transport layer.
2. The missed port was not caused by missing shared code. The shared
   code (`domain/retry.py`, `domain/dead_letter.py`) already exists
   and is deliberately provider-neutral. GH-1423 made it "a pure
   policy, since the gh path is async over a subprocess and the Slack
   path is synchronous urllib". What was missing was an **adoption
   check**: nothing noticed that one provider had adopted a policy
   and the other had not.

## Decision

1. **No `ChatProvider` base class or `review_request_base.py` now.**
   The review-request layers share about 40 lines and diverge
   everywhere else. That is the same call GH-1454 made for persisted
   documents: a forced common base is not paid for by coincidental
   shape.
2. **Cross-cutting transport behaviour lives in provider-neutral
   `domain/` policy modules, and every chat transport adopts them.**
   `domain/retry.py` and `domain/dead_letter.py` are the current
   members. A future concern of the same kind (rate-limit budgeting,
   redaction, timeouts) goes into the same kind of module, never into
   one provider's file.
3. **Adoption is guarded by a parity test.** The test asserts that
   every chat transport module uses each shared policy. A policy
   adopted by one provider then fails a test until the other adopts
   it too. This is the mechanism that would have caught the
   `cac896d0` miss. It lands with follow-up GH-1479, which also ports
   the missing retry and dead-letter handling to Google Chat.
4. **The trigger for extracting a shared base**, whichever comes
   first:
   - a **third chat provider** is planned, since three copies of the
     resolver and envelope make the hoisted code worth a protocol, or
   - a **second recorded cross-port miss**. The GH-1423/GH-1421
     transport miss recorded here is the first, and D2 and D3 address
     its cause. A second miss that lands *after* the parity test
     exists would show that shared policy modules are not enough.

   GH-1307 does not count, because it was never a cross-port. Record
   each further miss in this ADR's References.

## Alternatives Considered

### Alternative 1: Extract `ChatProvider` now (audit sketch)

**Pros:** One resolver, one `cmd_prepare` skeleton.

**Cons:** It hoists about 40 lines behind a protocol whose methods
(`resolution_fields`, `format_mention`) exist mainly to carry
differences. It would not have prevented the one real miss, which was
at the transport layer and went through modules that are already
shared. Effort is L.

**Verdict:** Rejected. It pays L effort for the layer that was not
leaking.

### Alternative 2: Defer with the audit's trigger unchanged

**Pros:** It matches the milestone text.

**Cons:** The trigger counts "cross-ported bug fixes" without
checking whether they were cross-ports. GH-1307 would have been
counted as one. The trigger also names no mechanism, so the next
transport policy would land on one side again.

**Verdict:** Rejected as stated. It is kept in revised form: the
trigger in D4 plus the adoption guard in D3.

### Alternative 3 (Selected): Shared policy modules + parity guard + revised trigger

**Pros:** It closes the observed failure mode at its layer, costs one
small test, and keeps the providers free to diverge where their
features do.

**Cons:** The parity test needs an explicit list of transport modules
and shared policies. A third provider must be added to it, and doing
so is itself the trigger for revisiting D1.

**Verdict:** Selected.

## Consequences

### What Becomes Easier

1. A new transport-level concern has one obvious home, and the parity
   test tells the author which provider still lacks it.
2. Provider-specific features (cards, previews, threads) keep evolving
   without routing through a shared abstraction.

### What Becomes More Difficult

1. The duplicated review-request resolver (about 20 lines per side)
   stays duplicated. A change to the three-branch shape must still be
   made twice. That is accepted because every change in the recorded
   history was provider-specific.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A cross-cutting fix is written inline in one provider instead of as a policy module | Medium | Medium | D2 names the rule; reviewers point at this ADR; a miss counts toward D4 |
| The parity test's module list drifts from the providers on disk | Low | Medium | The test globs `skills/notifications/*_notify.py`, not a hand list |

## Implementation Plan

1. This ADR.
2. [GH-1479](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1479):
   port retry and dead-letter handling to `gchat_notify` and add the
   parity test.

## References

- `src/dev10x/skills/notifications/slack_review_request.py:33-82`,
  `gchat_review_request.py:25-108`, `:268-289`: the review-request
  siblings
- `src/dev10x/skills/notifications/slack_notify.py:209`, `:404-438`,
  `gchat_notify.py:267-300`, `:492-514`: the transport siblings
- `src/dev10x/domain/retry.py`, `src/dev10x/domain/dead_letter.py`:
  the shared policies
- `cac896d0`: GH-1423/GH-1421, adopted on Slack only
- `895bbd5d`: GH-1451, the one piece of review-request code already
  shared
- [GH-1441](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1441):
  the issue this decides
- Cross-port misses counted toward D4: (1) GH-1423/GH-1421 on Google
  Chat, addressed by GH-1479
