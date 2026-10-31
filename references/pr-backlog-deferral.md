# Backlog Items and Deferred Findings

If review uncovers non-blocking improvements (WARNINGs) that should be
deferred, mention them in a comment with a clear backlog reference:

```
[Backlog: GH-197] skill-reinforcement/SKILL.md exceeds 200-line budget.
Plan for next iteration: extract Step 3b (lines 124-145) into
references/audit-procedure.md.
```

This keeps review momentum while documenting future work clearly.

## A deferral needs the ticket ID, wherever it is written

"Ticket requested", "noted for a future pass", "out of scope, will
follow up" and a PR body's "Not in this PR" list are placeholders, not
deferrals. Each deferred finding needs the actual ticket ID next to it
before merge — in an author's reply, a reviewer's own summary, or the
PR body — or an explicit reason a ticket is not warranted ("too trivial
to ticket"). Grep the PR body and comments for the ID; the phrase alone
leaves the finding open. Without the ID nothing follows up once the PR
merges.
