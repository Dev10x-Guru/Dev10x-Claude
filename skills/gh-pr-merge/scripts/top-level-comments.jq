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

def is_bot:
  (.user.type == "Bot")
  or ((.user.login // "") | test("claude|github-actions|coderabbit|sourcery|openai|codex|copilot"))
  or ((.body // "") | test("<!--"));

def blocking:
  (.body // "")
  | test("REQUIRED|CRITICAL|BLOCKING|\\*\\*\\[BLOCKING\\]\\*\\*|\\*\\*\\[CRITICAL\\]\\*\\*");

def active:
  (.state // "") | (. != "PENDING" and . != "DISMISSED");

[ .[]
  | select(((.body // "") != "") and is_bot and blocking and active)
  | {id, user: .user.login, snippet: ((.body | split("\n")[0])[:80]), source: $src} ]
