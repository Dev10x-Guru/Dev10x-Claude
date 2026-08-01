# GitHub API Behavioral Quirks

Catalog of unexpected GitHub API behaviors that affect tool design and skill implementation.

## Force-Push Resets Draft State (GH-958)

**Impact**: Critical — PR state silently changes  
**Affected tools**: `mcp__plugin_Dev10x_cli__pr_ready`, `mcp__plugin_Dev10x_cli__create_pr`  
**Scenario**: A PR is created with `draft=false` or `pr_ready` is called to publish the PR. Then a force-push (`git push --force-with-lease`) is executed (rebase, amend, groom). The PR **silently reverts to draft state**, invalidating the prior `pr_ready` call.

**Recovery**: After any force-push operation (rebase, amend, groom), re-verify PR draft state with a fresh `pr_get` call:
```
create_pr(draft=false) → [push] → pr_get (verify isDraft=false) → 
[force-push] → pr_ready (re-publish) → pr_get (verify isDraft=false)
```

**Why this happens**: GitHub's API resets a PR's review state on force-push as a safety measure. The draft state is part of review readiness and gets reset along with review status.

---

## PR Ready Bidirectionality (GH-931)

**Impact**: Medium — behavioral surprise in tool semantics  
**Affected tools**: `mcp__plugin_Dev10x_cli__pr_ready`  
**Scenario**: `pr_ready` with no arguments publishes a draft PR. `pr_ready` with `undo=true` returns a published PR to draft.

**Usage**:
```
pr_ready(pr_number=123)              # Publish a draft PR
pr_ready(pr_number=123, undo=true)   # Revert published PR to draft
```

**Recovery**: The `undo` parameter is the only sanctioned way to un-publish a PR (equivalent to clicking "Convert to draft"). Use this when a problem surfaces after marking ready but before CI completes.

**Why this matters**: A one-directional tool would force users to work around the limitation; bidirectionality keeps the tool self-contained.

---

## Create-PR Validation Rejects Incomplete JTBD (GH-945)

**Impact**: Medium — tool call fails at validation boundary  
**Affected tools**: `mcp__plugin_Dev10x_cli__create_pr`  
**Scenario**: A PR body is passed to `create_pr` that is missing any of the required JTBD phrases:
- Missing `**When**` clause
- Missing `**[actor] wants to**` clause  
- Missing `**so [beneficiary] can**` clause

**Recovery**: The tool rejects the call with an actionable error before opening the PR. Inspect the error message, rewrite the body to include all three JTBD clauses, and retry.

**Why this matters**: JTBD validation at the tool boundary prevents submitting incomplete job stories to the repo's hygiene bot, which would fail the PR check anyway.

---

## Closes Lines Don't Auto-Close on Develop (GH-958)

**Impact**: Medium — cross-reference behavior differs by merge target  
**Affected tools**: `mcp__plugin_Dev10x_cli__create_pr`  
**Scenario**: A PR body includes `Closes: #N` lines above the `Fixes:` trailer. The PR is merged to `develop`. GitHub's auto-close automation **never fires** on the `Closes:` lines — only the `Fixes:` trailer auto-closes issues.

**Recovery**: The `closes=` parameter in `create_pr` is informational only (emits `Closes:` lines into the body). For a milestone-bundle PR that fixes multiple issues:
1. Add `closes=` for cross-referencing
2. After merge, manually close non-`Fixes:` issues with `mcp__plugin_Dev10x_cli__issue_close`
3. Verify each one rather than assuming the bundle auto-closed

**Why this happens**: GitHub's auto-close automation is scoped to the `Fixes:` trailer only (the semantic marker for "this PR resolves the issue"). `Closes:` is a convenience cross-reference that doesn't carry the same intent.

---

## Update-PR Moves Trailing Content Above Fixes Trailer (GH-945)

**Impact**: Low — text formatting change  
**Affected tools**: `mcp__plugin_Dev10x_cli__update_pr`  
**Scenario**: A PR body has content after the `Fixes:` line:
```
Body content...

Fixes: https://...
Extra text here
```

When `update_pr` is called, the tool **moves the extra text above the `Fixes:` line**:
```
Body content...
Extra text here

Fixes: https://...
```

**Recovery**: Do not add content after `Fixes:` — it will be reordered. The `Fixes:` line should always be the last line of the PR body.

**Why this happens**: The tool enforces the convention that `Fixes:` is the final line; any trailing content is presumed to be part of the body and relocated accordingly.

---

## Pushing to a Closed PR Fails (Expected)

**Impact**: Low — expected MCP tool failure  
**Affected tools**: `mcp__plugin_Dev10x_cli__push_safe`  
**Scenario**: A PR has been closed or merged. An attempt to push to its branch fails with a permissions error (the branch protection rules or remote configuration prevent pushes to a closed PR's branch).

**Recovery**: Re-open the PR via `mcp__plugin_Dev10x_cli__pr_close` with `undo=true` (if the tool supports it) or use `gh pr reopen`. Then retry the push.

**Why this matters**: This is expected behavior, not a tool bug. The tool correctly reports the GitHub API error.

---

## Related References

- `.claude/rules/mcp-tools.md` — canonical MCP tool parameter documentation and behavioral caveats
- `skills/gh-pr-merge/` — critical enforcement point for force-push re-verification
- `foreman/references/crew-contract.md` — post-condition re-verification contract
