# Pull Request & Branch Grooming Guidelines

Standards for pull requests and branch grooming in this repository.

## Branch Grooming

Restructure commit history to create atomic, well-organized commits.

### When Grooming is Acceptable

- ✅ Before creating a PR
- ✅ While PR is in **draft** status
- ✅ After CI feedback (before human review starts)
- ✅ When CI blocks merge due to fixup commits

### When Grooming is Discouraged

- ❌ After a human reviewer has started reviewing

*Why?* Rewriting history after human review started creates noise and
confusion. Reviewers lose context, and GitHub shows "force-pushed"
which hides the diff of what changed.

### Strategies

**A. Fixup + Autosquash** (small targeted fixes):
```bash
git commit --fixup=<target-sha>
git rebase -i --autosquash $(git merge-base develop HEAD)
```

**B. Soft Reset** (major reorganization):
```bash
git reset --soft $(git merge-base develop HEAD)
git reset HEAD  # unstage
git add -p      # selectively stage
git commit -m "First logical change"
# repeat for each logical unit
```

**C. Interactive Rebase** (reorder/edit/split):
```bash
git rebase -i $(git merge-base develop HEAD)
```

### Safety

- Create backup before complex rewrites: `git branch backup-before-rewrite`
- Use `--force-with-lease` not `--force` when pushing rewrites
- Coordinate with teammates before force-pushing shared branches

## Pull Request Guidelines

### Before Creating PR

1. Ensure all commits are atomic and well-organized
2. Squash any fixup commits
3. Run quality checks locally (shellcheck for scripts, ruff for Python)
4. Verify branch is up to date with develop
5. Rebase to linearize history — no merge commits before opening

### PR Title

Use the main commit's title line (gitmoji + ticket + description).

**Important**: The gitmoji appears in the **commit message**, not in the
GitHub PR title field. GitHub's UI shows these separately — your main
commit's gitmoji will automatically appear in release notes and git log
regardless of how the PR title field is filled. The critical requirement
is that your commit contains the gitmoji; GitHub renders it in the PR UI.

### PR Body

The body should be **compact** to avoid cluttering Slack previews.

**Required elements** (in this order):
1. A JTBD Job Story as the **first paragraph** (1-3 lines, see `git-jtbd.md`)
2. `Fixes:` link — must be the **absolute last line** of the body:
   - `Fixes: https://github.com/Dev10x-Guru/dev10x-claude/issues/NUMBER`
     (for issue-tracked work)
   - `Fixes: none — self-motivated refactor` (for internal improvements,
     features, or experiments without a tracking issue)
   - Do NOT manually add `---`, blank lines, or separators after `Fixes:`
     (Note: The `create-pr.sh` template automatically adds separators as
     part of standard formatting. Do not remove them.)

**Optional elements** (keep brief):
- Compact commit list with links (one line per commit)
- Critical context that reviewers need immediately

**Do not include in body**:
- Detailed summaries (put in first comment)
- Implementation checklists (put in first comment)
- Known limitations or TODOs (put in first comment)

### Examples

**VOICE REQUIREMENT**: The "I want to" form is mandatory—never use objective
voice like "wants to" or "the developer wants to". See
`references/git-jtbd.md` § Voice Requirement (lines 35-50).

**WRONG** — Header before JTBD (breaks release notes parsing):
```markdown
## Summary

**When** reviewing code, **I want to** have automated checks, **so I can** catch issues.

[Details...]

Fixes: ...
```

**CORRECT** — JTBD as absolute first element:
```markdown
**When** reviewing code, **I want to** have automated checks, **so I can** catch issues.

[Details or commit list — optional...]

Fixes: ...
```

### Proper Format

```markdown
**When** reviewing PRs without automated checks, **I want to** have
Claude review code quality, **so I can** catch issues before merging.

[`b3a015a`](REPO_URL/commit/HASH) ✨ GH-7 Enable code review
[`fec4999`](REPO_URL/commit/HASH) 📝 GH-7 Document review agents

Fixes: https://github.com/Dev10x-Guru/dev10x-claude/issues/7
```

*Why?* The JTBD Job Story must be the first paragraph because the
release notes process parses PR descriptions by position.

*Bootstrapping exception:* A PR that introduces a new PR body
requirement may not follow that requirement itself — the rule
wasn't enforced when the PR was submitted.

### If Review Issues Are Found

If Claude finds code or metadata issues during review, your PR will be
automatically converted to **draft** status. This prevents the merge button
from becoming available while issues remain unfixed.

After fixing all flagged issues, click **"Ready for review"** on the
PR page to re-trigger the review workflows and allow merge once checks pass.

### PR First Comment (Summary + Checklist)

Detailed context for reviewers without bloating the Slack preview.

```markdown
### Summary

- Added multi-agent code review architecture
- Created 5 domain-specific reviewer agents
```

### PR Checklist

- [ ] Self-reviewed the diff
- [ ] Updated documentation if needed
- [ ] No fixup commits remaining

## Handling Review Feedback

1. Create fixup commits for each review comment
2. Reference the comment in fixup commit body
3. Reply to comment with commit SHA
4. Before final push, squash all fixups:
   ```bash
   git rebase -i --autosquash $(git merge-base develop HEAD)
   git push --force-with-lease
   ```

For commit format and branch naming, see `git-commits.md`.

### Backlog Items and Deferred Findings

If review uncovers non-blocking improvements (WARNINGs) that should be
deferred, mention them in a comment with a clear backlog reference:

```
[Backlog: GH-197] skill-reinforcement/SKILL.md exceeds 200-line budget.
Plan for next iteration: extract Step 3b (lines 124-145) into
references/audit-procedure.md.
```

This keeps review momentum while documenting future work clearly.

## Consolidation PRs

When a PR consolidates multiple directories, features, or components, the JTBD
must capture the consolidation outcome, not individual features. See
`consolidation-pr-guide.md` for full guidance, including:

- When consolidation is appropriate (plugin/directory merges, not feature bundling)
- How to structure JTBD and commits for consolidation scope
- Review expectations for large structural changes
- Testing strategies for consolidated components
