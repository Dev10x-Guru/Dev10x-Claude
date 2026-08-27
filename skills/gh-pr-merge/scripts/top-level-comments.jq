# Select unaddressed automated-reviewer top-level comments / review
# bodies (GH-743 F2, GH-764). Input is a GitHub REST array of issue
# comments OR pull reviews. $src tags the surface ("comment" | "review").
#
# A row is returned when it is from an automated reviewer AND carries a
# blocking keyword AND is an active review surface:
#
#   is_bot   — IDENTITY evidence: the account is a bot, a known
#              review-bot login, OR the body embeds an HTML marker
#              (third-party LLM reviewers post under generic CI accounts
#              and self-identify only via an HTML comment, GH-764 F1).
#   blocking — SIGNAL: a REQUIRED/CRITICAL/BLOCKING keyword. Kept
#              separate from identity so a bot's marker-tagged
#              walkthrough (no keyword) is NOT a false merge blocker.
#   active   — skip PENDING (author-visible draft) / DISMISSED reviews;
#              issue comments have no .state and always pass.
#   reply    — the documented gh-pr-respond format for addressing a
#              finding starts with "Re:". A faithful reply quotes the
#              finding's severity token, so scanning its raw body makes
#              the reply self-trigger as a NEW finding (GH-777). Replies
#              are responses, not findings — exclude them, and strip
#              quoted context before scanning everything else. A reply
#              ALSO disposes of the finding it keys to: its "Re:" line
#              carries that finding's comment id, and the keyed finding
#              drops out of the result (GH-907, GH-884).

def is_bot:
  (.user.type == "Bot")
  or ((.user.login // "") | test("claude|github-actions|coderabbit|sourcery|openai|codex|copilot"))
  or ((.body // "") | test("<!--"));

# The "Re:" lines in a body, matched PER LINE (GH-1057). Testing the whole
# body against "^[[:space:]]*Re:" anchors at the start of the STRING in jq, so
# the documented gh-pr-respond shape — a
# "Merge-gate dispositions (keyed):" preamble line above the "Re:" lines —
# matched nothing. Both halves of the reply contract broke from that one
# cause: the disposition self-triggered as a new finding, and
# `reply_target_ids` (gated on `is_reply`) never collected its keys, so every
# disposition posted to satisfy Check 1b raised the count by one instead of
# lowering it. Splitting first makes each line its own string, so a key is
# found wherever in the body it sits.
def reply_lines:
  (.body // "") | split("\n") | map(select(test("^[[:space:]]*Re:"; "i")));

def is_reply:
  (reply_lines | length) > 0;

# The comment ids a reply DISPOSES OF (GH-907, GH-884). `is_reply` alone only
# stops the reply from self-triggering (GH-777) — nothing mapped it back to the
# finding it answers, so the answered finding kept blocking forever and Check 1b
# had no sanctioned exit. Matching is KEYED, not prose-fuzzy: the documented
# gh-pr-respond reply format embeds the finding's comment id ("Re: comment
# <id> …" / "Re: #<id> …"), so every digit run of 6+ characters on a "Re:" line
# is taken as a disposed-of id. Comment ids are 9-10 digits; ticket refs
# ("GH-907") and round numbers stay well under the floor, so they cannot
# accidentally clear a live finding. The key is scanned from the RAW body, not
# `unquoted`, so backticking the id (the old manual code-span workaround) is no
# longer load-bearing.
#
# Only "Re:" lines carry keys. Widening WHERE such a line may sit (GH-1057)
# deliberately does not widen WHAT counts as a key: a bare id in prose is
# still not a disposition signal.
def reply_target_ids:
  reply_lines | join(" ") | [ scan("[0-9]{6,}") ];

# The reviewer's own re-review wrapper (references/review-guidelines.md):
# a "## Review Summary (Round N)" comment whose "### Addressed since last
# review" section RESTATES already-fixed findings (severity tokens and
# all). Scanning that restated text self-triggers the finding as if it
# were live (GH-858 F2), permanently false-blocking Check 1b. This is the
# reviewer's own aggregate summary, not an author "Re:" reply, so is_reply
# does not catch it.
#
# The "(Round N)" suffix is OPTIONAL (GH-1011). A first review is commonly
# posted as a bare "## Review Summary", and requiring the suffix made such a
# comment fall through to the full-body scan — resurrecting the very
# severity tokens its "Addressed since last review" section restates, even
# after a later round confirmed them fixed. The wrapper is identified by its
# heading, not by whether the reviewer numbered it.
#
# Heading markup is OPTIONAL when the wrapper numbers itself (GH-1054 F2).
# Requiring a leading "##" made a bot that opens with a bare, plain-text
# "Review Summary (Round 3)" line invisible as a wrapper, so the
# latest-round-supersedes logic below never engaged and an earlier round
# kept blocking forever. The markup-free alternative demands the explicit
# "(Round N)" suffix: that suffix is what makes the line a review-round
# wrapper rather than prose that happens to say "review summary", and the
# match is anchored to the start of a line so a mid-sentence mention
# cannot silently narrow the scan.
def is_round_summary:
  (.body // "")
  | (test("^[[:space:]]*##[[:space:]]*Review Summary"; "im")
     or test("^[[:space:]]*[*_]{0,2}Review Summary[*_]{0,2}[[:space:]]*\\(Round[[:space:]]*[0-9]+"; "im"));

# The round number N from a "## Review Summary (Round N)" comment. Used to
# supersede earlier rounds (GH-873 F3): once a later round is posted, an
# earlier round's "Remaining issues" are a historical snapshot, not live
# blockers — only the highest round number is authoritative.
#
# An unnumbered summary counts as round 1 (GH-1011): it is somebody's first
# pass, so a later "(Round 2)" must supersede it, while on its own it stays
# authoritative (1 >= 1). Non-summary comments stay at 0 so they never
# participate in supersession.
def round_number:
  if is_round_summary then
    ((.body // "")
     | (capture("Review Summary[*_[:space:]]*\\(Round[[:space:]]*(?<n>[0-9]+)"; "im").n // "1")
     | tonumber)
  else
    0
  end;

# For a round summary, scan ONLY the "### Remaining issues" section — the
# live, still-unaddressed findings — and ignore the "Addressed since last
# review" restatement above it. Non-summary comments scan the full body
# unchanged. A summary with no "Remaining issues" heading (or an empty one)
# yields no scan text and is treated as clean (fail-open) — the same posture
# a fully-addressed round already warrants.
#
# The section ENDS at the next horizontal rule or heading (GH-1011). An
# unbounded `.*` ran to end-of-body, so a summary that said "Remaining
# issues: None" still blocked the merge on a *CRITICAL* token appearing in
# an unrelated later section (a false-positive-drops list). Stopping at the
# boundary keeps the scan inside the section the heading names.
#
# `###` is a terminator as well as `##`, because a sibling `###` section is
# far likelier than a `###` sub-heading nested INSIDE a remaining-issues
# list — findings there are list items directly under the heading. Erring
# this way can only narrow the scan, and a scan that is too narrow
# under-blocks a merge the author is already driving, whereas one that is
# too wide blocks it with no sanctioned exit.
#
# The section heading's own markup is optional for the same reason
# `is_round_summary` no longer demands it (GH-1054 F2): a plain-text wrapper
# writes "Remaining issues:" without `###`, and failing to find the section
# yields an empty scan — a false NEGATIVE, the one direction this gate must
# not err in.
def scan_body:
  if is_round_summary then
    ((.body // "")
     | (capture(
          "(?s)#{0,6}[[:space:]]*[*_]{0,2}Remaining issues[*_]{0,2}[[:space:]]*:?[[:space:]]*(?<rest>.*?)(\n[[:space:]]*---|\n###?[^#]|$)";
          "i"
        ).rest // ""))
  else
    (.body // "")
  end;

# Remove quoted context so a token that only appears inside a quote does
# not read as a fresh blocking finding (GH-777): markdown blockquote
# lines (`> …`), inline code spans, and double-quoted strings.
def unquoted:
  (scan_body | split("\n") | map(select(test("^[[:space:]]*>") | not)) | join("\n"))
  | gsub("`[^`]*`"; "")
  | gsub("\"[^\"]*\""; "");

# A severity token can appear in a line that says the OPPOSITE of a live
# blocker — "No CRITICAL issues found", "All CRITICAL items fully addressed",
# "✅ Fix verified — CRITICAL resolved" (GH-1054 F2). Scanning those as
# findings false-blocked merges the reviewer had already signed off.
#
# The pattern set is deliberately NARROW, and stays that way: a false
# negative here lets a genuinely-blocking finding merge, which is strictly
# worse than a false positive the author can still answer with a keyed "Re:"
# reply. So each shape below demands an explicit exoneration cue on the SAME
# line as the token — a quantifier ("no"/"none"/"all"/"every"), a resolution
# verb ("addressed"/"resolved"/"fixed"/"cleared"/"verified"), or a checkmark
# paired with one — rather than any general "sounds positive" heuristic.
# Prose like "CRITICAL: this was previously fine" carries no cue and keeps
# blocking, which is the intended bias.
# The token set spans BOTH severity families (GH-1057). Exoneration cues were
# recognised only around REQUIRED/CRITICAL/BLOCKING, so a reviewer's own
# "all INFO items addressed" wrap-up kept registering as a live INFO finding
# that still demanded a disposition. Widening the token set — while leaving the
# cue shapes untouched — is the safe direction here: an INFO-family finding
# does not hard-block a merge, it only needs a disposition, so a false
# negative costs a missed nit rather than a missed blocker.
def severity_token:
  "(REQUIRED|CRITICAL|BLOCKING|INFO|NOTE|SUGGESTION)";

def exonerated_line:
  test(
       "(?i:\\b(no|none|zero)\\b)([[:space:]]+of[[:space:]]+the)?"
       + "[[:space:]]+[*_]{0,2}" + severity_token + "\\b"
     )
  or test(
       severity_token + "[*_]{0,2}[[:space:]]*:?[[:space:]]*"
       + "(?i:\\b(none|not found|n/a)\\b)[[:space:]]*[.!]?[[:space:]]*$"
     )
  or test(
       "(?i:\\b(all|every|both)\\b)[[:space:]]+[*_]{0,2}" + severity_token + "\\b"
       + "[^.]{0,60}(?i:\\b(addressed|resolved|fixed|cleared|completed|done)\\b)"
     )
  or (test("^[[:space:]]*(✅|✔|☑|\\[x\\])")
      and test("(?i:\\b(addressed|resolved|fixed|cleared|verified|completed|done)\\b)"));

def unexonerated:
  unquoted | split("\n") | map(select(exonerated_line | not)) | join("\n");

def blocking:
  unexonerated
  | test("REQUIRED|CRITICAL|BLOCKING|\\*\\*\\[BLOCKING\\]\\*\\*|\\*\\*\\[CRITICAL\\]\\*\\*");

# SIGNAL: a non-blocking recommendation token (GH-808 F1). A bot finding
# tagged INFO/NOTE/SUGGESTION in a COMMENTED/APPROVED review body is
# invisible to a blocking-only scan, so it can merge with no disposition.
# The set is kept narrow on purpose — matching arbitrary bot prose (a plain
# LGTM) would flood the gate with noise. These findings do not hard-block;
# they need an explicit disposition (a "Re:" reply satisfies it).
#
# Scans `unexonerated`, not `unquoted` (GH-1057): the exoneration filter was
# wired into the blocking scan only, so a reviewer's own "all INFO items
# addressed" wrap-up stayed a live INFO finding no matter how plainly it said
# it was handled. Both severity scans now start from the same filtered text.
def info_marker:
  unexonerated | test("\\bINFO\\b|\\bNOTE\\b|\\bSUGGESTION\\b");

def severity:
  if blocking then "blocking" else "info" end;

def active:
  (.state // "") | (. != "PENDING" and . != "DISMISSED");

# Latest authoritative round: the highest "Round N" across all round-summary
# rows (0 when there are none). Earlier round summaries are superseded and
# excluded below so a green final round clears stale earlier "Remaining
# issues" (GH-873 F3).
(([ .[] | select(is_round_summary) | round_number ] | max) // 0) as $latest_round
# Every comment id disposed of by a "Re:" reply on EITHER surface. A reply
# keyed to id X necessarily post-dates X, so no explicit ordering check is
# needed — the key itself carries the "later comment" semantics (GH-907).
#
# `$extra` carries the OTHER surface's raw rows (GH-1002). The caller scans
# issue comments and review bodies in two invocations, so scanning only `.`
# made the disposition surface-local: a review-BODY finding could never be
# cleared, because `gh-pr-respond` posts body-finding replies as issue
# comments (GH-907/GH-920) and those land in the other array. That left a
# blocking review-body finding permanently unaddressable through sanctioned
# tooling — the only exits were rewriting the reviewer's own body or
# bypassing the gate. Union both surfaces so a keyed reply disposes of its
# finding wherever that finding lives.
| ([ (.[], ($extra[]?)) | reply_target_ids ] | flatten | unique) as $answered_ids
| [ .[]
  | select(
      ((.body // "") != "")
      and (is_reply | not)
      and is_bot
      and (blocking or info_marker)
      and active
      and ((is_round_summary | not) or (round_number >= $latest_round))
      and ((.id | tostring) as $rid | ($answered_ids | index($rid)) | not)
    )
  | {id, user: .user.login, snippet: ((.body | split("\n")[0])[:80]), source: $src, severity: severity} ]
