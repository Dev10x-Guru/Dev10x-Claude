# Privacy Scrubbing for Upstream Issue Bodies

Treat the source session as private by default. The upstream issue
filed at `Dev10x-Guru/Dev10x-Claude` is a public artifact and MUST
NOT disclose any identifier from a non-public repository, project,
branch, ticket tracker, file path, person, or service that is not
part of the public Dev10x plugin.

## Replacement Table

| Source value | Replace with |
|---|---|
| Non-Dev10x repo name (e.g., `acme/billing`) | `<private-repo>` |
| Non-Dev10x org/user owner | `<private-owner>` |
| Branch name not on the public PR branch | `<private-branch>` |
| Ticket IDs from non-Dev10x trackers (`PAY-133`, Linear/JIRA URLs) | `TICKET-NN` |
| File paths under `/work/<project>/` or other non-plugin paths | `<project>/path/to/file` |
| Internal hostnames, DB names, customer names, domains | `<internal-host>`, `<internal-db>` |
| Person names, emails, Slack handles | `<user>` |
| Free-text excerpts from private commits, comments, or messages | summarize abstractly |
| Sentry/observability project slugs that are not public | `<observability-project>` |

## Allowed Verbatim (public Dev10x context)

- Skill names with the `Dev10x:` prefix (`Dev10x:git`,
  `Dev10x:git-commit`, …)
- Hook script names that ship in this plugin
- Public file paths inside this repo (`skills/<name>/SKILL.md`,
  `hooks/...`, `references/...`)
- The plugin version and the public repo URL
- GitHub issue / PR numbers from `Dev10x-Guru/Dev10x-Claude`

## Algorithm

1. Extract the verbatim findings text.
2. Apply the replacement table above using a deterministic
   per-session mapping — the same private value gets the same
   generic placeholder throughout the body so cross-references
   stay readable (e.g., `TICKET-01` for the first private ticket
   seen, `<private-repo-A>` for the first repo).
3. Replace transcript turn references that point at private
   session files (`session 529d497f`,
   `~/.claude/projects/-work-...`) with `<source session>`.
   Keep in-session turn numbers ("turn 75", "turns 59–73") —
   they are anonymous within the upstream issue.
4. Strip any "Local fixes" / "Notes for triage" sections — by
   definition these are private context.
5. Re-read the assembled body and verify no identifier from the
   disallowed list above remains. If any slips through, scrub
   again. Do not file the issue until the body is clean.

## Decision Gate: Unscrubbable Findings

**STOP and ask the user** if a finding cannot be reported
without a private identifier (e.g., the finding is fundamentally
about a private codebase pattern). Use `AskUserQuestion`:

- **Scrub aggressively and file (Recommended)** — abstract the
  identifier even at the cost of some specificity
- **Skip this finding** — exclude it from the upstream issue
  and keep it in local notes only

Never auto-include unscrubbed text.
