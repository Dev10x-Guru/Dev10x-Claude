# Plugin Silently Skipped at Session Start (GH-874)

A Claude Code session can start **without the Dev10x plugin loaded**:
no `Dev10x:*` skills, no `mcp__plugin_Dev10x_*` tools, and no plugin
hooks firing (chained `;`/`&&` Bash commands pass unvalidated). No
error is surfaced anywhere — the user discovers it only when a skill
invocation fails, and must run `/plugin reload` to recover. It recurs.

## Root cause

The plugin state on disk is consistent and other plugins from the same
registry load fine in the affected session, so this is **not** a Dev10x
config or packaging defect. Best hypothesis [Verify — Claude Code
internals, not confirmable from outside]: a **startup race** in Claude
Code's plugin discovery when multiple sessions start near-simultaneously
and one is rewriting shared plugin state (`installed_plugins.json` /
`known_marketplaces.json` during a marketplace auto-update). The losing
session silently skips the plugin.

Upstream, this belongs to Claude Code. Dev10x cannot fix the race — but
it can stop it from being **silent**.

## Dev10x-side mitigation

1. **Per-session load marker** — the SessionStart orchestrator
   (`hooks/scripts/session-start.py` → `session_load_marker` in
   `src/dev10x/hooks/session_place.py`) touches
   `/tmp/Dev10x/sessions/<session_id>` on every load.
2. **Userspace load-guard** — `hooks/scripts/plugin-load-guard.sh`,
   installed to `~/.claude/hooks/` and registered as a **userspace**
   SessionStart hook (which runs even when plugin discovery skipped the
   plugin). It waits a short grace window for the marker; if it is still
   absent it emits `additionalContext` telling the user to
   `/plugin reload`. Warn-only, fail-open — never blocks a session.
   See `skills/upgrade-cleanup/SKILL.md` for install + registration.

The guard stays silent when the plugin loaded (marker present), when the
plugin is deliberately disabled (`enabledPlugins` pins it false), or when
`/tmp/Dev10x/sessions` is missing entirely (old plugin or cleared tmp).

## Diagnosis chain

When a session looks like the plugin was skipped, confirm with this
evidence chain (each step distinguishes "skipped at startup" from a
genuine config/packaging defect):

1. **MCP server logs** — `mcp-logs-plugin-Dev10x-cli/` for the project.
   Compare the last `Dev10x-cli`/`db` server-start timestamp against the
   session start time. A skipped session starts its claude.ai MCP
   servers but never starts `Dev10x-cli`/`db`.
2. **Hook audit log** — `/tmp/Dev10x/logs/hooks-YYYY-MM-DD.jsonl`. A
   skipped session has **no SessionStart records** at its start time —
   the plugin was never dispatched (distinct from a hook that ran and
   failed, which would log a failure).
3. **`claude plugin list`** (run from the same CWD) — shows the plugin
   `✔ enabled`. State files are fine; the failure is transient at
   startup, not a persistent config problem.
4. **`~/.local/share/claude/versions` mtimes** and
   `installed_plugins.json` / `known_marketplaces.json` rewrite times —
   a Claude Code auto-update or a concurrent session's marketplace
   auto-update landing near the session start corroborates the race.
5. **Config sanity** — global `~/.claude/settings.json` has
   `"Dev10x@Dev10x-Guru": true` (correct casing), and no project-scope
   `enabledPlugins` mis-cased key shadows it (a separate, known failure
   mode). If those are clean, the transient race is the remaining
   explanation.

## Related

- Mis-cased `enabledPlugins` key shadowing user scope is a **different**
  failure mode (persistent, per-project) — check it before concluding
  the transient race.
