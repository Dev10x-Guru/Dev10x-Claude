# Evaluation — rtk (rtk-ai/rtk) support

GH-1640 asked to evaluate "support for https://github.com/rtk-ai/rtk"
and gave no further description. This is the written finding. It is
not code.

## Decision

**Do not integrate rtk into Dev10x, and do not ship any rtk-specific
code or permission rules.** Document coexistence for users who install
it themselves (below), and reopen only with a measured saving on a real
Dev10x session.

## What rtk is

A single Rust binary that sits in front of shell commands and
compresses their output before it reaches the model's context. The
project claims 60–90% fewer tokens on common dev commands, across 100+
commands (git, gh, cargo, npm/pnpm, jest/vitest, ruff, pytest, mypy,
docker, kubectl, …), with under 10 ms overhead.

For Claude Code, `rtk init -g` installs a **PreToolUse hook** that
rewrites Bash commands — `git status` becomes `rtk git status` — so the
agent gets compact output without calling `rtk` itself. The hook fires
on Bash only; Read, Grep and Glob are not intercepted.

Licensing is mixed: the CLI is Apache-2.0, while `rtk-engine` and the
optional `rtk-proxy` daemon are BUSL-1.1, and an Apache-only `rtk-oss`
edition omits the engine. The repository is very active (about 85k
stars, ~920 open issues, ~720 open PRs as of 2026-10-31).

Source: the project README. Its savings figure measures Bash output
bytes ÷ 4, not the bill — the README says so itself.

## Why not integrate

1. **Dev10x already keeps its noisy commands off the Bash layer.** The
   commands rtk compresses best — `gh pr view`, `gh pr checks`,
   `pytest`, `jest` — are routed to MCP tools (`pr_get`,
   `ci_check_status`, `run_tests`, `run_node_tests`) by the
   skill-redirect hook. Those return structured, already-summarized
   payloads and never pass through a Bash PreToolUse hook, so rtk never
   sees them. The remaining Bash traffic in a Dev10x session is mostly
   short `git` calls whose output is already small.

2. **A command-rewriting hook collides with how Dev10x permissions
   work.** Allow rules and the DX001–DX017 validator chain match the
   command string's prefix (`.claude/rules/hook-patterns.md`). A hook
   that turns `git status` into `rtk git status` is the same class of
   prefix shift Dev10x already blocks for env-var prefixes and `&&`
   chains. Plugin hooks run in parallel with no defined order (GH-1556),
   so whether Dev10x's validators see the original or the rewritten
   command is not something either side controls. [Verify] which input
   Claude Code evaluates allow rules against when one hook rewrites a
   command — it is not documented in rtk's README.

3. **Shipping it would put a BUSL component in the default path.** The
   engine's licence restricts offering it to third parties as a
   product; Dev10x is distributed to other users. Recommending the
   Apache `rtk-oss` edition avoids that, but it also drops the part
   that does the compressing.

4. **Nothing measured asks for it.** Token pressure in Dev10x sessions
   comes from skill bodies, playbooks and subagent transcripts — the
   problems the skill-body extraction rules and GH-1627 address — not
   from Bash output.

## If a user installs rtk anyway

- Run `rtk init -g --dry-run` first and read what it writes to Claude
  Code's settings before applying it.
- Expect allow rules keyed on `Bash(git …:*)` to stop matching a
  rewritten `rtk git …` command, which means new permission prompts.
  Do not answer them with a broad `Bash(rtk:*)` allow: it pre-approves
  every command rtk can wrap, which would void DX001–DX017 for those
  commands.
- `rtk bypass <cmd>` runs a single command unfiltered.

## What would reopen this

A session transcript where Bash tool results (not MCP payloads or
skill bodies) are measured as a top-three token cost — for example
from a forensic `dev10x:skill-audit --full` pass over the transcript.
`usage_blocks` is not enough: it reports totals per block, with no
attribution to tool results. Then evaluate a
narrow, opt-in integration, for example recommending rtk only for
`cargo` / `go test` in non-Python projects, and re-check point 2 against
Claude Code's documented hook semantics at that time.
