# Step 3g: Check the Recommended Tool Exists Here (GH-1087)

A `use-tool` compensation names a tool the map assumes is present —
but the tool surface varies per session. A `find -name` rejection
routed to `Glob`, and the `Glob` call answered "No such tool available:
Glob — find files with `find` via the Bash tool instead": the map and
the harness contradicting each other, producing a friction diagnosis
that could not be executed. That is the failure mode this skill exists
to prevent.

Before recommending a `use-tool` compensation:

1. Confirm the named tool is in this session's tool surface (it appears
   in the available-tools listing, or in the deferred-tool list
   loadable via `ToolSearch`).
2. If it is absent, recommend the compensation's `fallback:` instead —
   for `find-search` that is `rg --files -g '<glob>'` (name discovery)
   or `rg -l <pattern> -g '<glob>'` (content), both covered by
   `Bash(rg:*)`.
3. Never fall back to the offending command itself. The harness's own
   "use `find` via the Bash tool" suggestion reinstates exactly the
   friction the rule removes — a pre-approved `rg` shape is available
   in every session.

State the substitution you verified, so the supervisor can see the
recommendation was checked rather than recited.
