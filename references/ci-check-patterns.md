# CI Check Patterns

Architectural patterns for wiring static analysis tools into CI workflows.

## Diff-Scoped Checks

When a new static analysis tool (linter, detector, auditor) is wired into
CI, prefer **diff-scoped execution** that only checks files this PR touches,
matching the established CLI-friction scanner precedent.

### Pattern (from `.github/workflows/skill-eval-gaps.yml`)

1. In the "Collect files touched by this PR" step, diff against the merge base:
   ```bash
   git diff --name-only --diff-filter=AM "origin/${BASE_REF}" HEAD \
     | grep -E '^skills/[^/]+/SKILL\.md$' \
     | sed -E 's#^(skills/[^/]+)/SKILL\.md$#\1#' \
     | sort -u > /tmp/changed-paths.txt
   ```

2. Pass the collected paths to your tool, not the entire repo:
   ```yaml
   run: xargs -a /tmp/changed-paths.txt uv run bin/check-tool.py
   ```

3. Include the tool's own config files in the workflow's `paths:` trigger:
   ```yaml
   paths:
     - "skills/**/SKILL.md"
     - "skills/**/evals/evals.json"
     - "bin/check-skill-eval-gaps.py"        # tool entry point
     - ".github/workflows/skill-eval-gaps.yml"  # workflow itself
   ```

### Benefits

- **Unblocked unrelated PRs**: Pre-existing gaps in non-touched skills don't fail CI
- **Fast feedback**: Only checks what changed, not the full corpus
- **Incremental debt tracking**: Existing gaps tracked separately without blocking new PRs

### When NOT to Diff-Scope

- High-risk changes (security, breaking API changes) — always full-repo scan
- Multi-phase checks where later phases depend on earlier results

See `.claude/rules/mcp-tools.md` § Tool Availability for precedent on how
canonical tools document their CI integration strategy.
