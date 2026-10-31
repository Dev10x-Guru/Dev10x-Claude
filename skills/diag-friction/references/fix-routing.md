# Step 3h: Fix the Friction, Not Just Explain It (GH-1669)

A diagnosis that names the right skill and offers a retry leaves the
friction where it was: the next session hits the same prompt. Field
case: a background subagent was refused `bash ./scripts/validate-migrations.sh`
and `scripts/hooks/check-hard-rules.sh`. Neither had an allow rule,
and the hook form `CLAUDE_PROJECT_DIR=… bash … < payload.json` could
never be matched by one. The coaching note was correct and changed
nothing.

So the skill ends in a fix. Diagnosis (Steps 1–3g) decides *which*
fix; this step applies it.

## Triage first

Every route below starts from one read-only call:

```
mcp__plugin_dev10x_cli__permission_triage(
    target=<offending command, verbatim>,
    working_dirs=[<primary dir>, <every additional dir>],
    cwd=<primary working dir>,
)
```

Pass the **full command string**, not a rule you built. Triage needs
the shape to see chaining, expansions, env prefixes and reads outside
the working directories. All `working_dirs` must be absolute.

Never write a rule before this call returns. The friction fix order
is *source > normalize > grant*; triage returns the first verdict in
that order that applies.

## The four classes

| Class | How it shows | Fix | Writes? |
|-------|--------------|-----|---------|
| Deliberate deny | verdict `denied`, or Step 3f (gate said yes, rule said no) | Explain which rule holds and hand the exact command to the human (GH-972) | Never |
| Propagation gap | Step 3a outcome (a): rule in the catalog, missing from the effective file | Backfill gate in Step 3a | Via `ensure-base` / `seed-worktree` |
| Plugin default | Step 3a outcome (b): generally safe, absent from the catalog | Upstream issue (Step 3c) for everyone; grant locally now if triage says `grant` | Via `dev10x:permission-grant` |
| Project-specific | Step 3a outcome (c), verdict `grant` | Delegate to `dev10x:permission-grant` | Via `dev10x:permission-grant` |

A deliberate deny is a decision someone made. Do not grant, do not
search for a spelling that slips past it, and do not offer
"Grant" as an option at any gate.

## Verdicts that mean "fix the source, not the rules"

These verdicts end without a grant. State the rewrite or proposal
as the fix:

| Verdict | Fix to state |
|---------|--------------|
| `use-alternative` | The skill, MCP tool or alias from `advice`. Run the retry gate (Step 6) on it |
| `normalize` | Quote each `advice` line. The shape (chaining, `${…}`, `$(…)`, escaped quotes, env prefix) cannot be matched by any rule |
| `outside-workdir` | The `additionalDirectories` entry or `Read()` rule from `advice`. A Bash rule would not help |
| `too-broad` | The narrower subcommand from `reason`, or keep approving per use |
| `refuse-sensitive` | DX014 keeps this prompt on purpose; approve case by case |
| `already-allowed` | The rule exists everywhere readable. The cause is elsewhere: stale session settings (restart), a deny or ask shadowing it, or Step 3a's propagation gap |

### When no rule can ever match

Some commands are unmatchable *by construction*, not by accident of
spelling. The command form a hook or dispatcher emits is fixed:

```
CLAUDE_PROJECT_DIR=/repo bash scripts/hooks/check-hard-rules.sh < payload.json
```

An env-var prefix plus a redirect means no `Bash(...)` rule matches,
however generalized. Rewriting the agent's habits does not help when
the agent is not the author. Propose one of:

1. **A wrapper script** in the project (`scripts/run-hard-rules.sh`)
   that sets the variable and reads the payload itself, so the call
   becomes `scripts/run-hard-rules.sh payload.json`, a shape
   `Bash(scripts/run-hard-rules.sh:*)` covers. Then triage the new
   form and route it like any other `grant`.
2. **An MCP tool** when the operation recurs across projects. File it
   with `dev10x:ticket-create` (upstream for Dev10x, project tracker
   otherwise).

Say which of the two you recommend and why. Do not propose a rule.

## The grant path

On verdict `grant`:

1. `Skill(skill="dev10x:permission-grant", args="<offending command, verbatim>")`

`dev10x:permission-grant` owns the rest: it re-runs triage, names the
generalized rule and **every** settings file lacking it (global, each
project, each worktree's `settings.local.json`) at ONE
`AskUserQuestion` gate, writes through `permission_grant`, and
re-triages to verify. Do not build the target-file list here, and do
not write settings files directly. A second list would drift from the
one the grant tool computes.

Several offending commands: delegate once per command, in the order
the session hit them.

## Background-dispatch friction (Step 3e)

When the prompt came from a background subagent, two things change:

1. The dispatcher still needs the Step 3e fix: the friction
   preamble and the tool in its pre-seeded `allowed_tools` list.
   Name the dispatcher (skill, playbook step or agent spec) and the
   exact entry to add.
2. When triage says `grant`, the Bash rule also goes through
   `dev10x:permission-grant`. A pre-seeded `allowed_tools` list does
   not reach the settings files; a background child that hits the
   same script on its next dispatch prompts again, and nobody is
   watching to answer.

## Verify with the retry

After a fix lands, the Step 6 retry is the verification, not the fix:

- After a grant: retry the original command and confirm it runs
  without a prompt. Settings are read at session start, so a prompt
  in *this* session is expected; say so instead of reporting failure.
- After a rewrite or source fix: retry using the new form or skill.
- After a deliberate deny: no retry. The human runs it.
