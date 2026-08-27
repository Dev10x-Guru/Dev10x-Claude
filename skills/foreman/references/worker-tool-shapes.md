# Why the crew template pins specific tool shapes

The evidence behind the verbatim lines in
[`crew-prompt-template.md`](crew-prompt-template.md) § 2 and § 5.

The template itself carries only what a worker receives word-for-word;
it is far over its size budget already, so the reasoning lives here.
Each rule below is a worker death, not a style preference — and each
failed the same way, which is the part worth internalising: **a wedged
worker leaves no trace.** A pending permission prompt is neither a
block nor a denial, so it records nothing in the hook log. The only
signal is silence, and silence is what the stall detector reads last.

## `find` → the Glob tool (GH-1059)

Two sonnet workers froze simultaneously on the same shape — a Bash
`find` over a SvelteKit route group, whose path segments carry
shell-escaped parentheses:

```
find …/routes/\(app\)/class-health/\[classId\]/print -type f
```

Both went silent for 25–35+ minutes with no heartbeat. A respawned
gen-3 worker, told "use the Glob tool, never Bash `find`", cleared the
identical step immediately.

Note what the older `find-search` validator patterns missed: they keyed
on `-name` / `-path` / `-exec`, and this command has none of them. A
plain `find <path> -type f` looked innocuous right up until the escaped
parens matched no allow rule. The patterns were widened in the same
change that added this rule.

**The diagnostic lesson generalises.** When two workers die at the same
command shape, that is a tool-layer defect, not a monitoring-cadence
problem. The corrective respawn must name the substitution; a
replacement handed the same shape wedges the same way. See
[`stall-protocol.md`](stall-protocol.md) § Structural false positives.

## `pre-commit` → whatever Phase 0.4 proved (GH-1066)

`{{lint_shape}}` is a placeholder precisely because there is no
universal answer.

The validate-bash hook denies `uv run --directory <worktree>
pre-commit …` and advises "pre-commit is installed on PATH — run
pre-commit directly". For a main session that steer is correct. For an
`Agent`-spawned subagent it is actively wrong: Bash CWD resets to the
dispatcher's directory on every call (GH-1028), so a bare `pre-commit`
resolves the git repo from the wrong worktree and lints a tree the
worker never touched — silently, and green.

The `--directory` form is now exempted from that block, because there
the `uv` wrapper is pinning CWD rather than shifting an env prefix. But
the shape still has to be proven for the night, or lint declared
CI-only, at Phase 0.4. Otherwise every run rediscovers it at 02:00 —
which is what the 2026-08-23 run did, settling on CI-only lint for the
whole night (run decision D4).

## Web build/check shapes → `run_node_tests(script=…)` (GH-1052)

`run_node_tests` was originally read as a *test* wrapper, so the crew
template named only test invocations and workers reached for the Bash
layer for everything else. But GH-1029 gave the tool a `script=`
parameter: any `package.json` script runs through it, which makes
`pnpm run build`, `pnpm run check:*`, a bare `vite`, and
`node <script>` wrapper-reachable too.

2026-08-19 night run: crew worker B2 (opus) posted the heartbeat "pnpm
deps installed; starting SvelteKit UI" at 10:11Z, then made zero tool
calls and zero file writes for 80+ minutes. The exact command is
unrecoverable — a *pending* prompt records nothing, which is the same
no-trace signature as the `find` and `pre-commit` deaths above — but
the timing puts it on a web-tooling shape immediately after deps
install. Its replacement, briefed to route ALL web tooling through
`run_node_tests(script="build" / "check:i18n" / "check:plurals")`,
delivered the chunk cleanly: 1035 vitest tests, the build, and both
i18n gates, with zero prompts.

Two shape rules the wrapper enforces, worth stating in the brief:

- Only `yarn`/`npm`/`pnpm` resolve a script name. `jest`/`vitest` are
  invoked directly through `npx` and have no script table, so pairing
  `script=` with them returns an error rather than silently ignoring it.
- `env=` is overlaid on the inherited environment, not substituted for
  it — the escape hatch for a script whose definition pins something
  the wrapper would otherwise drop, such as a `TZ` that snapshot tests
  depend on.

The `node-build-scripts` entry in `command-skill-map.yaml` carries the
same steer for sessions outside a foreman run. It is advisory, not
blocking: hard-blocking a web-tooling shape would strand an unattended
worker exactly the way the unanswered prompt did.

## Re-running the `ToolSearch` bootstrap (GH-1063)

The bootstrap does not hold for a worker's whole life. Three
independent crew workers lost their Dev10x MCP surface after 60–90+
minutes: `create_pr` and `push_safe` became unreachable on tools they
had already loaded and already used.

Two of the three had pushed their work and lost only the final
PR/verify step. The third wedged pre-PR with a branch on origin and no
PR, and needed a fresh-spawn takeover to finish a chunk that was
substantively done.

Hence the retry line. It is a mitigation, not a fix — reconnect-on-demand
belongs in the wrapper layer and is tracked separately (GH-1072). What
the retry buys is preventing the worse failure: a worker that reads
"tool not found" as "this operation is impossible" improvises raw CLI
for a gated operation, which is exactly what the tool-surface split
exists to prevent. Full evidence:
[`tool-surface.md`](tool-surface.md) § MCP connectivity is not
permanent.
