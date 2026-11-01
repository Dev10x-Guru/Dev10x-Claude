# MCP Tool Caveats — Project Pins and `resolve_gate`

Behavioural caveats for the durable-preference writers and the gate
resolver, moved out of `.claude/rules/mcp-tools.md` § Canonical
Parameter Shapes (GH-1606).

- `pin_tracker` / `tracker_status` carry the project's issue-tracker
  choice (GH-768). `ensure-base` and `seed_worktree` seed only that
  tracker's MCP rules, so a Jira user stops collecting ~35 inert
  `mcp__claude_ai_Linear__*` allows while their own Atlassian tools
  prompt on first use. The choice is a durable `tracker:` key in the
  matching `projects[]` entry of `~/.config/Dev10x/friction.yaml` —
  same repo-stem keying as `pin_gate_preset`, so one answer covers a
  repo and every worktree of it. Gate the onboarding ask on
  `tracker_status` → `pinned: false`; note that `pinned` reports
  whether a *project entry* names one, while `tracker` always reports a
  resolved value (defaulting to `linear`, the pre-GH-768 behaviour, so
  upgrades lose nothing). v1 covers Linear / Jira / GitHub Issues;
  GitLab and ClickUp are deliberately unsupported rather than shipped
  as empty blocks.

- `pin_ide` / `ide_status` carry the same fact for the project's IDE
  (GH-1261), and `ensure-base` folds that IDE's block the way it folds
  the tracker's. Two things differ from `pin_tracker`. First, the
  resolved default is `none`, not a named IDE: every project has a
  tracker, but most checkouts run no IDE MCP server, so an unpinned
  repo folds nothing rather than seeding a guess — `pinned: false` is
  the unanswered flag, and a resolved `none` is a real answer. Second,
  an IDE block carries **denies** as well as allows: a tool that runs a
  terminal command is a Bash call the PreToolUse chain never sees, so
  its three shell-equivalent tools are denied unconditionally — in
  `base_denies`, not only under the IDE's own key — because the hazard
  does not depend on which IDE was pinned. `seed_worktree` folds
  neither the IDE block nor the tracker block; that pre-existing
  asymmetry is unchanged here.

- `pin_gate_preset` persists a Phase-0 preset pick into the global
  `~/.config/Dev10x/friction.yaml`, keyed by the repo stem read from the
  git **common dir** — so a pick made inside worktree `<repo>-3` also
  covers `<repo>` and a `<repo>-9` created later (GH-855). It is
  idempotent: an entry already covering the checkout is replaced, never
  duplicated. Gate the ask on `preset_pin_status` → `pinned: false`
  (the first-pick condition); asking on every pick is the friction the
  pair exists to remove. Nothing is written under a repo's `.claude/`
  (ADR-0018), so the self-settings gate never fires.

- `pin_supervisor_review` / `supervisor_review_status` carry the
  ADR-0022 D-2 review-boundary fact — does the supervisor read this
  repo's PRs before the next step is allowed (`required` | `none`)
  (GH-1165). `pin_gate_preset` is **not** superseded: it still owns the
  Phase-0 preset/overlay/per-gate-override triad (`_ENUM_TOGGLES`), and
  `supervisor_review` is deliberately not one of those toggles — it is a
  project-wide fact, not a gate-instance decision, so it needed its own
  writer rather than a `gate_overrides` entry. Both pins share the same
  repo-stem keying and the same `pin_project_prefs` writer, and both are
  idempotent: an entry already covering the checkout is replaced, never
  duplicated. Gate the onboarding ask on `supervisor_review_status` →
  `pinned: false`. Only `supervisor_review` counts as pinned: the retired
  `human_review` boolean key (ADR-0019) is no longer read (GH-1771), so
  run `dev10x config migrate-schema` on a repo that still carries it.
  Nothing is written under a repo's `.claude/` (ADR-0018).
- `resolve_gate` returns `{gate, effect (ask|auto-advance|skip),
  resolved_option, log_to, reason, floors_applied,
  anchor_recommendations}`; on an `auto-advance` it adds a `record`
  key carrying the visible D-7 line (`⚙ gate:… → "…" (reason)`),
  absent for `ask`/`skip` (ADR-0016 #754). Session policy is read
  from `.claude/Dev10x/session.yaml` through `gate_preset` /
  `gate_overlays` / `gate_overrides` and nothing else — GH-1162
  deleted the read-compat seam that used to translate the v1
  `friction_level` / `active_modes` / `walk_away` keys, so a config
  still carrying them is **refused** with an error naming
  `dev10x config migrate-schema` rather than silently resolving to a
  posture nobody wrote. An omitted `gate_overlays` inherits nothing.
  The durable project pin lives at git-tracked
  `.dev10x/gate-policy.yaml` (legacy `.claude/Dev10x/gate-policy.yaml`
  still read as a fallback, #752).
