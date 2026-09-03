# Criteria Resolution Detail

Extracted from `SKILL.md` (GH-1172) so the skill body keeps only the
steps that gate execution. Load this when resolving the check list.

The gating half — Step 4's review-posture and active-mode filter —
stays in `SKILL.md`, because a run that skips it silently widens what
counts as done.

## Step 1b: Re-infer from live session state (GH-780)

The caller passes the `work_type` detected at **plan** time (work-on
Phase 1). Some plays legitimately change shape mid-execution — the
`local-only` play's "Decide: create ticket, create PR, or done" step
can resolve to "create PR", so the session is feature-shaped by the
time verification runs. Trusting the plan-time `work_type` then loads
the thin `local-only` checklist (working copy + "changes verified")
and silently skips the checks that now apply.

After loading Step 1's checks, probe live state and **union** the
richer check set in when a PR exists:

1. Resolve the associated PR via
   `mcp__plugin_Dev10x_cli__pr_detect(arg="")`. (This is the same
   probe the PR-Merge-State section runs — resolve it once and reuse
   the result; an `error` / no-PR response means PR-less.)
2. If an **open** PR exists **and** the caller's `work_type` is a
   PR-less type whose default check set lacks PR checks (`local-only`,
   `investigation`), load `defaults.feature.checks` and **union** them
   into the list from Step 1, de-duplicated by `name` (a caller check
   with the same `name` wins — never duplicate or overwrite it).
3. This is a **union, not a replacement** — every check the caller's
   `work_type` contributed is preserved; re-inference only *adds* the
   missing PR checks (CI passing, PR not draft, no fixup commits, no
   unresolved review threads, review requested).
4. **Never downgrade.** When the caller's `work_type` already carries
   PR checks (`feature`, `bugfix`, `pr-continuation`), or no open PR
   exists, make no change.

Record which checks re-inference added so the presentation can surface
them (see SKILL.md Presentation → "added by live-state re-inference").
The subsequent override/merge (Step 2–3) and the posture/mode filter
(Step 4) apply to the unioned list, so repo `remove`/`replace` deltas
and mode skips still govern the added checks.

## Step 2: Load repo overrides (if present)

Read overrides from a single global file:

```
~/.config/Dev10x/dod-acceptance-criteria.yaml
```

**Read-compat fallback (one release).** When that file is absent, fall
back to the GH-941-retired
`~/.claude/memory/Dev10x/dod-acceptance-criteria.yaml`. When the
fallback fires, say so in the run's output — e.g.
`legacy_read: ~/.claude/memory/Dev10x/dod-acceptance-criteria.yaml` —
and tell the user to move the file to `~/.config/Dev10x/`
(`dev10x config migrate` folds it forward). A silent fallback is what
let the two locations diverge in the first place (GH-1035): the user
edits the documented copy and sees no effect because the skill read
the other one. Never *write* to the legacy path — writes always target
`~/.config/Dev10x/` (see SKILL.md Decision Gate).

This file maps repositories to their override deltas:

```yaml
repos:
  example-org/app-pos:
    bugfix:
      add:
        - name: Sentry issue linked
          check: >
            gh pr view {pr_number} --repo {repo}
            --json body -q .body  # cli-friction: allow raw-gh-pr
          expect_contains: "sentry.io"
      remove:
        - Slack notification posted
  Dev10x-Guru/dev10x-claude:
    feature:
      remove:
        - Review requested
      add:
        - name: PR ready (solo maintainer)
          check: >
            gh pr view {pr_number} --repo {repo}
            --json isDraft -q .isDraft  # cli-friction: allow raw-gh-pr
          expect: "false"
```

**Repo detection:** Resolve the current repo via `gh repo view --json
nameWithOwner -q .nameWithOwner` or session context. Look up
`repos[nameWithOwner][work_type]` for deltas.

## Step 3: Merge with delta semantics

Apply the repo-scoped deltas from the global file to the plugin
defaults:

- **`add`** — append checks to the defaults list.
- **`remove`** — remove checks by `name` (exact match).
- **`replace`** — replace a check by `name` with the new definition.

Apply in order: remove first, then replace, then add. This prevents
removing a just-added check or replacing a removed one.
