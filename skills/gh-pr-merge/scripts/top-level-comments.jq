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

# Remove quoted context so a token that only appears inside a quote does
# not read as a fresh blocking finding (GH-777): markdown blockquote
# lines (`> …`), inline code spans, and double-quoted strings.
def unquoted:
  ((.body // "") | split("\n") | map(select(test("^[[:space:]]*>") | not)) | join("\n"))
  | gsub("`[^`]*`"; "")
  | gsub("\"[^\"]*\""; "");

def blocking:
  unquoted
  | test("REQUIRED|CRITICAL|BLOCKING|\\*\\*\\[BLOCKING\\]\\*\\*|\\*\\*\\[CRITICAL\\]\\*\\*");

def active:
  (.state // "") | (. != "PENDING" and . != "DISMISSED");

[ .[]
  | select(((.body // "") != "") and (is_reply | not) and is_bot and blocking and active)
  | {id, user: .user.login, snippet: ((.body | split("\n")[0])[:80]), source: $src} ]
