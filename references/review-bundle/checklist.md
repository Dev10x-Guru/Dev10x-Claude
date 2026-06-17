# Bundled PR Review Checklist (repo-agnostic)

Self-contained reviewer guidance for the installable Dev10x review
Action (GH-352). It distills the internal multi-agent pipeline
(`.github/workflows/claude-code-review.yml` + `.claude/agents/reviewer-*`
+ `references/review-checks-common.md`) into a single file that ships
**inside the Action**, because consumer repositories do not have those
internal files checked out.

Apply it together with the mined learned-rules digest (when present).
The learned rules are heuristic signals from the consumer repo's own
review history — weigh them, do not enforce them blindly.

## Scope (read first)

- Review **only the lines changed in this PR's diff**. Pre-existing
  issues outside the diff are out of scope — do not flag them.
- PR metadata (title, body, commit messages, branch name) is handled by
  separate hygiene tooling. Do not comment on it.
- Be brief but thorough. Prefer a small number of high-confidence,
  actionable findings over a long list of preferences.

## False-positive prevention gate

Before posting **any** inline comment, all must hold:

1. **In diff** — the line is actually part of this PR's changes
   (`gh pr diff --name-only` to confirm the file changed).
2. **Verified in the file** — you read the surrounding code in the
   actual file, not just the diff snippet, and quoted the real code.
3. **Rule or pattern backs it** — it violates a documented project
   convention or contradicts an established pattern (5+ existing uses),
   not merely your preference.
4. **Real, not stale** — the issue still exists at current HEAD (not
   fixed in a later commit of the same PR).

If any check fails, do not post.

## Severity

- **CRITICAL / REQUIRED** — correctness bug, security hole, data loss,
  or a violation enforced by CI/merge protection. Blocks merge.
- **WARNING** — likely defect or maintainability risk; author should
  address or justify.
- **INFO / RECOMMENDED** — advisory; never blocks merge. Do not
  re-raise once the author has consciously declined it.

Only label REQUIRED when a real enforcement mechanism exists.

## Cross-cutting checks (all files)

- **Correctness** — logic errors, off-by-one, wrong conditionals,
  unhandled None/empty, incorrect error propagation.
- **Security** — no hardcoded secrets/tokens, no `eval`/`exec` of
  untrusted input, safe handling of user input, proper quoting in shell.
- **Error handling** — failures are surfaced, not silently swallowed
  (`except: pass`, `|| true`, `2>/dev/null` on a command whose output
  drives branching). `except E: side_effect(); raise` is NOT swallowing.
- **Dead code** — for a new class/function/constant, confirm it is
  referenced outside its definition file (exclude tests, ABCs, exports).
- **Parameter changes** — when a signature changes, all call sites must
  be updated; check beyond the diff.
- **Naming** — only flag genuinely misleading names; respect existing
  conventions (5+ uses), version suffixes, and domain prefixes.

## Architecture checks (new / substantially modified code)

Apply on PRs adding or significantly changing endpoint/view/service
code; skip for docs-only, config-only, or test-only PRs.

- New endpoints/views delegate business logic to a service layer rather
  than calling repositories/ORM directly (WARNING).
- Functions/methods over ~50 lines, or one function doing
  validation + business logic + persistence + formatting, likely
  violate SRP (WARNING).
- Inline dicts with 4+ keys crossing module boundaries should be typed
  DTOs (INFO). Validate inputs early via serializer/DTO (WARNING when
  raw `request.data[...]` parsing is unvalidated).

## Domain quick-checklists

Load only the domains with changed files.

- **Python / shell code** — type hints on signatures; named args for
  3+ params; `set -e` and meaningful exit codes in shell; check the
  shebang before flagging shell syntax (bash vs sh vs fish); a new
  production `.py` module with logic should have a matching test
  (WARNING when absent; exempt pure DTOs/ABCs/config).
- **Infrastructure (CI workflows, Makefiles, scripts)** — no hardcoded
  branch names (use the PR's base ref); idempotent branch creation
  (`checkout -B`); never expose secrets in logs; quote expansions.
- **Documentation** — referenced commands/files/dirs must exist; mark
  not-yet-implemented features `[PLANNED]`; unverified references in
  user-facing docs are WARNING.
- **Migrations / schema** — guard against data loss and tenant-scope
  leaks; prefer backward-compatible, low-lock changes.
- **Async tasks / event handlers** — idempotency, retry/timeout
  semantics, no swallowed exceptions, correct registration.
- **Frontend** — accessibility, SSR safety, auth/i18n correctness,
  fragile locators avoided.

## Shell anti-patterns

- No hardcoded temp paths; create temp files via the project's helper.
- A shell command-parsing check must inspect **all** segments — both
  pipe (`|`) and `&&`/`;` chained sub-commands.
- Flag implicit defaults (`jq '.field // ""'`) when the default value
  silently drives branching; validate explicitly instead.

## Producing the review

1. Check existing review comments and summaries first to avoid
   duplicates; determine the correct round number (highest + 1).
2. Post specific issues as **inline comments** on the changed lines.
3. Post **one** summary comment per review cycle. If the PR is clean,
   say so plainly and validate the good work.
4. After the author pushes fixes, acknowledge them and focus only on
   new issues — do not re-raise resolved or consciously-declined items.

## Convert to draft when issues are found

After reviewing, read the real inline-comment count from the API
(`gh pr view <N> --json reviewComments --jq '.reviewComments | length'`)
— do not rely on recollection. If the count is greater than 0, convert
the PR to draft (`gh pr ready --undo <N>`) so the author can batch fixes
without re-triggering a review on every push. If the count is 0, leave
the PR as-is.
