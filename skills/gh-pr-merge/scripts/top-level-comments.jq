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
#              quoted context before scanning everything else.

def is_bot:
  (.user.type == "Bot")
  or ((.user.login // "") | test("claude|github-actions|coderabbit|sourcery|openai|codex|copilot"))
  or ((.body // "") | test("<!--"));

def is_reply:
  (.body // "") | test("^[[:space:]]*Re:"; "i");

# The reviewer's own re-review wrapper (references/review-guidelines.md):
# a "## Review Summary (Round N)" comment whose "### Addressed since last
# review" section RESTATES already-fixed findings (severity tokens and
# all). Scanning that restated text self-triggers the finding as if it
# were live (GH-858 F2), permanently false-blocking Check 1b. This is the
# reviewer's own aggregate summary, not an author "Re:" reply, so is_reply
# does not catch it.
def is_round_summary:
  (.body // "") | test("^[[:space:]]*##[[:space:]]*Review Summary[[:space:]]*\\(Round"; "im");

# For a round summary, scan ONLY the "### Remaining issues" section — the
# live, still-unaddressed findings — and ignore the "Addressed since last
# review" restatement above it. Non-summary comments scan the full body
# unchanged. A summary with no "Remaining issues" heading (or an empty one)
# yields no scan text and is treated as clean (fail-open) — the same posture
# a fully-addressed round already warrants.
def scan_body:
  if is_round_summary then
    ((.body // "")
     | (capture("(?s)###[[:space:]]*Remaining issues[[:space:]]*\n(?<rest>.*)"; "i").rest // ""))
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

def blocking:
  unquoted
  | test("REQUIRED|CRITICAL|BLOCKING|\\*\\*\\[BLOCKING\\]\\*\\*|\\*\\*\\[CRITICAL\\]\\*\\*");

# SIGNAL: a non-blocking recommendation token (GH-808 F1). A bot finding
# tagged INFO/NOTE/SUGGESTION in a COMMENTED/APPROVED review body is
# invisible to a blocking-only scan, so it can merge with no disposition.
# The set is kept narrow on purpose — matching arbitrary bot prose (a plain
# LGTM) would flood the gate with noise. These findings do not hard-block;
# they need an explicit disposition (a "Re:" reply satisfies it).
def info_marker:
  unquoted | test("\\bINFO\\b|\\bNOTE\\b|\\bSUGGESTION\\b");

def severity:
  if blocking then "blocking" else "info" end;

def active:
  (.state // "") | (. != "PENDING" and . != "DISMISSED");

[ .[]
  | select(((.body // "") != "") and (is_reply | not) and is_bot and (blocking or info_marker) and active)
  | {id, user: .user.login, snippet: ((.body | split("\n")[0])[:80]), source: $src, severity: severity} ]
