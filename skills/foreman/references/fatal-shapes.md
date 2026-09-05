# Fatal shapes — evidence

Why the crew brief opens with a fatal-shapes block, and what belongs
in it. The block itself is worker-verbatim and lives in
[`crew-prompt-template.md`](crew-prompt-template.md) § 2; this file
carries the evidence, so the template does not grow to hold it.

Companion to [`worker-tool-shapes.md`](worker-tool-shapes.md), which
covers the *positive* shapes (which wrapper, which CWD mode). This file
covers the shapes that kill a worker outright.

## What a fatal shape is

Not a command that fails. A command that opens a **permission prompt**.

A failure returns a non-zero exit and a message the worker can act on.
A prompt returns nothing: the worker freezes mid-turn waiting for an
approval nobody is awake to give, and — because a *pending* prompt
records neither a block nor a denial — leaves no trace in the hook log.
From the overseer's side it is indistinguishable from a slow worker
until the heartbeat gap crosses the stall threshold.

Cost, measured: ~15 minutes of watchdog attention plus a respawned
generation, each time. One chunk in the GH-1214 run needed seven
generations.

## The GH-1214 run: ten recoveries, ten shapes, zero code problems

Verbatim last calls of the frozen workers, taken from the `TaskStop`
results that resolved each pending prompt as "rejected" at the instant
of the stop:

| Last call | Why it prompted |
|---|---|
| `manage.py makemigrations` via shebang | brief said `uv run python manage.py` |
| `bin/check-adr-numbers.py` direct | brief already banned it |
| `gh api -X PATCH .../pulls/53 -F body=@…` | a PR-body write from a subagent |
| `cd <dir> && ENV=value command \| tail` | chain + env prefix + pipe, three ways |
| `node_modules/.bin/vitest run --root <dir>` | reached for after `npm --prefix … test` was hook-blocked toward an unavailable `run_node_tests` |
| `gh pr create --body-file` (twice), then a self-written `open-pr.sh` calling `gh pr create` | the wrapper was unreachable; the worker escalated instead of reporting |
| a `*-rebase` alias, then `git config --get-regexp "^alias\."` | frozen inside an interactive rebase with every conflict already resolved and staged |
| `bash /tmp/Dev10x/bin/mktmp.sh git commit-msg .txt` | the fallback the git-commit skill itself names |

Two patterns run through the whole list.

**Every death was in a `git` / `gh` / `npm` / script call — never while
editing code.** Model tier does not help here; shape discipline does.

**Half the shapes are ones our own documentation names.** `mktmp.sh`
is the documented fallback. `gh pr create --body-file` is the
documented fallback. A worker reaching for a fallback is a worker that
has already lost its wrappers (see
[`mcp-connectivity.md`](mcp-connectivity.md) § Absent from spawn) — so
the fallback fires exactly when it is most likely to prompt. The brief
must say **report the empty surface** rather than name a fallback that
prompts.

## Why a ban line halfway down the brief does not work

Every one of those shapes already had a ban in the brief. The `cp` case
is the cleanest demonstration: both porting workers carried the line
"Use Read + Write only — never `cp` — porting means understanding and
re-expressing the design", and both prompted on `cp` anyway. The
supervisor's own words mid-run were "cp again" and "why do you need cp
for?".

A worker reads the brief once, at spawn, and then works from what it
recalls under load. A prohibition on line 160 does not fire when it
reaches for the command at line 12 of its own reasoning. Consolidating
the bans into one block at the top — before the mission, before the
tool list — is what stopped the pattern mid-run.

Keep the block **short and shaped like the commands it forbids**. It
competes for attention with everything else in the brief; a paragraph
of rationale there is a paragraph that does not get read. The rationale
is this file.

## The watchdog is not exempt

One `cp` in that run was the watchdog's own: copying a commit-message
file into `/tmp/Dev10x/git/`. The sanctioned shape is `mktmp` →
`Write` directly to the returned path. Any file the plugin hands out a
path for should be *written* at that path, never written elsewhere and
copied in.

## Friction notes — denials that were correct but unhelpful

Two watchdog denials in the same run were the hook working as designed,
and both still cost time. They belong in a brief's shape vocabulary too.

**Grepping for a banned shape.**
`grep -n -i -E 'manage\.py|check-adr|gh api|gh pr edit|update_pr' <brief>`
was denied as a `gh pr edit` call. The search-tool exemption bailed out
on the `|` characters — regex alternation, read as a pipeline — so the
pattern's own text was evaluated as a command. Auditing a brief for the
shapes it bans is precisely what a supervisor should be doing. Fixed in
`dev10x.domain.rules.validation_rule._is_search_command`, which now
tests the *unquoted* command for a pipeline.

**Bulk worktree cleanup.**
`git worktree list --porcelain | awk … | xargs -r -n1 git worktree remove --force`
was denied with the parallel-calls steer, correctly: it is a pipeline
ending in a loop that runs a git write per line. The replacement is the
steer itself — enumerate once, then issue one `git worktree remove` per
path as separate Bash calls. At dawn-cleanup scale that is a handful of
calls, not a reason for a pipeline.
