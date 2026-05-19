# Step 3c: Detect Structural Friction (File Upstream)

Sometimes the friction is not the agent's fault — the hook
itself is too aggressive, the command-skill map is missing an
entry, or no safe targeted allow-rule would cover the legitimate
use case. In those cases, point the user at the upstream issue
tracker so the hooks can be improved for everyone, not patched
locally over and over.

## Signals that suggest structural friction (file upstream)

- The hook's `systemMessage` says "file an issue at
  https://github.com/Dev10x-Guru/dev10x-claude" or similar
- Step 2 found NO matching skill AND Step 3 SKILLS.md scan
  found no clear skill either
- Step 3b found no simpler pre-approved variant AND the only
  workable allow-rule would be unsafely broad (e.g.,
  `Bash(git:*)`, `Bash(curl:*)`)
- The same command was rejected in this session more than once,
  suggesting the hook keeps re-blocking a legitimate workflow
- The supervisor's complaint is "the hook is wrong", not "the
  command is wrong"

## When at least one signal fires

Add an "Upstream issue" section to the Step 4 output:

- Brief problem statement (one sentence — what the agent needed
  to do, why current rules block it)
- Suggested resolution (one of: add command-skill-map entry,
  loosen a specific hook check, ship a new pre-approved
  template, document a per-project setting)
- Pre-filled `gh issue create` invocation that the user can
  approve to file the ticket:

  ```
  gh issue create \
    --repo Dev10x-Guru/Dev10x-Claude \
    --title "<gitmoji> Permission friction: <one-line summary>" \
    --label "permission-friction" \
    --body "<problem statement, repro command, suggested fix>"
  ```

Do NOT auto-file the issue. The user decides whether the
friction is genuinely structural or a one-off and approves
the `gh issue create` call manually (or via the existing
`Dev10x:ticket-create` skill if available).

## When to omit

The friction is clearly local (a skill or pre-approved
alternative already covers the case). Filing an upstream issue
for every prompt would be noise.
