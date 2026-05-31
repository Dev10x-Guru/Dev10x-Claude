# Flag-Overrides for Safe Flags

A `flag_overrides` catalog in `baseline-permissions.yaml` allows specifying
safe flags for normally-unsafe commands. When a command is gated because its
bare form is destructive (e.g., `git clean`, `git reset`), flag_overrides
lists safe flag combinations that expand to explicit allow rules.

## Why Flag-Overrides Instead of Deny Rules

A natural defense is to ship `deny` rules for catch-all forms (`Bash(git *)`).
This **backfires**: Claude Code evaluates rules `deny → ask → allow`, and the
first match wins. A `deny: Bash(git *)` would block even `git status` and
`git log` for every plugin user, even with `allow: Bash(git status:*)`
present.

Flag-overrides avoids this by specifying only the safe forms as allows. The
unsafe command never matches a rule and prompts or gets caught by a hook.

## Structure

```yaml
git-safe-flags:
  tier: 2
  flag_overrides:
    "git clean":
      - "-n"           # dry-run
      - "--dry-run"
    "git reset":
      - "--dry-run"
    "git branch":
      - "-d"           # delete local only (not -D)
```

This expands to allow rules:
```
Bash(git clean -n:*)
Bash(git clean --dry-run:*)
Bash(git reset --dry-run:*)
Bash(git branch -d:*)
```

## When to Use Flag-Overrides

- **Base command is destructive or state-changing** → use flag_overrides
  to enumerate safe flags
- **All flags are safe (read-only)** → use a blanket allow rule instead
  (no flag_overrides needed)
- **Some flags are safe, others aren't** → use flag_overrides (never use
  deny rules for unsafe flags)

## Renderer Implementation

`doctor.py` expands flag_overrides to rules via `expand_flag_overrides()`
during permission auditing and reports. The expansion is transparent to
the permission layer — it sees the same allow rules it would see if they
were hand-written.
