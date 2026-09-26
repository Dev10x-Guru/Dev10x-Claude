# Rule Documentation Standards

Guidance for authoring new rules in `.claude/rules/*.md` (moved out
of `CLAUDE.md` under its 100-line budget, GH-1438).

When documenting new rules:

- Expand reviewer checklists with concrete checks before they
  accumulate as lint suggestions (a new rule invites new edge
  cases; document them when the rule lands to prevent silent
  divergence).
- Document acceptable exceptions explicitly (e.g., when
  `sys.exit()` is OK in a domain function): future consolidations
  need clear guidance on what violates the rule vs. what is a
  documented exception.
- Use numbered lists in checklists (not bullets) to signal
  mandatory sequential verification steps to reviewers.
