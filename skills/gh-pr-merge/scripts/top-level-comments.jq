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
#   blocking — SIGNAL: a REQUIRED/CRITICAL/BLOCKING keyword scanned on
#              the UNQUOTED body. Kept separate from identity so a bot's
#              marker-tagged walkthrough (no keyword) is NOT a false
#              merge blocker.
#   is_reply — a response that ADDRESSES a prior finding, not a new one.
#              The documented way to reply to a body finding is a
#              top-level comment beginning "Re:" (see gh-pr-respond
#              "Replying to body findings"); such replies faithfully
#              quote the finding title and must never re-trigger the
#              scanner (GH-777).
#   active   — skip PENDING (author-visible draft) / DISMISSED reviews;
#              issue comments have no .state and always pass.

def is_bot:
  (.user.type == "Bot")
  or ((.user.login // "") | test("claude|github-actions|coderabbit|sourcery|openai|codex|copilot"))
  or ((.body // "") | test("<!--"));

# Strip quoted context before scanning for severity keywords so a
# comment that QUOTES a finding — a markdown blockquote line or an
# inline code span — is not itself flagged as a new finding (GH-777).
def unquoted:
  (.body // "")
  | split("\n")
  | map(select((test("^\\s*>") | not)))
  | join("\n")
  | gsub("`[^`]*`"; "");

def blocking:
  unquoted
  | test("REQUIRED|CRITICAL|BLOCKING|\\*\\*\\[BLOCKING\\]\\*\\*|\\*\\*\\[CRITICAL\\]\\*\\*");

def is_reply:
  (.body // "") | test("^\\s*Re:");

def active:
  (.state // "") | (. != "PENDING" and . != "DISMISSED");

[ .[]
  | select(((.body // "") != "") and is_bot and blocking and active and (is_reply | not))
  | {id, user: .user.login, snippet: ((.body | split("\n")[0])[:80]), source: $src} ]
