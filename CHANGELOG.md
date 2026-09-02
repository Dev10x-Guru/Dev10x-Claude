# Changelog

All notable changes to the Dev10x Claude Code Plugin are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

## 0.96.0 — Catalog Propagation, Narrated Evidence & Outside-Session Recovery

Released 2026-09-02

### Features

- **Wake a quota-paused night run from outside every session** — a platform
  pause takes the session and its event queue down together, so a run cannot
  observe its own quota reset: `foreman watch` emitted QUOTA RESET 15 minutes
  after the 2026-08-31 freeze and nothing delivered it, leaving five hours of
  paid capacity unused until the supervisor returned. `dev10x watchdog` now
  runs from cron or a systemd timer and owns the three parts that are ours —
  reading the 5h block offline, finding runs whose heartbeats have all gone
  silent, and firing at most once per block boundary. It deliberately does not
  speak the harness cross-session protocol; the operator supplies the resume
  command their setup supports
  ([GH-1109](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1109))
- **Let a filed ticket arrive already triaged** — the filing tools always
  accepted `milestone` and `labels`, but no flow populated them, so the backlog
  depended on manual restructure sweeps: on 2026-08-30, 11 of 16 open issues
  were unmilestoned and 10 of 13 unlabeled, every one filed through these
  wrappers. A read-only `triage_roster` exposes open milestones and the live
  label roster in one call, `Dev10x:ticket-create` proposes both from it, and
  `needs-triage` is filed when nothing fits so strays stay findable
  ([GH-1102](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1102))
- **Let a walkthrough recording speak and frame its own story** — `qa-self`
  captions were already narration copy, but nothing spoke them and nothing
  persisted them, so a reviewer read a caption bar that had often already timed
  out. `Dev10x:tts` wraps piper (one batched process, licence reported never
  enforced), caption dwell derives from the spoken audio so the two cannot
  drift, and nine annotation shapes returned by five real capture runs —
  redaction that survives navigation, before/after compare, steps and measured
  chapters, absence captions, interstitial cards, highlight/zoom/hold — compose
  with the pointer halo rather than replacing it
  ([GH-1112](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1112),
  [GH-1126](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1126))
- **Let QA evidence reach a shareable link and assemble without a prompt** —
  `qa-self`'s publish step only knew Linear, so a walkthrough that would carry
  the argument on a PR had nowhere to go. `Dev10x:yt-upload` and
  `Dev10x:qa-publish` return the embed form each destination can use, resolve
  account and channel from userspace config with no built-in default, and
  namespace the borrowed token per uid and pid. Stitching an evidence sheet no
  longer prompts either — the composing verbs ship as a catalog group in both
  the IM6 and IM7 spellings
  ([GH-1119](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1119),
  [GH-1141](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1141))
- **Let the PR surface carry the caller's body, branch and milestone** —
  `create_pr` assembled every body from `job_story` plus a generated commit
  list, so anything else the caller supplied was dropped silently; it derived
  the head branch from the invoking process's CWD, leaving a cross-worktree
  orchestrator no way to name the branch it meant; and nothing on the MCP
  surface could write a milestone, so `gh-pr-monitor` Phase 3.5 always took its
  silent skip branch on a bundle PR
  ([GH-1073](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1073),
  [GH-1098](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1098))
- **Let a waiter sit out bot legs while a required check is red** — a Phase 4.6
  dispatcher needed the review legs to anchor before grooming force-pushed
  their SHAs, but on any branch carrying `fixup!` commits the required
  `git-history-linting` leg fails by design, and `wait_out_pending` covers a
  failed ADVISORY leg only. The dispatcher read the contract correctly,
  hand-rolled a `while`/`sleep` loop through `Monitor` — which no hook
  validated — and stalled on a prompt. `wait_for` names checks that must settle
  regardless, `Monitor` joins the same validator chain as `Bash`, and both
  hand-rolled loop shapes are now hard blocks
  ([GH-1138](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1138))
- **Let diag-friction see a missing permission layer** — the skill a supervisor
  reaches for at the moment of friction audited rule shapes but never asked
  whether the effective settings file carried the catalog at all, so a worktree
  short by 137 of 285 rules stayed "constantly stuck on basic actions" while
  every run diagnosed the individual command. A new Step 3a resolves the file
  the engine actually reads, runs `catalog-gap`, and gates any backfill behind
  a required question
  ([GH-1139](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1139))
- **Let a blocked command name the rule that stopped it** — audit records for a
  denied command carried only `outcome=block` and a timing, so a day's log
  could say seventeen blocks happened but never which rules fired, making
  friction impossible to prioritise by frequency or to prove fixed. `rule_id`
  now rides from the emitting validator through to the audit record
  ([GH-1095](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1095))
- **Let open loops outlive the exchange that raised them** — `Dev10x:ask` saw
  only decision-shaped questions in the last 10-15 turns; a promised follow-up,
  a finding scrolled past, an unanswered supervisor question had no detector
  and left no trace. Mode 3 detects four loop shapes with closed-by criteria,
  reconciles against the task list, and routes only decisions into the widget
  batch ([GH-1081](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1081))
- **Enable formatted Google Chat review panels by default** — notifications
  could only carry one plain-text body, so a review request arrived as an
  undifferentiated run of text. `cardsV2` panels ship with a
  markup-to-card-HTML translator, mentions kept in the text half where they
  still notify, and default-on with both per-repo and global opt-outs intact
  ([GH-1113](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1113),
  [GH-1115](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1115))
- **Let a batched shell loop and a plumbing git read steer instead of prompt** —
  a `for`/`xargs` loop over a known list collapses N individually-approved
  calls into one unmatchable command, and `git --git-dir=… status` from a
  worktree matched none of the pre-approved prefixes while offering `git *` as
  the "don't ask again" rule. The loop shape now carries an advisory steer to
  parallel Bash calls; the plumbing spelling is pre-approved for read-only
  verbs in both argument orderings, with mutating verbs still routed to the git
  skills ([GH-1117](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1117),
  [GH-1135](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1135))
- **Let the capture path serve any deployment or checkout layout** — two
  hardcoded values made `run-playwright.sh` unusable as documented outside one
  deployment and one pair of accounts, so users forked it and lost the
  syntax-validation and no-hardcoded-credentials guarantees it exists to
  provide. `STAGING_URL` gets the `${VAR:-default}` treatment, and a credential
  map read from the secrets file makes a third account two lines of config.
  `qa-self` Phase 1.2 had the same defect one layer up — absolute clone paths
  and the argocd manifest path were baked into the deploy check, so the one
  step the skill calls critical could not run outside a single layout and was
  the first to get skipped, with a teammate falling back to a local script.
  Every remaining deployment path is now the fallback half of a documented
  override, pinned so it cannot drift back
  ([GH-1130](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1130),
  [GH-1147](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1147))

### Fixes

- **Let the catalog reach every project settings file** — once a machine's
  global `~/.claude/settings.json` had been seeded, no catalog rule ever
  reached a project file again: both write paths filtered the rendered catalog
  against global before writing, and `include_user_settings` puts global in the
  same list. Every addition after that first seeding was a no-op for every
  project — 137 of 285 shipped rules absent — while the run printed "All base
  permissions already covered by global settings." Writes are now unfiltered
  (`--dedupe-global` restores the old behaviour as opt-in), per-file counts are
  reported, a real write that leaves a gap exits non-zero, and `catalog-gap`
  makes verification a command rather than an inference
  ([GH-1136](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1136))
- **Let an edit keep the code it did not touch** — the PostToolUse formatter ran
  `ruff format` plus `ruff check --fix` over the whole file after every edit.
  Each Edit+hook pair is evaluated in isolation, so a three-edit revert had an
  intermediate state where an import genuinely was unused: F401 stripped it,
  edit 3 restored the call site, nothing restored the import, and the file was
  left raising `NameError` at a line nobody edited. No individual step was
  wrong. Formatting is now scoped to the edited hunk, lint fixes are gone
  entirely, the project's own line-length configuration is honoured, and the
  notice names the changed lines instead of saying "likely a formatter"
  ([GH-1143](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1143))
- **Stop a groom from fusing a fix into a foreign commit** — when a branch's PR
  is merged by rebase the base gains the same patch under a different SHA, so
  `git rebase -i <base>` drops the todo's `pick` as already-applied and replays
  the trailing `fixup` onto whatever sits at the base tip, fusing a 267-line
  fix into an unrelated commit and losing the feature commit. The tool reported
  `conflict: true` with an empty file list while git saw no conflict, and
  following its hint completed the damage. The groom now refuses on an obsolete
  branch, disables rerere, and reports a stop with no unmerged paths as
  `REBASE_PAUSED` ([GH-1103](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1103))
- **Let an unknown tool parameter name itself** — FastMCP's generated arg model
  neither forbids extra keys nor carries them into the handler, so a parameter
  a release does not have is dropped twice over and the tool returns success
  having changed nothing: `update_pr(milestone=55)` against a pre-GH-1098
  install reported success and left the field null. Every wrapper gains that
  hazard the moment its documented surface runs ahead of the released one, so
  unknown arguments are now rejected at the boundary, naming each one and the
  running plugin version
  ([GH-1122](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1122))
- **Let a search name a linter without being blocked** — the DX016 guard split
  commands on `|` with a raw string split that ignores shell quoting, so
  `rg -n "pre-commit|ruff|mypy" settings.json` cut into three fragments whose
  middle was the bare token `ruff` — denied, with a suggested remedy that
  cannot apply to a search. Segmentation is now quote-aware and also covers
  `&&`, `;` and `||`
  ([GH-1133](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1133))
- **Let a bundle PR close every issue it names** — a bundle PR passing two issue
  references got one `Fixes` line, so only the first auto-closed and the second
  stayed open with nothing saying why. From the same 14-lane run: a swarm child
  that lost the MCP server fell back to raw `gh` for the merge itself, bypassing
  every pre-merge validation, because the template mandated wrappers but never
  said what to do when they are unreachable
  ([GH-1107](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1107))
- **Let a crew worker bound its own CI wait** — the crew template told workers to
  wait with an unbounded `ci_check_status(wait=true)` and named no fallback: on
  one night run CI recorded SUCCESS at 20:35Z and the worker was still "waiting
  on CI" when it was killed at 21:25Z. The wait is now pinned and falls back to
  the check rollup; separately `poll_until_terminal` probes before sleeping, so
  a call landing after CI finished no longer pays 60s for a verdict GitHub had
  already decided ([GH-1088](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1088))
- **Let fanout tear down locked agent worktrees** — an Agent-tool worktree can
  still hold the harness lock when teardown starts, so every
  `git worktree remove` failed with "cannot remove a locked working tree" and
  five of nine teardowns in one evening stalled — while the error text steers
  the reader to `remove -f -f`, which bypasses the dirty-tree checks that keep
  unmerged work ([GH-1094](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1094))
- **Let a body-only review round retire the earlier round** — "only the latest
  round is authoritative" was keyed on review summary comments alone, so a
  reviewer whose final round was a body checklist refresh plus an empty-body
  review left the previous round's INFO findings demanding a disposition after
  they had effectively signed off
  ([GH-1085](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1085))
- **Stop point_at from passing an off-screen element, and land it mid-frame** —
  `point_at` was documented as the capture-time assertion that catches a wrong
  screenshot, but `bounding_box()` returns coordinates for anything laid out,
  so below-the-fold targets — the normal state of most of a long page — sailed
  through. It now scrolls, settles and asserts against the viewport, and
  centring replaces "anywhere in view", since a target flush against the bottom
  edge passes the assertion and is still the worst place to point
  ([GH-1129](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1129),
  [GH-1144](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1144))
- **Let a settings-file read reach a surface that works** — `rg` against
  `~/.claude/settings.json` prompts while the same verb elsewhere runs clean:
  `~/.claude` is deliberately not a registered working directory, so the
  harness's path-scope gate fires and no allow rule can suppress it — and the
  prompt's second option grants unprompted edits to the file governing every
  other permission decision. The shape is now hook-blocked with the two
  sanctioned surfaces named, and a doctor strategy catches an option 2 accepted
  in an earlier session
  ([GH-1140](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1140))
- **Keep the working tree clean after a test run** — `command-skill-map.msgpack`
  was tracked in git but is a cache the loader rewrites whenever it is stale, so
  any test run, hook invocation or MCP call dirtied the tree; on one PR it rode
  into an unrelated fixup commit and produced a binary rebase conflict with no
  meaningful resolution. Untracked, alongside `.coverage.*` fragments, at the
  cost of a one-time ~15ms cold parse
  ([GH-1075](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1075))
- **Let the base branch report a real CI verdict** — the `create_pr` tests never
  stubbed the branch-detection seam, so their verdict depended on which branch
  CI checked out: green on a feature branch, 16 failures on every push to
  develop. That made develop's Actions signal worthless — the state in which a
  genuine regression goes unnoticed
  ([GH-1124](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1124))

### Documentation

- **Contain an MCP surface loss without a human** — an overnight run lost MCP
  three ways and the docs described one: the top-level case ended the run's
  merge queue until a human ran `/mcp`, and a dropped `update_pr` was silently
  lost, so a worker believed a PR body it had never written.
  `references/mcp-connectivity.md` is now the one home for all three surfaces,
  the watchdog gets its own recovery path at the merge gate, and the
  caller-side rule — a write is a request, not a receipt — is stated where
  every caller sees it. Reconnect-on-demand is closed as unbuildable here: the
  dying hop is harness-owned
  ([GH-1099](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1099),
  [GH-1072](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1072),
  [GH-1121](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1121))
- **Stop a takeover from discarding the work it saves** — the watchdog's STALL
  step 3 named respawn unconditionally, while a respawned isolation worker gets
  a fresh worktree, so a chunk that died holding uncommitted work lost all of
  it silently — the replacement reporting success on a tree it cannot see
  ([GH-1110](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1110))
- **Stop one gate from steering into the next** — the harness blocks a
  standalone `sleep` and recommends a Monitor until-loop, the exact shape the
  watch-loop rule flags as un-allow-listable, so an agent obeying the first
  hint lands on the second gate. The compensations now lead with the shapes
  that do not prompt
  ([GH-1132](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1132))
- **Spare an orchestrator from re-proving a worker's merge** — a worker that
  cannot fire an ALWAYS_ASK gate hands its nine-check report up, and the
  re-invocation contract made the orchestrator re-run all nine, validating every
  swarm merge twice for 3-4x duplicated tool traffic. A bounded handoff
  exception accepts the commit-graph and worker-local checks against a head SHA,
  while CI and all three comment checks stay fresh
  ([GH-1093](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1093))
- **State what the permission layer and the poll budget actually do** — the
  execution-order diagram gave precedence as deny/allow/ask while the cited
  section gave deny/ask/allow, and two places claimed catalog tiers are merged
  by `ensure-base`, which never happens. Separately `poll_until_terminal`'s
  docstring gave a poll budget that was neither its own formula's product nor
  the real ceiling, and had already misled one investigation. Also corrected:
  the upgrade-cleanup Modes table, which omitted the `ensure-base` step from
  bootstrap and dropped five "full only" steps
  ([GH-1095](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1095),
  [GH-1104](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1104),
  [GH-1127](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1127))
- **Let workers pin a sibling worktree with `git -C`** — the redundancy rule
  lived inside two mode branches and was never stated as a rule, so a worker
  carried "never `git -C /path`" as a blanket ban and hesitated to use the one
  shape that reliably works when CWD has reset
  ([GH-1089](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1089))

## 0.95.0 — Unattended-Run Hardening & Tracker-Aware Seeding

Released 2026-08-28

### Features

- **Seed the tracker a project actually uses** — `ensure-base` seeded the
  Linear MCP rules unconditionally, so a Jira or GitHub-Issues user
  collected ~35 inert `mcp__claude_ai_Linear__*` allows and 5 inert denies
  while their own tracker's tools still prompted on first use. The
  tracker→rules mapping now lives in the shipped catalog keyed by tracker,
  resolved from a durable `tracker:` key persisted by `pin_tracker` (repo-stem
  keyed, so one answer covers every worktree) and reported back rather than
  silently applied. GitLab and ClickUp stay out — an empty block would read
  as support that is not there
  ([GH-768](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/768))
- **Prove QA evidence shows what the test cases claim** — a green capture run
  proved only that the code ran: a step guarded by a silent
  `if locator.count() > 0:` no-opped without failing, so blank screenshots and
  content-free videos published straight to an append-only ticket trail.
  Every artifact is now verified before publishing (size floor, uniform-frame
  check, three frames sampled per video), the upload is gated on a local
  approve / re-capture / abort review, and the recording overlay moved out of
  prose into an importable, tested module installed via `add_init_script` so
  it survives navigation
  ([GH-1086](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1086))
- **Attribute a stall to its worker and wake the merge gate** — stall detection
  read the newest mtime across the whole run directory, so a foreman writing
  its own status hid every silent worker behind it; three sat quiet 87–92 min
  before the alarm fired. Escalations had the mirror problem — the disk record
  was authoritative but had no reader, so three MERGE REQUESTs waited hours.
  Each `status-*.md` is now timed and rate-limited separately, and
  `escalations-*.md` is tailed from an arm-time byte cursor with every MERGE
  REQUEST / ESCALATION line re-emitted verbatim
  ([GH-1064](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1064),
  [GH-1060](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1060))
- **Let read-only project queries run unprompted** — listing an org project's
  items to build a work queue stopped on an approval prompt whose "don't ask
  again" suggestion offered `gh project *`, a rule that also admits the delete
  verbs. The four read verbs ship pre-approved; every board-mutating verb keeps
  prompting, the way `gh run` and `gh workflow` are already stratified
  ([GH-1078](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1078))
- **Let unattended cleanup delete local branches unprompted** — an overnight
  crew tidying up after killed workers hit a confirmation prompt on
  `git branch -D`: an ask-bucket entry was shadowing three existing allow
  rules, and ask outranks allow. At 3 a.m. that is a silent wedge, not a
  safeguard, and deleting a local branch removes a ref rather than history. The
  family is pre-approved, and a new `ask-shadows-allow` doctor strategy reports
  any ask/deny rule outranking a same-family allow
  ([GH-1067](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1067))

### Fixes

- **Let the CI wait absorb the polling it promises to absorb** —
  `ci_check_status(wait=true)` ended its wait on the blended verdict, which
  flips to `failing` the moment ANY check fails, required or not. With
  `claude-review` red org-wide during a night run, every call returned
  instantly with three legs still pending — an unactionable verdict the caller
  could only answer by hand-polling, the exact work the wait exists to remove.
  Remaining legs now settle first (`wait_out_pending`, default true), while a
  failed REQUIRED check stays terminal on sight
  ([GH-1065](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1065))
- **Let a posted disposition actually clear the merge gate** — Check 1b
  promised a keyed `Re: comment <id>` reply disposes of the finding it
  answers, but `is_reply` tested the whole body against `^[[:space:]]*Re:` and
  jq anchors that at the start of the STRING. The documented gh-pr-respond
  shape opens with a preamble line, so every disposition posted to satisfy the
  gate RAISED the blocking count by one. `Re:` now matches per line
  ([GH-1057](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1057))
- **Ensure a force push to a protected branch is refused** — GH-1047 closed one
  evading spelling; six more remained, including a force push to `main` on its
  canonical spelling, because the shell loop overwrote `remote` with both
  positionals whenever the remote was actually named `origin`. Both guards now
  count positionals, skip value-taking flags, treat a leading `+` as force,
  unqualify `refs/heads/<x>`, locate `push` relative to a `git` token, and fail
  closed on shell expansion — what the guard cannot read, it must not clear
  ([GH-1049](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1049))
- **Stop a script guard from blocking talk about the script** — the DX006
  `git-push-safe-script` rule guards a script path, but patterns are searched
  against the whole command string, so every command that merely NAMED the
  script was denied — and the block named `push_safe` as the remedy, which can
  neither lint nor move a file. An opt-in `match_position: invocation` matches
  only tokens naming a program being run, with env prefixes stripped in both
  spellings and the choice carried through the msgpack cache
  ([GH-1084](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1084))
- **Stop steering a file search into a dead end** — the shell-write validator
  read `find … -printf '%p\t%s\n' 2>/dev/null` as a `printf` redirect and
  steered to Write/Edit, which cannot enumerate files; diag-friction then routed
  the rejected `find` to `Glob`, which answered "No such tool available". A
  leading `-` now reads as a flag, every use-tool compensation carries a
  `fallback:`, and Step 3g verifies the recommended tool exists in this session
  ([GH-1087](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1087))
- **Let crew workers test their CWD mode instead of guessing** — three artifacts
  told a worker three different absolute rules about Bash CWD, and each was
  wrong at some spawn depth: the crew template mandated `git -C <worktree>`,
  the background preamble forbade it, and validate-bash DENIES `git -C <path>`
  when CWD already equals that path. Worker B1 wedged at fetch/rebase for ~2h
  and two takeovers. Persistence is not a property of being a subagent, so the
  fixed spelling is replaced by a self-test — `cd` then `pwd` as separate calls
  — with the mode declared in heartbeat 1
  ([GH-1050](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1050))
- **Prevent crew workers wedging on unsanctioned tool shapes** — Bash `find`
  over parenthesised route-group paths, a lost MCP connection after ~60 minutes
  read as "operation impossible", and a bare `pre-commit` linting the
  dispatcher's tree each wedged unattended workers with no hook-log trace. The
  crew template mandates Glob over Bash `find`, retries the ToolSearch
  bootstrap once, and carries a `{{lint_shape}}` placeholder;
  `uv run --directory <wt> pre-commit` is allowed as the only shape that
  reaches the intended worktree
  ([GH-1059](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1059),
  [GH-1066](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1066))
- **Stop three gates from blocking on their own false readings** — the merge
  gate refused PRs over severity words in comments that said the opposite ("No
  CRITICAL issues found") and missed an unmarked Review Summary wrapper, so
  supersedes never engaged; `set-friction` wrote a worktree entry shadowing the
  repo's, silently dropping `human_review`, which fails toward true; and the
  gh-issue-comment rule answered its own block with a hint naming a shape the
  same rule blocks
  ([GH-1054](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1054))
- **Tell the operator which key is holding the merge gate** — a night run
  composed adaptive + [solo-maintainer, afk] froze on its first merge with
  `floor:human_review overrides preset:adaptive`. The floor is right — no
  session overlay may lift a durable project fact (ADR-0019) — but the operator
  had no way to learn that a project key, not the preset, was holding it, at
  02:00 with nobody to ask. Floors with a remedy now name it and the file it
  lives in; action floors stay remedy-free
  ([GH-1056](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1056))
- **Stop re-litigating allows the maintainer accepted** — the shape-only auditor
  reported `Bash(git reset --hard:*)` as REDUNDANT beside `Bash(git reset:*)`
  and proposed removing the very rule `ensure-base` re-adds, so
  plugin-maintenance steps 4 and 10 undid each other every run. Accepted
  findings are now recorded (shipped defaults plus a user
  `~/.config/Dev10x/accepted-findings.yaml`), still computed and shown under
  "Suppressed by accepted-findings" but no longer proposed, scoped to named
  classification tokens so one acceptance cannot silence a different finding
  ([GH-1053](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1053))
- **Keep web build shapes off the Bash layer** — `run_node_tests` reads as a
  test wrapper, so its build/check siblings kept running on the Bash layer even
  though GH-1029 gave the tool a `script=` parameter covering them. In an
  unattended subagent an unmatched shape that prompts is a silent wedge: worker
  B2 posted "starting SvelteKit UI" and made zero tool calls for 80+ minutes.
  A `node-build-scripts` map entry steers those shapes, listed after
  `node-tests` so first-match-wins keeps `npm run test` on the test rule
  ([GH-1052](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1052))
- **Let a local test run stay readable on any hardware** — the startup baselines
  were recorded on the CI runner, and developer hardware varies enough to make
  them unreachable (~135 ms against a 37 ms baseline, failing identically on a
  clean `origin/develop`). Three permanently-red tests teach every reader that
  a red `bench` means "the baselines again" — the exact state in which a real
  regression goes unnoticed. A breach now fails in CI and warns locally, with
  `DEV10X_BENCH_STRICT=1` to opt in
  ([GH-1080](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1080))

### Refactoring

- **Prevent per-session audit label accumulation** — every audit-file run minted
  a fresh `audit-YYYY-MM-DD` label; 26 had piled up. The date duplicates the
  session date already in each issue body, and milestone bundling supersedes
  their grouping value, so the category is retired while `skill:<name>` and
  topical labels stay
  ([GH-1070](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1070))
- **Let the maintainer merge their own PRs without a prompt** — the git-tracked
  `merge: ask` pin assumed a team repo needing a human merge through the PR UI,
  a premise `settings-pr-merge.yaml` (`solo_maintainer: true`) no longer
  matches. The pin is removed and the file kept with the rationale rewritten,
  since an absent file is indistinguishable from one that never existed
  (self-motivated)

### Docs & Guidance

- **Ensure pre-flight proves the gates the watchdog needs** — Phase 0.4
  enumerated only the crew's command shapes, so the merge gate's own policy was
  never resolved, the watchdog's CI and triage commands were never proven, and a
  worker could learn a check went red with no sanctioned way to read why. Each
  froze a night run. Pre-flight now dry-runs `resolve_gate(gate="merge")` with
  three honest remedies, routes watchdog reads to wrappers, and proves the
  failing-check log, dependency-install, and worktree-cleanup shapes
  ([GH-1051](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1051),
  [GH-1058](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1058),
  [GH-1062](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1062))
- **Stop crediting a lock the foreman harness does not have** — the tool-surface
  doc argued the merge gate holds because workers cannot reach it. Only half
  true: `merge_pr` is an ordinary deferred tool a worker can load itself, and in
  the audited run one did, and merged. What actually holds the line — the prompt
  contract plus the omission of `merge_pr` from the crew select-query — is now
  named, with the unenforced path recorded as a known gap. The merge gate must
  read each `Fixes:` line against the diff, the overseer must paste its own
  `ci_check_status` output before any MERGE REQUEST, reverting delivered work
  counts as a scope cut, and a takeover brief carries a mandatory manifest
  preface
  ([GH-1061](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1061))
- **Size fanout waves to the host, not just the concurrency cap** —
  `max_concurrency` caps CPU and API concurrency, but each isolated agent also
  carries its own worktree checkout and process footprint; a wave sized purely
  to that cap drove the host into memory pressure, and the mass-resume that
  followed recreated it. Host memory is named as a wave-sizing input, and a
  mass-resume is stated to be a dispatch that waves like any other
  ([GH-1068](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1068))

## 0.94.0 — Force-Push Rails & Config-Path Convergence

Released 2026-08-25

### Features

- **Enable shipped defaults to reach every install** — the userspace catalog
  shadowed the shipped one: `resolve_config` returned the first existing
  candidate, so a `projects.yaml` created once by `permission init` hid every
  safe default shipped after it, while `ensure-base` validated against the
  stale copy and reported success. The only signal a user got was a permission
  prompt at point of use. Rules now merge as shipped + additions − suppressions
  at load time, a suppression naming a shipped deny is refused, and
  `permission catalog-diff` reports drift
  ([GH-912](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/912))
- **Enable non-test package scripts inside the wrapper** — `run_node_tests`
  hardcoded the test script, so a `lint:tsc` check fell back to a raw `tsc`
  invocation on the Bash layer, outside the wrapper's guardrails and into the
  brace-expansion block no allow-rule can suppress. `script=` and `env=` are now
  accepted; only the package managers resolve a script name, and jest/vitest
  fail loud rather than ignoring it. Bundled with a durable
  `protected_branches` pref for `push_safe` and a bounded merge-gate
  Remaining-issues scan
  ([GH-1029](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1029),
  [GH-1031](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1031),
  [GH-1011](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1011))
- **Enable keyless Google Chat auth via SA impersonation** — orgs enforcing
  `iam.disableServiceAccountKeyCreation` cannot download service-account keys,
  which blocked `gchat-send` setup entirely; even where keys are allowed they
  are long-lived credentials that never expire. gcloud ADC can now impersonate
  the Chat bot's service account through the IAM Credentials API, minting
  short-lived `chat.bot` tokens with no key ever created. The `sa_key` keyring
  flow remains the implicit default
  ([GH-1032](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1032))

### Fixes

- **Prevent agents executing unvalidated database writes** — the read-only SQL
  gate exempted psql wrapped by `docker exec` or `op run` unconditionally, so a
  wrapped `-c "DROP DATABASE"` cleared every check; three destructive writes ran
  against tt-pos despite a SELECT-only contract. The documented last line of
  defence was inert too, because `should_run()` gates on `_QUICK_TOKENS` and of
  the write verbs only CREATE contains one. The wrapped invocation's SQL is now
  checked, getopt bundles and attached values are parsed, `-f`/`--file` counts
  as a write, and `pg_terminate_backend`/`pg_cancel_backend` are blocked
  ([GH-1034](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1034))
- **Let foreman workers reach their own worktree** — crew workers were told
  their CWD persists across Bash calls; in Agent-spawned subagents it resets
  every call. Workers found git operating on the dispatcher's tree, improvised
  `git --git-dir=…`, and wedged on a prompt nobody could answer overnight — and
  a pending prompt records neither a block nor a denial, so the only symptom was
  a heartbeat stall: ~2h and two takeovers to detect
  ([GH-1028](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1028),
  [GH-1025](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1025))
- **Surface worker git prompts while the supervisor is there** — Phase 0.4
  proved the CLI shape, MCP wrappers, the subagent ToolSearch surface, and
  per-domain test tools, but never a git command in the worktree-pinned shape a
  worker actually runs. The probe came back fully green and two workers still
  died later on git permission prompts, at an hour when a prompt is
  unanswerable and leaves no denial trace
  ([GH-1030](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1030))
- **Prevent a bundled force flag skipping the push rail** — the skill-redirect
  hook lets a push bypass the rail when it names a non-protected branch and
  carries no force flag, but the force half tested whole tokens only: POSIX
  short-flag bundling meant `git push -uf origin feature-branch` sailed through
  as an ordinary push. Short-flag clusters are decomposed letter-by-letter in
  both the validator and `git-push-safe.sh`, while long options stay on the
  exact-match path so `--force-with-lease` never matches on a substring
  ([GH-1047](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1047))
- **Protect staging from the hook-layer push escape hatch** — GH-1031
  reconciled three statements of the protected-branch default, but a fourth
  lived in `branch_name.py` as `frozenset(BASE_BRANCH_PRIORITY)`, which omits
  `staging` — so a push naming `staging` slipped through a guard the
  shell-level default does protect. The two lists answer different questions
  ("what does a PR target?" vs "what does nobody force-push?"), which is why
  they drifted; both are now commented and pinned by test
  ([GH-1041](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1041))
- **Let XDG config be the one place Dev10x prefs live** — GH-941 rehomed tier-2
  user config to `~/.config/Dev10x`, but playbook discovery still resolved
  overrides exclusively from the retired memory tree and `slack-notify`'s
  `CONFIG_PATH` had drifted to a path nothing has ever written. Docs kept
  naming the retired tree, sending users to write config where nothing reads it
  ([GH-1045](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1045))
- **Ensure one DoD criteria file governs every checkout** — `verify-acc-dod`
  read its override criteria from the retired `~/.claude/memory/Dev10x/` path
  while the documented home was `~/.config/Dev10x/`, so a maintainer editing
  the documented copy saw no effect. The guard rule shipped for GH-948 covered
  only the ADR-0018 retirement, so both stale lines scanned clean
  ([GH-1035](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1035))
- **Give one posture one answer across gates and modes** —
  `legacy_session_mapping` maps `active_modes` to gate overlays and never back,
  so a repo migrated to `gate_preset` + `gate_overlays` read as solo-maintainer
  to `resolve_gate` and as nothing at all to every `active_modes` consumer: on
  the same PR, `request_review` resolved to skip while `verify-acc-dod` reported
  "Review requested — 0" as a failing check
  ([GH-1003](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1003))
- **Allow a fixup when one commit owns every branch hunk** — the resolver
  classified `single` only with zero orphan hunks, so any orphan promoted the
  result to `multi` and callers aborted, printing "restage per owning commit"
  against an owner list holding exactly one commit. Adding an import beside its
  first usage produces that shape every time. Classification now counts
  distinct owning commits alone, reporting `orphan_hunks` for visibility
  ([GH-1042](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1042))

### Docs & Guidance

- **Settle whether git restore sits inside the checkout rail** — a truncated
  worktree was repaired with `git restore` after `git checkout HEAD --` was
  denied, and doctrine had no clear answer: the substitution table forbade the
  swap, nothing said the rail covered the successor spelling, and the shipped
  baseline allows both. The rail covers the outcome, so it covers
  `git restore`; corrupted-tree recovery stays a supervisor-run procedure, with
  an unattended route that abandons the tree rather than repairing it
  ([GH-1039](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1039))
- **Record rejection of the plugin split** — a full dependency scan of all 87
  skills falsified ADR-0020's premise: the work-on closure spans 32 skills
  across five of the seven planned areas, so the satellites are not
  independently installable and only infra and data (4 skills) were severable.
  ADR-0020 is marked Rejected with the measured rationale, the SPLIT initiative
  prefix retired, and light-audience needs routed to a playbook profile
  ([GH-913](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/913),
  [GH-1013](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1013))

## 0.93.0 — Review Posture & Durable Session State

Released 2026-08-04

### Features

- **Let a project's review posture decide reviewer assignment, DoD checks
  and merge autonomy from one answer** — `review-deferred` was written to
  the `session.yaml` ADR-0018 retired, so in any configured repo the flag
  was written and never read: verify-acc-dod re-ran the very checks the
  supervisor had just deferred, and the write cost a consent prompt for no
  effect. Whether humans review PRs is now a standing project property
  (durable `human_review`, ADR-0019), read by reviewer resolution, both DoD
  review checks, and — as a gate floor rather than a skill-side check — the
  merge gate, so a repo declaring humans in the loop can never watch the
  agent merge for itself
  ([GH-950](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/950),
  [GH-1000](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1000))
- **Carry a self-review clearance beyond the session that granted it** — a
  supervisor answering "I reviewed it, OK to merge" had that answer
  recorded nowhere, so the next session re-entered the gate on the same PR
  and asked again. A `pr_labels` MCP tool (`list`/`add`/`remove`, shaped
  like `pr_comments`, both writes idempotent) carries a durable per-PR
  `review:cleared` label — and git-groom drops it after a force-push, since
  a sign-off covers only the commits that were read
  ([GH-1008](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1008))
- **Park work without paying a consent prompt** — five skills still wrote
  the ephemeral task index under a repo's `.claude/`, the exact trigger for
  Claude Code's self-settings consent gate that no allow rule suppresses.
  So every park, Slack reminder, PR bookmark and wrap-up paid a prompt. The
  index moves to `~/.config/Dev10x/task-index/<repo-stem>.yaml` behind
  `task_index_get`/`_append`/`_set` — keyed off the git common dir, so one
  index serves a repo and all its worktrees — with the retired path read
  and folded forward for one release
  ([GH-1009](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1009))
- **Warn before the quota wall so the queue parks first** — the watcher
  reported spend only after the fact, so nothing projected whether the
  remaining block budget could still carry the active crew; two workers
  burned into exhaustion and were misread as harness stalls for two hours.
  A forward-looking `QUOTA LOW` event fires once per block when projected
  exhaustion lands inside the chunk window, with the documented response
  (land a chunk one merge away, else WIP-checkpoint and park until
  `QUOTA RESET`) and the crew-wide-silence signature that distinguishes
  exhaustion from a per-worker stall
  ([GH-979](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/979))

### Fixes

- **Restore issue comments to every caller** — `issue_comments` died with
  "dictionary update sequence element #0 has length 11" because the script
  emitted a bare JSON array that `to_dict()` then ran `dict()` over. The
  failure was data-dependent, not unconditional: an issue with no comments
  yielded `[]`, which became a silent `{}` — callers read "no comments"
  from an equally broken payload. The unwrap is dropped, and non-object
  JSON now fails loud at the parse layer naming the offending script
  ([GH-993](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/993))
- **Let a pinned gate policy reach an agent worktree** — `friction.yaml`
  entries are keyed off the git common dir but matched against the
  invocation toplevel, and a linked agent worktree's directory name matches
  neither glob. The repo's pinned walk-away policy silently evaporated and
  the merge gate fell back to an `ask` wall at exactly the step an
  unattended run needs automated. Policy resolution now probes the worktree
  first and falls back to the repo root the entry was keyed by
  ([GH-978](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/978))
- **Give a stand-by PR an exit that is not an argument** — a repo
  configured `standby: true` had no way to say "I have now reviewed this",
  so the only exit was to argue the override down again on every PR. The
  path now asks, offering stand by / reviewed and OK to merge / reviewed and
  request the team now, and points a repo answering the same way repeatedly
  at the durable posture it actually wants
  ([GH-998](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/998))
- **Dispose of a review finding on whichever surface it lives** — the
  merge gate's answered-ids set was computed per-surface, so a keyed reply
  posted as an issue comment never matched a finding in a review body. A
  blocking review-body finding was unaddressable through sanctioned tooling
  — the only exits were rewriting the reviewer's own body or bypassing the
  gate. Both surfaces are now unioned before filtering
  ([GH-1002](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1002))
- **Route permalink rewrites through the sanctioned tool** — git-groom
  hardcoded a raw REST PATCH for rewriting commit permalinks, carrying a
  suppression marker that claimed no MCP edit action existed. GH-304
  shipped `pr_review_comment_edit` and made that stale, but the marker kept
  the lint quiet, so an agent following the skill literally still issued
  raw API calls until a supervisor rejected them
  ([GH-996](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/996))
- **Rebase a background agent onto the base that actually moved** — the
  standing guidance prescribed `git develop-rebase` as THE rebase tool for
  background agents, but `-i` hangs with no editor attached and the
  merge-base resolves against a possibly stale LOCAL ref, so it printed
  "Successfully rebased" while HEAD never left stale ancestry. Every
  prescription now names the explicit `fetch` + `rebase origin/<base>` pair
  plus a mandatory ancestry postcondition, since the success message is not
  proof; `foreman probe` also labels its base sha `origin/develop` so a
  reader can tell which ref they got
  ([GH-964](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/964))
- **Read a shell script without the execution guard firing** — a read-only
  `grep -E 'a|b' bin/x.sh` was denied as script execution: the alternation
  split the pipeline mid-quote and the fail-closed fallback matched the
  `sh` in the *filename*, so the guard fired hardest exactly when
  diagnosing a defect inside a shell script. The fallback now requires the
  interpreter in command position
  ([GH-971](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/971))
- **Keep the canonical lint suite green with worktrees present** — the
  dependency-pin hook full-repo scans by design, and its skip list omitted
  worktrees, each a complete checkout of the same repo. Every finding was
  re-reported once per tree, so leftover agent worktrees failed lint
  repo-wide: observed with 44 trees, a two-file `pre-commit run --files`
  emitted thousands of violations from paths the change never touched —
  blocking unattended crew commits outright
  ([GH-1004](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1004))

### Security

- **Close the command-substitution hole in the interpreter guard** — only
  start-of-string, pipe, semicolon, ampersand and newline counted as
  command boundaries, so `echo $(python3 <<< '...')` and its backtick twin
  slipped past: the guard saw the leading `echo`, and shlex tokenises
  `$(python3` as one word so the pipeline scan could not help. Both
  substitution spellings are now boundaries on the heredoc and fail-closed
  paths, with read-only utilities inside a substitution asserted still
  allowed ([GH-986](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/986))
- **Let an unattended agent push a finished branch when MCP is down** —
  with the cli server unreachable, `push_safe` was absent, the wrapper was
  blocked with "use the MCP tool", and raw `git push` was blocked with "use
  Skill(Dev10x:git)" — each message naming the other as the remedy, and the
  documented resolution assuming a human is present to ask. A non-force
  push naming an explicit, non-protected branch is now allowed straight
  through; the deny stands for anything the hook cannot verify statically
  ([GH-963](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/963))

### Docs & Guidance

- **Tell a stalled crew worker apart from a dead one** — the 2026-08-01
  night run killed five live, productive workers, throwing away two
  complete chunks, because heartbeat mtime cannot separate "wedged" from
  "absorbed in a long turn" and nothing preempts a model mid-turn to check
  a clock. The heartbeat is re-anchored to observable events (commit, test
  run, push, verification) with the clock demoted to a backstop, and
  `TaskStop` reserved for heartbeat *and* tool-call activity both stale;
  the sonnet caveat is recorded so the tier default reads as risk
  reduction, not immunity
  ([GH-967](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/967),
  [GH-966](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/966))
- **Give the night shift the references its harness assumed** — five
  reference docs close gaps each rediscovered the expensive way:
  `overseer-discipline.md` (an idle agent cannot heartbeat, so
  "passive wait + heartbeat" ends as a false STALL — heartbeat, ONE bounded
  blocking wait, heartbeat, act), `durability-envelope.md` (only pushed
  commits and issue comments survive a session death; transcripts do not),
  `worktree-recovery.md` (`EnterWorktree` into a sibling worktree reports
  success then wedges the subagent's Bash permanently — loud, but too late
  to be a safe probe), `roster.md` (a single-writer at-a-glance table of
  every delegated chunk, explicitly a derived rendering), and the
  spawn-by-request inversion where the watchdog becomes the crew's parent
  ([GH-962](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/962),
  [GH-965](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/965),
  [GH-977](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/977),
  [GH-976](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/976),
  [GH-972](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/972))
- **Find the night loop without scrolling past explanatory depth** —
  `foreman/instructions.md` had grown to 585 lines with the
  execution-gating parts buried, and its INDEX.md override entry described
  neither the real size nor the already-extracted split candidate. Depth
  moves to four new reference files behind named pointers; the loop,
  handshake, crew contract and red-flag tables stay inline
  ([GH-987](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/987))
- **Trust the docs about where session config lives** — ADR-0018 retired
  the per-repo `session.yaml`, but the schema reference still taught
  readers to create one, work-on forbade the write and then instructed it,
  and git-worktree guarded a seed on a file nothing creates any more. Every
  read and write site is repointed at the durable prefs
  ([GH-1001](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1001))
- **Let a groom's own steps land on pre-approved shapes** — git-groom
  opened Phase 1 with bare `git log`/`git merge-base` calls it never
  declared, so both cost a rejected Bash call, and Phase 1 read as a direct
  contradiction of work-on's never-self-assess rule. The two shapes are
  declared, `origin/<base>`-qualified forms are primary, and the groom
  prohibition is scoped to the orchestrator
  ([GH-997](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/997))
- **Survive a force-push at the merge gate** — a force-push resets a
  published PR to draft, so an earlier `pr_ready` (including
  `create_pr(draft=false)`) proves nothing by the time the gate runs. Check
  3 now requires `pr_ready` after the FINAL push plus a fresh `isDraft`
  read, and mid-body `Closes #N` lines are documented as informational
  only — the `Fixes:` trailer is what closes an issue on merge
  ([GH-958](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/958))
- **Author this repo's own `.claude` docs unattended** — the self-settings
  consent gate fires on the Write/Edit family for any path under
  `.claude/`, regardless of matching allow rules, and an unattended worker
  cannot answer a prompt. Since the gate is bound to the tool rather than
  the path, crew workers stage content outside `.claude/` and move it into
  place, with `settings*.json` and `.claude/Dev10x/**` hard-excluded.
  Recorded as a stopgap: the upstream fix is narrowing the gate
  ([GH-1004](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1004))
- **Offer an HTML artifact for reports a human actually reads** — long
  comparison-shaped reports wrap badly as transcript markdown.
  `references/html-artifact-reporting.md` makes an artifact an option for
  exactly those cases, with markdown still the default and a hard guard
  that no completion gate may depend on an artifact existing
  ([GH-974](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/974))

## 0.92.0 — Night-Shift Discipline & Dependency Bounds

Released 2026-08-01

### Features

- **Require a deliberate commit to adopt a breaking dependency** — the
  GH-914 trap (an unbounded `mcp` requirement silently taking down both
  MCP servers) existed in ~30 other uv-scripts. A shared
  `dependency_pins` detector now scans every PEP 723 header and
  `pyproject.toml` dependency array for a missing upper bound, wired into
  the canonical pre-commit suite, with bounds backfilled across every
  hook, server and skill script
  ([GH-916](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/916))
- **Surface pins that have gone stale instead of waiting for breakage** —
  pinning shifted the failure mode from silent breakage to silent
  staleness. `dev10x deps sweep` asks PyPI for each distribution's
  current stable release and reports pins whose upper bound now excludes
  an available major; a weekly workflow runs the same subcommand and
  opens an issue when the report is non-empty
  ([GH-937](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/937))
- **Fail CI when a REQUIRED gate ships without gate-enforcement evals** —
  a new eval-gap detector plus CI workflow and a standing skill-audit
  Wave 1 check closes the hole where a documented `AskUserQuestion` gate
  could be silently replaced with plain text. The CI scan is diff-scoped
  so pre-existing gaps do not block unrelated PRs, and coverage was swept
  onto every gated skill — 0 gaps across 87 skills, was 7
  ([GH-835](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/835),
  [GH-940](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/940),
  [GH-885](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/885),
  [GH-783](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/783))
- **Make a Phase-0 preset choice stick for the whole repo** — a preset
  picked at the session-adoption gate evaporated at session end, so every
  stale session re-asked and hand-authoring `friction.yaml` was the only
  way to make it durable. `pin_gate_preset` / `preset_pin_status` derive
  the key from the git common dir, so a pick made inside worktree
  `<repo>-3` also covers the main checkout and a `<repo>-9` created
  later — and nothing is written under any repo's `.claude/`
  ([GH-855](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/855))
- **Route an audit finding to the tracker of the plugin that shipped the
  skill** — skills from every installed plugin live under
  `~/.claude/plugins/`, so skill-audit Phase 7 could not tell whose skill
  a finding was about and either dropped it or misfiled it at the Dev10x
  repo. `resolve_plugin_origin` maps a skill path to its owning
  marketplace and source repo, with a REQUIRED gate confirming the
  destination and no guessing when the origin is unresolved
  ([GH-816](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/816))
- **Retire a superseded PR through a routed call** — `pr_close` mirrors
  `issue_close`'s shape so closing a stale PR is one MCP call instead of
  a raw `gh pr close` fallback, and `issue_close` now fails loud with
  "N is a pull request; use pr_close"
  ([GH-924](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/924))
- **Let an unattended watchdog see only events needing a decision** — the
  foreman watcher dedupes `BASE MOVED` echoes of the run's own merges and
  mutes quota/stall spam behind a parked flag, docs name both CLI shapes
  (`dev10x` vs `uv run dev10x`), and Phase 0.3 defaults to the
  adaptive+afk auto-advance composition rather than re-asking
  ([GH-946](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/946),
  [GH-947](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/947),
  [GH-944](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/944))

### Fixes

- **Keep a guard firing when the command is reformulated** — rule
  patterns match command-name prefixes with `re.search`, so a git global
  option between the executable and the verb broke substring adjacency:
  `git -C <path> push --force` matched no rule and pushed. That reads as
  "the check passed" rather than "the check was evaded", and it affected
  all 42 catalog rules. Global options are now normalized before
  matching, fixing every rule at once; `pr_ready` also gains `undo` so
  returning a PR to draft — the safe direction — has a sanctioned path
  ([GH-931](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/931))
- **Give the merge gate an exit once a bot finding is answered** — Check
  1b promised a finding was addressed once a later comment replied to it,
  but the scan never mapped a reply back to the finding it answered, so
  `blocking_count` never returned to 0. Replies now dispose of findings
  by comment id on the `Re:` line, keyed rather than prose-fuzzy, and
  `gh-pr-respond` emits the id so both skills agree on the contract
  ([GH-907](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/907))
- **Stop hiding a comment from reading as a disposition** — Gate 6
  auto-advanced to minimizing a resolved finding, which looks like it
  should clear Check 1b. It cannot: the scan consumes the REST
  issue-comments array, which carries no `isMinimized` field, so an agent
  following the gate to the letter still landed on `blocking_count: 1`.
  Minimization is now marked cosmetic everywhere it appears
  ([GH-920](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/920))
- **Produce a hygiene-clean PR body on the first try** — generated bodies
  recurrently tripped the hygiene bot: the Job Story sometimes lacked the
  `**so … can**` marker, and the checklist separator was emitted *after*
  the `Fixes` trailer, so every body ended with a bare `---`. `create_pr`
  now refuses a job story missing a marker and names it, and `update_pr`
  moves trailing content above the trailer
  ([GH-945](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/945))
- **Keep Slack review requests landing without `slack_sdk`** — the send
  path imported the SDK unconditionally and turned an `ImportError` into
  a dead end *after* `prepare` had already reported `ready: true`. The MCP
  server process does not always run where the declared dependency was
  installed, so every message path now falls back to a stdlib `urllib`
  POST using the token already resolved — making `ready: true` truthful.
  The privacy inventory documents the direct `slack.com/api` calls, with
  a test pinning the exemption to the policy entry that justifies it
  ([GH-917](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/917))
- **Discover MCP tools from an installed plugin, not just a checkout** —
  `permission enumerate-mcp` walked up from `__file__`, which lands in
  site-packages from an installed wheel, so the catalog came back empty
  and printed "No Dev10x MCP tools discovered" — indistinguishable from a
  genuine no-op. Any stale wildcard was left in place and the run still
  exited 0. A single `resolve_plugin_root()` resolver now covers the
  installed plugin cache, and a discovery failure exits 1
  ([GH-919](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/919))
- **Keep a perl substitution rule valid through canonicalize** — `doctor
  canonicalize` collapsed every `//` outside a `://` scheme, so an inline
  `perl -pe 's/…//g'` allow rule lost a delimiter and was rewritten into
  a syntactically invalid expression. The collapse is now scoped to path
  contexts and skips quoted interpreter bodies
  ([GH-918](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/918))
- **Get the right worktree from the worktree wrappers** — invoked from a
  session whose CWD is itself a linked worktree, `create_worktree` let
  optionals land in the repo-root positional slot and
  `next_worktree_name` computed the parent relative to the current
  worktree. The parent now resolves via `--git-common-dir`, and
  `create-worktree.sh` gains a real base-ref positional
  ([GH-960](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/960))

### Security

- **Keep an App JWT off the process command line** — app-auth calls
  shelled out to `gh api -H "Authorization: Bearer <jwt>"`, leaving the
  token readable via `ps` / `/proc/<pid>/cmdline` for the child's
  lifetime. Both calls now go through an in-process stdlib HTTPS client,
  so the JWT never reaches a subprocess argv
  ([GH-499](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/499))

### Refactoring

- **Keep durable gate prefs outside the repo entirely** — `Dev10x:afk`
  still wrote `.claude/Dev10x/config.yaml`, which ADR-0018 retired and
  GH-818's migrate-config deletes — a migrate/recreate loop charging a
  self-settings consent prompt on every invocation. Nothing guarded it,
  because the cli-friction scanner skipped YAML front matter where the
  authorizing grant lived. Reads now go through `preset_pin_status`,
  writes through `dev10x session set-friction`, and a new scanner rule
  covers front matter so the retired path cannot be smuggled back
  ([GH-948](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/948))

### Docs & Guidance

- **Give a crew worker the discipline it can actually reach** — the crew
  contract named `Skill()` calls no Agent-spawned subagent can invoke. A
  worker told to merge via `gh-pr-merge` could not reach it, fell back to
  a raw merge, and landed a PR squashed against the documented rebase
  discipline: the 9-check gate was imaginary at exactly the moment it
  mattered. The lifecycle now splits at the MCP boundary — workers
  bootstrap MCP wrappers via ToolSearch and stop at PR-open; merging
  moves to the watchdog, the one role that can invoke the gate
  ([GH-922](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/922))
- **Open a handshake before taking a stalled agent's work** — a tripped
  `STALL` now messages the agent with every completed action and requires
  a STOP-ACK plus a second silent heartbeat window before TaskStop; any
  reply is evidence of liveness and the agent is resumed instead of
  replaced. Flat spend is explicitly rejected as corroborating evidence
  of death, and `status-<chunk>.md` is worker-owned so a third-party
  write cannot forge the mtime the detector reads
  ([GH-923](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/923))
- **Admit what a respawn cannot reach** — a respawned worker gets a fresh
  isolation worktree, so a dead worker's uncommitted work is unreachable
  to it, and cross-worktree copies fail silently while reporting success.
  Respawn now recovers a chunk, never a tree, and a chunk that stalls
  twice with the same shape gets a different model tier on the third
  attempt rather than a more directive brief
  ([GH-957](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/957))
- **Start a crew worker in the right, clean worktree** — a spawned
  subagent inherits its dispatcher's CWD, so "you are already in your
  worktree, do not `cd`" was false for every parallel wave: one worker
  implemented a whole fix on the wrong branch, another never got
  traction. The template now opens with a cd-and-verify preamble and
  bakes in the dirty-worktree recipe verbatim — prose guidance failed in
  the field where the literal five-step recipe worked
  ([GH-959](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/959))
- **Prove the shapes a night run needs before arming it** — two Phase 0
  gaps burned pre-flight window on consecutive runs. The `dev10x` CLI
  shape now resolves from a table covering the plugin-cache install where
  bare `uv run` picks the wrong project, and any chunk whose deliverable
  is an executable artifact must have that artifact dry-run during the
  window — otherwise a worker meets a permission prompt at 02:00 and
  improvises a banned-shape workaround
  ([GH-961](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/961))
- **Write Job Stories in the project's own language** — localized story
  guidance for non-English tickets, pointing at Cucumber's Gherkin
  language reference for derived keywords
  ([#901](https://github.com/Dev10x-Guru/Dev10x-Claude/pull/901))

## 0.91.0 — MCP Pin Recovery & Judgment-Tier Discussion

Released 2026-07-30

### Fixes

- **Keep MCP servers loading when a new mcp major publishes** — both
  server entry points declared an unbounded `mcp>=1.0` in their PEP 723
  blocks, so every invocation resolved the newest release. When mcp 2.0
  dropped `mcp.server.fastmcp`, both servers died at plugin load and
  sessions started with no Dev10x tools, skills, or agents at all. The
  range is now pinned to `mcp>=1.0,<2` across both servers, the dev
  extra and the wheel smoke install, with a test rejecting any
  unbounded mcp requirement so the trap cannot reopen
  ([GH-914](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/914))
- **Keep `Dev10x:investigate` on plugin-owned skills** — the skill
  routed PR review to `pr:review`, a user-level skill that exists only
  on one machine, so the documented path silently fell through for
  every other install. Review now delegates to `Dev10x:gh-pr-review`
  ([#909](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/909))

### Features

- **Let the supervisor pick the model tier for ddd discussion agents** —
  solo facilitation hard-coded haiku personas, and in a real workshop
  that produced naive output: generic policies with no
  interaction-level thinking, where the same prompts on a frontier
  model surfaced actionable compound-failure scenarios. Discussion
  agents do judgment work, so the fetch/prep cost-tiering rationale
  does not apply — a REQUIRED model-tier gate now runs once per
  session and applies to both persona rounds and the devil's advocate
  ([GH-789](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/789))

### Infrastructure

- **Parse read-only config uniformly** — `rule_engine.py` and
  `platform/registry.py` read YAML with no error handling, so a
  malformed or missing file raised straight into the PreToolUse hook
  path while sibling readers degraded to `{}`. A shared
  `domain/common/config_io.py` (ADR-0015) now provides tolerant-by-
  default `load_yaml`/`load_json` with a strict mode raising a single
  `ConfigIOError`, and the fragmented readers route through it
  ([GH-828](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/828))
- **Keep `~/.claude` path resolution behind ClaudeDir** — a few direct
  `Path.home() / ".claude"` constructions lingered after GH-575/GH-80,
  re-scattering home resolution and bypassing the
  `DEV10X_CLAUDE_HOME` test override. The remaining sites now use the
  accessors, and an AST ratchet test fails on any new home-relative
  join outside them
  ([GH-829](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/829))

### Docs & Guidance

- **Plan the commit sequence before implementing** — a bundle of seven
  work-on findings: refactor-first commit planning in the feature and
  structured-spec plays, a documented subagent implementation model
  (disjoint-file partition, one parallel wave, no concurrent shared-DB
  test runs), merge-state checks before re-monitoring CI or rewriting
  history, a review-thread re-scan after human reviews, reuse of
  git-commit's 72-char validation when grooming, and a new
  `dev10x spec drift` CLI so SPDD gates run where inline python is
  blocked
  ([GH-904](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/904))
- **Stop afk runs freezing on self-opened gates** — an overnight run
  surfaced three orchestration gaps: a handoff-answered
  `AskUserQuestion` freezes the run (answer inline instead), afk must
  check the ALWAYS_ASK allowlist before self-initiated gates, and a
  no-watcher foreman should merge directly on green rather than
  rebasing a non-conflicting PR into CI ping-pong
  ([GH-903](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/903))
- **Create JIRA tickets reliably and own the k8s skill in-plugin** —
  `ticket-create` claimed Atlassian writes were pre-approved when they
  prompt as outward-facing mutations, so they cannot run from a
  background agent; the k8s skill lived only in one user's local
  skills dir behind a broken wrapper path. It ships as `Dev10x:k8s`
  with plugin-relative paths and the read-only kubectl wrapper
  ([GH-899](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/899))
- **Frame JTBD actor wants as outcomes, not work** — guidance still
  allowed the desire clause to read as effort ("the customer wants to
  pay online"), but nobody wants to run a transaction, and framing the
  mechanism as the want misidentifies both actor and beneficiary.
  Transactional effort verbs are now discouraged alongside UI verbs,
  with a "happiest doing nothing" heuristic and a money-movement
  worked example
  ([GH-902](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/902))
- **Bless `load_*` and `read_*` as data-retrieval names** — the naming
  rule sanctioned only `get_*`/`fetch_*`, while 33 functions across the
  package already used `load_*` for config parsing and `read_*` for
  file I/O with no documented standing. Both are now first-class
  conventions, `fetch_merged_prs` is a documented exception, and
  existing names must not be rename-swept
  ([GH-830](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/830))

## 0.90.0 — Google Chat Notifications & Unattended Delivery

Released 2026-07-20

### Features

- **Deliver PR review requests to Google Chat alongside Slack** —
  reviewers who watch Google Chat had no equivalent of the Slack
  review ping. A full transport slice now posts through a private
  Chat bot: config and service-account key resolution from the OS
  keyring, RS256 JWT access-token minting on the existing
  pyjwt + stdlib stack (no new dependency), message posting, and the
  `Dev10x:gchat` (send) and `Dev10x:gchat-review-request` skills with
  human-approval and draft guards mirroring the Slack pair
- **Enable unattended overnight milestone delivery** — long
  unattended runs died on permission stalls: an inline watch loop in
  a Monitor command once froze the supervisor session for seven hours
  while crew workers hung on blocking CI waits. The new
  `Dev10x:foreman` skill plus `dev10x foreman probe|watch` CLI give a
  two-tier watchdog/foreman/crew harness where every watcher lives
  behind one pre-approved command enumerated while the supervisor is
  present, and cut scope always survives harness loss by persisting to
  tracker issues
  ([GH-890](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/890))
- **Guide per-project friction setup at session start** — gate policy
  silently fell back to a preset for any repo without an explicit
  `friction.yaml` entry, so a project could run an autonomy posture
  the supervisor never chose. SessionStart now seeds a strict baseline
  when the file is absent, nudges when the project is unmatched, and
  the new `Dev10x:friction-setup` skill walks the supervisor through
  choosing gate and playbook axes
  ([GH-886](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/886))
- **Report the active usage block offline via dev10x cli** — agents
  reached for `npx ccusage` to read the active 5-hour usage block,
  which hard-prompts on every worktree and cannot be allow-listed. A
  native `dev10x usage blocks --active --json` command and pre-approved
  `usage_blocks` MCP tool provide the capability at source, parsing
  `~/.claude` usage JSONL with a bundled offline rate table
  ([GH-878](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/878))
- **Strengthen orchestration and merge-gate reliability** — a bundle
  of six skill-audit findings across work-on, fanout, gh-pr-merge,
  verify-acc-dod, gh-pr-create and gh-pr-request-review: armed
  auto-merge detection, plan-branch refresh on branch change,
  warn-and-ignore unknown gate context, non-resumable user-killed
  agents, a mandated full-suite gate before DONE, and a solo-maintainer
  adaptive completion gate
  ([GH-848](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/848))
- **Enable milestone re-open and editing via MCP** — re-opening a
  closed milestone was the only milestone mutation with no wrapper,
  forcing a raw `gh api PATCH`. New `milestone_reopen` and
  `milestone_edit` tools close that gap and satisfy the no-raw-gh-api
  rule
  ([GH-850](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/850))
- **Steer inline watch loops to pre-approved watchers** —
  structurally un-allow-listable `while`/`until`/`sleep` and
  `watch -n` shapes are matched exactly like Bash even as Monitor
  commands, so one prompted watch froze an orchestrator turn for
  seven hours. An advisory rule now routes them to `dev10x foreman
  watch`, `~/.claude/tools` scripts, or `ci_check_status`
  ([GH-879](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/879))
- **Route npm monorepo tests through run_node_tests** — the
  `npm --prefix <dir> test` shape stacked four friction sources with
  no single allow-rule. A hook-block rule now steers the monorepo
  forms to `run_node_tests(cwd=DIR)`
  ([GH-880](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/880))

### Fixes

- **Harden shared-state writes against concurrency (ADR-0011 wave)** —
  a bundle closing the gaps the ADR-0011 concurrency wave left behind:
  the rule-confidence store now holds a lock across load→mutate→save
  and writes atomically, the doubt-sink appends via a single
  `atomic_append_line`, the settings-migration apply pass re-reads
  under lock so a racing edit is never overwritten, gh/git subprocess
  calls in five polling scripts are bounded with timeouts, the dead
  `ConfigYamlDocument.write` path is retired, and reviewer checklists
  now enforce file-locks + timeouts on new stores and subprocess calls
  ([GH-822](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/822),
  [GH-823](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/823),
  [GH-824](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/824),
  [GH-825](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/825),
  [GH-826](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/826),
  [GH-827](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/827))

### Testing

- **Close eval and unit-test gaps on orchestration surfaces** — add
  evals for gh-pr-monitor and gh-pr-request-review, the ddd workshop
  skill, parametrized unit tests for session_rules policy decisions,
  and per-package coverage floors for domain, validators, config,
  spec, audit, hooks and skills
  ([GH-831](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/831),
  [GH-832](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/832),
  [GH-833](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/833),
  [GH-834](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/834))

### Docs

- **Adopt third-person domain-actor Job Story voice** — Job Story
  guidance mandated first-person voice, hiding the concrete domain
  role behind the need. The canonical reference and all skill docs now
  require a third-person actor + beneficiary, with "Choosing the
  Actor" and localized-story guidance added
  ([GH-847](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/847))

## 0.89.0 — Surface Silent Plugin-Load Failures

Released 2026-07-16

### Features

- **Warn when the Dev10x plugin was silently skipped at session start** —
  a startup race between concurrent sessions can leave Claude Code
  loading the session without the Dev10x plugin, and because no plugin
  hook fires nothing warns the user until a skill invocation fails. The
  race is upstream and unfixable from here, but it no longer stays
  silent: the SessionStart orchestrator writes a per-session load
  marker, and a userspace `plugin-load-guard.sh` that runs even when the
  plugin was skipped points the user to `/plugin reload` when the marker
  is absent
  ([GH-874](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/874))

## 0.88.0 — AFK Session Robustness & Permission-Policy Completion

Released 2026-07-16

### Features

- **Complete the Permission-As-Policy platform with an auditor and a
  resolver** — PAP-3/4/5 shipped `auditor_assessment`,
  `resolve_effect(context=)`, and `load_policy_layers` as tested
  surfaces with no production caller. `dev10x permission audit` now
  classifies allow rules (OVERLY_BROAD, WILDCARD_ESCAPE, HOOK_ENABLED,
  REDUNDANT) through the shared renderer, `dev10x permission resolve`
  resolves an effect with skill context off the layered tiers, and the
  seven ad-hoc `Bash(...)` regex parsers are unified behind `AllowRule`
  and `Policy`
  ([GH-819](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/819),
  [GH-841](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/841),
  [GH-867](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/867),
  [GH-868](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/868))
- **Migrate legacy per-repo config into the global friction.yaml** —
  ADR-0018 retired `.claude/Dev10x/config.yaml` but PR #815 shipped only
  a lazy read fallback, so existing repos kept working while their
  durable prefs never migrated and the stale files lingered. An
  agent-driven upgrade-cleanup step now folds a repo's legacy durable
  keys into a `friction.yaml` `projects[]` entry and removes the stale
  files once parity is confirmed
  ([GH-818](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/818))
- **Gate git-groom Strategy B on target shape before rebuilding** — Full
  Restructure reached the intended commit shape only after several
  destructive re-groom passes because the skill guessed the shape and
  iterated. A pre-rewrite AskUserQuestion gate now elicits the
  shape-defining constraints up front, a hook-safe N-commit
  reconstruction recipe replaces the improvised path, and a backup tag
  plus tree-equality diff gate the force-push
  ([GH-860](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/860))
- **Stop prompting on safe branch deletes under AFK** — `git branch -d`
  still prompted during fanout worktree teardown even though git refuses
  it for any unmerged branch. The stratified safe-delete forms are now
  synced into the flat `projects.yaml` catalog that ensure-base deploys,
  while the destructive `-D`/`--force` form stays behind the prompt
  ([GH-864](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/864))
- **Keep work-on artifact delivery ahead of embedded questions** —
  work-on could latch onto an inline question as the primary task and
  stop instead of keeping artifact delivery as the goal. A Phase 1 rule
  now treats a question alongside an artifact target as context, and a
  pure-question fallback fires only when there is no artifact target at
  all
  ([GH-865](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/865))
- **Prevent short-closing a Fixes-linked issue at merge** — a Fixes:
  link auto-closes its issue on merge regardless of how much of the
  stated scope the diff delivers, so a narrower slice could close the
  issue short. A new verify-acc-dod scope check and gh-pr-merge Check 1d
  compare the linked issue's scope against the diff before merge
  ([GH-856](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/856))

### Fixes

- **Restore file-write pre-approval via Edit() rules** — recent Claude
  Code versions no longer honor `Write(path)` permission rules or skill
  allowed-tools; only `Edit(path)` matches, and it covers all
  file-editing tools. `Write()` is converted to `Edit()` across the
  baseline catalog, the upgrade-cleanup seed, and ~18 skill
  allowed-tools blocks, and a doctor `rewrite` deprecation migrates
  already-seeded user rules
  ([GH-862](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/862))
- **Unblock AFK bot-to-bot review cycles and fix review order** —
  bot-authored threads still forced supervisor prompts, the reviewer's
  own round summary false-blocked the merge gate, and Code review ran
  before any commit existed. Threads now carry `author_type` and
  auto-delegate to gh-pr-respond when every unresolved thread is
  bot-authored, the jq filter scans only "Remaining issues", and the
  shipping pipeline commits before review
  ([GH-858](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/858))
- **Restore branch and task list on session resume** — a mid-work-on
  restart lost the visible TaskList and reported the base branch instead
  of the feature branch. `branch` is now a reserved `set_context` key
  that mirrors to the banner's top-level metadata, and a work-on Phase
  0.5 step rebuilds the TaskList from the persisted plan on a detected
  resume
  ([GH-861](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/861))

### Performance

- **Speed up the unresolved-threads sweep at scale** — the repo-wide
  sweep fired ~2 gh subprocesses per merged PR and timed out at scale.
  Batching PRs into chunked GraphQL queries via field aliasing (25 per
  request) and folding the audit-marker fetch into the same query drops
  ~400 subprocesses to ~9
  ([GH-836](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/836))
- **Speed up pr_notify with concurrent PR fetches** — three independent
  gh fetches ran serially (3× latency per monitor tick). New
  `PRStatusSnapshot`/`PRNotificationContext` value objects run the calls
  concurrently via a thread pool and make the formatters testable
  without a live PR
  ([GH-839](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/839))

### Internal

- **Consolidate the 2026-07-10 architecture-audit polish** — a run of
  archetype-alignment and testability refactors from the audit: gate
  resolution split into a testable query object, the ensure-* CLI folded
  behind a shared runner, the gh wrappers unified behind a run-and-parse
  skeleton, gate conditions made data-driven, plugin loading shared
  across validators and doctor, the Plan terminal-task invariant pulled
  into the aggregate, domain archetypes aligned, and the `skills/`
  directory added to `.gitignore`
  ([GH-837](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/837),
  [GH-838](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/838),
  [GH-840](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/840),
  [GH-842](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/842),
  [GH-843](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/843),
  [GH-844](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/844),
  [GH-845](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/845),
  [GH-846](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/846))

## 0.87.0 — Permission-As-Policy Re-Platform & Session-State Relocation

Released 2026-07-11

### Features

- **Re-platform the permission catalog onto typed Policies** — two
  catalogs had drifted apart (the flat `base_permissions`/`base_denies`
  lists that `ensure_base` ships and the grouped, tier-tagged
  `baseline-permissions.yaml`), and permission rules carried provenance
  but had no engine to resolve conflicting layers. Every flat rule is now
  a `Policy` with lifecycle, scope, owner, and assessments; a
  forbid-wins, project > user > plugin resolution engine (`ask` beats
  `allow` inside the deciding tier) answers which effect governs a
  signature; and `ensure_base`, worktree seed/merge, doctor, and
  settings.json rendering all operate on the Policy set. A golden-corpus
  regression net gates the refactor and settings output stays byte-parity
  with the pre-PAP lists — the one intended diff is home-dir twin
  expansion for `~/` rules
  ([GH-797](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/797),
  [GH-798](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/798),
  [GH-799](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/799),
  [GH-800](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/800),
  [GH-801](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/801),
  [GH-802](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/802))
- **Enable gate-free session prefs via a global friction.yaml** — writing
  `.claude/Dev10x/{session,config}.yaml` with the Write/Edit tool tripped
  Claude Code's self-settings consent gate on every session regardless of
  allow rules, and per-repo durable prefs never synced across a repo's
  worktrees. Durable prefs now live in a global
  `~/.config/Dev10x/friction.yaml` keyed by project dir-path globs; the
  ephemeral `session.yaml` is deleted and the adoption/staleness gate
  reads branch/tickets from plan-sync; work-on Phase 0 and the
  post-checkout templates no longer write per-repo session state (ADR-0018)
  ([GH-812](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/812))
- **Guard skill docs against runtime `.claude/` writes** — with session
  state relocated out of a repo's `.claude/`, a new `write-guard-claude`
  rule flags `Write/Edit/MultiEdit(...)` calls whose path is under
  `.claude/`, scanning prose (not just shell fences) since the
  instruction is typically plain text, with the standard
  `# cli-friction: allow` opt-out
  ([GH-817](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/817))

### Fixes

- **Stop plugin-maintenance silently skipping worktrees** — worktree
  discovery only scanned `<root>/.worktrees/*`, so a project whose
  worktrees live elsewhere (still registered in `git worktree list`) was
  skipped entirely while the run reported success. Discovery now unions
  the `git worktree list --porcelain` set with the `.worktrees/` glob and
  the merge-worktree CLI echoes discovered coverage so a gap is visible,
  not implied
  ([GH-813](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/813))

### Docs

- **Record the 2026-07-10 A–I architecture audit memo** — the nine-phase
  project audit produced 37 findings that existed only as agent
  transcripts; they are now consolidated into one findings memo,
  reconciled against the 2026-06-10 memo, and re-verified against
  `origin/develop` after a parallel session merged the PAP and
  session-relocation work past the audited baseline
  ([GH-481](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/481))

## 0.86.0 — Drift-Free Session Config & Merge-Gate Hygiene

Released 2026-07-09

### Features

- **Split session config into durable and ephemeral state** — a single
  gitignored `.claude/Dev10x/session.yaml` conflated durable repo prefs
  (`friction_level`, `active_modes`, `gate_*`) with ephemeral
  per-worktree state (branch, tickets), so every write tripped Claude
  Code's self-edit gate and worktree provisioning carried stale
  branches. Durable prefs now live in a copied-by-post-checkout
  `config.yaml`; ephemeral state stays in a hook-seeded, read-only
  `session.yaml`, with transparent migration from a pre-split file
  ([GH-774](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/774))
- **Guard against stale high-autonomy modes bypassing gates** — a
  copied-forward `active_modes: [solo-maintainer]` could silently skip
  request-review and external-notify repo-wide. A local, gitignored
  `allowed_overlays` allow-list in `config.yaml` now filters overlays at
  the `resolve_gate` boundary (dropping only removes autonomy, never
  weakens a gate) and warns at SessionStart when a durable mode is
  dropped ([GH-805](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/805))
- **Keep the working tree clean during Dev10x sessions** — runtime
  artifacts under `.claude/Dev10x/` surfaced as untracked and tripped
  the clean-tree gates in `verify_pr_state`, gh-pr-merge, verify-acc-dod,
  and `create_pr`. The session seed now writes a directory-wide
  `.gitignore`, superseding the earlier per-file ignore
  ([GH-809](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/809))
- **Surface non-blocking findings and CI-infra outages** — INFO-level
  bot recommendations in COMMENTED/APPROVED review bodies were invisible
  to the merge/monitor comment gates, and `ci_check_status(wait=true)`
  collided with the MCP idle-timeout during hosted-runner outages. The
  gates now bucket blocking vs. needs-disposition findings and a distinct
  `infra_unavailable` verdict is returned when checks never register
  ([GH-808](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/808))
- **Handle bot findings cleanly at the merge gate** — skip `Re:` replies
  and strip quoted context before the severity scan, add a
  `pr_review_edit` wrapper to rewrite a submitted review body, and add a
  `pr_ready` wrapper to un-draft a PR so CI-suppressed drafts stop
  stalling the monitor
  ([GH-777](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/777),
  [GH-778](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/778),
  [GH-779](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/779))
- **Reflect live PR state in DoD checks** — a local-only plan that
  resolved "create PR" mid-run silently skipped the CI, draft, fixup,
  review-thread, and review-request checks. verify-acc-dod now re-infers
  the feature check set when an open PR is detected and surfaces the
  re-inferred checks in the results table
  ([GH-780](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/780))
- **Surface stale session carryover before resuming** — session-wrap-up
  now stamps its resume payload with branch, tickets, and a `wrapped_at`
  timestamp, and classifies carried park-discover entries as live vs.
  stale so a months-old task list is no longer re-surfaced as current
  ([GH-782](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/782))
- **Give bootstrap permission consent an informed disclosure** — the
  onboarding bootstrap now surfaces the state-changing subset (git, gh,
  script execution, settings) before the permission-approval gate so a
  cautious new user can see what they are about to grant
  ([GH-769](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/769))

### Fixes

- **Enable prompt-free session-config writes** — exact-path Read/Write/
  Edit rules for `session.yaml` and `config.yaml` join the unreliable
  `.claude/Dev10x/**` globs in base_permissions and propagate to every
  `settings.local.json`, so a normal run no longer re-prompts on
  git-derivable state
  ([GH-790](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/790))
- **Restore PR-monitor CI status reporting** — the status report crashed
  because `gh pr checks --json` no longer accepts `conclusion`; it now
  requests the normalized `bucket` field and guards duration math against
  gh's zero-time timestamps
  ([GH-773](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/773))
- **Ensure background-agent reports reach the orchestrator** — named
  background agents delivered only an idle notification, losing every
  report; dispatch templates now deliver the report via `SendMessage`
  with a documented escalation ladder
  ([GH-776](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/776))
- **Prevent duplicate Verify-AC tasks in the local-only play** — the
  play-level Verify-AC is now conditioned to the no-PR path so exactly
  one terminal gate instantiates on either path
  ([GH-781](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/781))

### Performance

- **Tier Claude CI review models** — the code-review orchestrator now
  runs on sonnet and dispatches one haiku subagent per matched domain
  for the bulk per-rule review, and `anthropics/claude-code-action` is
  pinned to a commit SHA across all four Claude workflows

### Docs

- **Record ADR-0017 for the mode-guard policy location** — `allowed_overlays`
  is a personal-machine trust preference in gitignored `config.yaml`, not
  a git-tracked pin; documents the defense-in-depth split from the
  separate `.dev10x/gate-policy.yaml` project pin
  ([GH-805](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/805))
- **Document rule-documentation standards from consolidation review** —
  guidance on when to expand reviewer checklists, when to document
  exceptions, and checklist formatting
  ([GH-788](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/788))
- **Remove the GH-774 scoping spec merged into develop by mistake** —
  `docs/specs/GH-774.md` shipped in 0.84.0 via a mistakenly-merged draft
  PR; the implementation now supersedes it (forward delete, no history
  rewrite) ([GH-774](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/774))
- **Capture PR #382 lessons-learned implementation notes**

## 0.85.0

Released 2026-07-08

Mechanical version-alignment release — no functional changes since
0.84.0.

## 0.84.0 — DDD Workshop Foundations & Capability-Based Authz Probes

Released 2026-07-07

### Features

- **Ground the DDD workshop in researched domain knowledge** — the
  `Dev10x:ddd` skill shipped with 11 loosely-sourced archetypes and no
  pattern / anti-pattern / standards guidance; it now carries a
  21-signal archetype catalog across four source families,
  design-pattern / anti-pattern / authz / integration guides, a 30+
  standards map with a verified bibliography, and solo-facilitation
  tooling (blind persona panel, devil's advocate, `[ASSUMPTION]`
  guardrail) as the documented default. Shared knowledge moves to
  `references/domain/` for reuse by `project-audit`, the architect
  agents, and `adr-evaluate`
  ([GH-771](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/771))
- **Probe capability-based authz in workshops** — the authz reference
  covered only account-centric models (RBAC/ABAC/ReBAC); a new
  bearer-invitation model adds a Capability row to the grant-sentence
  and decision-guide tables plus a Step 2b with eight probe questions
  (scope, forwardability, attenuation, expiry, redemption identity,
  delegation, revocation, leak blast radius), grounded in W3C
  capability URLs and Macaroons
  ([GH-771](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/771))

### Docs

- **Scope the session.yaml durable/ephemeral split** — design for
  separating durable session state from ephemeral state without
  tripping the clean-tree gates
  ([GH-774](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/774))
- **Prevent implementation-flavored Job Story drafts** — jtbd guidance
  keeps Job Stories situation-driven rather than implementation-flavored
  ([GH-786](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/786))
- **Keep the ddd SKILL.md budget override honest** — corrected the
  documented line count for the ddd skill's budget override
  ([GH-771](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/771))

## 0.83.0 — Data-Driven Friction Gate Policy & Light-AFK Presets

Released 2026-07-04

### Features

- **Tune friction per gate with a data-driven policy** — per-gate
  friction policy backed by a `resolve_gate` resolver tool and
  gate-policy foundations
  ([GH-742](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/742),
  [GH-752](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/752))
- **Run light-AFK with human-gated merges** — a guided AFK preset that
  auto-advances mechanical steps but keeps merge human-only; `afk`
  recomposed as an adaptive+afk preset
  ([GH-748](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/748),
  [GH-759](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/759))
- **Detect bot top-level and review-body comments** — recognize bot
  top-level and review-body comments, and warn on contradictory
  oversight modes at the adaptive level
  ([GH-743](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/743),
  [GH-744](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/744))
- **Guard against premature completion while a PR is unmerged**
  ([GH-729](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/729))
- **Enforce the empty-task-list invariant**
  ([GH-681](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/681))
- **Override merge for blocked PRs with admin/auto**
  ([GH-733](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/733))
- **Offer ripgrep/Grep when `find -exec` search is blocked**
  ([GH-726](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/726))
- **Show the work-on plan structure as a box-drawing tree**
  ([GH-730](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/730))
- **Enable the request-review stand-by widget at guided**
  ([GH-758](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/758))

### Fixes

- **Fix top-level bot-comment detection (identity vs signal)**
  ([GH-764](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/764))
- **Honor deferred review threads at the completion gate**
  ([GH-736](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/736))
- **Resolve stale permission `--init` references**
  ([GH-741](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/741))

### Performance

- **Speed up single-PR unresolved-thread checks** — a single per-PR
  `reviewThreads` GraphQL query replaces the merged-PR sweep
  ([GH-710](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/710))

### Refactors

- **Route gates through the friction resolver** — work-on,
  gh-pr-respond, and merge/commit/monitor gates now resolve through
  the shared friction resolver; batch-gate auto-advance keys on comment
  author and respond short-circuits on an already-merged PR
  ([GH-755](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/755),
  [GH-756](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/756),
  [GH-757](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/757),
  [GH-745](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/745),
  [GH-744](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/744))
- **Simplify duplicated bulk, restore, and regex helpers**
  ([GH-583](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/583))

### Docs

- **Converge friction docs on the resolver, deprecate `walk_away`**
  ([GH-760](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/760))
- **Unblock config-loader consolidation via a read-I/O ADR**
  ([GH-536](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/536))
- **Document script-domain-boundaries enhancements** — reviewer
  checklist and config-loader exception guidance from PR #382 lessons
  ([GH-246](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/246))

### Tests

- **Prevent tests from rewinding the real repo HEAD**
  ([GH-699](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/699))

## 0.82.0 — Unattended JIRA Tickets, Worktree Session Seeding & Prefix-Friction Fixes

Released 2026-06-26

### Features

- **Create JIRA tickets unattended** — `Dev10x:ticket-create`'s JIRA
  path dispatched a background agent that stalled on the Atlassian MCP
  write-tool permission prompt; a new `mcp-atlassian-write` tier-2
  baseline group pre-approves the six non-destructive JIRA write verbs
  (create / edit / comment / link / transition / worklog, no deletes),
  routes the JIRA branch through `createJiraIssue`, and pins the
  GH-593 write-precedence override as a deliberate, audited exception
  ([GH-631](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/631))
- **Carry session config across worktrees without dirtying the tree** —
  `session.yaml` is work-on session state, but git-tracking it tripped
  the clean-tree gates in `verify_pr_state`, `Dev10x:gh-pr-merge`
  Check 5, and `create_pr`, while gitignoring it broke continuity in
  new worktrees; `dev10x session seed` now does an idempotent O_EXCL
  write of a default, post-checkout templates copy or seed it, and a
  new `Dev10x:session-config-seed` skill wraps the CLI for agent-time
  delegation ([GH-705](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/705))

### Fixes

- **Stop recommending unreliable `**` path wildcards** — the permission
  tooling rewrote version-pinned plugin paths into `**` wildcards, but
  `**` matching proved unreliable in the permission engine; the two
  canonicalize deprecations are dropped, `canonicalize_rule` is
  narrowed to the GH-704 `//` collapse, and regression tests assert no
  `**` is ever emitted
  ([GH-715](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/715))
- **Prevent `git -c` prefix friction** — a `git -c <key>=<value>`
  prefix shifts the matched command string so `Bash(git <verb>:*)`
  never fires; DX007 now blocks the prefix, routes `core.pager` /
  `color.ui` to `git nopager` / `git nocolor` aliases, treats
  `core.hooksPath` as a safety block, and routes the
  `core.editor` / `sequence.editor` rebase form to a plain
  `git rebase --continue`
  ([GH-717](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/717),
  [GH-720](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/720))
- **Prevent `uv run`/`uvx pre-commit` prefix friction** — the wrapper
  shifts the matched command string so `Bash(pre-commit run:*)` never
  fires; DX007 now blocks it and routes to the bare `pre-commit` form
  ([GH-717](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/717))

### Tests

- **Cover the PR lifecycle skills and MCP tools** — eval coverage for
  `gh-pr-review`, `gh-pr-merge`, and `gh-pr-triage`, plus unit tests
  for `merge_pr` safety gates, `resolve_review_thread`, and
  `unresolved_threads`
  ([GH-547](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/547))
- **Cover fanout dispatch and worktree wrappers** — `create_worktree`
  error paths, `next_worktree_name` collisions, batch-detection edges,
  and subagent status-protocol parsing
  ([GH-553](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/553))
- **Cover audit/plan MCP error paths** — the `err()`/`{"error": ...}`
  wire contract for the audit tools and `plan_sync` key-conflict,
  archive-race, and CWD-binding paths
  ([GH-556](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/556))
- **Cover the work-on pipeline skills** — evals for `ticket-branch`,
  `session-wrap-up`, and `session-tasks` guarding branch naming, the
  never-empty task-list invariant, and wrap-up routing
  ([GH-560](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/560))
- **Cover the MCP daemon lifecycle** — restart, STDIO fallback,
  deleted-CWD recovery, StreamableHTTP concurrent sessions, and
  session-TTL expiry
  ([GH-563](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/563))

### Docs

- **Prevent stale-base conflicts in bundle and fanout** — work-on
  Strategy B gains a per-batch fetch + rebase-onto-`origin/<base>`
  pre-step and fanout branches each item from a fresh base, both gated
  off once review fixups or unresolved threads exist
  ([GH-626](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/626))
- **Guide full restructure to atomic layer commits** — Strategy B now
  documents commit granularity and cohesion (small atomic layer
  commits, ordered bottom-up), disambiguates "full restructure" from
  squash-to-one, and gates strategy selection by fixup presence
  ([GH-723](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/723))

## 0.81.1 — GitHub MCP Tool Responses & Review-Setup Gate Fixes

Released 2026-06-25

### Fixes

- **Restore GitHub MCP tool success responses** — every github MCP tool
  (`issue_get`, `pr_comments`, `pr_comment_reply`, `detect_base_branch`,
  `verify_pr_state`, …) failed Pydantic output-schema validation in
  0.80.0 despite the underlying GitHub call succeeding; the
  `@github_tool` decorator now pins the wrapper's return type to `dict`
  so FastMCP derives no output schema and accepts the flattened wire
  dict ([GH-712](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/712))
- **Keep gh-review-setup's module gate within the option cap** — the six
  review modules are split across two `AskUserQuestion` questions in one
  call, since each question caps at four options, so the setup gate no
  longer fails with `InputValidationError`
  ([GH-713](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/713))

## 0.80.0 — Continuous Learning Loop, Installable PR-Review Action & Source-Derived Permissions

Released 2026-06-25

### Features

- **Close the review-to-rule learning loop** — recurring PR review
  comments are mined into candidate patterns, scored for confidence and
  false-positive risk, authored into reference rules, and surfaced for
  review, so the system learns from past reviews instead of repeating
  them ([GH-346](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/346),
  [GH-347](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/347),
  [GH-348](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/348),
  [GH-349](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/349),
  [GH-350](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/350),
  [GH-353](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/353))
- **Install Dev10x PR review as a GitHub Action on any repo** — a guided
  setup wires up the reviewer Action, including learned-rule review, on
  repositories beyond this one
  ([GH-351](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/351),
  [GH-352](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/352),
  [GH-707](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/707))
- **Derive permissions from a source two-axis manifest** — a
  source-derived manifest plus proactive seeding grants default-safe
  reads for surfaces like Sentry, JIRA, and Vercel, unifies sensitivity
  classification across surfaces, and seeds rule provenance fleet-wide
  for worktrees, so safe reads stop re-prompting per project
  ([GH-600](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/600),
  [GH-601](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/601),
  [GH-602](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/602),
  [GH-603](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/603),
  [GH-606](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/606),
  [GH-607](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/607))
- **Approve sensitive read probes in-session** — credentialed reads and
  sensitive probes can be approved without dropping to a manual shell,
  and read-only MCP tools can be promoted to global settings
  ([GH-604](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/604),
  [GH-480](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/480))
- **Run node/yarn dev loops off the Bash layer** — `run_node_tests`
  brings jest/vitest/yarn/npm/pnpm test runs through the MCP boundary,
  sidestepping the brace-expansion block no allow-rule could suppress
  ([GH-703](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/703))
- **Run PR-state merge checks without the raw CLI** and **distinguish
  required from advisory CI verdicts**, so merge gating reflects which
  checks actually block
  ([GH-668](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/668),
  [GH-658](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/658))
- **Enable server-initiated LLM sampling** via a `request_sampling` MCP
  tool ([GH-343](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/343))
- **Trust the plan while attending later gates** — background subagents
  stay off hook-tripping command shapes and the supervisor can defer
  attention to later decision gates
  ([GH-678](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/678),
  [GH-610](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/610))
- **Register platforms during onboarding** and resolve skill-script
  paths canonically, with diag-friction routing for four more raw
  command shapes
  ([GH-528](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/528),
  [GH-611](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/611),
  [GH-609](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/609))
- **Establish pre-commit as the canonical lint entry point** — ruff,
  shellcheck, and mypy run through `.pre-commit-config.yaml` as the
  single lint gate
  ([GH-619](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/619))

### Security

- **Close the DX003 interpreter-stdin execution bypass** — piping a
  script into an interpreter's stdin no longer evades the execution
  safety validator
  ([GH-687](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/687))

### Performance

- **Collect release PRs in one batch query** instead of per-PR fetches,
  and reduce git subprocess forks at session stop
  ([GH-550](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/550),
  [GH-552](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/552))

### Fixes

- **Resolve git-fixup misfire on a stale local develop** — the
  fixup-target resolver cross-checks `origin/develop` instead of a stale
  local ref ([GH-676](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/676))
- **Enable closing issues as not planned**
  ([GH-674](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/674))
- **Match plugin skill-script grants across roots and `//`**
  ([GH-704](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/704))
- **Surface hook-denial findings to MCP audit callers** and in default
  installs, so friction-riddled sessions no longer report zero unmatched
  calls ([GH-507](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/507),
  [GH-574](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/574))
- **Fail closed when safety validators raise**, rather than letting an
  exception open the gate
  ([GH-494](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/494))
- **Prevent the daemon from killing the wrong process** and keep the
  roots cache fresh by retaining the refresh task
  ([GH-573](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/573),
  [GH-498](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/498))

### Hardening

- **Close write races across session, settings, and lock state** —
  bounded waits on contended file locks, torn-write protection for the
  applied-version stamp, lost-update protection for `SessionStore.update`
  and settings mutators, and non-interleaving concurrent skill-metric
  lines ([GH-555](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/555),
  [GH-558](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/558),
  [GH-562](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/562),
  [GH-571](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/571))
- **Ensure Slack send failures reach callers** and keep the MCP server
  from crashing on missing config
  ([GH-537](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/537),
  [GH-532](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/532))

### Refactors

- **Enforce the Result contract at the MCP boundary** (ADR-0009) and
  adopt Catalog, Query Object, AbstractHook, and Value Object archetypes
  across the permission, session, github, and validator packages, sealing
  package boundaries and typing the domain models throughout
  ([GH-509](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/509),
  [GH-654](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/654),
  [GH-584](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/584))
- **Consolidate permission config on `projects.yaml`** and centralize
  protected-branch handling, validator dispatch, and session-state
  capture ([GH-577](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/577),
  [GH-583](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/583),
  [GH-635](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/635))

### Tests

- **Enforce default-stage mypy and shellcheck warnings** and strengthen
  the permission-classifier fixture corpus via evidence triage, closing
  CI-hang and reproducibility gaps
  ([GH-619](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/619),
  [GH-271](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/271),
  [GH-614](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/614))

### Docs

- **Document any-repo install and the learning loop**, the accepted App
  JWT argv exposure, and permission-rule generalization patterns
  ([GH-354](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/354),
  [GH-499](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/499),
  [GH-592](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/592))

## 0.79.0 — Permission Friction Reduction, Structured Policy Model & Cross-Fork PRs

Released 2026-06-08

### Features

- **Model permission rules as structured policies** — the flat
  allow-rule string list becomes typed `Policy` value objects carrying
  tier, source, and effect, laying the foundation for the deny catalog,
  user/project source precedence, and worktree forward-sync that the
  GH-271 friction evidence converged on
  ([GH-271](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/271))
- **Close six permission-friction and tooling gaps in one bundle** —
  DX014 matches production hosts by context rather than a bare `prod-`
  prefix (GH-482), `uvx`-launched `skill notify slack-send` declares
  slack-sdk so it actually runs (GH-483, thanks
  [@szx19970521](https://github.com/szx19970521) for surfacing it in
  [#487](https://github.com/Dev10x-Guru/Dev10x-Claude/pull/487)),
  `issue_comment` gains a
  `body_file` arg (GH-484), DX007 normalizes `uv run` env-flags before
  prefix-matching (GH-485), git-groom resolves its base against
  `origin/<base>` instead of a stale local ref (GH-486), and
  project-audit persists its Phase 4 findings memo (GH-481)
  ([GH-481](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/481))
- **See which read-only MCP tools and research domains can go global** —
  `dev10x permission promote-plan` produces a deduped, read-only dry-run
  plan of the claude.ai-hosted tools and WebFetch domains that re-prompt
  per project, so they can move to global settings instead of being
  re-approved in every repo (write tools and plugin-distributed tools
  are never promoted)
  ([GH-470](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/470))
- **Open cross-fork PRs through `create_pr`** — `create_pr` /
  `Dev10x:gh-pr-create` accept an optional head repo, push the branch to
  the fork owner's remote, and emit `--head <owner>:<branch>`, so
  contributing to an external repo from a fork keeps the wrapper's Job
  Story, commit list, summary comment, and notify flow
  ([GH-473](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/473))

### Security

- **Refuse to auto-approve `uv run --with` installs** — `--with <pkg>`
  now disqualifies `uv run` auto-approval, closing a supply-chain hole
  where an allowed inner command silently installed an arbitrary package
  and bypassed the fence-tool ask
  ([GH-485](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/485))

### Fixes

- **Surface hook denials in skill-audit friction reports** — Phase 4 now
  scans the tool-result blocks it previously dropped for
  `permissionDecision: deny` and `BLOCKED:` validator signals, so
  sessions riddled with hook friction no longer report "0 unmatched
  calls"
  ([GH-474](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/474))
- **Allow containerized and 1Password-wrapped psql through the DB gate**
  — the DX004 read-only SQL gate exempts `docker exec … psql` (runs in a
  test container) and `op run -- psql` (the sanctioned secrets wrapper)
  while still blocking bare host psql
  ([GH-474](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/474))
- **Reclaim merged agent worktrees holding replicated dirt** — fanout
  teardown force-removes merged-but-dirty worktrees when their only
  changes are stale or a repo-wide `.claude/` rewrite replicated
  identically across siblings, so leftovers stop piling up
  ([GH-476](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/476))
- **Stop bash/sh/zsh exec from bypassing DX003** — the execution-safety
  guard now covers shell interpreters alongside python3, steering
  `bash /tmp/x.sh` and `sh -c …` to the Write-tool/uv-script path
  instead of relying on an unreliable deny-rule
  ([GH-469](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/469))
- **Run plugin scripts without re-prompting** — plugin-maintenance emits
  concrete version-pinned script rules instead of `**` globs that Claude
  Code's Bash matcher never matches, and purges the dead globs that were
  masking script coverage
  ([GH-471](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/471))

### Docs

- **Document worktree CWD and push discipline** — the git-worktree skill
  now warns that `cd` does not persist between Bash calls and that raw
  `git push` is hook-blocked, steering callers to absolute paths and
  `Skill(Dev10x:git)`
  ([GH-474](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/474))
- **Document the lessons-learned implementation plan** — capture the
  GH-460 plan for harvesting merged PRs and review threads into the
  learning loop
  ([GH-460](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/460))

## 0.78.0 — MCP Client Integration, Swarm Teardown & CI Quality Gates

Released 2026-06-03

### Features

- **Read Dev10x knowledge as addressable MCP resources** — playbooks,
  rules, references docs, and the skill index are exposed under
  `dev10x://` URIs, so MCP clients read them directly instead of
  falling back to Bash tool-calls or filesystem searches
  ([GH-339](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/339))
- **Invoke review, commit, and jtbd templates as MCP prompts** — the
  workflow templates are registered as first-class MCP prompts with
  argument autocomplete, so clients run Dev10x's conventions without
  re-deriving them by hand each time
  ([GH-340](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/340))
- **Keep client resource caches fresh** — a knowledge-resource watcher
  polls the files backing the registered MCP resources and emits
  `list_changed`/`updated` notifications when they change on disk, so
  connected clients refresh instead of serving stale content
  ([GH-341](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/341))
- **See progress on long-running MCP tools** — `run_tests`,
  `mass_rewrite`, `rebase_groom`, and `create_pr` stream progress and
  log notifications when the client supplies a progress token, so long
  operations no longer look like a silent stall
  ([GH-342](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/342))
- **Scope MCP operations to client-declared directory roots** — the
  server fetches and caches the client's `roots/list`, refreshes on
  `roots/list_changed`, and exposes a `list_client_roots` tool so
  skills can validate CWD against what the client considers in-scope,
  with a `DEV10X_ROOTS_ENABLED=0` escape hatch
  ([GH-344](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/344))
- **Tear down swarm worktrees after merge** — fanout now runs a
  teardown decision tree per merged child PR (remove clean worktrees,
  force-remove stale duplicates of develop HEAD, keep and surface
  genuinely unique content), prunes leftovers, and delegates abandoned
  branch cleanup to the new branch-prune skill
  ([GH-463](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/463))
- **Prune stale local branches in rebase-merge repos** — the new
  `Dev10x:git-branch-prune` skill classifies branches into four
  categories (gone-upstream, merged-ancestor, content-landed-via-
  rebase, ahead/undecidable) behind a REQUIRED deletion gate, so
  branch hygiene works in repos where `git branch --merged` misses
  most merged branches
  ([GH-464](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/464))
- **Block performance regressions in CI** — the benchmark suite runs
  on every PR against a cached per-branch baseline and fails on a mean
  regression greater than 20%, so hook-latency and startup regressions
  can no longer ship undetected
  ([GH-432](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/432))
- **Enforce hook-test coverage in CI** — the hooks workflow measures
  coverage against a 70% threshold and the project-wide floor rose
  from a stale 38% to 75%, so coverage discipline is machine-enforced
  rather than agent-dependent
  ([GH-433](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/433))
- **Warn before editing code whose spec is stale** — the experimental
  `DX015` spec-drift validator fires on Edit/Write when the branch's
  ticket maps to an active spec not yet touched in the working set,
  moving the Golden Rule from "skill-if-invoked" to "hook-always"
  (opt-in via `DEV10X_HOOK_EXPERIMENTAL=1`)
  ([GH-434](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/434))
- **Audit skill usage inline by default** — skill-audit's new
  lightweight strategy works from visible conversation context with a
  single disposition gate; the forensic transcript-extraction fan-out
  moves behind `--full` or auto-escalation, so most sessions capture
  findings without a separate terminal
  ([GH-436](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/436))
- **Harvest merged PRs and review threads for the learning loop** —
  fail-soft fetchers turn closed PRs and their inline review threads
  into structured data, feeding downstream clustering and
  candidate-rule scoring without re-scraping GitHub
  ([GH-345](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/345))
- **Find all Dev10x config under XDG paths** — `databases.yaml` is
  discovered at `~/.config/Dev10x/`
  ([GH-448](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/448)),
  global playbook overrides resolve from
  `~/.config/Dev10x/playbooks/`
  ([GH-445](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/445)),
  and upgrade-cleanup migrates both automatically — including configs
  stranded in hidden backup directories
  ([GH-446](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/446),
  [GH-447](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/447))
- **Detect stale running hooks at SessionStart** — the session
  compares the running-hook version against the latest installed
  plugin and nudges for a restart when a mid-session
  `claude plugin update` left shipped friction fixes dormant
  ([GH-407](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/407))

### Fixes

- **Resume dead swarm agents instead of re-dispatching** — fanout now
  prefers SendMessage resume when an agent's turn dies, swarm children
  verify their worktree before any branch checkout, gh-pr-merge runs
  comment checks strictly after CI is green (closing the bot-post
  race), the drift gate no longer offers switching to a deleted
  branch, and canonical MCP parameter shapes are documented to prevent
  first-call validation errors
  ([GH-462](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/462))
- **Survive hostile worktree topologies in fanout** — child worktrees
  stay writable and base-safe (branch-upstream guard prevents bare
  pushes from advancing the base PR), and orchestrators dispatching
  from a sibling worktree detect the cross-repo-root condition and
  fall back to serial mode
  ([GH-424](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/424),
  [GH-427](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/427))
- **Stop full-mode cleanup from reintroducing friction** —
  plugin-maintenance's global-dedup and doctor canonicalize are now
  opt-in (`--aggressive`), preserving the project-local rules and
  literal `~/` paths the permission engine actually needs
  ([GH-420](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/420))
- **Send Slack notifications from any install context** —
  `uvx dev10x skill notify slack-send` calls an importable module
  instead of resolving filesystem paths into `skills/`, so it works
  when installed as a wheel
  ([GH-442](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/442))
- **Recover the MCP server from a deleted process CWD** — when the
  worktree the server was spawned in is removed after a merge, the
  server chdirs to the plugin root instead of failing every
  subsequent subprocess call with ENOENT
  ([GH-418](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/418))

### Refactors

- **Encode friction-level behaviour on the enum itself** —
  `pending_decisions_guidance()` and `fallback_guidance()` replace
  if/elif dispatch chains in the decision-guidance rule and
  skill-redirect message formatting
  ([GH-249](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/249))

### Docs

- **Unified backpressure architecture reference** — a single doc maps
  the two-direction model (action gating + output gates) across every
  hook, validator, and completion-gate surface
  ([GH-435](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/435))
- Rule-index updates for `DX014`/`DX015` and the perf CI gate;
  corrected the investigate skill's Common Mistakes routing table
  ([GH-444](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/444))

## 0.77.0 — Persistent MCP Daemon, Sensitivity-Axis Gating & Live GitHub Contract Tests

Released 2026-06-01

### Features

- **Run the MCP servers as a persistent daemon over HTTP** — a managed
  background daemon adds health checks, graceful shutdown, and
  restart-safe lock handling, per-client session state is maintained
  across StreamableHTTP requests, and a new session-aware client wires
  Claude Code to the running daemon when it is healthy while falling
  back to a fresh per-session STDIO server when it is not, so sessions
  pay lower startup overhead with no manual configuration
  ([GH-336](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/336),
  [GH-337](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/337),
  [GH-338](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/338))
- **Keep MCP tools working after a bound worktree is deleted** — cli
  tool calls now fall back gracefully instead of failing with ENOENT
  when a worktree is removed after a branch merge, so `mktmp` and the
  other MCP tools keep working in post-merge sessions instead of
  hitting "Current directory does not exist"
  ([GH-410](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/410))
- **Gate commands that touch sensitive targets** — a new orthogonal
  sensitivity axis classifies actions against secrets, credentials,
  PII, and production infrastructure, and the `DX014` validator blocks
  and asks for review before executing even trivially-reversible reads
  that the tier and reversibility axes alone would let through
  ([GH-406](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/406),
  [GH-395](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/395))
- **Catch GitHub GraphQL/REST field drift before it reaches sessions** —
  a live contract-test tier exercises the GitHub-backed MCP read tools
  (`pr_get`, `pr_comments`) against the real REST/GraphQL surface and a
  known fixture PR, and queries are validated against the published
  GraphQL schema, so invalid fields and response-shape drift are caught
  in CI instead of forcing a downstream session to fall back to raw `gh`
  ([GH-398](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/398),
  [GH-386](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/386))
- **Smoke-test a release candidate before tagging** — the release flow
  now builds and installs the wheel locally, prints the real remote
  side effects before the irreversible tag, and requires a live
  `--plugin-dir` run for changes that touch the MCP server or
  permission hooks, so a broken server/hook surface can no longer reach
  PyPI or move the marketplace ref by accident
  ([GH-387](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/387))
- **Sharpen the permission doctor across worktrees** — the doctor now
  surfaces horizontal duplicates when multiple MCP servers expose the
  same capability under different prefixes, and anchors each project's
  `.worktrees` parent across every CWD-keyed permission scope, so
  cross-worktree work no longer drifts out of coverage
  ([GH-371](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/371),
  [GH-376](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/376))
- **Self-review a green PR before pinging a teammate** —
  `Dev10x:gh-pr-request-review` lets a supervisor eyeball the PR
  themselves and defer the review request cleanly, with the DoD runner
  picking up the gh-pr checks and a standby Write permission so the
  flow runs without friction
  ([GH-396](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/396))
- **Run fanout swarms straight through to merged PRs** — each
  `Dev10x:work-on` child in a worktree-isolated swarm no longer stalls
  after branch or PR creation, so the orchestrator carries every item
  to completion without manual nudging
  ([GH-368](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/368))
- **Read plugin-maintenance preferences from the XDG config path** —
  `Dev10x:plugin-maintenance` now reads and writes
  `plugin-maintenance-prefs.yaml` under `~/.config/Dev10x/`, completing
  the XDG config-layout migration
  ([GH-390](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/390))
- **Name milestones without collisions across initiatives** —
  milestone naming gains initiative-prefixed conventions so parallel
  initiatives can create milestones without clashing
  ([GH-388](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/388))

### Fixes

- **Stop `permission clean` from silently removing covered rules** —
  cleanup no longer drops project-local rules that may not be covered
  by global rules, ending phantom permission prompts after a clean
  ([GH-391](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/391))
- **Restore `mass-rewrite.py` to its un-mangled form** — a bulk-rewrite
  workaround had corrupted the file's glyphs, docstring, and print
  strings; it is restored to its last-good commit so git-groom
  mass-rewrite works correctly
  ([GH-415](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/415))

## 0.76.0 — Friction-Free CLI, Typed MCP Boundaries & Smarter PR Review

Released 2026-05-31

### Features

- **Pre-approve the safe inspection surface so unattended runs stop
  stalling** — narrow allow-rules for read-only tools, `--version`
  flags, and read-only git/gh/uv subcommands let adaptive and AFK
  sessions run without tripping the permission gate or the "don't ask
  again" catch-all footgun
  ([GH-310](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/310))
- **Run structured-data tools without a prompt** — 15 read-only
  processors and validators (`jq`, `yamllint`, `actionlint`, `shellcheck`,
  binary-existence lookups, and more) join the base permission catalog,
  so the canonical structural alternatives `Dev10x:diag-friction` steers
  toward no longer prompt themselves
  ([GH-308](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/308))
- **Pre-approve docs, extracted probes, Railway, and safe git flags** —
  four permission-catalog follow-ups land together: ~30 canonical HTTPS
  doc domains for WebFetch, execution of extracted `/tmp/Dev10x` and
  `~/.claude/tools` probes, a Railway read-only tier-3 group, and a
  `flag_overrides` schema that ships `git clean -n`, `git branch -d`,
  and `git reset --dry-run`
  ([GH-369](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/369),
  [GH-370](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/370),
  [GH-372](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/372),
  [GH-373](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/373))
- **Stop quoted shell metacharacters from triggering false blocks** — a
  quote-aware tokenizer strips single-quoted spans, ANSI-C strings, and
  escaped pairs before threat detection, and the new `DX012`
  safe-expansion validator approves commands whose metacharacters resolve
  to known-safe env vars, so `gh api graphql -f query='{...}'` and
  `echo "$CLAUDE_PLUGIN_ROOT"` pass cleanly
  ([GH-309](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/309))
- **Block MCP tool names pasted as shell commands** — the new `DX013`
  validator hard-blocks a command whose first token matches
  `mcp__<server>__<tool>` and steers back to the tool-call protocol,
  closing a recurring failure mode that memory and docs alone could not
  prevent
  ([GH-375](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/375))
- **Steer in-place stream editors to the Write/Edit tool** — flag-aware
  detection routes `sed -i`, `perl -i`, `gawk -i inplace`, and
  `dd of=<file>` to the editing tools while leaving read-only `sed -n`
  and `awk` forms untouched
  ([GH-374](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/374))
- **Request JIRA and Slack reviews without env-prefix friction** — the
  `dev10x:jira` base skill becomes the plugin-bundled `Dev10x:jira` with
  a documented tenant-wrapper pattern, and `Dev10x:slack-review-request`
  gains a real `dev10x skill notify` CLI surface, so neither tenant
  wrappers nor Slack steps fall back to version-pinned script paths
  ([GH-233](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/233),
  [GH-313](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/313))
- **Edit PR inline review-thread comments via MCP** — the new
  `pr_review_comment_edit` wrapper covers the `pulls/comments` endpoint
  that `issue_comment_edit` could not reach, so clearing a stale bot
  finding to unblock the merge gate no longer needs raw `gh api PATCH`
  ([GH-304](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/304))
- **Push small fixes directly during PR review** — `Dev10x:gh-pr-review`
  adds a courtesy-fixup path that classifies mechanical findings
  (unused imports, trivial renames, dead code) and offers a batch scope
  gate before pushing, ending the comment-then-author round-trip
  ([GH-323](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/323))
- **Leave a PR review as a GitHub draft** — a draft-vs-submit gate in
  `Dev10x:gh-pr-review` lets reviewers finalize on the Files-changed tab
  before the review becomes visible, with intent-detection defaults and
  author-aware biasing
  ([GH-319](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/319))
- **Use comment reactions as a triage signal** — `Dev10x:gh-pr-triage`
  reads a comment's reactions as a verdict lean when no directing prose
  exists, and `Dev10x:gh-pr-respond` surfaces a `Signal` column so
  reaction-only verdicts stay auditable before the batch approval gate
  ([GH-314](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/314))
- **Catch a stale CLI before running maintenance** — `Dev10x:plugin-maintenance`
  now reads the marketplace manifest and installed versions in a
  preflight step, prompts to update when either surface is behind, and
  can persist the choice so future sessions skip the prompt
  ([GH-307](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/307))
- **Surface parked work from the canonical session store** —
  `Dev10x:park-discover` now reads `session.yaml` as its primary
  substrate, every park writer indexes into that store, and its
  documented commands route through Read/Grep/MCP wrappers instead of
  friction-triggering `cat`/`grep -rn`/subshell forms
  ([GH-85](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/85))
- **Run the MCP servers over HTTP without code changes** — a
  `DEV10X_MCP_TRANSPORT` env var selects the transport, making the
  daemon/HTTP path opt-in while STDIO stays the default
  ([GH-335](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/335))
- **Normalize PyCharm/uv worktrees after checkout** — the new
  `Dev10x:ide-normalize` skill fixes `.idea/` module names, disables the
  `ADD_CONTENT_ROOTS` setting that breaks editable installs, backfills the
  Django settings module, and patches the uv-SDK FLAVOR_DATA gap that
  crashed PyCharm on fresh worktrees
  ([GH-320](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/320))

### Hardening

- **Block privilege-escalation commands by default** — `sudo`, `doas`,
  `pkexec`, and `sudoedit` deny rules ship in the base catalog for any
  command shape, with a narrow `sudo-apt` opt-in group for routine
  package management, closing the root-level bypass an agent reached for
  in the wild
  ([GH-326](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/326))

### Fixes

- **Restore the `pr_get` and `resolve_review_thread` MCP tools** — both
  wrappers failed and forced raw `gh` fallbacks; `pr_get` no longer
  requests the invalid `merged` field (deriving merged-ness from state),
  `resolve_review_thread` queries the correct `reviewThreads` shape, and
  `request-review` routes detection through the stable `pr_detect` wrapper
  ([GH-329](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/329))
- **Convert a PR review to draft only when inline comments exist** — the
  CI review step queries the real `reviewComments` count instead of
  trusting the model's recollection, ending spurious draft conversions
  that blocked merge with zero findings
  ([GH-333](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/333))
- **Stop the permission generalizer from emitting invalid rules** — two
  classes of bug produced mid-string `:*` forms that Claude Code rejects
  after running maintenance on 0.75.0; the generalizer pattern and two
  redundant `grep` rules are fixed, with a regression test for the
  quoted-JSON-blob arg case
  ([GH-315](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/315))
- **Unblock the pre-PR gate on every branch** — the doctor passes
  `str(cwd)` to `subprocess_utils.run`, resolving a mypy type mismatch
  that the GH-245 cwd-discipline merge introduced on develop
  ([GH-245](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/245))

### Refactors

- **Enforce a uniform `Result[T]` contract at the MCP boundary** — the
  polymorphic `to_dict` branch is dropped, `record_upgrade` and `_gh_api`
  return `Result[dict]`, and the 1834-line `server_cli.py` splits into
  github/git/plan/audit/misc tool modules; ADR-0009 records the decision
  ([GH-243](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/243))
- **Seal context boundaries with domain protocols** — Milestone 5 of the
  architecture audit adds ADR-0007/0008, moves session policy rules and
  the audit writer behind protocols, extracts `SettingsDocument` for
  settings I/O, and re-homes the audit-skills permission analysis so the
  context boundary points the right way
  ([GH-244](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/244))
- **Make subprocess calls honor the caller's worktree** — a sync
  `subprocess_utils.run` chokepoint defaults `cwd` to the bound effective
  CWD, direct `subprocess.run`/`os.getcwd()`/module-scope `GitContext()`
  usages are routed through it, and a lint test forbids regressions
  ([GH-245](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/245))
- **Resolve contradictory allow-rule diagnostics** — a single canonical
  `AllowRule` value object with space-boundary-aware matching replaces
  four drifted matchers and several duplicated settings loaders, so a
  rule can no longer be reported matched by one diagnostic and unmatched
  by another
  ([GH-242](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/242))
- **Extract skill logic into importable, unit-tested modules** — the
  release classifier, JTBD extraction, Slack formatting, permission
  config loading, skill-index builder, and subagent-status/batch-detection
  protocols move into `dev10x.skills.*` modules with full coverage, the
  dead PR-status batch query API is retired, and the audit-skills boundary
  is sealed
  ([GH-246](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/246),
  [GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/248),
  [GH-244](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/244))
- **Replace dispatch chains with declarative patterns** — Milestone 10
  of the architecture audit applies map-based dispatch and the
  template-method pattern across hooks, validators, and the task state
  machine, retiring if/elif chains and per-call should_run/validate
  sequencing (11 of 36 findings; the rest deferred)
  ([GH-249](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/249))
- **Drop env-prefix friction from plugin-maintenance, JIRA, and
  aws-vault** — maintenance steps route uniformly through
  `uvx dev10x permission`, and the JIRA and aws-vault scripts accept a
  leading `--tenant`/`--registry` flag so callers never need the
  allow-rule-defeating `VAR=value script.sh` prefix
  ([GH-306](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/306),
  [GH-311](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/311))

### Tests

- **Cover the recently shipped MCP and CLI shipping paths** — handler
  tests land for PR/issue comment, review-request, and thread-resolution
  tools, plus playbook CLI and config-schema validation, closing the M8
  audit's zero-coverage gaps
  ([GH-247](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/247))
- **Stop plan_sync tests from polluting the repo root** — the two
  offending tests return a real `tmp_path`, and a session-scoped autouse
  guard removes and fails on stray `<MagicMock …>` files
  ([GH-332](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/332))

### Docs

- **Ratify the importable-module policy and script-vs-domain rules** —
  ADR-0010 records that skill logic lives in importable modules with
  thin uv-script shims, a new boundaries rule sets the print-vs-logging
  and `sys.exit`-vs-`Result` conventions, and `ci_check_status` emits its
  error JSON on stdout so stdout-parsing consumers never see empty output
  ([GH-246](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/246))
- **Record the `dev10x` CLI invocation benchmark and decision** —
  ADR-0012 captures the startup comparison of `dev10x`, `uvx dev10x`, and
  the in-process call, leading with `dev10x …` as the preferred form and
  keeping `uvx dev10x …` as the zero-install fallback
- **Document validator, permission, and orchestration test patterns** —
  new reference docs capture safe-flag overrides, multi-flag validator
  detection, validator test structure, permission tier-assignment logic,
  and regression/schema testing for orchestration paths, distilled from
  lessons-learned analysis
  ([GH-271](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/271))

## 0.75.0 — Friction Reduction, Typed Boundaries & Business-ROI JTBD

Released 2026-05-27

### Features

- **Anchor JTBD Job Stories in business ROI** — the `Dev10x:jtbd`
  skill now traces refactor, infrastructure, and dependency-bump
  work up to the end-customer outcome instead of accepting "the
  developer wants to" as the actor, so every PR body, ticket scope,
  and release note inherits business-meaningful framing. A new
  doctrine memo grounds the rule with worked examples and citations
  ([GH-276](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/276))
- **Eliminate per-version permission churn via the `uvx dev10x`
  CLI** — plugin-maintenance work routes through the version-stable
  CLI so a single set of allow-rules survives every plugin upgrade,
  retiring four cache-path shim scripts that went stale on each
  version bump
  ([GH-269](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/269))
- **Allow trimmer pipelines without broadening allow-rules** — the
  new `PipelineAllowValidator` (DX011) auto-approves `| tail`,
  `| head`, and `| wc` pipelines when every segment already matches
  an existing Bash allow-rule, removing a recurring source of one-off
  approval prompts
  ([GH-262](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/262))
- **Edit and delete PR/issue comments via MCP** — `issue_comment_edit`
  and `issue_comment_delete` wrappers replace raw `gh api PATCH/DELETE`
  calls, so the "edit a stale bot finding to clear the merge gate"
  workflow no longer triggers an approval prompt
  ([GH-283](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/283))
- **Recommend structured tools in `diag-friction`** — blocked
  inline-code commands now map to canonical tools (yq, jq, yamllint,
  actionlint, curl) from a bundled knowledge base instead of always
  suggesting a `~/.claude/tools/` extraction
  ([GH-282](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/282))
- **Land fixups on the commits that own their lines** — `Dev10x:git-fixup`
  blames each staged hunk against the branch range to target the owning
  commit, ending the autosquash conflict loops that rerere memoized
  ([GH-299](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/299))
- **Enable scope-aware triage and priority-split responses** — a YAGNI
  verdict in `gh-pr-triage` plus a now/fast-follow priority axis in
  `gh-pr-respond` let reviewers route out-of-scope findings and defer
  non-urgent VALIDs without manual steering
  ([GH-297](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/297))
- **Prevent silent feature activation via reused relations** — PR
  review gains a cross-consumer behavioural-reuse check that flags when
  populating an existing relation could activate a feature gated on row
  presence in a sibling repo
  ([GH-290](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/290))
- **Prevent context-anxiety pauses in adaptive solo sessions** — a
  SessionStart reassurance block fires under adaptive friction with a
  solo maintainer so the agent trusts long task lists instead of
  re-asking settled scope decisions
  ([GH-261](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/261))
- **Expose the Dev10x config root via bare CLI invocation and finish
  the XDG migration** — bare `dev10x` echoes the resolved config root
  for portable shell idioms, and the last three user configs migrate
  off `~/.claude/` so fresh projects no longer hit the sensitive-path
  consent gate
  ([GH-270](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/270))
- **Ship AWS Secrets Manager access as a plugin-bundled skill** —
  `Dev10x:aws-vault` relocates the secrets/kubectl wrappers out of
  user space with a configurable service registry so the skill is
  shareable across projects

### Fixes

- **Stabilize the permission doctor on wheel installs** — the baseline
  permissions catalog now ships inside the package and resolves via a
  module-relative path, fixing the `FileNotFoundError` crash on
  PyPI-installed dev10x
  ([GH-264](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/264))

### Hardening

- **Enforce atomic writes and locks on boundary hot paths** — session
  state, plan context, the platform registry, and the audit log now use
  atomic writes and file locks so concurrent worktrees, parallel hooks,
  and the long-lived MCP server cannot lose state in a race; ADR-0011
  documents the layered atomicity model
  ([GH-240](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/240))

### Refactors

- **Enforce typed identifiers across plan and PR surfaces** — five new
  value objects (Task, TicketId, SkillName, RepositoryRef, BranchName)
  replace dict-of-Any threading and scattered regex literals, validating
  inputs once at each boundary
  ([GH-241](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/241))
- **Ship flaky-test fixes through the `work-on` pipeline** —
  `Dev10x:py-test-flaky` is now a thin investigator and ticket scoper
  that hands delivery to `Dev10x:work-on`, so flaky fixes inherit the
  same gates, self-review, and PR monitoring as any other ticket
  ([GH-281](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/281))
- **Strip forbidden-token priming from skill docs** — skill bodies no
  longer name `DEV10X_SKIP_CMD_VALIDATION` as a negative example, and a
  doctor strategy scans for the priming token outside the hook layer
  ([GH-272](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/272))

### Docs

- **Anchor config paths in cross-platform notation** — skill docs use
  abstract `<Dev10x config>/<file>` paths backed by a platform
  resolution table instead of literal `~/.config/Dev10x/` forms that
  misled Windows users
  ([GH-270](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/270))
- **Ensure the no-checkpoints rule travels with auto-advance** — a
  canonical "no checkpoints" definition plus per-skill reinforcement
  stops adaptive-friction sessions from inserting "Ready to proceed?"
  pauses mid-pipeline
  ([GH-223](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/223))
- **Route fixup comment fetch through MCP wrappers** — `Dev10x:git-fixup`
  Step 2 documents `pr_detect` and `pr_comments` instead of the raw `gh`
  shapes the friction scanner forbids
  ([GH-299](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/299))
- **Document review and testing patterns from superseded bot PRs** —
  add the backlog-deferral format, pytest fixture/async handler
  patterns, the hook refactor + lazy-import checklist, and the
  instructions.md allowed-tools scope clarification
  ([GH-202](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/202),
  [GH-124](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/124),
  [GH-130](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/130),
  [GH-104](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/104))

## 0.74.0 — MCP Routing Coverage & Session Mode Awareness

Released 2026-05-21

### Features

- **Route pytest through the `run_tests` MCP wrapper** — `Dev10x:py-test`
  now drives test execution through the MCP tool so coverage gates,
  output capture, and skill enforcement stay consistent across
  invocations
  ([GH-238](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/238))
- **Route `gh pr view` and issue state changes through MCP wrappers** —
  `pr_get`, `issue_close`, and `issue_reopen` replace raw `gh` calls,
  closing the last common CLI fallbacks the routing hook saw in the
  wild
  ([GH-267](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/267))
- **Route `ticket-scope` comments through the `issue_comment` MCP tool**
  — scoping comments land via the structured wrapper instead of `gh
  issue comment`
  ([GH-228](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/228))
- **Surface session mode and classify interrupts** — sessions now
  expose their active mode (attended, walk-away, etc.) and classify
  interrupts so skills can adapt their gating behavior
  ([GH-189](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/189),
  [GH-229](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/229))
- **Pre-format Python files before staging in `git-commit`** —
  ruff/black run automatically on staged Python changes so commits
  never carry unformatted code
  ([GH-224](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/224))

### Fixes

- **Restore `Dev10x:py-test` after a hook hard-block regression** —
  the validation hook no longer hard-blocks the documented `uv run
  pytest` invocation that `Dev10x:py-test` retries
  ([GH-274](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/274))

### Refactors

- **Codify skill-name suffix convention and apply the rename map** —
  skill directory and invocation names now follow a consistent suffix
  convention; the rename map keeps backward references working
  ([GH-217](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/217))
- **Trim `diag-friction` and `gh-pr-review` SKILL.md bodies** — both
  skill bodies were extracted to references so per-invocation token
  cost drops without losing detail
  ([GH-197](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/197),
  [GH-199](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/199))

## 0.73.0 — XDG Config, MCP Wrapper Coverage & Walk-Away Mode

Released 2026-05-19

### Features

- **Move Dev10x userspace config out of `~/.claude/`** — config now
  lives under the OS-standard XDG path (`~/.config/Dev10x/` on
  Linux/macOS, `%APPDATA%/Dev10x/` on Windows; override via
  `DEV10X_CONFIG_HOME`). Legacy files at `~/.claude/memory/Dev10x/`
  and `~/.claude/Dev10x/` are migrated lazily on first read and
  explicitly by `dev10x config migrate` (wired into both
  `Dev10x:upgrade-cleanup` Step 1 and `Dev10x:doctor` Step 0)
  ([GH-215](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/215))
- **Enable spec-as-source-of-truth pipeline (SPDD)** — M1 milestone
  lands the spec-driven development flow so tickets, code, and
  acceptance criteria stay aligned from a single source
- **Close GitHub CLI wrapper gap with 4 new MCP tools** —
  `milestone_create`, `issue_edit`, `issue_comment`, and
  `issue_list` replace raw `gh api`/`gh issue` invocations so
  the routing hook can steer agents away from CLI fallbacks
  ([GH-220](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/220))
- **Route `project-scope` through bulk MCP wrappers** — milestone
  and issue creation use the bulk tools, eliminating per-item
  approval friction for multi-ticket projects
  ([GH-222](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/222))
- **Route `gh pr edit` to the `update_pr` MCP wrapper** — drops
  another raw-CLI path and keeps PR edits behind the structured
  wrapper
  ([GH-209](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/209))
- **Enable `gh-pr-merge` Step 5 via the `merge_pr` MCP tool** —
  final merge step runs through the wrapper so guardrails stay
  consistent end-to-end
  ([GH-232](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/232))
- **Enable walk-away mode for unattended sessions** — supervisor
  can hand off long-running flows so the user does not need to
  baby-sit each prompt
  ([GH-231](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/231))
- **Defer skill-audit invocations via `Dev10x:skill-audit-queue`** —
  audits run asynchronously instead of blocking the active session
  ([GH-219](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/219))
- **Detect Slack-forwarded threads in `ticket-scope` Phase 1.2** —
  forwarded threads carry their original context so scoping reads
  the right conversation
  ([GH-218](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/218))
- **Enable sibling pub/sub coordination via a JSONL bus** —
  parallel sub-agents exchange progress and findings on a shared
  JSONL channel
  ([GH-133](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/133))
- **Surface `push_safe` results so callers can confirm pushes** —
  the wrapper now returns `{pushed, ref, remote, sha, tracking,
  ci_run_url}` instead of `{}` on success, removing the
  silent-success ambiguity
  ([GH-188](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/188))
- **Surface permission-friction diagnosis as `diag-friction`** —
  refactored diagnosis is now a first-class command/skill
  ([GH-214](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/214))
- **Advise on redundant content fetches in PreToolUse** — agents
  get steered away from re-reading content the session already
  loaded
  ([GH-206](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/206))
- **Steer agents to serialized commands over shell loops** —
  guidance hook nudges toward separate tool calls instead of
  `for`/`while` bash loops that defeat permission matching
  ([GH-234](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/234))
- **Audit every validation bypass via a rationale string** — the
  skip path now requires a justification recorded in the audit
  log
  ([GH-226](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/226))

### Fixes

- **Stabilize skill self-checks and permission rules**
  ([GH-252](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/252))
- **Stop Gate 6 from silently skipping after resolve** —
  `gh-pr-respond` now re-validates instead of treating a
  resolved thread as fully addressed
  ([GH-208](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/208))
- **Stop false-positive blocks on `find -name 'git-push-safe.sh'`** —
  the validator no longer mistakes the literal pattern for a
  push command
  ([GH-210](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/210))

### Docs & Internals

- Record 2026-05-18 architecture audit findings under `docs/memos/`
- Document Example 5 in the diag-friction examples list
- Restore ruff format on doctor and permission modules

## 0.72.0 — Doctor, Fanout Swarm & Permission Hygiene

Released 2026-05-17

### Features

- **Diagnose systemic drift with `Dev10x:doctor`** — new skill
  surfaces plugin-version mismatches, missing per-project skill
  pre-approvals, and clusters session paths to propose coherent
  directory coverage so permission friction is fixed at the root
  ([GH-87](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/87),
  [GH-116](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/116),
  [GH-115](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/115))
- **Prompt for upgrade-cleanup when plugin version drifts** —
  SessionStart detects an installed version newer than the
  recorded baseline and nudges the user toward
  `Dev10x:upgrade-cleanup`
  ([GH-109](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/109))
- **Enable native-Agent fanout swarm dispatch** — `Dev10x:fanout`
  now dispatches independent work items as parallel sub-agents
  with a 6-phase execution model, conflict-wave management, and
  recursive-fanout guard
  ([GH-36](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/36))
- **Invert monitor architecture to supervisor + micro-agents** —
  `gh-pr-monitor` runs a long-lived supervisor that dispatches
  read-only micro-agents per check, constrained by contract so
  background monitors cannot mutate the repo
  ([GH-68](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/68))
- **Enable solo-maintainer milestone-bundle PR shipping** —
  `work-on` and `gh-pr-create` understand parent tracker tickets
  and bundle overlapping sub-tickets into a single PR with a
  scoped review auto-skip
  ([GH-185](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/185),
  [GH-196](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/196),
  [GH-161](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/161))
- **Adopt subagent status protocol across orchestration** —
  orchestrators read explicit `DONE / DONE_WITH_CONCERNS /
  NEEDS_CONTEXT / BLOCKED` status from dispatched agents
  ([GH-69](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/69))
- **Pre-approve Linear MCP tools in plugin baseline** — drops
  per-session approval prompts for Linear issue, comment, and
  document operations
  ([GH-204](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/204))
- **Enable top-level PR issue-comment replies via MCP** — new
  `pr_issue_comment` tool replaces raw `gh api POST` fallbacks
  ([GH-205](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/205))
- **Enable multi-workspace Slack posting** — Slack skills route
  per-workspace credentials so multiple orgs can be addressed
  from one session
  ([GH-98](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/98))
- **Enforce push-then-create order in `gh-pr-create`** — branch
  is pushed before `gh pr create` runs, eliminating empty-PR
  failures
  ([GH-159](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/159))
- **Default `gh-pr-merge` to rebase for curated history** —
  matches the project's atomic-commit convention
  ([GH-134](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/134))
- **Enforce one-fixup-per-comment via mechanical guardrail** —
  prevents bundled fixup commits that obscure review traceability
  ([GH-123](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/123))
- **Detect branch drift before commits land off-target** —
  pre-commit gate catches mistargeted feature work
  ([GH-147](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/147))
- **Enrich audit issues with bundling labels** — skill-audit
  output groups related findings for batched remediation
  ([GH-190](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/190))
- **Enable early-insight short-circuit in `skill-audit`** —
  surfaces high-confidence findings before all phases complete
  ([GH-113](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/113))
- **Enable bundled-fixup replies and post-groom SHA refresh** —
  PR comment replies follow rebase-rewritten history
  ([GH-86](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/86))
- **Compare user playbooks against plugin defaults** — surfaces
  stale overrides after plugin upgrades
  ([GH-192](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/192))
- **Cover monorepo `uv run --project` invocations with one rule**
  — single allow rule eliminates per-subdir approval prompts
  ([GH-137](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/137))
- **Nudge agents away from prefix-bypassing shell shapes** — new
  hook validator flags `cd && cmd` and env-prefix patterns that
  defeat allow-rule prefix matching
  ([GH-119](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/119))
- **Enable hook-block routing for bare `pytest` invocations** —
  redirects to the `py-test` skill so coverage gating runs
  ([GH-155](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/155))
- **Enable self-healing permission hints** — `skill-reinforcement`
  proposes the missing allow rule alongside the skill redirect
  ([GH-178](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/178))
- **Enforce pre-staging gate in `git-commit` Step 10** — refuses
  to commit when nothing is staged, avoiding empty commits
  ([GH-157](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/157))
- **Enforce Phase 3 plan-approval `AskUserQuestion` always** —
  `work-on` cannot skip the plan-approval gate
  ([GH-158](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/158))
- **Track `skill-audit` invocation as cycle-audit task** —
  audit runs surface as first-class work items
  ([GH-148](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/148))

### Refactors

- **Group domain by archetype into 4 sub-packages** — domain
  layer reorganized along Software Archetypes for clarity
  ([GH-145](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/145))
- **Unify MCP boundary error envelope via `Result[T]`** —
  internal functions return typed `SuccessResult`/`ErrorResult`;
  MCP handlers unwrap at the boundary
  ([GH-108](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/108))
- **Decompose `hooks/session.py` into archetype-aligned modules**
  ([GH-144](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/144))
- **Consolidate Plan domain via service layer + `TaskStatus`** —
  Plan operations route through a service layer with a typed
  status enum
  ([GH-81](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/81))
- **Promote validator registry and capability dispatch** —
  validators register declaratively
  ([GH-82](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/82))
- **Split platform `Registry` and add Tell-Don't-Ask helpers** —
  permission diagnostics and investigator facades promoted to
  public surface
  ([GH-83](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/83))
- **Type hook phase/outcome via `HookPhase` + `HookOutcome`** —
  replace `friction_level` strings with `FrictionLevel` enum,
  `PROFILE_HIERARCHY` tuple with `ProfileTier` enum, and
  centralize Claude Code filesystem paths via `ClaudeDir`
  ([GH-80](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/80))
- **Promote permission helpers to public, drop stdout-capture
  hack** — permission helpers no longer rely on captured stdout
  ([GH-92](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/92))
- **Unify validator error returns with `Result[str]`** — single
  return shape across all validators
  ([GH-78](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/78))
- **Run permission-audit analysis in-process** — eliminates
  subprocess fan-out for audit phases
  ([GH-142](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/142))
- **Consolidate audit log reading into `audit/log_reader`** —
  one reader serves CLI, MCP, and the audit skill
  ([GH-143](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/143))
- **Centralize PR status fetches behind `PRStatusQuery`** —
  removes scattered `gh pr view` calls
  ([GH-146](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/146))

### Fixes

- **Authenticate GitHub App via Bearer scheme** — JWT requests
  now use the correct header
  ([GH-76](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/76))
- **Stabilize subprocess error contract for missing scripts** —
  consistent error shape when scripts are absent
  ([GH-89](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/89))
- **Exclude bot approvals from review-state precheck** — bot
  approvals no longer satisfy human-review gating
  ([GH-128](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/128))
- **Stop blocking `mktmp.sh` args as git commit** — hook
  validator no longer misreads helper invocations
  ([GH-84](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/84))
- **Surface git-repo errors from `plan.json_summary`** —
  callers see the underlying repo error instead of an empty
  payload
  ([GH-78](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/78))

### Security

- **Prevent state file corruption under concurrent writers** —
  state writes use atomic file replacement
  ([GH-77](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/77))
- **Enforce cwd binding on MCP handlers via `@requires_cwd`** —
  handlers cannot operate outside the bound working directory
  ([GH-78](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/78))
- **Constrain background monitor agents to read-only by
  contract** — dispatched monitor sub-agents cannot mutate state
  ([GH-68](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/68))
- **Enforce `gh-pr-merge` skill via raw CLI deny** — raw
  `gh pr merge` is blocked to keep pre-merge gates in play
  ([GH-112](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/112))
- **Allow `uv run dev10x` from plugin-maintenance** — scoped
  allow rule so maintenance can self-invoke
  ([GH-99](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/99))
- **Allow read-only `find` over plugin cache** — narrow rule
  for cache hygiene checks
  ([GH-122](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/122))
- **Enable grep across plugin cache + memory without prompts** —
  removes friction for retrospective queries
  ([GH-135](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/135))

### Docs

- **Keep internal GitHub MCP over official server** — ADR-0006
  documents why Dev10x ships composite GitHub tools rather than
  depending on `github/github-mcp-server`
- **Lift `Verify AC` invariant to a universal Dev10x rule** —
  every skill ends with a Verify-AC terminal task
  ([GH-149](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/149))
- **Close skill-bypass gaps in `work-on` shipping pipeline** —
  documents mandatory skill chain through commit and PR
  ([GH-152](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/152))
- **Mandate `gh-pr-monitor` invocation after PR creation** —
  removes the "and then what?" gap
  ([GH-162](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/162))
- **Close 7 permission/hook gaps across scaffolding and skills**
  ([GH-127](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/127))
- **Plan SPDD REASONS Canvas adoption across scope skills**
  ([GH-70](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/70))
- **Document `Result[T]` envelope in `mcp-tools.md`**
  ([GH-93](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/93))

### Internal

- **Raise test coverage on critical MCP and CLI paths**
  ([GH-79](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/79))
- **Rebaseline `mcp_server_import` startup gate** — startup-time
  budget updated after import refactors
  ([GH-121](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/121))

## 0.71.0 — GitHub App Verification & Acknowledgments

Released 2026-05-08

### Features

- **Prove github-app setup credentials end-to-end** — setup flow
  prompts for install scope (Personal/Org/Manual), accepts a
  `.pem` file path (defaulting to the newest key in `~/Downloads`)
  and stores it under `~/.claude/Dev10x/github-bot/` with chmod
  600, then verifies the App JWT against `GET /app`,
  `GET /app/installations`, and a per-installation token+repo
  read before writing config — failed verification exits without
  saving ([GH-72](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/72))

### Refactors

- **Discourage agents from misusing skip-validation flag** —
  rewrite the skill-redirect block-message hint as a ⚠️ warning
  that names the lazy-bypass pattern and reserves
  `DEV10X_SKIP_CMD_VALIDATION=true` for skill authors, so agents
  stop copy-pasting it as a shortcut around recommended skills

### Docs

- **Acknowledge external contributors and inspirations** — add
  `ACKNOWLEDGMENTS.md` crediting @tiretutor-paul as project
  godfather alongside external bug reporters, and list the
  projects, talks, and writing that shaped Dev10x's design
  (QRSPI / HumanLayer, obra/superpowers, Fowler PoEAA,
  Refactoring Guru, Software Archetypes, gitmoji,
  semantic-release, JTBD community)

### Internal

- **Apply ruff format to permission-related files** — bring six
  pre-existing files under `src/dev10x/skills/permission*` and
  matching tests in line with project style after pre-PR checks
  flagged them on develop

## 0.70.0 — Subagent Protocols & Privacy Hardening

Released 2026-05-05

### Features

- **Enable subagent status protocol parsing** — orchestrators
  read explicit `DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT /
  BLOCKED` final-status lines from dispatched agents instead of
  guessing from free-form prose, and `gh-pr-monitor`'s GH-901
  fallback parses `BLOCKED:` as the primary signal
  ([GH-69](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/69))
- **Enable bot identity for agent-generated PR replies** — opt-in
  GitHub App identity routes review-thread replies and PR summary
  comments through `dev10x-bot[bot]` while keeping PR creation,
  reviewer assignment, and thread resolution under the engineer's
  account ([GH-65](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/65))
- **Enable in-place PR body updates via MCP tool** — new
  `mcp__plugin_Dev10x_cli__update_pr` lets `gh-pr-create` update
  mode and `git-groom` Phase 4 refresh PR body, title, or base
  branch without raw `gh api PATCH` permission prompts
  ([GH-60](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/60))
- **Stabilize fixup! reply links across grooming** — fixup reply
  comments use absolute `/commit/HASH` permalinks so links keep
  resolving after rebase rewrites SHAs
  ([GH-52](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/52))
- **Detect privacy and external service drift in CI** — a new
  privacy-audit workflow scans source for external services and
  outbound network usage, cross-checks against `PRIVACY_POLICY.md`,
  and comments on PRs that introduce undocumented integrations
  ([GH-6](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/6))

### Fixes

- **Allow MCP tools to target session worktree** — MCP tools that
  shell out to `git`/`gh` honor a per-call `cwd` so EnterWorktree
  sessions stop hitting the spawning repo's branch and dirty-tree
  state ([GH-979](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/979))
- **Cover user-global `settings.json` in upgrade-cleanup
  rewrites** — `update-paths.py` now discovers both
  `~/.claude/settings.json` and `settings.local.json` when
  `include_user_settings: true`, so versioned plugin paths no
  longer go stale after every upgrade
  ([GH-982](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/982))

### Security

- **Scrub private context from skill-audit upstream reports** —
  audit-report and skill-audit Phase 7 redact private repo
  names, branches, tracker IDs, paths, and free-text excerpts
  before filing upstream issues, with `AskUserQuestion` gating
  unscrubbable findings ([GH-56](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/56))

### Refactors

- **Reduce agent dispatch tokens via body extraction** — apply
  the skill-body-extraction strategy to plugin-distributed
  agents; `permission-auditor.md` shrinks from 226 → 159 lines
  with bulk content moved under
  `references/agents/permission-auditor/`
  ([GH-983](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/983))
- **Defer pre-PR checks to project pre-commit settings** —
  `pre-pr-checks.sh` delegates to `pre-commit run` when
  `.pre-commit-config.yaml` is present so projects own their
  ruff/mypy versions and excludes end-to-end
  ([GH-38](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/38))
- **Allow direct-to-base commits in solo-maintainer mode** —
  `git-commit` reads `solo_maintainer` from session config and
  skips the develop/main/master block so single-author repos
  can commit directly to the base branch
  ([GH-57](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/57))

### Docs

- **Inject friction context into skill-audit Wave 2** — Phase 3
  compliance subagent receives `friction_level` and
  `active_modes` so documented auto-select gates score as
  COMPLIANT instead of SKIPPED_STEP
  ([GH-55](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/55))
- **Tighten `ticket-scope` research tool routing** — Phase 2
  mandates Grep/Read tools over bash `grep`/`cat` and Phase 7.1
  routes through the `mktmp` MCP tool
  ([GH-55](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/55))
- **Strengthen `work-on` Phase 1 + Phase 2 enforcement** — route
  workspace detection through `gh-context`, inline the TaskList
  self-check, mark subtask creation REQUIRED before any Agent
  dispatch, and prohibit Explore-subagent dispatch for source
  fetch ([GH-55](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/55))
- **Repoint changelog GH refs to the right repo** — convert
  footnote-style refs to inline links and pin pre-0.67 entries
  plus 0.68 high-number refs to the archived
  `Dev10x-Claude2` repo so historical links keep resolving
  ([GH-53](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/53))

## 0.69.0 — Permission Friction & Audit Empiricism

Released 2026-05-01

### Features

- **Enable empirical investigation of permission rule shapes** —
  audit tooling captures real-world permission rule patterns so
  prefix-friction diagnostics rest on observed behavior instead
  of assumptions ([GH-47](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/47))
- **Emit per-skill Read rules with `~/` + `/home` twins** —
  `plugin-maintenance` writes both expansions so Read rules match
  regardless of which form Claude resolves at allow-check time
  ([GH-48](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/48))
- **Detect Write-overwrite, workspace, and exit-code friction in
  audit** — three new diagnostics surface common permission
  prompt causes that previously slipped past audit reports
  ([GH-46](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/46))
- **Prefer working-dir scripts when CWD is plugin source** —
  hooks and skills resolve script paths to the active checkout
  rather than the installed plugin, so local edits take effect
  immediately ([GH-42](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/42))
- **Register `/tmp/Dev10x` workspace via `plugin-maintenance`
  bootstrap** — first-run setup adds the workspace allow rule so
  `mktmp` and friends stop prompting on fresh installs ([GH-40](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/40))
- **Stop pre-creating files in `mktmp` to avoid Write-overwrite
  prompt** — the MCP tool returns a fresh path without touching
  it, so the first Write call no longer trips the overwrite gate
  ([GH-39](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/39))
- **Expose audit-wrap log discovery via MCP tools** —
  `audit_hook_log_path` and `audit_hook_recent` let skills query
  hook timing data without shelling out ([GH-29](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/29))
- **Add PoC option to `ticket-scope` approval gate** — scoping a
  proof-of-concept ticket no longer forces the full template
  treatment ([GH-33](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/33))
- **Auto-detect Slack state to skip redundant prompts** —
  `slack-review-request` checks for an existing token before
  prompting, smoothing the request-review flow ([GH-19](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/19))

### Fixes

- **Fix Server Tests workflow path** — the CI path filter now
  matches the relocated MCP server module ([GH-9](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/9))
- **Use REST API for PR body updates to avoid Projects-classic
  exit 1** — `gh-pr-create` update mode bypasses a `gh` GraphQL
  failure on repos still attached to classic projects ([GH-41](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/41))
- **Resolve pre-existing mypy errors in MCP github and hook
  audit** — strict typing passes again after the GitHub-domain
  lift
- **Scope pre-PR mypy invocation to `src/`** — match
  `pyproject.toml` so the pre-PR check stops scanning unrelated
  trees

### Refactors

- **Lift the GitHub domain into a top-level package** — MCP
  GitHub helpers move out of the server-internal namespace so
  CLI tools and tests can share them ([GH-9](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/9))
- **Lift simple MCP domains into top-level packages** —
  cohesive single-purpose MCP modules become standalone packages
  for easier reuse ([GH-9](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/9))
- **Reuse subprocess utilities outside the MCP layer** — the
  shared subprocess helper graduates out of `mcp/` so audit and
  CLI consumers stop duplicating it ([GH-9](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/9))
- **Enforce template selection in `ticket-scope` Phase 5.1** —
  skill body blocks free-text drift through the template gate
  ([GH-28](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/28))
- **Enforce `jtbd` delegation in `ticket-scope` Phase 4b** —
  Job Story drafting routes through the dedicated skill
  ([GH-27](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/27))
- **Enforce `instructions.md` read at `ticket-scope` startup** —
  body content loads explicitly so phase logic is visible to the
  agent ([GH-26](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/26))
- **Preserve hook guardrails outside split-rebase docs** —
  `git-commit-split` references hook rules instead of redefining
  them ([GH-15](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/15))
- **Enable consistent coverage gates in skill scripts** — every
  skill script enforces the same coverage threshold ([GH-13](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/13))
- **Route raw `git` CLI in skill bodies through wrappers** —
  skills call the safe-rebase / safe-push wrappers instead of
  raw `git` so guardrails stay in force ([GH-14](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/14))

### Documentation

- **Document fanout-parallel hook propagation surprises** —
  parent hooks may not run inside fanout children; the rule lives
  next to the skill ([GH-32](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/32))
- **Document fanout-parallel cold-load budget floor** — children
  pay a fixed cold-load cost, so fanout below the floor is
  slower than serial ([GH-31](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/31))
- **Document `--bare` strips OAuth in fanout-parallel children**
  — bare clones lose token auth, breaking `gh` calls inside
  fanout children ([GH-30](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/30))
- **Clarify mode prompt overrides preserve skills delegation** —
  override examples no longer suggest dropping skill calls
  ([GH-45](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/45))
- **Forbid skill partial-read downgrade in `work-on`** — the
  skill always reads the full body to keep orchestration
  contracts intact ([GH-44](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/44))
- **Enforce `gh-pr-respond` for all PR review comments** —
  responding directly via `gh` bypasses validation gates
  ([GH-43](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/43))

### Polish

- **Modernize `Result` generics with PEP 695 syntax**
- **Wrap long literal strings in `src/dev10x` and tests**
- **Resolve `RuleEngine F821` in `edit_validator` hook**
- **Sort imports in `skill-audit` script entry points**
- **Remove dead test variables and rename ambiguous loop var**

## 0.68.0 — First-Run Setup & PR-Skill Hardening

Released 2026-04-29

### Features

- **Streamline first-run permission setup** — bootstrap walks new
  users through the minimum permission set so the plugin works
  without per-tool prompting on day one ([GH-1](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1))
- **Detect raw CLI in skill docs to prevent MCP/Skill bypass** —
  reviewer surfaces `gh`/`git` shell-outs in skill bodies that
  should route through MCP tools or sibling skills ([GH-5](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/5))
- **Eliminate per-invocation permission prompts in 18 skills** —
  audit-driven sweep adds the missing `allowed-tools` entries so
  these skills run without approval friction ([GH-11](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/11))
- **Allow scoped `pr_comments` listings on heavily reviewed PRs**
  — pagination + filtering avoid response-size limits on PRs with
  hundreds of threads ([GH-997](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/997))
- **Enable batched comment hiding via single GraphQL mutation** —
  one round-trip hides many comments instead of N requests
  ([GH-987](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/987))
- **Enable bootstrap coverage for uv/yq/git/gh patterns** —
  bootstrap allow rules cover the toolchain seen across skills
  out of the box ([GH-20](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/20))

### Fixes

- **Halt PR creation when pre-PR checks fail** — `gh-pr-create`
  no longer pushes a draft PR when type-check or test gates
  failed ([GH-998](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/998))
- **Enforce ticket-create haiku dispatch and tracker fast-fail**
  — tracker mismatches surface immediately and ticket creation
  uses the right model tier ([GH-998](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/998))
- **Enforce slack-review-request prepare script use** — Slack
  notifications go through the prepared script so token handling
  stays consistent ([GH-998](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/998))
- **Allow numeric-string comment IDs on `pr_comment` reply** —
  reply tool accepts both forms returned by upstream APIs
  ([GH-995](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/995))

### Refactors

- **Eliminate raw `gh` CLI in PR-skill bodies** — PR skills route
  through MCP wrappers, fixing audit findings and removing the
  raw-CLI bypass ([GH-12](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/12))
- **Guard `request-review` against approved PR pings** — already-
  approved PRs no longer ping reviewers redundantly ([GH-993](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/993))

## 0.67.0 — Maintenance & Repository History Pruning

Released 2026-04-26

Maintenance release. No new features or behavior changes — the
plugin keeps its 0.66.0 surface area while the repository itself
gets a fresh start.

### Maintenance

- **Prune repository history** — the public repository was rewound
  to a minimal commit history. Past development history is no
  longer reachable from `main`/`develop`; existing checkouts will
  need a fresh clone.

## 0.66.0 — Skill Slimdown & Post-Upgrade Polish

Released 2026-04-20

### Features

- **Enable pytest flaky-test fix orchestration** —
  `Dev10x:py-test-flaky` orchestrates the full flaky-test
  workflow (reproduce, root-cause, fix, ticket, branch,
  commit, PR) and delegates to Dev10x sibling skills so
  fixes follow project conventions without per-step coaching
- **Streamline upgrade-cleanup post-upgrade flow** —
  `ensure_base` auto-expands stale MCP wildcards, a new
  `enumerate-mcp.py` wrapper runs by absolute path,
  worktree-absolute paths drop out of the merge filter, the
  `session-start-reload.py` allow rule is annotated, and
  `update-paths`/`clean` gain a `--summary` flag so the post-
  v0.65.0 upgrade pass no longer needs hand-holding ([GH-965](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/965))

### Refactors

- **Rename oversized SKILL.md files to instructions.md** —
  pure rename of 14 skill bodies (work-on, skill-audit,
  git-commit, gh-pr-monitor, gh-pr-respond, fanout, git-groom,
  qa-self, scope, git-commit-split, playbook, ticket-scope,
  gh-pr-merge, gh-pr-create) so `git log --follow` preserves
  history ahead of the frontmatter split ([GH-970](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/970))
- **Split skill frontmatter from body via instructions.md** —
  each oversized skill now ships a ~30–50 line SKILL.md (YAML
  frontmatter plus a pointer) with the body in `instructions.md`,
  so MOTD index and skill discovery costs drop and the body only
  loads once a skill is invoked ([GH-970](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/970))
- **Split task-orchestration.md into per-pattern files** —
  the 649-line shared reference shrinks to a 50-line index
  that links to per-pattern files under `references/orchestration/`,
  so downstream consumers keep working without edits and
  pattern detail loads only when a skill links the specific
  file ([GH-970](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/970))

### Documentation

- **Clarify data-handling practices for adopters** — the
  plugin documentation now describes local-only storage paths,
  states that no telemetry or user data leaves the machine,
  enumerates third-party integrations with credential scopes,
  and provides data deletion commands plus the audit-log
  disable switch, closing the disclosure gap flagged by an
  external security audit ([GH-966](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/966))
- **Enable reliable plugin install via shell CLI** — install
  instructions now prefer `claude plugin marketplace add` and
  `claude plugin install` shell commands (run outside a Claude
  Code session) over the unreliable `/plugin` slash commands,
  and drop the non-existent `claude plugin add --local`
  subcommand from the local-development path

## 0.65.0 — Hook Performance & Control

Released 2026-04-19

### Features

- **Shorten session startup by consolidating hooks** —
  SessionStart now runs 5 features in one orchestrator (Stop
  runs 2), replacing 8 `uv run --project` wrappers with
  direct-shebang scripts so every session feels faster without
  paying uv project resolution and CLI import cost per hook
  ([GH-959](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/959))
- **Surface per-hook execution timing for latency triage** —
  `@audit_hook` plus an `audit-wrap` shell wrapper capture
  body-phase and total (including uv startup) timing per
  invocation to `/tmp/Dev10x/logs/hooks-*.jsonl`, with
  `dev10x hook audit summary` and `prune` subcommands so slow
  hooks are diagnosable before users complain ([GH-860](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/860))
- **Let users dial hook strictness per session** — validator
  specs now carry `rule_id` (DX001–DX008), `profile`
  (minimal/standard/strict), and `experimental` flags, so
  `DEV10X_HOOK_PROFILE`, `DEV10X_HOOK_DISABLE`, and
  `DEV10X_HOOK_EXPERIMENTAL` can drop opinionated rules for
  throwaway work while keeping safety-critical guardrails on
  shared-repo commits ([GH-413](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/413))
- **Guide users to reconnect MCP instead of bypassing hook** —
  when the `Dev10x_cli` MCP server is unavailable, use-tool
  block messages now instruct the agent to ask the user to
  reconnect rather than fall back to wrapper scripts or reach
  for `DEV10X_SKIP_CMD_VALIDATION`, which users reject for
  transient outages ([GH-957](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/957))

## 0.64.0 — Platform Reach & Merge Safety

Released 2026-04-18

### Features

- **Support multi-platform installs via unified CLI** — register
  any AI assistant (Claude Code, Copilot, Windsurf, Continue,
  Cursor, or custom targets) with `dev10x platform add/list/remove`
  so Dev10x can extend beyond its original two-host scope without
  per-user path editing ([GH-908](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/908))
- **Automate PyPI publishing on release tags** — `v*` tag pushes
  publish the `dev10x` package via OIDC trusted publishing, so
  users can `pip install Dev10x` for CI scripts and hook
  integration without manual upload steps ([GH-953](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/953))
- **Guide new users through Dev10x onboarding** — `dev10x init`
  seeds starter config and prints a Next 5 Commands quick-start
  card, replacing the zero-direction `/help` landing with a
  frictionless guided setup ([GH-906](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/906))
- **Prevent silent merges past unresolved CI checks** —
  `Dev10x:gh-pr-merge` now blocks on `PENDING`, `IN_PROGRESS`, or
  any `bucket:fail` state and requires an explicit reason for
  override, closing the gap that shipped a bundle while e2e was
  still running ([GH-955](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/955))
- **Enforce instruction budget for large skills** — new
  `dev10x skill count-instructions` command measures actionable
  instructions and warns when skills exceed the 150-instruction
  reliability threshold from QRSPI research ([GH-882](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/882))
- **Offer structured retry after rejected commands** — when a
  user rejects a CLI command, `Dev10x:skill-reinforcement` now
  fires `AskUserQuestion` with retry/manual/cancel options
  instead of a plain-text follow-up that could silently auto-
  advance ([GH-952](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/952))
- **Prefer bundled PR for same-milestone multi-issue work** —
  `Dev10x:work-on` auto-selects a bundled PR strategy when all
  tickets share a milestone under solo-maintainer mode, cutting
  N branch switches, CI cycles, and merges down to one
  ([GH-948](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/948))
- **Enable MCP glob enumeration in upgrade-cleanup** — new
  `dev10x permission enumerate-mcp` subcommand replaces
  `mcp__plugin_Dev10x_*` wildcards with enumerated tool names,
  eliminating the manual approval prompts Claude Code fires when
  globs silently match nothing ([GH-947](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/947))
- **Enable Supabase env bootstrap in worktree hooks** — post-
  checkout hooks now copy `.env.supabase` into new worktrees so
  local Supabase connectivity works without manual file copying
  ([GH-946](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/946))

### Refactors

- **Isolate Dev10x scratch files under /tmp/Dev10x/** — plugin
  scratch files, session state, and the mktmp binary moved from
  the shared `/tmp/claude/` namespace to `/tmp/Dev10x/`, letting
  users scope allow rules to plugin-only paths ([GH-949](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/949))

### Chores

- **Keep scheduled_tasks.lock out of version control** — the
  session-local scheduler lock file is now gitignored so it
  cannot land alongside unrelated skill changes ([GH-955](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/955))

## 0.63.0 — Solo Shipping & Playbook Resilience

Released 2026-04-15

### Features

- **Enable auto-merge in solo-maintainer shipping pipeline** —
  solo maintainers no longer need to manually merge every PR;
  the shipping pipeline now includes a conditional merge step
  ([GH-940](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/940))
- **Enable playbook schema version tracking** — playbook files
  include a version field bumped automatically on release so
  drift between skills and core plugin is detectable ([GH-910](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/910))
- **Enable decision-aware session resume guidance** — resumed
  sessions surface pending decisions from task metadata and
  inject friction-level guidance so agents re-ask or
  auto-advance correctly ([GH-934](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/934))

### Fixes

- **Prevent non-functional MCP wildcards from masking
  permissions** — upgrade cleanup detects and removes top-level
  MCP wildcard patterns that Claude Code ignores at runtime,
  preventing false coverage from hiding missing tool entries
  ([GH-943](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/943), [GH-942](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/942))
- **Prevent fragment shadowing from dropping skills** — user
  playbook fragments that shadow defaults now inherit skills,
  agent, model, and modes fields instead of silently dropping
  them ([GH-938](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/938))
- **Prevent ACC review-requested from failing solo mode** —
  review-requested checks are skipped in solo-maintainer mode
  where no reviewers are ever assigned ([GH-939](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/939))
- **Resolve upgrade-cleanup broken script flags** — MCP tool
  routes ensure-base, generalize, and ensure-scripts to Python
  functions directly instead of passing invalid CLI flags
  ([GH-936](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/936))

### Refactors

- **Simplify onboarding skill with reference redirect** —
  extracted tour content to a references file, reducing
  SKILL.md from 202 to ~40 lines ([GH-897](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/897))

### Docs

- **Document CLI startup performance baseline** — baseline
  metrics and monitoring instructions for regression tracking
  ([GH-907](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/907))
- **Clarify tier 2 path after old projects/ removal** — config
  resolution docs updated to reflect the canonical
  `~/.claude/memory/Dev10x/` path ([GH-941](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/941))
- **Update gitignore for backup settings files** — settings
  backup files are now excluded from version control

## 0.62.0 — Issue Milestones & Permission Safety

Released 2026-04-14

### Features

- **Enable milestone assignment on issue creation** — ticket-create
  skill assigns milestones when specified, keeping project tracking
  aligned from the start ([GH-926](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/926))
- **Enable rollback for upgrade-cleanup bulk edits** — bulk settings
  modifications create timestamped backups so changes can be reverted
  if something goes wrong ([GH-921](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/921))
- **Enable CLI access to permission scripts** — permission audit and
  cleanup scripts are accessible from the dev10x CLI entry point
  ([GH-924](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/924))

### Fixes

- **Prevent wildcard rules from stripping permissions** — upgrade
  cleanup no longer removes valid allow rules when wildcard patterns
  overlap with specific entries ([GH-922](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/922))
- **Strengthen recurring audit finding guards** — audit-report skill
  checks for duplicate findings before filing, preventing redundant
  GitHub issues ([GH-928](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/928))

### Docs

- **Improve README with cover image and badges** — README now leads
  with marketplace badge, version badge, and a cover image for better
  first impressions

## 0.61.0 — Permission Diagnostics & Skill Refinements

Released 2026-04-14

### Features

- **Surface permission-denied diagnostics** — hooks detect blocked
  tool calls and provide actionable guidance on missing allow rules
  or hook configuration ([GH-918](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/918))
- **Improve upgrade-cleanup audit reporting** — upgrade-cleanup
  produces structured, severity-categorized findings instead of
  flat text output ([GH-914](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/914))
- **Enable direct review thread resolution** — gh-pr-respond can
  resolve review threads directly after posting fixup commits,
  reducing round-trips ([GH-902](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/902))

### Fixes

- **Stabilize uv dep resolution test assertion** — fix flaky test
  that depended on exact pip resolver output ordering ([GH-913](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/913))

### Tests

- **Validate uv shebang script dependencies** — new test ensures
  all PEP 723 inline-metadata scripts declare valid, resolvable
  dependencies ([GH-913](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/913))

### Docs & Skills

- **Persist session state across context resets** — session-stop
  hook preserves branch, plan, and task state so resumed sessions
  recover context automatically ([GH-917](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/917))
- **Detect architecture violations in PR review** — review skill
  checks for Clean Architecture boundary crossings ([GH-916](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/916))
- **Ensure monitor fallback on permission failure** — PR monitor
  retries with reduced permissions instead of failing silently
  ([GH-901](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/901))
- **Support natural-language input in work-on** — work-on accepts
  free-text task descriptions alongside ticket URLs ([GH-886](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/886))
- **Prefer vertical slice decomposition in scope** — scope skill
  favors feature slices over horizontal layer splits ([GH-885](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/885))
- **Monitor context fill at phase boundaries** — work-on tracks
  context window usage and warns before overflow ([GH-884](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/884))
- **Surface design analysis as a review gate** — scope skill
  requires design review before implementation begins ([GH-883](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/883))
- **Prevent confirmation bias with blind research** — brainstorming
  skill gathers evidence before presenting options ([GH-881](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/881))
- **Enable skill instruction count tracking** — skill-index reports
  instruction line counts for budget monitoring ([GH-877](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/877))
- **Resolve hook error handling standardization** — align hook exit
  codes and error messages across Python and shell ([GH-826](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/826))
- **Resolve milestone findings** — address M3–M6 architecture,
  pattern adoption, test coverage, and cross-cutting consistency
  findings ([GH-811](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/811), [GH-812](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/812), [GH-813](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/813), [GH-814](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/814))

## 0.60.0 — Multi-Issue Bundling & Audit Clarity

Released 2026-04-13

### Features

- **Bundle multiple issues in work-on** — work-on skill accepts
  multiple ticket URLs or IDs in a single invocation, gathering
  context in parallel and building a unified task list ([GH-868](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/868))
- **Separate audit detection from solution design** — permission
  auditor splits finding identification from fix proposals so
  users review problems before seeing solutions ([GH-904](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/904))

### Fixes

- **Restore MCP server dependencies** — re-add yaml and msgpack
  dependencies removed during consolidation so MCP servers start
  without import errors ([GH-911](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/911))
- **Enforce PR reference update after groom force-push** — groom
  skill now updates the PR head ref after force-pushing rebased
  commits, preventing stale SHA references ([GH-900](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/900))
- **Prevent misleading completion messages in fixup** — fixup
  skill no longer reports success when the underlying commit
  was not created ([GH-899](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/899))
- **Prevent wildcard allow-rule proposals in audit** — permission
  auditor blocks overly broad glob patterns that would bypass
  security boundaries ([GH-903](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/903))

### Docs

- **Clarify gh-pr-respond as PR comment entry point** — update
  skill description to direct users to gh-pr-respond instead
  of gh-pr-fixup for handling review comments ([GH-898](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/898))

## 0.59.0 — Permission Automation & Review Intelligence

Released 2026-04-13

### Features

- **Auto-detect semantic-release config** — release-notes skill
  now discovers project-specific ticket patterns and output
  targets without manual configuration ([GH-585](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/585))
- **Auto-groom fixup commits in CI** — PR monitor detects
  fixup! commits and triggers automatic interactive rebase
  before merge readiness ([GH-869](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/869))
- **Pre-approve temp file and MCP permissions** — new permission
  namespaces eliminate approval prompts for temp files, plugin
  scripts, MCP tools, and git aliases ([GH-878](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/878))
- **Simplify code after review** — post-review pipeline step
  scans changed files for reuse and quality improvements
  ([GH-874](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/874))
- **Filter review findings by confidence** — review skill drops
  low-confidence findings to reduce noise in PR comments
  ([GH-872](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/872))
- **Detect silent failures in reviews** — new reviewer agent
  catches swallowed exceptions and missing error logging
  ([GH-873](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/873))
- **Verify plugin script coverage** — pre-PR check ensures all
  plugin scripts referenced in skills have test coverage
  ([GH-876](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/876))
- **Invoke scripts via MCP instead of paths** — MCP server
  wraps plugin scripts so skills avoid path-dependent Bash
  allow rules ([GH-807](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/807))
- **Persist upgrade-cleanup config** — cleanup preferences
  survive across sessions via YAML settings file ([GH-862](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/862))

### Improvements

- **Extensible PR comment action dispatch** — comment handler
  uses registry pattern for adding new reply actions ([GH-827](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/827))
- **Self-formatting session state objects** — state dataclasses
  render their own display strings, removing format duplication
  ([GH-820](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/820), [GH-823](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/823))
- **Canonical rule evaluation via RuleEngine** — single
  evaluation path replaces scattered rule-checking code
  ([GH-818](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/818))
- **Single-source YAML rule parsing** — rule definitions load
  from YAML instead of duplicated Python dicts ([GH-822](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/822))
- **Path-independent plan context updates** — plan sync works
  from any working directory without hardcoded paths ([GH-802](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/802))
- **Type-safe MCP tool returns** — MCP tools return typed dicts
  instead of raw strings, catching schema mismatches early
  ([GH-819](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/819))
- **Validated repository references** — repo URL construction
  uses validated objects instead of string concatenation
  ([GH-821](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/821))

### Fixes

- **Prevent shipping pipeline skill regressions** — pin
  eval assertions that caught behavioral drift in PR create,
  groom, and merge skills ([GH-851](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/851))
- **Block fanout completion before monitors finish** — gate
  now waits for all background PR monitors before advancing
  ([GH-859](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/859))
- **Fix plugin cache lookup after repo rename** — cache key
  derivation uses canonical repo name, not stale path
  ([GH-861](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/861))
- **Detect stale plugin paths with different casing** — path
  comparison is now case-insensitive on case-folding
  filesystems ([GH-864](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/864))

### Tests

- **MCP GitHub tool coverage** — add unit tests for PR detect,
  issue get, and comment reply MCP tools ([GH-825](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/825))
- **Domain module regression safety** — add integration tests
  for core domain module imports and wiring ([GH-824](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/824))

## 0.58.0 — Session Safety & Config Hygiene

Released 2026-04-09

### Features

- **Surface background agent progress in caller** — add
  caller-side task tracking for background monitor agents so
  supervisors see in-progress work instead of an idle session
  ([GH-854](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/854))
- **Prevent auditing wrong session via gate** — skill-audit
  now confirms resolved session identity before proceeding,
  blocking silent fallback to alternate path encodings
  ([GH-805](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/805))

### Improvements

- **Normalize config paths to canonical locations** — remove
  deprecated Tier 3 path references from 16 skills, consolidate
  bare memory configs under Dev10x/ subdirectory, and align
  config-resolution docs with actual resolution order ([GH-849](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/849))

### Fixes

- **Preserve git alias rules from cleanup** — permission
  maintenance no longer removes git alias allow rules that
  worktree sessions depend on for branch-switching and commit
  grooming ([GH-852](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/852), [GH-853](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/853))
- **Prevent session.yaml overwrite of active modes** — Phase 0
  now reads before writing, preserving existing active_modes
  instead of overwriting with empty defaults ([GH-846](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/846))

## 0.57.0 — Plugin Naming Consistency

Released 2026-04-09

### Improvements

- **Update plugin naming for Dev10x consistency** — align
  plugin.json and marketplace.json name fields to "Dev10x"

## 0.56.0 — Concurrency Safety & Context Efficiency

Released 2026-04-09

### New Skills

- **Enable parallel fanout experimentation** — dispatch
  worktree-isolated agents in parallel to validate newer
  Claude Code capability assumptions ([GH-781](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/781))
- **Allow maintenance commits to bypass JTBD** — configurable
  bypass gitmoji set lets changelog/version-bump commits skip
  outcome-focused title enforcement ([GH-797](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/797))

### Improvements

- **Delegate tracker CRUD to background agents** — project-scope
  and ticket-create offload Linear/GitHub API calls to a haiku
  agent, returning compact summaries instead of dumping 26k token
  API responses into context ([GH-842](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/842))
- **Unblock MCP event loop from subprocess calls** — convert all
  MCP tool handlers to async using asyncio subprocess, eliminating
  up to 60s blocking during shell execution ([GH-815](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/815))
- **Enable batch thread resolution in PR comments** — resolve
  all review threads in two GraphQL calls instead of O(2N)
  sequential calls, avoiding rate limits in large PRs ([GH-828](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/828))
- **Surface lesson-learned guidance from stale PRs** — extract
  orchestration anti-patterns, test-pattern checks, and hook
  state documentation from 5 stale draft PRs into rules

### Fixes

- **Enforce named parameter Skill() syntax** — fix positional
  Skill() calls in ticket-create and ticket-jtbd that caused
  agent misrouting ([GH-804](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/804))
- **Enforce PR comment resolution in fanout** — Phase 5 now
  blocks completion until all PR review comments are resolved;
  per-item check added in Phase 3 ([GH-829](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/829))
- **Prevent plan gate skip at adaptive friction** — clarify
  that auto-select means execute the recommended option, not
  skip the approval gate entirely ([GH-808](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/808))
- **Enable portable plugin path in pr-monitor** — replace
  hardcoded versioned path with ${CLAUDE_PLUGIN_ROOT} variable
  ([GH-806](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/806))
- **Prevent session state race between sessions** — atomic
  os.rename() claim prevents two concurrent sessions from
  reading and deleting the same state file ([GH-816](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/816))

### Security

- **Protect settings.json from concurrent writes** — introduce
  fcntl advisory locking with atomic write-then-rename so
  concurrent sessions cannot overwrite each other's changes
  ([GH-817](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/817))

### Breaking Changes

- **Isolate codex port to separate repo** — remove codex-skills/
  directory (45 skill ports), codex install/validate scripts,
  and docs/codex.md ([GH-678](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/678))
- **Unify documentation under docs/ directory** — ADRs moved
  from doc/adr/ to docs/adr/; update any external links or
  scripts referencing the old path ([GH-838](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/838))

## 0.55.0 — Merge Safety & Skill Guardrails

Released 2026-04-08

### Features

- **Resolve skill-audit findings across 5 skills** — address
  accumulated audit findings for improved compliance ([GH-760](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/760))
- **Preserve fixup commit links after grooming** — groom no
  longer drops fixup commit references from PR threads ([GH-777](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/777))
- **Strengthen skill delegation guardrails** — prevent agents
  from bypassing skill orchestration contracts ([GH-759](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/759))
- **Prevent undetected cd+git chaining** — hook now catches
  cd-then-git patterns that break allow rules ([GH-763](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/763))
- **Prevent false positives on skill-required rules** — permission
  auditor no longer flags rules that skills actively need ([GH-790](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/790))
- **Enable publisher rename in permission paths** — update-paths
  handles publisher directory renames correctly ([GH-791](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/791))

### Refactoring

- **Enable single-source hook implementations** — consolidate
  12 standalone hook scripts into dev10x CLI subcommands ([GH-748](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/748))

### Fixes

- **Prevent false green on draft-to-ready** — CI monitor now
  re-checks status after PR transitions from draft ([GH-774](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/774))
- **Prevent orchestrator from pre-empting groom** — merge skill
  waits for groom completion before proceeding ([GH-776](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/776))
- **Prevent inline CI polling in merge skill** — delegates
  polling to monitor agent instead of inline loops ([GH-775](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/775))
- **Prevent merge failure in worktree setups** — gh pr merge
  now uses --repo flag in worktree contexts ([GH-773](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/773))
- **Prevent CI check cascade failure** — handle partial check
  results without aborting the entire merge flow ([GH-772](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/772))

## 0.54.0 — Hook Consolidation & Lazy Imports

Released 2026-04-08

### Features

- **Enable SessionStart hooks via dev10x hook session** — unified
  hook entry point for session startup ([GH-741](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/741))
- **Enable SessionStop hooks via dev10x hook session** — unified
  hook entry point for session teardown ([GH-742](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/742))
- **Enable Skill and PostToolUse hooks via dev10x hook** — unified
  hook entry point for tool-use lifecycle ([GH-743](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/743))
- **Centralize config into ~/.claude/memory/Dev10x** — single
  location for all plugin configuration ([GH-726](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/726))

### Performance

- **Defer heavy imports to command invocation** — lazy-load
  expensive modules to reduce CLI startup time ([GH-746](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/746))

### Refactoring

- **Enable cli_server as thin uv shim** — reduce server startup
  overhead with lightweight wrapper ([GH-744](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/744))
- **Enable db_server as thin uv shim** — reduce server startup
  overhead with lightweight wrapper ([GH-745](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/745))

### Fixes

- **Resolve hook failures on systems without PyYAML** — graceful
  fallback when optional dependency is missing ([GH-766](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/766))
- **Prevent false positive on explicit JSONL path** — path
  validation no longer flags valid JSONL files ([GH-762](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/762))

### Documentation

- **Clarify glob pattern syntax in config-resolution** — improve
  examples for file matching patterns ([GH-757](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/757))

### Tests

- **Enable CLI startup time benchmarking** — measure and track
  startup performance regressions ([GH-749](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/749))
- **Enable server tests to measure mcp package coverage** —
  expanded test coverage for MCP servers ([GH-745](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/745))

## 0.52.0 — Marketplace & Repo Migration

Released 2026-04-07

### Refactoring

- **Standardize JSON format for marketplace name** — align
  marketplace.json naming convention to hyphenated format
  (Dev10x-Guru)

## 0.51.0 — Repository Migration

Released 2026-04-07

### Infrastructure

- **Migrate repo references to Dev10x-Guru/dev10x-claude** —
  update all installation instructions, plugin manifests, code
  paths, tests, and documentation to reflect the new repository
  location

## 0.50.0 — Fanout Safety & CI Overrides

Released 2026-04-07

### Features

- **Allow user override for infrastructure CI failures** — users
  can bypass infrastructure-only CI failures when appropriate
  ([GH-730](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/730))

### Fixes

- **Enforce fanout audit, monitor, and fixup safety** — fanout
  skill validates audit completion, monitors, and fixup commits
  before proceeding ([GH-724](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/724))
- **Enforce Check 1b in gh-pr-merge** — merge gate validates
  all required checks before allowing merge ([GH-728](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/728))
- **Prevent play step collapsing in work-on** — work-on skill
  preserves individual play steps during execution ([GH-729](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/729))
- **Prevent CI actions from running on merged PRs** — CI
  workflows skip already-merged pull requests ([GH-721](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/721))

### Tooling

- **Enable direct invocation of entry-point scripts** — scripts
  can be called directly without wrapper commands ([GH-732](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/732))
- **Update partner name in marketplace configuration** — align
  marketplace metadata with current branding

### Tests

- **Prevent script permission regressions** — test coverage for
  script file permissions ([GH-731](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/731))

## 0.49.0 — Cross-Context Auditing & Review Coverage

Released 2026-04-06

### Features

- **Ensure reviewers flag new classes without tests** — code
  review agents detect untested new classes ([GH-704](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/704))
- **Enable cross-context query detection in audits** — skill
  audit detects queries spanning multiple contexts ([GH-713](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/713))

### Fixes

- **Resolve plugin install failure from invalid key** — fix
  invalid configuration key blocking plugin installation
  ([GH-723](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/723))
- **Align phase selection spec with Phase I addition** — phase
  selection matches updated phase definitions ([GH-713](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/713))
- **Resolve batch review findings from 6 PRs** — address
  accumulated review findings across multiple PRs ([GH-709](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/709))

### Documentation

- **Document merge_mode and merge_strategy config** — add
  configuration reference for merge behavior options ([GH-707](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/707))
- **Clarify reference file discoverability and template
  guidance** — improve documentation for reference files

## 0.48.0 — Playbook Modes & Merge Safety

Released 2026-04-05

### Features

- **Per-step modes and friction in playbooks** — playbook steps
  can declare execution modes and friction levels independently
  ([GH-712](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/712))

### Fixes

- **Ensure acceptance criteria run before merge** — acceptance
  criteria checks execute before merge gate proceeds ([GH-711](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/711))

## 0.47.0 — Skill Reinforcement & Merge Safety

Released 2026-04-05

### Features

- **PermissionDenied hook corrections** — hooks detect and
  correct permission-denied errors with targeted guidance
  ([GH-705](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/705))
- **Merged PR audit for unaddressed findings** — surface
  unresolved review threads after merge ([GH-699](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/699))
- **Autonomous merge cascade in AFK mode** — unattended
  merge pipelines complete without manual intervention
  ([GH-688](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/688))
- **Session friction level prompt** — prompt users to select
  friction level at session start ([GH-689](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/689))
- **Comprehensive architecture auditing** — architecture
  advisor covers broader design evaluation ([GH-687](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/687))

### Fixes

- **Prevent merging with unaddressed review comments** —
  merge gate blocks when review threads remain open
  ([GH-698](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/698))
- **Prevent false positive on uv shebang hooks** — rule
  engine skips uv shebang lines in script validation
  ([GH-705](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/705))
- **Enable background CI monitor to poll autonomously** —
  CI monitor runs without blocking the session ([GH-695](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/695))
- **Resolve unaddressed PR #691 review findings** — fix
  outstanding review comments from prior PR ([GH-697](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/697))
- **Resolve circular import in rule_engine** — break import
  cycle in Python package structure ([GH-681](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/681))
- **Resolve fanout audit findings** — address audit issues
  in parallel work stream orchestrator ([GH-693](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/693))

### Refactoring

- **Rule-engine commit allowlist** — allowlist-based commit
  validation replaces ad-hoc checks ([GH-705](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/705))
- **Global skill-reinforcement overrides** — skill redirect
  rules configurable at global scope ([GH-705](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/705))

### Tests

- **Ensure Python entry point loadability** — verify all
  CLI entry points import without error ([GH-681](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/681))
- **Ensure Python script entry point loadability** — extend
  entry point tests to skill scripts ([GH-681](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/681))

## 0.46.0 — Architecture Consolidation & Performance

Released 2026-04-04

### Features

- **Unified Python package structure** — all validators, hooks,
  and CLI tools consolidated into `src/dev10x/` package with
  lazy-loading entry point ([GH-588](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/588), [GH-589](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/589))
- **RuleEngine for unified rule evaluation** — single engine
  replaces per-validator rule dispatch ([GH-644](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/644))
- **Typed config loading via Protocol** — config system uses
  Protocol-based contracts for type safety ([GH-650](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/650))
- **Friction-level tiered enforcement** — skill redirect hooks
  support configurable friction levels per command ([GH-530](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/530))
- **Executable acceptance criteria checks** — verify
  definition-of-done criteria programmatically ([GH-640](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/640))
- **Structured decision widgets** — AskUserQuestion gates use
  rich option widgets instead of plain text ([GH-636](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/636))
- **Pre-merge validation gate** — blocking check before merge
  ensures CI and review requirements are met ([GH-635](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/635))
- **On-demand PR review audits** — trigger review audits
  outside the normal PR lifecycle ([GH-551](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/551))
- **Configurable protected branch lists** — per-project
  protected branches without hardcoding ([GH-578](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/578))
- **Permission-aware dispatch in fanout** — parallel work
  streams respect permission boundaries ([GH-562](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/562))
- **Project-level commit gitmoji mapping** — projects can
  override default gitmoji conventions ([GH-585](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/585))
- **Groom skill conflict resolution** — interactive rebase
  handles merge conflicts gracefully ([GH-625](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/625))

### Performance

- **msgpack-cached config loading** — config reads use msgpack
  cache, reducing hook latency ([GH-591](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/591), [GH-652](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/652), [GH-653](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/653))
- **Lazy validator imports** — validators load only when
  needed, cutting startup time ([GH-654](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/654))
- **Startup time regression tests** — benchmark suite prevents
  hook performance regressions ([GH-656](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/656), [GH-657](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/657), [GH-658](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/658))

### Refactoring

- **Domain-driven validator architecture** — validators use
  Protocol conformance, shared GitContext, and reusable domain
  value objects ([GH-648](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/648), [GH-649](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/649), [GH-651](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/651))
- **Unified Rule/Config across all validators** — single Rule
  and Config types replace per-validator duplicates ([GH-645](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/645))
- **Single SQL validation source** — SQL checks consolidated
  into one module ([GH-647](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/647))
- **Domain-driven plan persistence** — plan storage uses
  domain models instead of raw file I/O ([GH-646](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/646))
- **Tell Don't Ask on EditRule** — EditRule encapsulates its
  own decision logic ([GH-643](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/643))
- **First-class skill script packages** — skill scripts are
  proper Python packages with imports ([GH-604](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/604))
- **Isolated tool modules** — Git, GitHub, and utility tools
  split into focused modules ([GH-600](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/600), [GH-601](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/601))
- **Python-based session hook dispatch** — session hooks
  migrate from shell to Python ([GH-598](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/598))
- **CLI-based validators** — Edit/Write and Bash validation
  use Click CLI commands ([GH-594](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/594), [GH-596](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/596), [GH-597](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/597))
- **Unified test directory** — all tests under `tests/`
  mirroring `src/` structure ([GH-595](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/595), [GH-607](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/607))
- **Deterministic test data via fakers** — factory-based
  test data generation ([GH-592](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/592))
- **Deprecated hook scripts removed** — old shell shims
  cleaned up ([GH-610](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/610))

### Fixes

- **Resolve macOS bash 3.2 hook errors** — hooks now work
  on macOS default bash ([GH-661](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/661))
- **Resolve permission-maintenance noise filter gaps** —
  false positive noise in permission audits ([GH-579](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/579))

### Docs

- **Reflect new src/ and tests/ layout** — documentation
  updated to match consolidated structure ([GH-611](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/611))
- **Document TOML vs YAML benchmark decision** — ADR for
  config format choice ([GH-655](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/655))
- **Showcase orchestration and planning in README** —
  feature highlights for new users
- **Coverage reporting in pytest runs** — test output
  includes coverage data ([GH-608](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/608))

### Tests

- **End-to-end validation of refactored plugin** — full
  plugin integration test suite ([GH-612](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/612))
- **Regex compilation benchmarking** — benchmark suite for
  compiled regex patterns ([GH-657](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/657))
- **Hook performance benchmarking** — pytest-benchmark
  integration for hook validators ([GH-656](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/656))

## 0.45.0 — CI Safety & Hook Config

Released 2026-04-01

### Features

- **CI merge-conflict detection** — CI pipeline now detects
  merge conflicts before allowing PR progression ([GH-563](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/563))
- **Safe deterministic transcript analysis** — enable
  transcript analysis with reproducible, safe parsing ([GH-565](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/565))

### Improvements

- **Config-driven hook validation** — all hooks use YAML-driven
  validation instead of hardcoded patterns ([GH-572](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/572))
- **Clarify memory path conventions** — db skill documents
  correct memory file path patterns ([GH-567](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/567))

### Fixes

- **Prevent PR ready with unaddressed findings** — PR cannot
  be marked ready when body-level findings remain ([GH-564](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/564))
- **Detect quoted paths in cd/git-C checks** — noop detection
  handles quoted directory paths correctly ([GH-568](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/568))
- **Remove unused CD_PREFIX_RE pattern** — dead regex cleanup

### Tests

- **Hook rule validation coverage** — ensure allow rules
  permit legitimate skill command invocations ([GH-572](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/572))

## 0.44.0 — MCP Expansion & Hook Hardening

Released 2026-03-31

### Features

- **MCP redirect for gh issue create** — issue creation routes
  through MCP tool instead of raw CLI ([GH-552](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/552))

### Improvements

- **Block direct git-push-safe invocation** — prevent users from
  calling push-safe directly via CLI, redirect to skill wrapper
  with safety guards ([GH-560](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/560))

### Fixes

- **Prevent monitor green during CI run** — monitor no longer
  reports premature success before CI completion ([GH-553](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/553))
- **Unblock commit from non-mktmp temp files** — allow commits
  from temporary files created outside mktmp system ([GH-554](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/554))

## 0.43.0 — Skill Ecosystem & Compliance Hardening

Released 2026-03-30

### Features

- **Competitive multi-agent design exploration** — ADR evaluation
  dispatches domain-specific architect agents in parallel for
  adversarial trade-off analysis ([GH-483](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/483))
- **YAML-driven skill redirect with friction levels** — PreToolUse
  hooks intercept raw CLI commands and redirect to skill wrappers
  with configurable friction ([GH-418](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/418))
- **Automated security review of changes** — reviewer-security
  agent scans diffs for OWASP vulnerabilities and hardcoded
  secrets ([GH-490](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/490))
- **CI-enforced test coverage for servers** — MCP server Python
  code now requires pytest coverage in CI ([GH-493](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/493))
- **Guided discovery for new users** — onboarding skill index
  and MOTD help new users find relevant skills ([GH-488](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/488))
- **Context window optimization** — systematic compaction
  patterns reduce token usage in long sessions ([GH-489](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/489))
- **Per-project model selection for dispatch** — playbook steps
  can override agent model tier per project ([GH-491](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/491))
- **Skill reinforcement for missing commands** — agent detects
  raw CLI usage and redirects to proper skills ([GH-506](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/506))
- **Proactive skill-audit triggers** — audit phase fires
  automatically when session processes 3+ items ([GH-537](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/537))
- **MCP redirect for gh issue view** — issue fetching routes
  through MCP tool instead of raw CLI ([GH-539](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/539))
- **Harden gh-pr-create skill compliance** — PR creation
  enforces all delegation and formatting rules ([GH-533](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/533))

### Improvements

- **Standardize tracker detection via MCP tool** — all skills
  use `detect_tracker` MCP call instead of script ([GH-507](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/507))
- **Reduce scoping wall-clock time** — background exploration
  agents parallelize codebase analysis ([GH-485](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/485))
- **Standardize skill trigger suffixes** — consistent TRIGGER/
  DO NOT TRIGGER patterns across all skills ([GH-484](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/484))
- **Enable standalone invocation of pipeline steps** — skills
  in pipelines can run independently ([GH-487](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/487))
- **Prefer MCP tool for PR context detection** — gh-context
  routes through MCP by default ([GH-534](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/534))
- **Allow inline synthesis when context suffices** — JTBD
  drafting skips full skill when session has rich context
  ([GH-536](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/536))
- **Establish canonical eval schema** — standardized JSON
  format for skill evaluation assertions ([GH-515](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/515))
- **Clarify decision gate assertion naming** — eval patterns
  use consistent signal names ([GH-488](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/488))
- **Prevent uv.lock drift after version bumps** — lock file
  stays in sync with pyproject.toml ([9630a11])

### Bug Fixes

- **Harden fanout and git skill guardrails** — Phase 5 checks
  PR comments, issues use sequential Skill(), MCP push_safe
  promoted, bypassPermissions documented ([GH-549](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/549))
- **Enforce test skill delegation in routing** — test step
  routes through skill wrapper, not raw pytest ([GH-504](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/504))
- **Enforce skill-create delegation in routing** — skill
  creation uses proper skill, not inline logic ([GH-503](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/503))
- **Prevent skill-audit from targeting current session** —
  audit dispatches to separate session context ([GH-508](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/508))
- **Resolve 3 complex skill-audit findings** — mixed
  compliance gaps in multiple skills ([d88ef81])
- **Self-healing for wrong mktmp namespace** — mktmp
  auto-corrects misrouted temp files ([d0acaf4])
- **Block cd+rev-parse chaining in hooks** — PreToolUse
  hook catches compound commands ([GH-528](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/528))
- **Prevent inline audit summary deviation** — audit
  results use structured output, not free text ([GH-531](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/531))
- **Mandate mktmp for commit message temp files** — commit
  skill always uses mktmp for collision-free paths ([GH-532](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/532))
- **Harden scope skill review compliance** — scope skill
  follows all review checklist items ([GH-485](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/485))
- **Resolve checklist numbering conflict** — PR body
  checklist renders correctly ([GH-486](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/486))

### Security

- **Enforce SKILL.md size discipline in reviewer** — reviewer
  flags skills exceeding line budgets ([GH-486](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/486))

### Documentation

- **Surface skill-pipelines in rule index** — pipeline
  composition patterns documented in INDEX.md ([GH-487](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/487))
- **Prevent MCP tool names used as CLI commands** — docs
  clarify MCP names are tool-call primitives only ([GH-535](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/535))
- **Enable prospective users to evaluate Dev10x** — public
  evaluation guide for potential adopters ([GH-492](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/492))

### CI

- **Tighten git commit -F allow pattern** — CI allow rules
  match the mktmp-based commit flow ([GH-418](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/418))

[9630a11]: https://github.com/Dev10x-Guru/dev10x-claude/commit/9630a11
[d88ef81]: https://github.com/Dev10x-Guru/dev10x-claude/commit/d88ef81
[d0acaf4]: https://github.com/Dev10x-Guru/dev10x-claude/commit/d0acaf4

## 0.42.0 — Plan Persistence & Audit Compliance

Released 2026-03-28

### Features

- **Persistent plan tracking across compaction** — task plans
  survive context window compaction via file-backed state
  ([GH-482](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/482))

### Bug Fixes

- **Resolve skill-audit TaskCreate validation failures** —
  audit skill handles missing task fields gracefully ([GH-496](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/496))
- **Ensure audit-report delegates to ticket-create** — report
  filing routes through proper skill wrapper ([GH-498](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/498))
- **Resolve script allow-rule permission friction** — script
  paths match updated plugin directory layout ([GH-499](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/499))
- **Prevent premature merge from SKIPPING checks** — CI
  monitor excludes SKIPPING from pass count ([GH-501](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/501))
- **Prevent inline triage bypass in gh-pr-respond** — all
  comments route through triage before fixup ([GH-502](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/502))
- **Prevent groom step bypass via self-assessment** — groom
  skill always presents strategy gate ([GH-505](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/505))

## 0.41.0 — Orchestration Guardrails & Plan Persistence

Released 2026-03-27

### Features

- **Per-skill model selection for agents** — agent specs and
  skill dispatch choose model tier based on task complexity
  ([GH-470](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/470))
- **Harden work-on orchestration guardrails** — skill routing
  enforcement table survives context compaction ([GH-477](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/477))
- **Plan persistence across compaction** — plans backed by
  files survive context window resets ([GH-414](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/414))

### Improvements

- **Clarify skill docs for nested mode and push** — nested
  invocation exemptions and push safety documented ([GH-475](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/475))

### Bug Fixes

- **Prevent marking PR ready with unaddressed comments** —
  post-CI comment re-check catches late bot reviews ([GH-465](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/465))

### Security

- **Enforce git-commit skill via PreToolUse hook** — raw
  `git commit` blocked; must use Dev10x:git-commit ([GH-473](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/473))

### Tests

- **Ensure dispatcher tests match commit hook rules** —
  test suite validates hook-to-skill routing ([GH-473](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/473))

## 0.40.0 — Delegation Hardening & Fixup Skill Gaps

Released 2026-03-26

### Features

- **Frictionless issue creation from skills** — skills can now
  create GitHub issues without approval prompts ([GH-445](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/445))
- **Strengthen delegation bypass prevention** — skills enforce
  proper delegation chains instead of raw CLI calls ([GH-458](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/458))
- **Resolve gh-pr-fixup skill gaps** — fixup skill now handles
  all edge cases surfaced by audit ([GH-459](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/459))

### Improvements

- **Harden work-on skill against audit regressions** — work-on
  orchestration no longer drifts when audit findings change
  ([GH-448](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/448))
- **Prevent raw command bypass in PR creation** — PR creation
  enforces skill delegation instead of raw `gh pr create`
  ([GH-448](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/448))
- **Prevent delegation bypass in gh-pr-respond** — response skill
  enforces proper triage-then-fixup pipeline ([GH-447](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/447))
- **Prevent premature CI exit in gh-pr-monitor** — monitor waits
  for all checks before declaring success ([GH-447](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/447))
- **Enforce triage delegation for all comment types** — every
  review comment routes through triage before fixup ([GH-463](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/463))
- **Enhance eval signal patterns** — delegation bypass detection
  uses more precise signal matching ([a09a2d6])
- **Clear PR merge policy and consolidation guidance** — document
  when to merge vs. consolidate PRs ([cf14b16])

### Bug Fixes

- **Resolve pr_comment_reply HTTP 422 on integer fields** — MCP
  tool now serialises numeric fields correctly ([GH-447](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/447))
- **Resolve skill audit findings in fixup and respond** — fix
  compliance gaps found during audit ([GH-459](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/459))
- **Prevent false positive unaddressed thread reports** — thread
  status detection no longer flags resolved threads ([GH-464](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/464))

### Documentation

- **Embed asciinema demo in README** — interactive terminal demo
  on the project landing page ([64d4a2e])

[a09a2d6]: https://github.com/Dev10x-Guru/dev10x-claude/commit/a09a2d6
[cf14b16]: https://github.com/Dev10x-Guru/dev10x-claude/commit/cf14b16
[64d4a2e]: https://github.com/Dev10x-Guru/dev10x-claude/commit/64d4a2e

## 0.39.0 — Generic Agents & Permission Hardening

Released 2026-03-25

### Features

- **Generic agent library for any project** — review, testing,
  architecture, and infrastructure agents now ship with the plugin
  for use on any codebase ([57e3830])
- **Quiet mode for update-paths.py** — suppress noisy output when
  running permission path updates ([GH-428](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/428))
- **Allow git reset without permission friction** — reset commands
  no longer trigger unnecessary approval prompts ([GH-441](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/441))

### Improvements

- **Promote review agents to plugin distribution** — domain-specific
  reviewer agents moved from internal to plugin-distributed so all
  users benefit ([23229f3])
- **Rebrand repo from dev10x-ai to Dev10x** — repository name,
  URLs, and marketplace references updated ([#442])
- **Tighten work-on approval gate and routing** — stricter approval
  flow prevents unintended auto-advance past decision gates ([GH-429](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/429))

### Bug Fixes

- **Prevent permission-maintenance bootstrap loop** — break the
  cycle where permission maintenance triggers itself ([GH-426](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/426))
- **Prevent stale permissions after worktree merge** — merged
  worktree rules are cleaned up so they don't cause false
  allow/deny matches ([GH-427](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/427))

### Documentation

- **Prevent misclassification of hook-enabled rules** — clarify
  that allow rules enabling hooks must not be removed even when
  the hook redirects the command ([GH-419](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/419))

[#442]: https://github.com/Dev10x-Guru/dev10x-claude/pull/442
[23229f3]: https://github.com/Dev10x-Guru/dev10x-claude/commit/23229f3
[57e3830]: https://github.com/Dev10x-Guru/dev10x-claude/commit/57e3830

## 0.38.0 — Brave-Labs Rebrand & Version Visibility

Released 2026-03-24

### Features

- **Version visibility in marketplace** — plugin description now
  leads with the installed version (e.g., `v0.38.0`) so users
  can tell at a glance what they're running
- **Automatic version in description** — bumpversion config
  updates both the `version` field and the description prefix
  in plugin.json

### Improvements

- **Repo rename to Brave-Labs** — all URLs, marketplace commands,
  and installation docs updated from `Brave-Labs/dev10x-ai` to
  `Brave-Labs/Dev10x`
- **Skill count update** — README and plugin description now
  reflect 59 skills (was 40)

### Bug Fixes

- **Restore PR comment and review tools** — re-enable
  `pr_comment_reply` and review MCP tools that were
  inadvertently disabled ([GH-422](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/422))

### Documentation

- **Data-driven skill redirect ADR** — propose friction-level
  based redirect system for hook validators ([GH-417](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/417))

## 0.37.0 — Skill Compliance Enforcement

Released 2026-03-24

Agents can no longer bypass skill delegations or use raw CLI
commands where skills exist. A new PreToolUse hook auto-denies
known CLI anti-patterns, SKILL.md enforcement markers prevent
inline handling of sub-skill operations, and a new MCP tool
eliminates the permission friction that incentivized bypasses.

### Features

- **Auto-deny wrong-tool drift** — PreToolUse hook blocks raw
  CLI commands (git commit -m, gh pr create, git push) that
  should go through skill wrappers, while allowing skill-internal
  patterns like -F and --fixup ([GH-397](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/397))
- **Frictionless PR comment replies** — new `pr_comment_reply`
  MCP tool replaces raw `gh api` calls in gh-pr-fixup,
  gh-pr-respond, and gh-pr-triage, removing per-invocation
  Bash permission prompts ([GH-399](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/399))

### Improvements

- **Sub-skill delegation enforcement** — gh-pr-respond gains
  REQUIRED: Skill() markers at all 5 delegation points (triage,
  fixup, groom, push, monitor), plus branch location pre-check
  and stash guard in git-groom ([GH-400](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/400))
- **Review delegation bypass prevention** — gh-pr-respond adds
  negative instruction prohibiting manual fixes; skill-reinforcement
  gains workflow-context checking for delegation bypasses ([GH-401](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/401))
- **Audit-driven skill hardening** — gh-pr-respond, gh-pr-fixup,
  and git-fixup gain mandatory markers for parallel dispatch,
  test gates, and CWD pre-checks based on audit findings ([GH-407](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/407))
- **Eval schema for Skill() assertions** — evaluation schema
  documents Skill() invocation assertion patterns, enabling
  detection of enforcement bypass regressions ([b90c5de])

[b90c5de]: https://github.com/Dev10x-Guru/dev10x-claude/commit/b90c5de

## 0.36.0 — PR Monitor Visibility & MCP Bugfix

Released 2026-03-23

PR monitoring reports full status context, and the MCP
pr_comments tool resolves a parameter mapping bug that
blocked all comment operations.

### Features

- **PR monitor status reporting** — monitor agent surfaces
  CI check details, unhandled review comments, and reviewer
  assignment status instead of completing silently ([GH-392](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/392))

### Bug Fixes

- **pr_comments parameter mapping** — fix `--pr-number` to
  `--pr` in cli_server.py so reply, resolve, and thread
  operations work correctly ([GH-393](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/393))

## 0.35.0 — Orchestration Integrity & Maintenance Skills

Released 2026-03-22

Skill delegation is enforced end-to-end, new maintenance skills
catch memory rot and playbook drift before they cause failures,
and CI deduplication eliminates wasted review runs.

### Features

- **Memory health auditing** — new `Dev10x:memory-maintenance`
  skill detects stale paths, script-calling instructions,
  contradictions, and MEMORY.md index drift ([GH-375](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/375))
- **Playbook drift detection** — new `Dev10x:playbook-maintenance`
  skill compares user overrides against defaults, surfacing new
  steps and prompt changes with severity levels ([GH-366](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/366))
- **Skill-usage reinforcement** — orchestration skill identifies
  CLI commands that should be replaced by dedicated skills or MCP
  tools, with prefix-matched command-to-skill mapping ([GH-384](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/384))
- **Project settings cleanup** — permission-maintenance gains
  Step 6 to strip duplicate, wildcard-covered, and stale rules
  from project settings files ([GH-386](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/386))
- **CI SHA deduplication** — GitHub Actions workflows skip
  redundant runs when a peer workflow already handles the same
  commit SHA ([GH-382](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/382))

### Improvements

- **Skill delegation enforcement** — work-on requires post-step
  Skill() verification and prohibits pipeline collapse during
  fanout execution ([GH-367](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/367))
- **CI re-monitoring after force push** — git-groom and work-on
  mandate `Dev10x:gh-pr-monitor` after any force push to avoid
  stale CI results ([GH-371](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/371))
- **Task reconciliation after delegation** — work-on reconciles
  parent task state after child skill completion, preventing
  orphaned tasks ([GH-376](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/376))
- **Wrong-database prevention** — db-psql requires target database
  comment prefix on manual SQL and sets PGAPPNAME for process
  identification ([GH-363](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/363))
- **Scope-aware fanout parsing** — fanout distinguishes scope URLs
  from specific item URLs, restricting scans to matching commands
  ([GH-351](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/351))
- **Skill routing through compaction** — compaction preservation
  directive keeps routing tables intact across context compression
  ([GH-358](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/358))
- **Unmatched play fallback** — work-on routes unmatched plays to
  the feature play instead of failing, and bans merge operations
  in gh-pr-monitor ([GH-357](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/357))
- **CWD-based worktree detection** — ticket-branch detects
  worktree context from current working directory ([GH-353](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/353))
- **Auto-filing audit findings** — skill-audit findings file
  automatically as GitHub issues ([GH-356](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/356))
- **Nested-mode task exemption** — formalized exemption for
  TaskCreate in nested skill invocations ([GH-355](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/355))

### Bug Fixes

- **Auditor deny-rule overreach** — permission-auditor now uses
  three-tier classification (deny/ask/hook-protected/skip) instead
  of blanket deny recommendations that blocked legitimate skills
  ([GH-385](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/385))
- **Premature completion gate** — work-on completion gate no longer
  fires before all tasks are finished ([GH-354](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/354))
- **Explore agent source failures** — GitHub/JIRA fetch subagents
  switched from Explore to general-purpose to gain Bash access
  ([GH-348](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/348))

## 0.34.0 — Fanout Safety & Skill Consistency

Released 2026-03-21

Fanout delegation is hardened against bypass and wrong-branch
commits, and trigger/skip documentation is standardized across
all skills.

### Bug Fixes

- **Fanout delegation safety** — prevent delegation bypass and
  wrong-branch commits with stricter orchestration guards
  ([GH-345](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/345))

### Improvements

- **Trigger/skip standardization** — consistent trigger and skip
  documentation across all skills, completing the effort started
  in v0.33.0 ([GH-313](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/313))

## 0.33.0 — Orchestration Discipline & Session Resilience

Released 2026-03-21

Fanout enforces structured work-on delegation, session state
survives compaction and restarts, and acceptance criteria
verification becomes a reusable skill.

### Features

- **Session resilience** — pre-compaction hook preserves critical
  context, session state persists across restarts, and skill
  invocation metrics are tracked for audit ([GH-310](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/310)–[GH-317](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/317))
- **Fanout orchestration discipline** — work-on delegation is now
  REQUIRED with enforcement language, per-issue subtask tracking,
  and new Monitor + Audit phases ([GH-338](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/338), [GH-339](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/339))
- **Full shipping pipeline in gh-pr-respond** — post-response
  continuation expanded from groom+push+monitor to the complete
  groom → push → ready → monitor → merge lifecycle with
  solo-maintainer auto-merge support ([GH-338](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/338), [GH-339](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/339))
- **Reusable definition-of-done verification** — extracted
  `Dev10x:verify-acc-dod` skill for consistent acceptance checks
  across work-on, fanout, and future orchestrators ([GH-340](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/340))

### Improvements

- **Task tracking in DDD and permission-maintenance** — both skills
  gain TaskCreate/TaskUpdate orchestration for supervisor visibility
  ([GH-41](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/41))
- **Statusline enrichment** — branch name and worktree context shown
  in terminal statusline ([GH-312](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/312))
- **Skill scaffolding** — `Dev10x:skill-create` generates directory
  structure with scripts via `scaffold.sh` ([GH-314](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/314))
- **Plugin health verification** — install and verify scripts validate
  plugin structure after updates ([GH-315](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/315))
- **Marketplace metadata** — enriched `marketplace.json` for better
  plugin discovery ([GH-317](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/317))
- **Trigger/skip standardization** — consistent trigger and skip
  documentation across 13+ skills ([GH-313](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/313))

## 0.32.0 — Permission Friction & Review Hardening

Released 2026-03-20

Permission friction eliminated across skill-audit, project-scope, and
py-uv skills. Code review agents gain stricter verification checks,
and work-on enforces playbook verification before plan generation.

### Features

- **Playbook verification in work-on** — Phase 3 now requires reading
  and verifying a playbook file before generating tasks, preventing
  ad-hoc plan generation that skips configured steps ([GH-308](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/308))
- **GitHub async timing checks** — code review agents detect stale
  `gh pr checks` results after force-pushes by verifying check count
  against expected baselines ([GH-318](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/318))
- **Table/implementation skew detection** — code review agents flag
  documentation tables that diverge from actual implementation

### Improvements

- **Reduced permission friction** — normalized `scripts/:*` to
  `scripts/*:*` across all `allowed-tools` declarations in skill-audit,
  py-uv, skill-create, and codex-skills equivalents ([GH-321](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/321))
- **Smarter sensitive file hook** — `block-sensitive-file-write.py` now
  uses basename matching instead of substring, eliminating false
  positives on sidecar metadata files like `.vars` ([GH-322](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/322))
- **Project-scope anti-patterns** — documented command substitution and
  env var prefix friction patterns to avoid in `gh` commands, switched
  sidecar files from `.env` to `.vars` ([GH-322](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/322))
- **Autosquash alias prefix** — `env` command prefix added to
  `GIT_SEQUENCE_EDITOR=true` in autosquash aliases for consistent
  shell expansion ([GH-319](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/319))
- **Skill name normalization** — Dev10x skill names normalized across
  documentation and scripts for consistency
- **Semicolon false positive fix** — SQL safety hook no longer blocks
  semicolons inside string literals like `STRING_AGG(name, '; ')`
  ([GH-320](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/320))

### Bug Fixes

- **Skill-audit permission prompt** — `extract-session.sh` no longer
  triggers approval prompts on every invocation due to mismatched
  `allowed-tools` glob pattern ([GH-321](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/321))

### Documentation

- **Updated skill pattern references** — all `scripts/:*` documentation
  examples updated to `scripts/*:*` across skill-audit, skill-create,
  and their codex-skills equivalents ([GH-309](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/309))

## 0.31.0 — MCP Consolidation & Parallel Workflows

Released 2026-03-20

MCP servers consolidate from 4 to 2, PR creation runs through native
MCP tools, macOS Keychain credentials land, and work-on gains parallel
stream processing with context compaction.

### Features

- **MCP tools for PR creation** — 6 gh-pr-create scripts and pr-notify
  wrapped as 7 MCP tools in gh_server.py, enabling dual-path transition
  with existing Bash paths ([GH-191](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/191))
- **Universal branch aliases** — git log, diff, rebase, and autosquash
  aliases now support main and master alongside existing develop,
  development, and trunk variants ([GH-288](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/288))
- **Non-destructive CTE in db queries** — db hook allows WITH clauses
  that don't modify data, unblocking analytical queries ([GH-303](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/303))
- **Slack thread investigation** — new plugin skill investigates Slack
  bug reports, root-causes in codebase, and creates Linear tickets
  ([#298])
- **Guided Slack integration setup** — interactive skill walks through
  Slack app creation, token configuration, and channel setup ([GH-14](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/14))
- **macOS Keychain credential retrieval** — secrets can be stored and
  retrieved via macOS Keychain as an alternative to env vars ([GH-119](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/119))

### Improvements

- **MCP server consolidation** — reduced from 4 servers to 2 (cli →
  git + utils, gh stays), cutting startup overhead ([GH-194](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/194))
- **Parallel work stream processing** — work-on dispatches independent
  tasks concurrently instead of sequentially ([#301])
- **Context compaction in orchestration** — skills compact context at
  phase boundaries to stay within token limits ([#299])
- **Work-on audit enforcement** — audit findings from GH-295, GH-296,
  GH-297 enforced as playbook and eval updates ([#300])
- **False positive prevention** — shared code patterns (MCP imports,
  PEP 723 inlining) no longer trigger review warnings ([#294])
- **Broader permission maintenance** — permission update workflow
  covers more path patterns and project configurations
- **Playbook pattern documentation** — reviewer guidance for validating
  playbook-powered skills and reference file patterns ([#243])
- **External tool declaration requirements** — skill authors must
  declare all external tool dependencies in SKILL.md front matter
  ([#270])
- **Invocation-name enforcement** — reviewer checklist enforces
  mandatory invocation-name field with exact-match rule ([#267])

### Testing

- **Automated hook testing** — pytest CI pipeline validates hook
  scripts with unit tests ([GH-214](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/214))
- **CI concurrency groups** — prevent duplicate CI runs on rapid
  pushes to the same branch ([GH-214](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/214))

### Bug Fixes

- **Non-interactive autosquash** — autosquash aliases wrap
  GIT_SEQUENCE_EDITOR=true to avoid escaping issues that broke alias
  expansion ([GH-288](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/288))

## 0.30.0 — Disciplined Orchestration

Released 2026-03-19

Work-on orchestration gets guardrails — mechanical plan generation,
mandatory phase tasks, and supervisor sign-off prevent shortcuts.
Git-domain skills gain MCP tool access, session skills get aligned
names, and script-path leaks are eliminated across the tooling surface.

### Features

- **MCP tool access for git skills** — git-domain skills can call MCP
  tools directly instead of shelling out via Bash wrappers ([GH-192](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/192))
- **Permission management skill** — base permission management enables
  structured allow/deny rule handling ([GH-274](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/274))
- **Slack file cleanup** — cleanup Slack config files and prompt for
  missing configuration ([GH-271](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/271))
- **Goodbye message** — session exit shows a resume command so users can
  pick up where they left off ([GH-272](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/272))
- **Block `$(cat ...)` substitution** — hook blocks command substitution
  via `cat` to prevent file content leaks in shell commands ([GH-277](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/277))

### Improvements

- **Aligned session skill names** — 11 session skills get consistent
  `Dev10x:` prefixed invocation names ([GH-224](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/224), [GH-102](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/102))
- **Script-path leak elimination** — skill tooling no longer leaks
  resolved cache paths in allowed-tools or Bash calls ([GH-280](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/280),
  [GH-275](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/275), [GH-283](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/283))
- **Destructive git commands ADR** — documented the decision to block
  destructive git operations by default ([GH-269](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/269))
- **Orchestration guardrail evals** — eval assertions enforce Phase 3
  mechanical planning and supervisor sign-off ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248), [GH-273](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/273))

### Bug Fixes

- **Supervisor sign-off required** — plan completion gate now requires
  explicit supervisor confirmation instead of auto-completing ([GH-273](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/273))
- **Natural language plan mapping** — phrases like "show me the plan"
  route to AskUserQuestion gate, not plan mode ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248))
- **Mechanical Phase 3** — plan generation enforces 1:1 task-to-step
  mapping from playbook, preventing step collapsing ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248), [GH-273](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/273))
- **Phase task verification** — Phase 2 blocked until all 4 phase tasks
  are confirmed to exist ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248))
- **ExitPlanMode prohibition** — work-on sessions cannot use Claude
  Code's built-in plan mode, preserving task tracking ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248))
- **MCP-aware subagent routing** — Phase 2 fetches requiring MCP tools
  (Linear, Slack, Sentry) route to general-purpose agents, not Explore
  agents which lack MCP access ([GH-155](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/155))

## 0.29.0 — Smoother Shipping

Released 2026-03-16

Worktrees handle Husky v4 and Yarn Berry correctly, fish shell stops
breaking GraphQL queries, and delegated skills skip redundant task
tracking for faster unattended execution.

### Improvements

- **Unattended PR creation** — gh-pr-create supports `--unattended` flag
  with documented detection conditions and gate bypass rules ([GH-263](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/263))
- **Delegated skills skip TaskCreate** — skills invoked as subtasks of a
  parent orchestrator skip internal task tracking, reducing noise ([GH-258](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/258))
- **Body-only review handling** — gh-pr-respond Mode B handles reviews with
  body text but no inline comments, common from CI bots ([GH-258](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/258))
- **Non-skippable monitor output** — gh-pr-monitor Step 4 marked as
  non-skippable so users always see background agent progress ([GH-259](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/259))
- **Reduced work-on friction** — workspace detection extracted to script,
  implicit plan approval when user provides a complete plan ([GH-253](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/253))
- **Friction-free grooming** — raw GIT_SEQUENCE_EDITOR rebase replaced with
  git autosquash-develop alias to avoid env-prefix permission friction ([GH-253](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/253))

### Bug Fixes

- **Husky v4 and Yarn Berry in worktrees** — detect Husky version, bootstrap
  ~/.huskyrc for v4, use version-aware yarn install flags ([GH-222](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/222))
- **Fish shell GraphQL compatibility** — convert GraphQL examples to
  double-quoted with escaped `$` to prevent fish interpolation ([GH-258](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/258))

## 0.28.0 — Conflict-Free PRs

Released 2026-03-16

PRs now auto-detect and resolve merge conflicts before they reach reviewers.
MCP servers start reliably, and jq queries no longer trigger false-positive
obfuscation blocks.

### Improvements

- **Conflict-free PRs** — PR creation and monitoring detect merge conflicts
  via `git merge-tree` and GitHub's mergeable API, with auto-rebase +
  force-with-lease resolution ([GH-261](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/261))
- **Consistent skill naming** — 9 skills get proper `Dev10x:` invocation
  names with documented branding rationale ([GH-234](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/234))
- **Friction-free issue status checks** — jq concatenation pattern replaces
  interpolation to avoid obfuscation detection ([GH-260](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/260))
- **Full changelog** — all 22 releases (v0.2.0–v0.27.0) documented with
  themed headlines and linked issue references
- **MCP server permission review checks** — reviewer-infra now explicitly
  requires `+x` on server scripts

### Bug Fixes

- **MCP server startup** — 3 server scripts (db, gh, git) were missing
  execute permissions, causing "Permission denied" on startup

## 0.27.0 — Self-Healing Code Review

Released 2026-03-15

The shipping pipeline now fixes its own review findings autonomously.
Also: GitHub Issues support in project-scope and auto-approval for safe
subshell commands.

### Features

- **Self-healing code review** — work-on shipping pipeline now dispatches
  `Dev10x:review` + `Dev10x:review-fix` to autonomously create fixup commits
  for review findings ([GH-252](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/252))
- **Full task visibility in unattended mode** — git-commit and gh-pr-create
  create all startup tasks regardless of mode; auto-skipped tasks are
  immediately marked completed with reason ([GH-251](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/251))
- **GitHub Issues in project-scope** — Phase 3 Tracker Dispatch now supports
  GitHub Issues alongside Linear and JIRA, with batch creation pattern for
  10+ issues ([GH-244](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/244))
- **Auto-approval for safe subshells** — new `HookAllow` result type lets
  read-only subshell commands like `basename "$(git rev-parse ...)"` pass
  without permission prompts ([GH-247](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/247))
- **Worktree permission merging** — merge allow rules accumulated in worktree
  sessions back into the main project settings
- **Batch plugin permission updates** — auto-detect latest plugin version
  and update stale versioned paths across all projects in one pass

### Bug Fixes

- Prevent path errors when CWD drifts during session ([GH-251](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/251))

## 0.26.0 — Release Notes as a Skill

Released 2026-03-15

Track what you ship with playbook-powered release notes — configurable
ticket patterns, output targets (stdout/GitHub/Slack), and release/hotfix
plays.

### Features

- **Release notes skill** — generic, playbook-powered release notes generation
  with configurable ticket patterns, output targets (stdout/GitHub/Slack),
  and release/hotfix plays

## 0.25.0 — Unattended Shipping

Released 2026-03-15

Skills can now commit, format, and ship without human intervention.
Playbook fragments eliminate duplication, unattended git-commit bypasses
all interactive gates, and ruff formatting runs automatically on every
Python edit.

### Features

- **Reusable playbook fragments** — extract shared step sequences (like the
  9-step shipping pipeline) into named fragments, reducing duplication from
  36 of 55 steps across 4 plays ([GH-232](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/232))
- **Unattended git-commit** — when invoked by an orchestrating skill with
  an active task list, all interactive gates are bypassed: auto-stage,
  auto-select commit type, auto-generate problem/solution ([GH-237](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/237))
- **Automated ruff formatting** — PostToolUse hook runs `ruff format` +
  `ruff check --fix` on every Python file edit ([GH-231](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/231))
- **Post-response shipping continuation** — gh-pr-respond now offers to
  groom, push, and monitor CI after fixup commits ([GH-225](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/225))
- **Redundant command detection** — hook blocks `git -C <path>` when CWD
  already matches, and `cd <cwd> && ...` noop chains ([GH-225](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/225))
- **Respond playbook comment hiding** — gh-pr-respond can hide obsolete
  review comments after addressing them ([GH-226](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/226))
- **uv-managed test execution** — pyproject.toml with pytest/ruff dev deps
  so `uv run pytest` works without extra flags ([GH-225](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/225))

### Bug Fixes

- **Skill-audit enforcement gaps** — AskUserQuestion rule extended to global
  scope, Linear API fallback for non-autolinked prefixes ([GH-227](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/227))
- Ensure release script stages pyproject.toml after bump

## 0.24.0 — Auto-Advance Pipeline

Released 2026-03-14

The shipping pipeline no longer blocks on preview approval. Commits and
draft PR creation proceed automatically with a code-reviewer agent step.

### Features

- **Auto-advance shipping pipeline** — commits and draft PR creation proceed
  without blocking on preview approval, with code-reviewer agent step ([GH-213](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/213))
- Community link added to README

## 0.23.0 — Domain-Driven Design Workshops

Released 2026-03-12

Explore and model domain architecture with Event Storming directly from
Claude Code sessions.

### Features

- **DDD workshop skill** — bootstrap Domain-Driven Design Event Storming
  workshops for domain exploration and modeling ([GH-219](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/219))

### Bug Fixes

- Declare missing `allowed-tools` in 6 skills to eliminate per-invocation
  approval prompts ([GH-70](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/70))

## 0.22.0 — Playbook Architecture

Released 2026-03-12

The biggest architectural release to date. Work plans become reusable,
customizable playbooks. The hook dispatcher consolidates 7 processes into
one with ~80% overhead reduction. User-space config overrides ship.

### Features

- **Playbook architecture** — generalize work plans into reusable,
  customizable playbooks with convention-based discovery. Any orchestration
  skill can become playbook-powered by adding `references/playbook.yaml`.
  User overrides stored per-skill in memory ([GH-209](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/209))
- **Guided work plan customization** — dedicated `Dev10x:work-plan` skill
  with list, view, edit, and reset subcommands ([GH-209](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/209))
- **Per-project work plan customization** — projects can override plan
  templates without modifying plugin source ([GH-140](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/140))
- **Consolidated hook dispatcher** — replace 7 separate hook processes
  with one unified Python dispatcher using a validator registry.
  ~80-85% hook overhead reduction ([GH-208](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/208))
- **User-space config overrides** — `~/.claude/skill-index/` for
  `families.yaml` and `hidden.yaml` without modifying plugin source ([GH-10](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/10))
- **Alias enforcement** — block raw `git` commands with env-var prefixes
  or `$(git merge-base ...)` subshells when aliases exist ([GH-200](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/200))
- **Automated issue closing** — GitHub Actions workflow parses `Fixes:` URLs
  from merged PR bodies and closes referenced issues ([GH-209](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/209))

### Refactoring

- Split reviewer-skill into structure and behavior specs
- Trim CLAUDE.md to stay within 100-line budget
- Prefer jq and yq over manual JSON/YAML parsing ([GH-196](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/196))

## 0.21.0 — One-Command Review Requests

Released 2026-03-11

Assign GitHub reviewers and notify Slack in a single skill invocation.
PR creation now works in repos without a develop branch.

### Features

- **Combined review request skill** — `Dev10x:request-review` assigns
  GitHub reviewers and posts Slack notification in one command ([GH-188](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/188))
- **PR creation without develop** — gh-pr-create works in repos that
  use main as their only branch ([GH-180](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/180))
- **Prevent WIP in worktrees** — new worktrees no longer inherit
  uncommitted changes from the parent branch
- **Dynamic base branch validation** — hook validates PR target branch
  at creation time ([GH-187](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/187))

### Bug Fixes

- Prevent silent project linkage failures in Linear ([GH-153](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/153))

## 0.20.0 — Reliable Skill Orchestration

Released 2026-03-09

Numbered lists replace code blocks across 39 skills so decision gates and
orchestration steps actually fire instead of being skipped as examples.

### Features

- **Bundled call spec pattern** — complex tool call specifications live
  in `tool-calls/` sidecar files, referenced from SKILL.md enforcement
  markers ([GH-179](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/179))
- **Numbered list enforcement** — 39 skills updated to use numbered lists
  (not code blocks) for mandatory TaskCreate/AskUserQuestion calls ([GH-179](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/179))
- Centralize rules documentation into INDEX.md

## 0.19.0 — MCP Tools & Project Scoping

Released 2026-03-08

Native MCP server tools replace fragile Bash wrappers. Multi-ticket
projects get first-class scoping with Linear, JIRA, and GitHub Issues.
Dozens of enforcement fixes improve skill reliability.

### Features

- **MCP tools** — GitHub, Git, and Database operations exposed as MCP
  server tools, replacing fragile Bash-based wrappers ([GH-126](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/126))
- **Project-scope skill** — scaffold multi-ticket projects with milestones,
  blocking relationships, and tracker integration. Supports Linear, JIRA,
  and GitHub Issues ([GH-154](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/154))
- **Skill eval criteria** — measurable quality gates for skill behavior,
  enabling automated detection of decision gate violations ([GH-133](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/133))
- **Auto-resolved PR reviewers** — GitHub team reviewers resolved
  automatically from CODEOWNERS ([GH-118](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/118))
- **Temp file MCP tool** — `mktmp` tool prevents temp file collisions
  across concurrent sessions ([GH-143](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/143))
- **Upstream issue filing from audits** — skill-audit findings can be
  filed as GitHub issues at the plugin repo ([GH-135](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/135))
- **Parallel subagent dispatch** — skill-audit runs analysis phases
  concurrently ([GH-131](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/131))
- **Pre-approved tool access** — 17 skills declare `allowed-tools`
  to eliminate per-invocation approval prompts ([GH-70](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/70))

### Bug Fixes

- Enforce AskUserQuestion at all decision gates ([GH-133](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/133), [GH-151](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/151))
- Enforce TaskCreate orchestration at startup ([GH-134](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/134))
- Prevent Write tool error in commit workflow ([GH-126](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/126))
- Prevent GIT_SEQUENCE_EDITOR permission friction ([GH-121](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/121))
- Exclude .claude/worktrees/ from hook copies ([GH-144](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/144))
- Allow bare fixup commits from humans ([GH-159](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/159))

## 0.18.0 — Documentation

Released 2026-03-07

Updated README with installation instructions.

## 0.17.0 — Task Orchestration Everywhere

Released 2026-03-07

Every skill now tracks progress with structured tasks. Orchestration
patterns (auto-advance, batched decisions, tier-based complexity)
retrofitted across the entire skill catalog.

### Features

- **Task orchestration framework** — define patterns for task tracking,
  auto-advance, batched decisions, and tier-based complexity across all
  skills
- **Mandatory task tracking** — every skill now creates startup tasks
  and updates them as phases complete
- Retrofit orchestration into 4 flagship skills, Tier Full, Tier Standard,
  and PR lifecycle skills

## 0.16.0 — Documentation

Released 2026-03-06

Document external tool dependencies in README.

## 0.15.0 — Cross-Platform Skills

Released 2026-03-06

Skills now work in OpenAI Codex alongside Claude Code via a compatible
skill pack and install tooling.

### Features

- **Codex-compatible skill pack** — install tooling for OpenAI Codex
  environments alongside Claude Code
- Fix local type and test discovery for mirrored skills

### Self-Improving Review System

- Clarify PR title gitmoji mapping and JTBD third-party variants
- Clarify self-motivated work conventions

## 0.14.0 — The Great Consolidation

Released 2026-03-05

11 sub-plugins merged into one unified Dev10x plugin with a consistent
`Dev10x:` namespace and cross-script compatible directory resolution.

### Refactoring

- **Single plugin consolidation** — merge 11 separate plugin directories
  into one unified Dev10x plugin with consistent `Dev10x:` namespace
- Refactor directory resolution for cross-script compatibility
- Remove unused session-start-git-aliases hook
- Clarify hook-blocked and advisory patterns in session guidance

## 0.13.0 — Convention Polish

Released 2026-03-04

Surface @mentions at start of Slack review messages and establish
conventions for agent directories and skill naming.

### Refactoring

- Surface @mentions at start of Slack review messages
- Establish conventions for agent directories and skill naming

## 0.12.0 — Namespace Unification

Released 2026-03-04

Every skill gets the `Dev10x:` prefix. Skills are isolated into 11
domain-specific sub-plugins with distributed hooks and marketplace
discovery.

### Refactoring

- **Namespace unification** — standardize all skill invocation names
  from mixed `dx:`, `ticket:`, `pr:`, `qa:` prefixes to `Dev10x:`
- **Multi-plugin architecture** — isolate skills into 11 domain-specific
  sub-plugins (fundamentals, git, gh, db, tickets, sessions, parking,
  py, skills, slack, qa) with distributed hooks
- Enable marketplace to discover all sub-plugins

## 0.11.0 — Permission Auditing

Released 2026-03-04

Systematically audit Claude Code permission settings for security gaps.
Config-driven Slack notifications and dual-format skill index also ship.

### Features

- **Permission security auditing** — systematic audit agent for
  Claude Code permission settings
- **Config-driven Slack notifications** — per-project Slack channel
  and mention configuration for review requests
- **Dual-format skill index** — MOTD and SKILLS.md output formats
  with proper `Dev10x:` invocation prefixes
- Use Haiku model in GitHub Actions for faster CI

### Refactoring

- Delegate Slack and reviewer steps from pr-monitor to dedicated skills
- Stabilize test suite with proper dependencies

## 0.10.0 — Database Access & Session Guidance

Released 2026-03-03

Safe database querying with SQL validation hooks and intelligent
session-start recommendations. Family-grouped skill index and acceptance
criteria verification round out the release.

### Features

- **Database querying** — safe, customizable database access via plugin
  with SQL validation hooks
- **Family-grouped skill index** — adaptive-density display with YAML
  config for families and hidden skills
- **Acceptance criteria verification** — work-on checks criteria before
  shipping ([GH-86](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/86))
- **Session guidance** — surface wrapper discovery and git alias
  recommendations at session start ([GH-87](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/87))
- **Slack review readability** — improved formatting ([GH-54](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/54))
- Preserve plugin permissions across upgrades ([GH-79](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/79))

### Bug Fixes

- Detect `postgresql://` scheme in SQL safety hook
- Detect `psql` in chained commands
- Stabilize mktmp.sh and groom script paths

## 0.9.0 — Release Stability

Released 2026-03-02

Prevent version number skipping in releases.

### Bug Fixes

- Prevent version number skipping in releases

## 0.6.0 — Ticket Management & QA Automation

Released 2026-03-02

Full ticket lifecycle from branch creation to technical scoping. QA test
execution as a portable plugin skill. Context-aware rule loading reduces
always-loaded token overhead.

### Features

- **Ticket management suite** — branch creation, ticket creation, JTBD
  story write-back, and technical scoping for Linear tickets
- **QA automation** — portable plugin skills for QA test execution
- **ADR creation** — Architecture Decision Records as a plugin skill
- **Context-aware rule loading** — reduce always-loaded rules by scoping
  them to relevant file patterns ([GH-68](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/68))
- **Obsolete review summary hiding** — automatically hide stale PR review
  summaries in interactive and CI modes ([GH-44](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/44))
- **User task injection** — inject tasks during work-on execution ([GH-59](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/59))
- **Temp file collision prevention** — namespace-based temp files ([GH-19](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/19))
- **Workspace-agnostic Slack** — notifications work from any directory
- **Reusable technical scoping** — base scoping workflow for tickets and ADRs

### Bug Fixes

- Prevent review workflow self-cancellation

## 0.4.0 — Cleanup

Released 2026-03-02

Remove obsolete docs plans.

## 0.2.0 — Genesis

Released 2026-03-02

Initial release with 40+ skills covering the full development lifecycle
in a single plugin.

### Features

- **Plugin scaffold** — manifest, marketplace installation, semver releases
- **Session management** — task tracking, skill-usage audit, session wrap-up,
  MOTD with available skills
- **Work orchestration** — task-list-driven `work-on` skill with acceptance
  criteria verification
- **Git workflow** — safe rebase/force-push with branch protection, structured
  commits, atomic commit splitting, branch history grooming, retroactive
  ticket tracking, scoped fixup commits, git alias detection
- **PR lifecycle** — automated PR creation with JTBD stories, autonomous
  monitoring, review requests, comment response orchestration, comment
  triage/validation, session bookmarking, inline review findings, fixup
  commits from review comments
- **Parking/deferral** — code-level deferrals, smart routing, Slack DM
  reminders, cross-source discovery
- **JTBD drafting** — reusable Job Story generation for consistent business
  narratives
- **Worktrees** — isolated worktrees with IDE-safe branch separation,
  dual-mode creation
- **Linear integration** — MCP operations reference without tool duplication
- **Skill authoring** — creation without permission friction, templates,
  JTBD guidance
- **Plugin-distributed hooks** — safety and quality hooks shipped with
  the plugin
- **Self-executing Python** — UV-based script execution ([GH-17](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/17))
- **Self-improving review system** — lessons from PR reviews automatically
  strengthen review checks

---

[#243]: https://github.com/Dev10x-Guru/dev10x-claude/pull/243
[#267]: https://github.com/Dev10x-Guru/dev10x-claude/pull/267
[#270]: https://github.com/Dev10x-Guru/dev10x-claude/pull/270
