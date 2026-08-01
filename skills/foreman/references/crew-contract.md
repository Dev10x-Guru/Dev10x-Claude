# Crew contract — what every worker prompt must contain

Build each worker prompt from
[`crew-prompt-template.md`](crew-prompt-template.md). Every element
below is non-negotiable, and each exists because its absence cost hours
in the field (GH-890).

| Element | Why it is mandatory |
|---|---|
| `background_preamble` (fetch via MCP) prepended verbatim | Background agents never see the session friction briefing; without it they reinvent `cd &&`, pipes, heredocs |
| `ToolSearch` select-query bootstrap for every MCP wrapper the chunk needs, and ZERO `Skill(...)` calls anywhere in the prompt | Subagents get MCP wrappers only as deferred tools and get no skills at all. A prompt naming `Skill(Dev10x:gh-pr-merge)` does not make its 9 checks run — it makes the worker improvise (`tool-surface.md`) |
| Lifecycle split: implement → test → commit → push → PR open and verified not-draft → CI green → review addressed → **STOP**. Workers never merge, never close issues | The merge gate lives in a skill only the top-level watchdog can call. A worker merging without it has full autonomy and no guardrails — "auto-merge on CI green" executing as "merge, having checked nothing" (field case: PR #901 landed squashed against documented rebase discipline) |
| Post-condition re-verification: re-check `isDraft` via `pr_get` after `create_pr` AND after every force-push | A state-changing call's effect does not survive later git operations. Field case: PR #926 was `pr_ready`-ed, then silently reset to DRAFT by a force-with-lease push — bots skip drafts, so CI and review went quiet on a PR believed open |
| Anti-stall rule: no `sleep`/`--watch`/poll loops; CI via single-shot `ci_check_status` | A blocking wait dies on a permission wall and the worker hangs silently |
| Named per-domain test tools with exact invocation (from Phase 0.4) | Generic "run the tests" prose sends workers to `npm … \| tail` shapes that prompt |
| Heartbeat protocol: append one line to `status-<chunk>.md` via Write every ~15 min AND at phase transitions | File mtime is the stall detector's ground truth; self-reported timestamps lie, mtimes don't |
| Scope authority + cut protocol — every cut ends as a tracker issue: defer (original stays OPEN with a structured deferral comment, EXCLUDED from `Fixes:`, commit footer reworded, requeued by issue number) or split (partial PR closes the original; remainder becomes a NEW scoped issue, `Refs:`-linked) | The queue and manifest live in a temp dir — after a catastrophic harness failure, open tracker issues are the ONLY surviving record of cut scope; a cut issue that still auto-closes on merge is a silent lie to the tracker |
| Review discipline: address ALL top-level review comments (even INFO); auto-resolve addressed BOT threads only — never human threads; zero `fixup!` commits left at hand-off | These are the merge-gate conditions the watchdog will check; a worker that ignores them just hands back a PR the gate refuses |
| Decision log file per chunk | The supervisor audits choices in the morning, not at 03:00 |
