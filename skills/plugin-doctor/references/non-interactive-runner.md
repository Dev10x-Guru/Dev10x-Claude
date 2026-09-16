# Non-Interactive Runner (GH-1321)

`dev10x doctor run` executes the same strategy sweep this skill
orchestrates, with no agent in the loop, and prints a structured
verdict. It exists so catalog health is assertable from CI rather
than by a human noticing a prompt — which is how GH-1100's
redundant-rule drift survived for months.

## Why the runner needed the acceptance catalog first

A runner is a **noise amplifier** before it is a convenience.
Automating a detector emits whatever its false-positive rate is on
a schedule, unattended, where nobody triages it. The doctor's
observed rate is high enough that the skill's own anti-patterns
already warn against repeat runs: *"a periodic run would re-prompt
for findings the user already chose to skip."*

That objection is about re-prompting a person, and it is answered
twice here — this command never prompts, and a dismissal now has
somewhere durable to live. Two mechanisms, applied in order:

1. **Severity grading.** Only findings at or above `--threshold`
   are counted as `blocking`. The default is `drift`, which
   excludes `suggestion`. The doctor's largest known
   false-positive class — `ask-shadows-allow`'s narrowing shape,
   69 of 73 findings in the 2026-09-07 audit — is graded
   `suggestion` by GH-1222 precisely so it never gates anything.
2. **The acceptance catalog.** Durable per-(strategy, location)
   answers from the maintainer.

## Acceptance catalog

`~/.config/Dev10x/doctor-accepted-findings.yaml` (Tier 2, so one
answer covers every project and worktree):

```yaml
accepted:
  - strategy: ask-shadows-allow
    location: "*/settings.local.json"   # optional fnmatch glob
    rationale: narrow denies under broad allows are deliberate here
```

- `rationale` is **required**. An entry without one is rejected at
  load, the way the sensitivity-exception catalog rejects a
  matcher-less entry (GH-604): an unexplained suppression is
  indistinguishable from a forgotten one six months later.
- Omitting `location` accepts every finding that strategy emits.
  That is the blunt instrument — prefer a glob.
- A missing file, malformed YAML, or an invalid entry falls back
  to the shipped defaults with a logged warning. A broken overlay
  must never break the run.

**An acceptance moves a finding; it does not hide one.** The
finding is still detected, still returned under `accepted` with
its rationale, and still counted. It is simply not blocking.
Suppression that hides is how a baseline rots into a place
findings go to disappear.

`stale_acceptances` closes the loop the other way: an entry that
matched nothing this run is reported, so the catalog cannot
accumulate answers to drift that no longer exists.

## Output

JSON on stdout in both directions — a verdict and an
`{"error": ...}` blob alike — so a CI consumer parses one channel
and never sees empty stdout on failure
(`.claude/rules/script-domain-boundaries.md`, the
`ci_check_status` shape).

| Key | Meaning |
|-----|---------|
| `findings` | Unaccepted findings, every severity |
| `accepted` | Suppressed findings, each with `rationale` + `source` |
| `stale_acceptances` | Catalog entries that matched nothing |
| `counts` | Per-severity tallies plus `accepted` |
| `threshold` | The severity floor in force |
| `blocking` | How many unaccepted findings reached it |
| `strategies_run` | Strategy ids, in registry order |

| Exit | Meaning |
|------|---------|
| 0 | Nothing unaccepted reached the threshold |
| 1 | At least one did |
| 2 | The sweep could not complete (a strategy raised) |

A strategy that raises fails the whole run with its id named. That
is a defect, not drift, and a run that silently dropped it would
report better health than the machine has.

## A CI check is not a periodic sweep

The distinction matters and the anti-pattern still stands. Run
this where a *change to the catalog* triggers it — a PR touching
permission or strategy files. Scheduling it against a developer's
machine re-raises the objection the acceptance catalog only
partly answers: a finding nobody has ruled on yet will keep
appearing, and a cron job is not a supervisor.
